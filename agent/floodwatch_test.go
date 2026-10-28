package main

import (
	"strings"
	"testing"
)

func TestFeedFloodSplitsLines(t *testing.T) {
	tr := newFloodTracker()
	input := "login from 203.0.113.7:1\nlogin from 203.0.113.7:2\nlogin from 198.51.100.4:3\nlast line without newline"
	feedFlood(strings.NewReader(input), "a", tr)
	got := tr.snapshot("a")
	if got["lines"] != 4 || got["sources"] != 2 || got["top"] != 2 {
		t.Errorf("unexpected counters: %v", got)
	}
}

func TestFeedFloodLongLineCountsOnce(t *testing.T) {
	tr := newFloodTracker()
	input := strings.Repeat("x", 30000) + "\nnext 203.0.113.7\n"
	feedFlood(strings.NewReader(input), "a", tr)
	got := tr.snapshot("a")
	if got["lines"] != 2 || got["sources"] != 1 {
		t.Errorf("unexpected counters: %v", got)
	}
}
