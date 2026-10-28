package main

import (
	"context"
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
