package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"regexp"
	"sort"
	"strings"
	"syscall"
)

// Error codes sent to the panel next to the raw error text. The panel maps them to
// short messages for users; the raw text only goes to the logs and to admins.
const (
	codePortInUse        = "PORT_IN_USE"
	codeContainerMissing = "CONTAINER_MISSING"
	codeBackupRunning    = "BACKUP_RUNNING"
	codeBusy             = "NODE_BUSY"
)

// agentError is an error with a stable code for the panel.
type agentError struct {
	Code string
	Msg  string
}

func (e *agentError) Error() string { return e.Msg }

// errorCode returns the code of err, or "" if it has none.
func errorCode(err error) string {
	var ae *agentError
	if errors.As(err, &ae) {
		return ae.Code
	}
	return ""
}

var (
	dockerBindRe = regexp.MustCompile(`Bind for ([^ ]+) failed`)
	noSuchRe     = regexp.MustCompile(`(?i)no such (container|object)`)
)

// classifyDockerError turns well-known docker failures into coded errors. Anything
// else is returned unchanged.
func classifyDockerError(err error) error {
	if err == nil {
		return nil
	}
	var ae *agentError
	if errors.As(err, &ae) {
		return err
	}
	text := err.Error()
	lower := strings.ToLower(text)
	switch {
	case strings.Contains(lower, "port is already allocated"),
		strings.Contains(lower, "address already in use"):
		where := "a host port"
		if m := dockerBindRe.FindStringSubmatch(text); m != nil {
			where = m[1]
		}
		return &agentError{Code: codePortInUse, Msg: fmt.Sprintf("%s is in use (%v)", where, err)}
	case noSuchRe.MatchString(text):
		return &agentError{Code: codeContainerMissing, Msg: text}
	}
	return err
}

// portProbe reports whether the host port can be bound right now. Only "address
// already in use" counts as busy: other errors (no permission, address not on this
// host) are left to docker, which has the final say.
type portProbe func(proto, ip string, port int) (busy bool)

func probePort(proto, ip string, port int) bool {
	addr := net.JoinHostPort(ip, fmt.Sprint(port))
	var err error
	switch proto {
	case "tcp":
		var l net.Listener
		if l, err = net.Listen("tcp", addr); err == nil {
			_ = l.Close()
		}
	case "udp":
		var c net.PacketConn
		if c, err = net.ListenPacket("udp", addr); err == nil {
			_ = c.Close()
		}
	default:
		return false
	}
	return err != nil && errors.Is(err, syscall.EADDRINUSE)
}

type hostBinding struct {
	HostIp   string `json:"HostIp"`
	HostPort string `json:"HostPort"`
}

// busyPorts lists the host ports of a container that something else already holds,
// as "27015/udp" entries (with the bind address when it is set).
func busyPorts(bindings map[string][]hostBinding, probe portProbe) []string {
	var busy []string
	for key, list := range bindings {
		proto := "tcp"
		if i := strings.Index(key, "/"); i >= 0 {
			proto = key[i+1:]
		}
		for _, b := range list {
			var port int
			if _, err := fmt.Sscanf(b.HostPort, "%d", &port); err != nil || port <= 0 {
				continue
			}
			ip := b.HostIp
			if ip == "" {
				ip = "0.0.0.0"
			}
			if probe(proto, ip, port) {
				busy = append(busy, fmt.Sprintf("%d/%s on %s", port, proto, ip))
			}
		}
	}
	sort.Strings(busy)
	return busy
}

// checkPorts fails with PORT_IN_USE before docker start if a published host port is
// held by another process (for example a container that is not managed by the panel).
// A container that is already running is skipped: its own ports are of course busy.
// If inspect output cannot be read, nothing is checked and docker decides.
func (m *containerManager) checkPorts(ctx context.Context, name string) error {
	out, err := m.run(ctx, "inspect", "--format", `{{.State.Running}}|{{json .HostConfig.PortBindings}}`, name)
	if err != nil {
		return nil
	}
	running, raw, ok := strings.Cut(out, "|")
	if !ok || running == "true" {
		return nil
	}
	var bindings map[string][]hostBinding
	if json.Unmarshal([]byte(raw), &bindings) != nil {
		return nil
	}
	probe := m.portProbe
	if probe == nil {
		probe = probePort
	}
	if busy := busyPorts(bindings, probe); len(busy) > 0 {
		return &agentError{
			Code: codePortInUse,
			Msg:  "host port in use before start: " + strings.Join(busy, ", "),
		}
	}
	return nil
}
