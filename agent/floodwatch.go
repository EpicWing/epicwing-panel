package main

import (
	"bufio"
	"context"
	"io"
	"log"
	"os"
	"os/exec"
	"sync"
	"time"
)

var (
	floodMu      sync.Mutex
	floodRunning = map[string]bool{}
)

// feedFlood hands every complete console line to the tracker. A line longer than
// the read buffer counts once, its remainder is skipped.
func feedFlood(r io.Reader, name string, t *floodTracker) {
	br := bufio.NewReaderSize(r, 8192)
	continued := false
	for {
		line, isPrefix, err := br.ReadLine()
		if err != nil {
			return
		}
		if !continued {
			t.observe(name, string(line))
		}
		continued = isPrefix
	}
}

// ensureFloodWatch follows the output of a running container for flood detection,
// whether or not anyone has the console open. Only lines from now on are counted,
// so the history of a restart never looks like a flood. The watcher ends with the
// container and is started again by the next stats sample.
func (c *consoleManager) ensureFloodWatch(name string) {
	floodMu.Lock()
	if floodRunning[name] {
		floodMu.Unlock()
		return
	}
	floodRunning[name] = true
	floodMu.Unlock()
	go func() {
		runFloodWatch(c.parent, name)
		floodMu.Lock()
		consoleFlood.forget(name)
		delete(floodRunning, name)
		floodMu.Unlock()
	}()
}

func runFloodWatch(ctx context.Context, name string) {
	cmd := exec.CommandContext(ctx, "docker", "logs", "--follow", "--since", sinceArg(time.Now()), name)
	pr, pw, err := os.Pipe()
	if err != nil {
		log.Printf("flood watch of %s: %v", name, err)
		return
	}
	defer pr.Close()
	cmd.Stdout, cmd.Stderr = pw, pw
	if err := cmd.Start(); err != nil {
		pw.Close()
		log.Printf("flood watch of %s: %v", name, err)
		return
	}
	pw.Close()
	defer func() { _ = cmd.Wait() }()
	feedFlood(pr, name, consoleFlood)
}
