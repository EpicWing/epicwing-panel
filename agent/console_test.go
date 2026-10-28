package main

import (
	"bufio"
	"context"
	"io"
	"net"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestSplitUTF8(t *testing.T) {
	cases := []struct{ name, in, head, tail string }{
		{"ascii", "abc", "abc", ""},
		{"complete rune", "a\u20ac", "a\u20ac", ""},
		{"cut rune", "a\xe2\x82", "a", "\xe2\x82"},
		{"only start byte", "\xe2", "", "\xe2"},
		{"invalid byte", "ab\xff", "ab\xff", ""},
		{"empty", "", "", ""},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			head, tail := splitUTF8([]byte(tc.in))
			if string(head) != tc.head || string(tail) != tc.tail {
				t.Fatalf("got %q/%q, want %q/%q", head, tail, tc.head, tc.tail)
			}
		})
	}
}

func TestValidConsoleInput(t *testing.T) {
	cases := map[string]bool{
		"say hello":                            true,
		"\u00fcn\u00ef":                        true,
		"":                                     false,
		"a\nb":                                 false,
		"a\rb":                                 false,
		"a\x10b":                               false,
		"\x7f":                                 false,
		"\xff":                                 false,
		strings.Repeat("a", consoleInputMax):   true,
		strings.Repeat("a", consoleInputMax+1): false,
	}
	for in, want := range cases {
		if got := validConsoleInput(in); got != want {
			t.Errorf("validConsoleInput(%.20q) = %v, want %v", in, got, want)
		}
	}
}

func TestParseDockerEvent(t *testing.T) {
	line := func(action, name, extra string) []byte {
		return []byte(`{"status":"` + action + `","Type":"container","Action":"` + action +
			`","Actor":{"ID":"x","Attributes":{"name":"` + name + `"` + extra + `}}}`)
	}
	const name = "ae0cf8b7-ee46-4aa8-b558-29211ff75bdd"

	f, ok := parseDockerEvent(line("start", name, ""))
	if !ok || f["state"] != "running" || f["name"] != name || f["type"] != "state" {
		t.Fatalf("start: %v %v", f, ok)
	}
	f, ok = parseDockerEvent(line("die", name, `,"exitCode":"137"`))
	if !ok || f["state"] != "exited" || f["exit_code"] != 137 {
		t.Fatalf("die: %v %v", f, ok)
	}
	f, ok = parseDockerEvent(line("destroy", name, ""))
	if !ok || f["state"] != "removed" {
		t.Fatalf("destroy: %v %v", f, ok)
	}
	if _, ok := parseDockerEvent(line("attach", name, "")); ok {
		t.Fatal("attach must be ignored")
	}
	if _, ok := parseDockerEvent(line("start", "My Name", "")); ok {
		t.Fatal("an invalid container name must be ignored")
	}
	if _, ok := parseDockerEvent([]byte("not json")); ok {
		t.Fatal("garbage must be ignored")
	}
}

func TestSinceArg(t *testing.T) {
	if got := sinceArg(time.Unix(1700000000, 5)); got != "1700000000.000000005" {
		t.Fatalf("got %q", got)
	}
}

func TestConsoleExecuteChecksBeforeDocker(t *testing.T) {
	m, calls := containerTestManager("true")
	c := newConsoleManager(context.Background(), m, func(map[string]any) {})
	ctx := context.Background()
	if _, err := c.execute(ctx, "console.input", rawJSON(`{"name":"web-1","data":"a\nb"}`)); err == nil {
		t.Fatal("expected an error for a control character")
	}
	if _, err := c.execute(ctx, "console.watch", rawJSON(`{"name":"web-1","extra":1}`)); err == nil {
		t.Fatal("expected an error for unknown fields")
	}
	if _, err := c.execute(ctx, "console.unwatch", rawJSON(`{"name":"web-1"}`)); err != nil {
		t.Fatalf("unwatch of an unknown container must be a no-op: %v", err)
	}
	if len(*calls) != 0 {
		t.Fatal("docker must not be called")
	}
}

