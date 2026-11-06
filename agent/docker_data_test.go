package main

import (
	"context"
	"errors"
	"os"
	"strings"
	"testing"
)

func dataTestManager() (*containerManager, *[][]string, *[]string) {
	m, calls := containerTestManager("true")
	m.policy.DataDir = "/srv/data"
	m.uid, m.gid = 993, 983
	made := &[]string{}
	m.mkdir = func(path string, _ os.FileMode) error {
		*made = append(*made, path)
		return nil
	}
	return m, calls, made
}

func TestUnlimitedResourcesOmitDockerLimits(t *testing.T) {
	m, calls := containerTestManager("true")
	spec := containerTestSpec()
	spec.MemoryMB, spec.CPUs = 0, 0
	if _, err := m.Create(context.Background(), spec); err != nil {
		t.Fatal(err)
	}
	joined := strings.Join((*calls)[0], " ")
	for _, flag := range []string{"--memory", "--memory-swap", "--cpus"} {
		if strings.Contains(joined, flag) {
			t.Errorf("%s must be left out for unlimited: %q", flag, joined)
		}
	}
}

func TestInvalidLimitsAreRejected(t *testing.T) {
	cases := map[string]func(*ContainerSpec){
		"memory too small": func(s *ContainerSpec) { s.MemoryMB = 8 },
		"memory too big":   func(s *ContainerSpec) { s.MemoryMB = 70000 },
		"memory negative":  func(s *ContainerSpec) { s.MemoryMB = -1 },
		"cpu too small":    func(s *ContainerSpec) { s.CPUs = 0.05 },
		"cpu too big":      func(s *ContainerSpec) { s.CPUs = 65 },
		"cpu negative":     func(s *ContainerSpec) { s.CPUs = -1 },
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
				t.Fatal("docker must not be called")
			}
		})
	}
}

func TestDataMount(t *testing.T) {
	m, calls, made := dataTestManager()
	spec := containerTestSpec()
	spec.Name = "srv-1"
	spec.Data = true
	if _, err := m.Create(context.Background(), spec); err != nil {
		t.Fatal(err)
	}
	joined := strings.Join((*calls)[0], " ")
	for _, want := range []string{
		"--user 993:983",
		"--mount type=bind,src=/srv/data/srv-1,dst=/home/container",
		"-w /home/container",
		"-e HOME=/home/container",
		"--interactive",
		"--tty",
	} {
		if !strings.Contains(joined, want) {
			t.Errorf("missing %q in %q", want, joined)
		}
	}
	for _, forbidden := range []string{" -v ", "--volume", "--privileged"} {
		if strings.Contains(joined, forbidden) {
			t.Errorf("forbidden %q in %q", forbidden, joined)
		}
	}
	if len(*made) != 1 || (*made)[0] != "/srv/data/srv-1" {
		t.Fatalf("unexpected directories %v", *made)
	}
}

func TestDataNeedsAValidDirectory(t *testing.T) {
	for _, dir := range []string{"", "relative/path", "/a,b", "/a/../b", "/"} {
		m, calls := containerTestManager("true")
		m.policy.DataDir = dir
		spec := containerTestSpec()
		spec.Data = true
		if _, err := m.Create(context.Background(), spec); err == nil {
			t.Fatalf("data_dir %q must be refused", dir)
		}
		if len(*calls) != 0 {
			t.Fatal("docker must not be called")
		}
	}
}

func TestInstallArgsUseBothDataMountsAndConfiguredShell(t *testing.T) {
	m, _, _ := dataTestManager()
	spec := InstallSpec{
		Name:                "srv-1",
		Image:               "nginx:1.27",
		InstallerImage:      "nginx:1.27",
		InstallerEntrypoint: "bash",
		InstallScript:       "#!/bin/bash\nexit 0",
	}
	args := strings.Join(m.installArgs(spec), " ")

	for _, want := range []string{
		"--mount type=bind,src=/srv/data/srv-1,dst=/home/container",
		"--mount type=bind,src=/srv/data/srv-1,dst=/mnt/server",
		"--workdir /home/container",
		"--entrypoint bash",
		installWrapper,
		"--cap-add CHOWN --cap-add DAC_OVERRIDE --cap-add FOWNER",
		"bash /tmp/epicwing-install.sh 993:983 /mnt/server",
	} {
		if !strings.Contains(args, want) {
			t.Errorf("missing %q in %q", want, args)
		}
	}

	if strings.Contains(args, "/bin/sh /tmp/epicwing-install.sh") {
		t.Fatalf("installer must not force scripts through /bin/sh: %q", args)
	}
}

