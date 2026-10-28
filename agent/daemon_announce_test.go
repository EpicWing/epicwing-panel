package main

import (
	"strings"
	"testing"
)

func TestAnnounceSendsDaemonLine(t *testing.T) {
	var got []map[string]any
	d := &commandDispatcher{console: &consoleManager{send: func(f map[string]any) { got = append(got, f) }}}
	d.announce("srv1", "Server marked as starting...")
	if len(got) != 1 || got[0]["type"] != "console" || got[0]["name"] != "srv1" {
		t.Fatalf("Frame falsch: %v", got)
	}
	if !strings.Contains(got[0]["data"].(string), "[EpicWing Daemon]") || !strings.Contains(got[0]["data"].(string), "starting...") {
		t.Fatalf("Zeile falsch: %v", got[0]["data"])
	}
}

func TestAnnounceWithoutConsoleIsSafe(t *testing.T) {
	(&commandDispatcher{}).announce("srv1", "x")
	(&commandDispatcher{console: &consoleManager{}}).announce("srv1", "x")
}
