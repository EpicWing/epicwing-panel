package main

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"os/exec"
	"strings"
	"sync"
)

// chunkWriter passes written bytes to emit in chunks: preferably up to the
// last line break, never more than consoleChunkBytes, and without splitting a UTF-8 character.
type chunkWriter struct {
	emit    func(string)
	mu      sync.Mutex
	pending []byte
}

func (w *chunkWriter) Write(p []byte) (int, error) {
	w.mu.Lock()
	defer w.mu.Unlock()
	w.pending = append(w.pending, p...)
	for len(w.pending) > 0 {
		cut := bytes.LastIndexByte(w.pending, '\n') + 1
		if cut == 0 && len(w.pending) < consoleChunkBytes {
			break
		}
		if cut == 0 || cut > consoleChunkBytes {
			cut = consoleChunkBytes
			if cut > len(w.pending) {
				cut = len(w.pending)
			}
		}
		head, _ := splitUTF8(w.pending[:cut])
		if len(head) == 0 {
			break
		}
		w.emit(string(head))
		w.pending = append([]byte(nil), w.pending[len(head):]...)
	}
	return len(p), nil
}

// Flush gibt den Rest ohne Zeilenumbruch aus.
func (w *chunkWriter) Flush() {
	w.mu.Lock()
	defer w.mu.Unlock()
	if len(w.pending) > 0 {
		w.emit(string(w.pending))
		w.pending = nil
	}
}

// installWithConsole startet die Installation und streamt die Ausgabe als "install"-Frames
// unter dem Namen des Server-Containers ans Panel.
func installWithConsole(ctx context.Context, m *containerManager, c *consoleManager, spec InstallSpec) (string, error) {
	var emit func(string)
	if c != nil && c.send != nil {
		send := c.send
		send(map[string]any{"type": "install", "name": spec.Name, "reset": true})
		emit = func(s string) {
			send(map[string]any{"type": "install", "name": spec.Name, "data": s})
		}
	}
	return m.installStream(ctx, spec, emit)
}

// installStream entspricht Install, leitet die Ausgabe aber zusätzlich live an emit.
func (m *containerManager) installStream(ctx context.Context, spec InstallSpec, emit func(string)) (string, error) {
	if err := m.validateInstall(spec); err != nil {
		return "", err
	}
	if err := m.mkdir(m.dataPath(spec.Name), 0o750); err != nil {
		return "", fmt.Errorf("creating the data directory: %w", err)
	}
	args := m.installArgs(spec)

	ctx, cancel := context.WithTimeout(ctx, installTimeout)
	defer cancel()
	var out, errOut bytes.Buffer
	var so, se io.Writer = &out, &errOut
	var cw *chunkWriter
	if emit != nil {
		cw = &chunkWriter{emit: emit}
		so = io.MultiWriter(&out, cw)
		se = io.MultiWriter(&errOut, cw)
	}
	cmd := exec.CommandContext(ctx, "docker", args...)
	cmd.Stdin = strings.NewReader(spec.InstallScript)
	cmd.Stdout = so
	cmd.Stderr = se
	runErr := cmd.Run()
	if cw != nil {
		cw.Flush()
	}
	if runErr != nil {
		logs := strings.TrimSpace(out.String() + "\n" + errOut.String())
		if len(logs) > 4000 {
			logs = logs[len(logs)-4000:]
		}
		if emit != nil {
			emit("\n[EpicWing] Installation failed.\n")
		}
		return logs, fmt.Errorf("install failed: %w: %s", runErr, logs)
	}
	if emit != nil {
		emit("\n[EpicWing] Installation finished.\n")
	}
	return strings.TrimSpace(out.String()), nil
}
