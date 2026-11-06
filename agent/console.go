package main

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"sync"
	"time"
	"unicode/utf8"
)

const (
	// Frames to the panel are limited to 16 KiB and control bytes grow sixfold in JSON.
	consoleChunkBytes = 2000
	consoleInputMax   = 1024
	consoleHistory    = "200"
)

type consoleWatch struct{ cancel context.CancelFunc }

// consoleManager streams the output of managed containers to the panel and sends
// single input lines to them. The panel starts and stops a watch per container.
type consoleManager struct {
	parent     context.Context
	containers *containerManager
	send       func(map[string]any)
	mu         sync.Mutex
	watches    map[string]*consoleWatch
}

func newConsoleManager(parent context.Context, containers *containerManager, send func(map[string]any)) *consoleManager {
	return &consoleManager{
		parent:     parent,
		containers: containers,
		send:       send,
		watches:    map[string]*consoleWatch{},
	}
}

// splitUTF8 cuts an incomplete multi-byte character off the end of b.
func splitUTF8(b []byte) (head, tail []byte) {
	for i := 1; i < utf8.UTFMax && i <= len(b); i++ {
		if utf8.RuneStart(b[len(b)-i]) {
			if !utf8.FullRune(b[len(b)-i:]) {
				return b[:len(b)-i], b[len(b)-i:]
			}
			break
		}
	}
	return b, nil
}

// validConsoleInput accepts one line of text without any control character, so no
// key sequence (detach keys, escape codes, newlines) can be smuggled into the container.
func validConsoleInput(s string) bool {
	if s == "" || len(s) > consoleInputMax || !utf8.ValidString(s) {
		return false
	}
	for _, r := range s {
		if r < 0x20 || r == 0x7f {
			return false
		}
	}
	return true
}

func sinceArg(t time.Time) string {
	return fmt.Sprintf("%d.%09d", t.Unix(), t.Nanosecond())
}

func sleepCtx(ctx context.Context, d time.Duration) {
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-ctx.Done():
	case <-t.C:
	}
}

// parseDockerEvent turns a line of `docker events` into a state frame for the panel.
func parseDockerEvent(line []byte) (map[string]any, bool) {
	var e struct {
		Action string `json:"Action"`
		Actor  struct {
			Attributes map[string]string `json:"Attributes"`
		} `json:"Actor"`
	}
	if err := json.Unmarshal(line, &e); err != nil {
		return nil, false
	}
	name := e.Actor.Attributes["name"]
	if !containerNameRe.MatchString(name) {
		return nil, false
	}
	frame := map[string]any{"type": "state", "name": name}
	switch e.Action {
	case "start":
		frame["state"] = "running"
	case "die":
		frame["state"] = "exited"
		code, _ := strconv.Atoi(e.Actor.Attributes["exitCode"])
		frame["exit_code"] = code
	case "destroy":
		frame["state"] = "removed"
	default:
		return nil, false
	}
	return frame, true
}

func (c *consoleManager) execute(ctx context.Context, action string, params json.RawMessage) (map[string]any, error) {
	if c == nil {
		return nil, errors.New("the console is not available")
	}
	var p struct {
		Name string `json:"name"`
		Data string `json:"data"`
	}
	if err := decodeParams(params, &p); err != nil {
		return nil, err
	}
	switch action {
	case "console.watch":
		return nil, c.Watch(ctx, p.Name)
	case "console.unwatch":
		c.Unwatch(p.Name)
		return nil, nil
	case "console.input":
		return nil, c.Input(ctx, p.Name, p.Data)
	}
	return nil, fmt.Errorf("unknown action %q", action)
}

func (c *consoleManager) Watch(ctx context.Context, name string) error {
	if err := c.containers.requireManaged(ctx, name); err != nil {
		return err
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if _, ok := c.watches[name]; ok {
		return nil
	}
	wctx, cancel := context.WithCancel(c.parent)
	w := &consoleWatch{cancel: cancel}
	c.watches[name] = w
	go c.watchLoop(wctx, name, w)
	return nil
}

func (c *consoleManager) Unwatch(name string) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if w, ok := c.watches[name]; ok {
		w.cancel()
		delete(c.watches, name)
	}
}

