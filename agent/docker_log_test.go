package main

import (
	"context"
	"strings"
	"testing"
)

func TestContainersGetBoundedLogs(t *testing.T) {
	m, calls := containerTestManager("true")
	if _, err := m.Create(context.Background(), containerTestSpec()); err != nil {
		t.Fatal(err)
	}
	joined := strings.Join((*calls)[0], " ")
	for _, want := range []string{"--log-opt max-size=10m", "--log-opt max-file=3"} {
		if !strings.Contains(joined, want) {
			t.Errorf("missing %q in %q", want, joined)
		}
	}
}
