package main

import (
	"context"
	"errors"
	"net"
	"strconv"
	"strings"
	"testing"
)

const bindingsJSON = `{"27015/tcp":[{"HostIp":"203.0.113.154","HostPort":"27015"}],"27015/udp":[{"HostIp":"203.0.113.154","HostPort":"27015"}],"27016/udp":[{"HostIp":"203.0.113.154","HostPort":"27016"}]}`

// startHarness fakes docker for Start: inspectPorts is the answer to the port inspect,
// startErr the result of docker start.
func startHarness(inspectPorts string, startErr error, busy map[string]bool) (*containerManager, *[]string) {
	var calls []string
	m := &containerManager{
		run: func(_ context.Context, args ...string) (string, error) {
			calls = append(calls, strings.Join(args, " "))
			if args[0] == "inspect" {
				if strings.Contains(args[2], "HostConfig.PortBindings") {
					return inspectPorts, nil
				}
				return "true", nil
			}
			if args[0] == "start" {
				return "", startErr
			}
			return "", nil
		},
		portProbe: func(proto, ip string, port int) bool {
			return busy[proto+"/"+ip+":"+itoa(port)]
		},
	}
	return m, &calls
}

func itoa(n int) string { return strconv.Itoa(n) }

func hasCall(calls []string, prefix string) bool {
	for _, c := range calls {
		if strings.HasPrefix(c, prefix) {
			return true
		}
	}
	return false
}

func TestStartRefusesBusyPortWithoutCallingDockerStart(t *testing.T) {
	m, calls := startHarness("false|"+bindingsJSON, nil, map[string]bool{"udp/203.0.113.154:27015": true})
	err := m.Start(context.Background(), "web-1")
	if errorCode(err) != codePortInUse {
		t.Fatalf("want PORT_IN_USE, got %v", err)
	}
	if hasCall(*calls, "start ") {
		t.Fatalf("docker start must not run, calls: %v", *calls)
	}
	if !strings.Contains(err.Error(), "27015/udp") {
		t.Fatalf("technical text should name the port, got %q", err)
	}
}

func TestStartRunsWhenPortsAreFree(t *testing.T) {
	m, calls := startHarness("false|"+bindingsJSON, nil, nil)
	if err := m.Start(context.Background(), "web-1"); err != nil {
		t.Fatal(err)
	}
	if !hasCall(*calls, "start web-1") {
		t.Fatalf("docker start missing: %v", *calls)
	}
}

func TestStartSkipsPortCheckForRunningContainer(t *testing.T) {
	// The container's own published ports are busy while it runs.
	m, calls := startHarness("true|"+bindingsJSON, nil, map[string]bool{"udp/203.0.113.154:27015": true})
	if err := m.Start(context.Background(), "web-1"); err != nil {
		t.Fatalf("running container must not be reported as busy: %v", err)
	}
	if !hasCall(*calls, "start web-1") {
		t.Fatalf("docker start missing: %v", *calls)
	}
}

func TestStartIgnoresUnreadableInspect(t *testing.T) {
	for _, out := range []string{"", "garbage", "false|not json", "true"} {
		m, calls := startHarness(out, nil, map[string]bool{"udp/203.0.113.154:27015": true})
		if err := m.Start(context.Background(), "web-1"); err != nil {
			t.Fatalf("inspect %q: docker decides, got %v", out, err)
		}
		if !hasCall(*calls, "start web-1") {
			t.Fatalf("inspect %q: docker start missing", out)
		}
	}
}

func TestStartClassifiesDockerRaceError(t *testing.T) {
	raw := errors.New("docker start: exit status 1: Error response from daemon: failed to set up container networking: driver failed programming external connectivity on endpoint x (y): Bind for 203.0.113.154:27015 failed: port is already allocated")
	m, _ := startHarness("false|{}", raw, nil)
	err := m.Start(context.Background(), "web-1")
	if errorCode(err) != codePortInUse {
		t.Fatalf("want PORT_IN_USE, got %v", err)
	}
	if !strings.Contains(err.Error(), "203.0.113.154:27015") {
		t.Fatalf("technical text should keep the address, got %q", err)
	}
}

func TestClassifyDockerError(t *testing.T) {
	if classifyDockerError(nil) != nil {
		t.Fatal("nil stays nil")
	}
	plain := errors.New("docker start: exit status 1: something else")
	if got := classifyDockerError(plain); got != plain || errorCode(got) != "" {
		t.Fatalf("unknown errors stay unchanged, got %v", got)
	}
	missing := errors.New("docker inspect: exit status 1: Error: No such object: abc")
	if errorCode(classifyDockerError(missing)) != codeContainerMissing {
		t.Fatal("no such object must be CONTAINER_MISSING")
	}
	if !strings.Contains(classifyDockerError(missing).Error(), "No such object") {
		t.Fatal("the text must stay, the panel relies on it for remove")
	}
	if errorCode(classifyDockerError(errors.New("listen tcp: address already in use"))) != codePortInUse {
		t.Fatal("address already in use must be PORT_IN_USE")
	}
}

func TestResultFrameCarriesCode(t *testing.T) {
	frame := resultFrame("1", nil, &agentError{Code: codeBackupRunning, Msg: "a backup operation is running for this server"})
	if frame["ok"] != false || frame["code"] != codeBackupRunning {
		t.Fatalf("unexpected frame %v", frame)
	}
	frame = resultFrame("2", nil, errors.New("plain"))
	if _, has := frame["code"]; has {
		t.Fatalf("plain errors carry no code: %v", frame)
	}
	frame = resultFrame("3", nil, errors.New("docker start: Bind for 1.2.3.4:5 failed: port is already allocated"))
	if frame["code"] != codePortInUse {
		t.Fatalf("docker race error must be coded in the frame: %v", frame)
	}
	if frame := resultFrame("4", map[string]any{"a": 1}, nil); frame["ok"] != true || frame["code"] != nil {
		t.Fatalf("success frame wrong: %v", frame)
	}
}

func TestProbePortDetectsRealListeners(t *testing.T) {
	tcp, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Skip("cannot listen: ", err)
	}
	defer tcp.Close()
	udp, err := net.ListenPacket("udp", "127.0.0.1:0")
	if err != nil {
		t.Skip("cannot listen: ", err)
	}
	defer udp.Close()
	tcpPort := tcp.Addr().(*net.TCPAddr).Port
	udpPort := udp.LocalAddr().(*net.UDPAddr).Port
	if !probePort("tcp", "127.0.0.1", tcpPort) {
		t.Error("held tcp port must be busy")
	}
	if !probePort("udp", "127.0.0.1", udpPort) {
		t.Error("held udp port must be busy")
	}
	free, _ := net.Listen("tcp", "127.0.0.1:0")
	freePort := free.Addr().(*net.TCPAddr).Port
	free.Close()
	if probePort("tcp", "127.0.0.1", freePort) {
		t.Error("free port must not be busy")
	}
	if probePort("sctp", "127.0.0.1", 1) {
		t.Error("unknown protocol is not probed")
	}
	if probePort("tcp", "203.0.113.77", 27015) {
		t.Error("an address that is not on this host is left to docker")
	}
}