func (c *consoleManager) forget(name string, w *consoleWatch) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.watches[name] == w {
		delete(c.watches, name)
	}
}

// watchLoop sends the last lines once and then follows the output. When the
// container stops it waits until the container runs again and continues from there.
func (c *consoleManager) watchLoop(ctx context.Context, name string, w *consoleWatch) {
	defer c.forget(name, w)
	var since time.Time
	history := false
	for ctx.Err() == nil {
		state, _, err := c.containers.Status(ctx, name)
		if err != nil {
			if ctx.Err() == nil {
				log.Printf("console of %s ends: %v", name, err)
			}
			return
		}
		if state != "running" {
			if !history {
				since = time.Now()
				// A console opened on a stopped container gets the offline line, which is otherwise only sent live.
				c.send(daemonFrame(name, "Server marked as offline"))
				history = true
			}
			sleepCtx(ctx, time.Second)
			continue
		}
		args := []string{"logs", "--follow"}
		if history {
			args = append(args, "--since", sinceArg(since))
		} else {
			// Only the current run: a restart keeps the container, so older lines are still in its log.
			if started, err := runDocker(ctx, "inspect", "-f", "{{.State.StartedAt}}", name); err == nil && started != "" {
				args = append(args, "--since", started)
			}
			args = append(args, "--tail", consoleHistory)
		}
		c.stream(ctx, name, append(args, name))
		history = true
		since = time.Now()
		sleepCtx(ctx, 500*time.Millisecond)
	}
}

// stream runs one docker logs call and forwards its output until it ends.
func (c *consoleManager) stream(ctx context.Context, name string, args []string) {
	cmd := exec.CommandContext(ctx, "docker", args...)
	pr, pw, err := os.Pipe()
	if err != nil {
		log.Printf("console of %s: %v", name, err)
		return
	}
	defer pr.Close()
	cmd.Stdout, cmd.Stderr = pw, pw
	if err := cmd.Start(); err != nil {
		pw.Close()
		log.Printf("console of %s: %v", name, err)
		return
	}
	pw.Close()
	defer func() { _ = cmd.Wait() }()

	buf := make([]byte, consoleChunkBytes)
	var pending []byte
	for {
		n, err := pr.Read(buf)
		pending = append(pending, buf[:n]...)
		head, tail := splitUTF8(pending)
		if len(head) > 0 {
			c.send(map[string]any{"type": "console", "name": name, "data": string(head)})
		}
		pending = append([]byte(nil), tail...)
		if err != nil {
			if !errors.Is(err, io.EOF) {
				_ = cmd.Process.Kill()
			}
			return
		}
	}
}

// watchEvents reports start, exit and removal of managed containers to the panel.
func watchEvents(ctx context.Context, send func(map[string]any)) {
	for ctx.Err() == nil {
		runEvents(ctx, send)
		sleepCtx(ctx, 3*time.Second)
	}
}

func runEvents(ctx context.Context, send func(map[string]any)) {
	cmd := exec.CommandContext(ctx, "docker", "events",
		"--filter", "type=container",
		"--filter", "label="+managedLabel+"=true",
		"--format", "{{json .}}")
	out, err := cmd.StdoutPipe()
	if err != nil {
		log.Printf("docker events: %v", err)
		return
	}
	if err := cmd.Start(); err != nil {
		log.Printf("docker events: %v", err)
		return
	}
	go syncStates(ctx, send)
	scanner := bufio.NewScanner(out)
	scanner.Buffer(make([]byte, 64*1024), 1024*1024)
	for scanner.Scan() {
		if frame, ok := parseDockerEvent(scanner.Bytes()); ok {
			send(frame)
			if msg, ok := daemonStateMessage(frame); ok {
				send(daemonFrame(frame["name"].(string), msg))
			}
		}
	}
	_ = cmd.Wait()
}

