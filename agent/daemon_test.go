package main

import (
	"strings"
	"testing"
)

func TestDaemonLineFormat(t *testing.T) {
	got := daemonLine("Server marked as starting...")
	if !strings.HasPrefix(got, "\x1b[33m\x1b[1m[EpicWing Daemon]\x1b[0m ") {
		t.Fatalf("wrong prefix: %q", got)
	}
	if !strings.HasSuffix(got, "Server marked as starting...\r\n") {
		t.Fatalf("Text oder Zeilenende falsch: %q", got)
	}
}

func TestDaemonFrameShape(t *testing.T) {
	f := daemonFrame("srv1", "hallo")
	if f["type"] != "console" || f["name"] != "srv1" {
		t.Fatalf("Frame falsch: %v", f)
	}
	if !strings.Contains(f["data"].(string), "[EpicWing Daemon]") {
		t.Fatalf("data without prefix: %v", f["data"])
	}
}