func TestInstallRejectsUnsafeEntrypoint(t *testing.T) {
	m, _, _ := dataTestManager()
	spec := InstallSpec{
		Name:                "srv-1",
		Image:               "nginx:1.27",
		InstallerImage:      "nginx:1.27",
		InstallerEntrypoint: "bash; touch /tmp/unexpected",
		InstallScript:       "exit 0",
	}
	if err := m.validateInstall(spec); err == nil {
		t.Fatal("expected unsafe installer entrypoint to be rejected")
	}
}

func TestStatus(t *testing.T) {
	cases := []struct {
		out   string
		state string
		code  int
		err   error
	}{
		{"true|running|0", "running", 0, nil},
		{"true|exited|137", "exited", 137, nil},
		{"", "", 0, errNotManaged},
		{"|running|0", "", 0, errNotManaged},
	}
	for _, c := range cases {
		m, _ := containerTestManager("true")
		out := c.out
		m.run = func(ctx context.Context, args ...string) (string, error) { return out, nil }
		state, code, err := m.Status(context.Background(), "web-1")
		if !errors.Is(err, c.err) || state != c.state || code != c.code {
			t.Errorf("%q: got %q %d %v", c.out, state, code, err)
		}
	}
}

func TestKill(t *testing.T) {
	m, calls := containerTestManager("true")
	if err := m.Kill(context.Background(), "web-1"); err != nil {
		t.Fatal(err)
	}
	if len(*calls) != 2 || (*calls)[1][0] != "kill" {
		t.Fatalf("unexpected calls %v", *calls)
	}
	m, calls = containerTestManager("")
	if err := m.Kill(context.Background(), "wings-1"); !errors.Is(err, errNotManaged) {
		t.Fatalf("expected errNotManaged, got %v", err)
	}
	if len(*calls) != 1 {
		t.Fatalf("only the label check may run, got %v", *calls)
	}
}

func TestDispatchKillAndStatus(t *testing.T) {
	d, _ := dispatchTestDispatcher("true")
	d.containers.run = func(ctx context.Context, args ...string) (string, error) {
		if args[0] == "inspect" {
			if strings.Contains(strings.Join(args, " "), "State.Status") {
				return "true|running|0", nil
			}
			return "true", nil
		}
		return "", nil
	}
	if _, err := d.execute(context.Background(), "container.kill", rawJSON(`{"name":"web-1"}`)); err != nil {
		t.Fatal(err)
	}
	data, err := d.execute(context.Background(), "container.status", rawJSON(`{"name":"web-1"}`))
	if err != nil {
		t.Fatal(err)
	}
	if data["state"] != "running" || data["exit_code"] != 0 {
		t.Fatalf("unexpected data %v", data)
	}
}

func TestPolicyDataDirDefaultsAndValidation(t *testing.T) {
	file := t.TempDir() + "/policy.json"
	write := func(s string) {
		if err := os.WriteFile(file, []byte(s), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	write(`{"allowed_images":["nginx:1.27"],"port_min":25000,"port_max":25100}`)
	if p := loadPolicyFile(file); p.DataDir != defaultDataDir {
		t.Fatalf("expected the default data dir, got %q", p.DataDir)
	}
	write(`{"allowed_images":["nginx:1.27"],"port_min":25000,"port_max":25100,"data_dir":"rel"}`)
	if p := loadPolicyFile(file); len(p.AllowedImages) != 0 {
		t.Fatalf("an invalid data_dir must deny everything: %+v", p)
	}
}