const dockerSocket = "/var/run/docker.sock"

// Input writes one line into the container's console. The Docker CLI refuses stdin
// from a pipe for containers with a TTY, so this uses the Docker API directly.
func (c *consoleManager) Input(ctx context.Context, name, data string) error {
	if !validConsoleInput(data) {
		return errors.New("invalid console input")
	}
	state, _, err := c.containers.Status(ctx, name)
	if err != nil {
		return err
	}
	if state != "running" {
		return errors.New("the container is not running")
	}
	return attachWrite(ctx, dockerSocket, name, data+"\n")
}

// attachWrite opens an attach connection to the container, switches it to a raw
// stream and writes one line into it.
func attachWrite(ctx context.Context, socket, name, line string) error {
	if !containerNameRe.MatchString(name) {
		return errors.New("invalid container name")
	}
	dialer := net.Dialer{Timeout: 5 * time.Second}
	conn, err := dialer.DialContext(ctx, "unix", socket)
	if err != nil {
		return fmt.Errorf("connecting to docker: %w", err)
	}
	defer conn.Close()
	_ = conn.SetDeadline(time.Now().Add(10 * time.Second))

	request := "POST /containers/" + name + "/attach?stream=1&stdin=1&stdout=1&stderr=1 HTTP/1.1\r\n" +
		"Host: docker\r\nUpgrade: tcp\r\nConnection: Upgrade\r\n\r\n"
	if _, err := io.WriteString(conn, request); err != nil {
		return fmt.Errorf("docker attach: %w", err)
	}
	resp, err := http.ReadResponse(bufio.NewReader(conn), nil)
	if err != nil {
		return fmt.Errorf("docker attach: %w", err)
	}
	if resp.StatusCode != http.StatusSwitchingProtocols && resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		return fmt.Errorf("docker attach: %s: %s", resp.Status, strings.TrimSpace(string(body)))
	}
	if _, err := io.WriteString(conn, line); err != nil {
		return fmt.Errorf("writing to the container: %w", err)
	}
	// Give the daemon a moment to pass the line on before the connection closes.
	sleepCtx(ctx, 150*time.Millisecond)
	return nil
}

// stateFromInspect turns one "name|state|exitcode" line from docker inspect into a state frame.
func stateFromInspect(line string) (map[string]any, bool) {
	parts := strings.Split(strings.TrimSpace(line), "|")
	if len(parts) != 3 {
		return nil, false
	}
	name := strings.TrimPrefix(parts[0], "/")
	if !containerNameRe.MatchString(name) {
		return nil, false
	}
	frame := map[string]any{"type": "state", "name": name}
	switch parts[1] {
	case "running":
		frame["state"] = "running"
	case "exited", "dead":
		frame["state"] = "exited"
		code, _ := strconv.Atoi(parts[2])
		frame["exit_code"] = code
	case "created":
		frame["state"] = "created"
	default:
		return nil, false
	}
	return frame, true
}

// syncStates reports the current state of every managed container once, so the panel
// catches up after a restart of the agent or a gap in the event stream.
func syncStates(ctx context.Context, send func(map[string]any)) {
	ids, err := runDocker(ctx, "ps", "-aq", "--filter", "label="+managedLabel+"=true")
	if err != nil {
		log.Printf("state sync: %v", err)
		return
	}
	if ids == "" {
		return
	}
	args := append([]string{"inspect", "--format", "{{.Name}}|{{.State.Status}}|{{.State.ExitCode}}"}, strings.Fields(ids)...)
	out, err := runDocker(ctx, args...)
	if err != nil {
		log.Printf("state sync: %v", err)
		return
	}
	for _, line := range strings.Split(out, "\n") {
		if frame, ok := stateFromInspect(line); ok {
			send(frame)
		}
	}
}
