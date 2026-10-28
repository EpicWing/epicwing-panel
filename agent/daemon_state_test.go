package main

import "testing"

func TestDaemonStateMessage(t *testing.T) {
	cases := []struct {
		name  string
		frame map[string]any
		want  string
		ok    bool
	}{
		{"running", map[string]any{"state": "running"}, "Container started", true},
		{"exited sauber", map[string]any{"state": "exited", "exit_code": 0}, "Server marked as offline", true},
		{"exited mit Code", map[string]any{"state": "exited", "exit_code": 137}, "Server marked as offline (exit code 137)", true},
		{"removed", map[string]any{"state": "removed"}, "", false},
		{"created", map[string]any{"state": "created"}, "", false},
	}
	for _, c := range cases {
		got, ok := daemonStateMessage(c.frame)
		if got != c.want || ok != c.ok {
			t.Errorf("%s: got (%q, %v), want (%q, %v)", c.name, got, ok, c.want, c.ok)
		}
	}
}
