package main

import (
	"context"
	"errors"
	"strings"
	"testing"
)

func netRunner(inspectFails, createFails bool) (dockerRunner, *[]string) {
	var seen []string
	return func(ctx context.Context, args ...string) (string, error) {
		seen = append(seen, strings.Join(args, " "))
		if args[1] == "inspect" && inspectFails {
			return "", errors.New("no such network")
		}
		if args[1] == "create" && createFails {
			return "", errors.New("boom")
		}
		return "", nil
	}, &seen
}

func TestEnsureServerNetworkCreatesIsolatedNetwork(t *testing.T) {
	serverNetwork.Store("")
	run, seen := netRunner(true, false)
	if err := ensureServerNetwork(context.Background(), run); err != nil {
		t.Fatal(err)
	}
	joined := strings.Join(*seen, "\n")
	for _, want := range []string{"network create", "--ipv6", "enable_icc=false", serverNetworkName} {
		if !strings.Contains(joined, want) {
			t.Errorf("missing %q in %q", want, joined)
		}
	}
	if currentServerNetwork() != serverNetworkName {
		t.Error("network not marked ready")
	}
	serverNetwork.Store("")
}

func TestEnsureServerNetworkKeepsExisting(t *testing.T) {
	serverNetwork.Store("")
	run, seen := netRunner(false, false)
	if err := ensureServerNetwork(context.Background(), run); err != nil {
		t.Fatal(err)
	}
	if len(*seen) != 1 {
		t.Errorf("expected only an inspect call, got %v", *seen)
	}
	serverNetwork.Store("")
}

func TestEnsureServerNetworkFailureLeavesDefaultNetwork(t *testing.T) {
	serverNetwork.Store("")
	run, _ := netRunner(true, true)
	if err := ensureServerNetwork(context.Background(), run); err == nil {
		t.Fatal("expected an error")
	}
	if currentServerNetwork() != "" {
		t.Error("network must not be used after a failure")
	}
}

func TestContainersJoinServerNetwork(t *testing.T) {
	m, calls := containerTestManager("true")
	m.network = serverNetworkName
	if _, err := m.Create(context.Background(), containerTestSpec()); err != nil {
		t.Fatal(err)
	}
	if got := strings.Join((*calls)[0], " "); !strings.Contains(got, "--network "+serverNetworkName) {
		t.Errorf("create without network: %q", got)
	}
	im, _, _ := dataTestManager()
	im.network = serverNetworkName
	args := strings.Join(im.installArgs(InstallSpec{
		Name: "srv-1", Image: "nginx:1.27", InstallerImage: "nginx:1.27",
		InstallerEntrypoint: "bash", InstallScript: "exit 0",
	}), " ")
	if !strings.Contains(args, "--network "+serverNetworkName) {
		t.Errorf("install without network: %q", args)
	}
}

func TestNoNetworkFlagWithoutServerNetwork(t *testing.T) {
	m, calls := containerTestManager("true")
	if _, err := m.Create(context.Background(), containerTestSpec()); err != nil {
		t.Fatal(err)
	}
	if got := strings.Join((*calls)[0], " "); strings.Contains(got, "--network") {
		t.Errorf("unexpected --network: %q", got)
	}
}
