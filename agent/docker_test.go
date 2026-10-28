package main

import (
	"context"
	"errors"
	"strings"
	"testing"
)

func containerTestManager(labelValue string) (*containerManager, *[][]string) {
	calls := &[][]string{}
	m := newContainerManager(ContainerPolicy{
		AllowedImages: []string{"nginx:1.27"},
		PortMin:       25000,
		PortMax:       25100,
	})
	m.run = func(ctx context.Context, args ...string) (string, error) {
		*calls = append(*calls, args)
		if args[0] == "inspect" {
			return labelValue, nil
		}
		return "abc123", nil
	}
	return m, calls
}

func containerTestSpec() ContainerSpec {
	return ContainerSpec{
		Name:     "web-1",
		Image:    "nginx:1.27",
		Ports:    []PortMapping{{Host: 25001, Container: 80, Proto: "tcp"}},
		Env:      map[string]string{"A": "1"},
		MemoryMB: 256,
		CPUs:     0.5,
	}
}

func TestContainerCreateValidation(t *testing.T) {
	cases := map[string]func(*ContainerSpec){
		"name with leading dash": func(s *ContainerSpec) { s.Name = "-rm" },
		"name with space":        func(s *ContainerSpec) { s.Name = "a b" },
		"image not allowed":      func(s *ContainerSpec) { s.Image = "alpine:3" },
		"image without tag":      func(s *ContainerSpec) { s.Image = "nginx" },
		"host port too low":      func(s *ContainerSpec) { s.Ports[0].Host = 80 },
		"host port too high":     func(s *ContainerSpec) { s.Ports[0].Host = 25101 },
		"bad protocol":           func(s *ContainerSpec) { s.Ports[0].Proto = "sctp" },
		"bad env name":           func(s *ContainerSpec) { s.Env = map[string]string{"A=B": "1"} },
		"env newline":            func(s *ContainerSpec) { s.Env = map[string]string{"A": "x\ny"} },
	}
	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			m, calls := containerTestManager("true")
			spec := containerTestSpec()
			mutate(&spec)
			if _, err := m.Create(context.Background(), spec); err == nil {
				t.Fatal("expected an error")
			}
			if len(*calls) != 0 {
				t.Fatal("docker must not be called for an invalid spec")
			}
		})
	}
}

func TestContainerCreateArgs(t *testing.T) {
	m, calls := containerTestManager("true")
	if _, err := m.Create(context.Background(), containerTestSpec()); err != nil {
		t.Fatal(err)
	}
	joined := strings.Join((*calls)[0], " ")
	for _, want := range []string{
		"--label epicwing.managed=true",
		"--cap-drop ALL",
		"--security-opt no-new-privileges",
		"-p 127.0.0.1:25001:80/tcp",
		"--memory 256m",
	} {
		if !strings.Contains(joined, want) {
			t.Errorf("missing %q in %q", want, joined)
		}
	}
	for _, forbidden := range []string{"--privileged", " -v ", "--volume", "--mount", "--network host", "--pid ", "--pid="} {
		if strings.Contains(joined, forbidden) {
			t.Errorf("forbidden %q in %q", forbidden, joined)
		}
	}
	if !strings.HasSuffix(joined, "nginx:1.27") {
		t.Errorf("image must be the last argument: %q", joined)
	}
}

func TestContainerActionsRefuseUnmanaged(t *testing.T) {
	actions := map[string]func(*containerManager) error{
		"start":  func(m *containerManager) error { return m.Start(context.Background(), "wings-1") },
		"stop":   func(m *containerManager) error { return m.Stop(context.Background(), "wings-1") },
		"remove": func(m *containerManager) error { return m.Remove(context.Background(), "wings-1") },
	}
	for name, act := range actions {
		t.Run(name, func(t *testing.T) {
			m, calls := containerTestManager("")
			if err := act(m); !errors.Is(err, errNotManaged) {
				t.Fatalf("expected errNotManaged, got %v", err)
			}
			if len(*calls) != 1 || (*calls)[0][0] != "inspect" {
				t.Fatalf("only the label check may run, got %v", *calls)
			}
		})
	}
}

func TestContainerActionsManaged(t *testing.T) {
	m, calls := containerTestManager("true")
	if err := m.Start(context.Background(), "web-1"); err != nil {
		t.Fatal(err)
	}
	if err := m.Stop(context.Background(), "web-1"); err != nil {
		t.Fatal(err)
	}
	if err := m.Remove(context.Background(), "web-1"); err != nil {
		t.Fatal(err)
	}
	if len(*calls) != 6 {
		t.Fatalf("expected 6 docker calls, got %d", len(*calls))
	}
}

func TestContainerInvalidNameNeverReachesDocker(t *testing.T) {
	m, calls := containerTestManager("true")
	if err := m.Start(context.Background(), "--all"); err == nil {
		t.Fatal("expected an error")
	}
	if len(*calls) != 0 {
		t.Fatal("docker must not be called")
	}
}
