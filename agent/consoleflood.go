package main

import (
	"regexp"
	"sync"
)

// floodMaxSources caps how many distinct sources are remembered per window, so a
// flood of random addresses cannot grow the agent's memory without limit.
const floodMaxSources = 4096

var (
	floodSteamID = regexp.MustCompile(`\b7656119\d{10}\b`)
	floodIPv4    = regexp.MustCompile(`\b(?:\d{1,3}\.){3}\d{1,3}\b`)
)

type floodWindow struct {
	lines   int64 // cumulative, only grows
	window  int64 // lines since the last snapshot
	sources map[string]int64
}

// floodTracker counts console lines per container and, per measuring window, how
// many different sources (SteamID64 or IPv4) appear in them.
type floodTracker struct {
	mu      sync.Mutex
	servers map[string]*floodWindow
}

func newFloodTracker() *floodTracker {
	return &floodTracker{servers: map[string]*floodWindow{}}
}

// floodSource returns the first SteamID64 or, if there is none, the first IPv4 in a line.
func floodSource(line string) string {
	if id := floodSteamID.FindString(line); id != "" {
		return id
	}
	return floodIPv4.FindString(line)
}

func (t *floodTracker) observe(name, line string) {
	source := floodSource(line)
	t.mu.Lock()
	defer t.mu.Unlock()
	w := t.servers[name]
	if w == nil {
		w = &floodWindow{sources: map[string]int64{}}
		t.servers[name] = w
	}
	w.lines++
	w.window++
	if source == "" {
		return
	}
	if _, known := w.sources[source]; known || len(w.sources) < floodMaxSources {
		w.sources[source]++
	}
}

// snapshot returns the counters of one container and starts a new window. The
// cumulative "lines" value is not reset.
func (t *floodTracker) snapshot(name string) map[string]int64 {
	t.mu.Lock()
	defer t.mu.Unlock()
	w := t.servers[name]
	if w == nil {
		return nil
	}
	var top int64
	for _, count := range w.sources {
		if count > top {
			top = count
		}
	}
	out := map[string]int64{
		"lines":        w.lines,
		"window_lines": w.window,
		"sources":      int64(len(w.sources)),
		"top":          top,
	}
	w.window = 0
	w.sources = map[string]int64{}
	return out
}

func (t *floodTracker) forget(name string) {
	t.mu.Lock()
	delete(t.servers, name)
	t.mu.Unlock()
}

var consoleFlood = newFloodTracker()
