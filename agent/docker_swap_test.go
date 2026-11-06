package main

import (
	"context"
	"strings"
	"testing"
)

func TestLimitedMemorySetsMatchingSwapLimit(t *testing.T) {
	m, calls := containerTestManager("true")
	spec := containerTestSpec()
	spec.MemoryMB = 2048
	if _, err := m.Create(context.Background(), spec); err != nil {
		t.Fatal(err)
	}
	joined := strings.Join((*calls)[0], " ")
	for _, want := range []string{"--memory 2048m", "--memory-swap 2048m"} {
		if !strings.Contains(joined, want) {
			t.Errorf("missing %q in %q", want, joined)
		}
	}
}

func TestInstallArgsLimitSwapToo(t *testing.T) {
	m, _, _ := dataTestManager()
	spec := InstallSpec{
		Name:                "srv-1",
		Image:               "nginx:1.27",
		InstallerImage:      "nginx:1.27",
		InstallerEntrypoint: "bash",
		InstallScript:       "#!/bin/bash\nexit 0",
		MemoryMB:            1024,
	}
	args := strings.Join(m.installArgs(spec), " ")
	for _, want := range []string{"--memory 1024m", "--memory-swap 1024m"} {
		if !strings.Contains(args, want) {
			t.Errorf("missing %q in %q", want, args)
		}
	}
}