func TestConsoleWithoutManager(t *testing.T) {
	var c *consoleManager
	if _, err := c.execute(context.Background(), "console.watch", rawJSON(`{"name":"web-1"}`)); err == nil {
		t.Fatal("expected an error")
	}
	d, _ := dispatchTestDispatcher("true")
	if _, err := d.execute(context.Background(), "console.watch", rawJSON(`{"name":"web-1"}`)); err == nil {
		t.Fatal("expected an error without a console manager")
	}
}

func fakeDocker(t *testing.T, reply string) (socket string, got chan string) {
	t.Helper()
	socket = filepath.Join(t.TempDir(), "d.sock")
	l, err := net.Listen("unix", socket)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = l.Close() })
	got = make(chan string, 2)
	go func() {
		conn, err := l.Accept()
		if err != nil {
			got <- "accept: " + err.Error()
			got <- ""
			return
		}
		defer conn.Close()
		r := bufio.NewReader(conn)
		first, _ := r.ReadString('\n')
		for {
			line, err := r.ReadString('\n')
			if err != nil || line == "\r\n" {
				break
			}
		}
		_, _ = io.WriteString(conn, reply)
		input, _ := r.ReadString('\n')
		got <- first
		got <- input
	}()
	return socket, got
}

func TestAttachWrite(t *testing.T) {
	socket, got := fakeDocker(t, "HTTP/1.1 101 UPGRADED\r\nConnection: Upgrade\r\nUpgrade: tcp\r\n\r\n")
	if err := attachWrite(context.Background(), socket, "web-1", "say hi\n"); err != nil {
		t.Fatal(err)
	}
	first, input := <-got, <-got
	if !strings.HasPrefix(first, "POST /containers/web-1/attach?") || !strings.Contains(first, "stdin=1") {
		t.Fatalf("unexpected request %q", first)
	}
	if input != "say hi\n" {
		t.Fatalf("unexpected input %q", input)
	}
}

func TestAttachWriteReportsDockerErrors(t *testing.T) {
	body := "no such container\n"
	reply := "HTTP/1.1 404 Not Found\r\nContent-Length: 18\r\n\r\n" + body
	socket, _ := fakeDocker(t, reply)
	err := attachWrite(context.Background(), socket, "web-1", "x\n")
	if err == nil || !strings.Contains(err.Error(), "no such container") {
		t.Fatalf("expected the docker message, got %v", err)
	}
}

func TestAttachWriteRejectsBadNamesAndMissingSocket(t *testing.T) {
	missing := filepath.Join(t.TempDir(), "none.sock")
	if err := attachWrite(context.Background(), missing, "--all", "x\n"); err == nil {
		t.Fatal("expected an error for an invalid name")
	}
	if err := attachWrite(context.Background(), missing, "web-1", "x\n"); err == nil {
		t.Fatal("expected an error without a socket")
	}
}

func TestStateFromInspect(t *testing.T) {
	const name = "ae0cf8b7-ee46-4aa8-b558-29211ff75bdd"
	f, ok := stateFromInspect("/" + name + "|running|0")
	if !ok || f["state"] != "running" || f["name"] != name || f["type"] != "state" {
		t.Fatalf("running: %v %v", f, ok)
	}
	f, ok = stateFromInspect("/" + name + "|exited|137")
	if !ok || f["state"] != "exited" || f["exit_code"] != 137 {
		t.Fatalf("exited: %v %v", f, ok)
	}
	f, ok = stateFromInspect("/" + name + "|created|0")
	if !ok || f["state"] != "created" {
		t.Fatalf("created: %v %v", f, ok)
	}
	for _, bad := range []string{"", "x|running", "/My Name|running|0", "/" + name + "|paused|0", "/" + name + "|running|0|x"} {
		if _, ok := stateFromInspect(bad); ok {
			t.Errorf("%q must be ignored", bad)
		}
	}
}
