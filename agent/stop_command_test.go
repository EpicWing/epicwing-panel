package main

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"
)

type stopHarness struct {
	m       *containerManager
	calls   []string
	written []string
	running bool
}

// newStopHarness fakes docker: stopsOnCommand makes the container exit once the
// stop command was written, writeErr makes writing fail.
func newStopHarness(stopsOnCommand bool, writeErr error) *stopHarness {
	h := &stopHarness{running: true}
	h.m = &containerManager{
		run: func(_ context.Context, args ...string) (string, error) {
			h.calls = append(h.calls, strings.Join(args, " "))
			if args[0] == "inspect" {
				if strings.Contains(args[2], "State.Status") {
					state := "exited"
					if h.running {
						state = "running"
					}
					return "true|" + state + "|0", nil
				}
				return "true", nil
			}
			return "", nil
		},
		inputWriter: func(_ context.Context, _, line string) error {
			h.written = append(h.written, line)
			if writeErr != nil {
				return writeErr
			}
			if stopsOnCommand {
				h.running = false
			}
			return nil
		},
		stopPoll: time.Millisecond,
		stopWait: 30 * time.Millisecond,
	}
	return h
}

func (h *stopHarness) dockerStop() string {
	for _, c := range h.calls {
		if strings.HasPrefix(c, "stop ") {
			return c
		}
	}
	return ""
}

func TestStopWithCommandStopsTheContainer(t *testing.T) {
	h := newStopHarness(true, nil)
	if err := h.m.StopWithCommand(context.Background(), "c1", "EXIT"); err != nil {
		t.Fatal(err)
	}
	if len(h.written) != 1 || h.written[0] != "EXIT" {
		t.Fatalf("written = %q", h.written)
	}
	if got := h.dockerStop(); got != "" {
		t.Fatalf("unexpected docker call: %s", got)
	}
}

func TestStopWithCommandFallsBackWhenTheContainerKeepsRunning(t *testing.T) {
	h := newStopHarness(false, nil)
	if err := h.m.StopWithCommand(context.Background(), "c1", "EXIT"); err != nil {
		t.Fatal(err)
	}
	if len(h.written) != 1 {
		t.Fatalf("written = %q", h.written)
	}
	if got := h.dockerStop(); got != "stop -t 10 c1" {
		t.Fatalf("docker call = %q", got)
	}
}

func TestStopWithCommandFallsBackWhenWritingFails(t *testing.T) {
	h := newStopHarness(true, errors.New("boom"))
	if err := h.m.StopWithCommand(context.Background(), "c1", "EXIT"); err != nil {
		t.Fatal(err)
	}
	if got := h.dockerStop(); got != "stop -t 10 c1" {
		t.Fatalf("docker call = %q", got)
	}
}

func TestStopWithoutCommandUsesDockerStop(t *testing.T) {
	h := newStopHarness(true, nil)
	if err := h.m.Stop(context.Background(), "c1"); err != nil {
		t.Fatal(err)
	}
	if len(h.written) != 0 {
		t.Fatalf("written = %q", h.written)
	}
	if got := h.dockerStop(); got != "stop -t 30 c1" {
		t.Fatalf("docker call = %q", got)
	}
}

func TestStopWithInvalidCommandUsesDockerStop(t *testing.T) {
	h := newStopHarness(true, nil)
	if err := h.m.StopWithCommand(context.Background(), "c1", "EXIT\nrm -rf"); err != nil {
		t.Fatal(err)
	}
	if len(h.written) != 0 {
		t.Fatalf("written = %q", h.written)
	}
	if got := h.dockerStop(); got != "stop -t 30 c1" {
		t.Fatalf("docker call = %q", got)
	}
}

func TestStopWithCommandSkipsAStoppedContainer(t *testing.T) {
	h := newStopHarness(true, nil)
	h.running = false
	if err := h.m.StopWithCommand(context.Background(), "c1", "EXIT"); err != nil {
		t.Fatal(err)
	}
	if len(h.written) != 0 || h.dockerStop() != "" {
		t.Fatalf("written = %q, docker = %q", h.written, h.dockerStop())
	}
}

func TestLockFreeActions(t *testing.T) {
	for _, a := range []string{"container.stop", "container.kill"} {
		if !lockFree(a) {
			t.Errorf("%s should not wait for the dispatcher lock", a)
		}
	}
	for _, a := range []string{"container.start", "container.create", "container.install", "container.remove", "container.status", "console.input"} {
		if lockFree(a) {
			t.Errorf("%s should keep the dispatcher lock", a)
		}
	}
}
