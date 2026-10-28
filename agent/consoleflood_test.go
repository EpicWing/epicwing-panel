package main

import (
	"fmt"
	"testing"
)

func TestFloodSource(t *testing.T) {
	cases := map[string]string{
		"Player 76561198012345678 connected from 203.0.113.7:7777": "76561198012345678",
		"Connection attempt from 198.51.100.4:51234":               "198.51.100.4",
		"Server tick took 12 ms":                                   "",
		"version 1.2.3 loaded":                                     "",
	}
	for line, want := range cases {
		if got := floodSource(line); got != want {
			t.Errorf("floodSource(%q) = %q, want %q", line, got, want)
		}
	}
}

func TestFloodSnapshot(t *testing.T) {
	tr := newFloodTracker()
	for i := 0; i < 90; i++ {
		tr.observe("a", "login from 203.0.113.7:1000")
	}
	for i := 0; i < 10; i++ {
		tr.observe("a", fmt.Sprintf("login from 198.51.100.%d:1000", i))
	}
	tr.observe("a", "no source here")
	got := tr.snapshot("a")
	want := map[string]int64{"lines": 101, "window_lines": 101, "sources": 11, "top": 90}
	for key, value := range want {
		if got[key] != value {
			t.Errorf("%s = %d, want %d", key, got[key], value)
		}
	}
	next := tr.snapshot("a")
	if next["lines"] != 101 || next["window_lines"] != 0 || next["sources"] != 0 {
		t.Errorf("window not reset: %v", next)
	}
	if tr.snapshot("unknown") != nil {
		t.Error("unknown container must give nil")
	}
}

func TestFloodSourceCap(t *testing.T) {
	tr := newFloodTracker()
	for i := 0; i < floodMaxSources+500; i++ {
		tr.observe("a", fmt.Sprintf("hello 10.%d.%d.%d", i>>16&255, i>>8&255, i&255))
	}
	got := tr.snapshot("a")
	if got["sources"] != floodMaxSources {
		t.Errorf("sources = %d, want cap %d", got["sources"], floodMaxSources)
	}
	if got["lines"] != floodMaxSources+500 {
		t.Errorf("lines = %d", got["lines"])
	}
}
