package main

import (
	"context"
	"os"
	"os/exec"
	"testing"
	"time"
)

// Runs only with EPICWING_DOCKER_TEST=1 against the local Docker daemon.
const integrationImage = "ghcr.io/ptero-eggs/yolks:mono_latest"

func dockerRM(name string) { _ = exec.Command("docker", "rm", "-f", name).Run() }

func startTestContainer(t *testing.T, name string, entrypoint string, cmd ...string) {
	t.Helper()
	dockerRM(name)
	t.Cleanup(func() { dockerRM(name) })
	args := []string{"create", "--name", name, "--label", managedLabel + "=true",
		"--interactive", "--tty", "--entrypoint", entrypoint, integrationImage}
	args = append(args, cmd...)
	if out, err := exec.Command("docker", args...).CombinedOutput(); err != nil {
		t.Fatalf("docker create: %v: %s", err, out)
	}
	if out, err := exec.Command("docker", "start", name).CombinedOutput(); err != nil {
		t.Fatalf("docker start: %v: %s", err, out)
	}
	time.Sleep(time.Second)
}

func TestDockerStopCommandIntegration(t *testing.T) {
	if os.Getenv("EPICWING_DOCKER_TEST") != "1" {
		t.Skip("set EPICWING_DOCKER_TEST=1 to run against the local Docker daemon")
	}
	m := newContainerManager(ContainerPolicy{})
	ctx := context.Background()

	t.Run("container reacts to the command", func(t *testing.T) {
		const name = "ewtest-stop-cmd"
		startTestContainer(t, name, "sh", "-c", "read x; exit 0")
		start := time.Now()
		if err := m.StopWithCommand(ctx, name, "EXIT"); err != nil {
			t.Fatal(err)
		}
		d := time.Since(start)
		state, code, err := m.Status(ctx, name)
		t.Logf("duration=%s state=%s exit=%d err=%v", d, state, code, err)
		if state == "running" || d > 5*time.Second || code != 0 {
			t.Fatalf("expected a quick, clean exit (duration=%s state=%s exit=%d)", d, state, code)
		}
	})

	t.Run("container ignores the command", func(t *testing.T) {
		const name = "ewtest-stop-ignore"
		startTestContainer(t, name, "sleep", "600")
		start := time.Now()
		if err := m.StopWithCommand(ctx, name, "EXIT"); err != nil {
			t.Fatal(err)
		}
		d := time.Since(start)
		state, code, err := m.Status(ctx, name)
		t.Logf("duration=%s state=%s exit=%d err=%v", d, state, code, err)
		if state == "running" || d < 35*time.Second || d > 55*time.Second || code != 137 {
			t.Fatalf("expected the fallback after ~40s and exit 137 (duration=%s state=%s exit=%d)", d, state, code)
		}
	})
}
