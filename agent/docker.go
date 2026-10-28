package main

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
)

const (
	managedLabel   = "epicwing.managed"
	dockerTimeout  = 60 * time.Second
	stopGraceSecs  = 30
	containerHome  = "/home/container"
	defaultDataDir = "/var/lib/epicwing/servers"
)

var (
	containerNameRe = regexp.MustCompile(`^[a-z0-9][a-z0-9_.-]{0,62}$`)
	envKeyRe        = regexp.MustCompile(`^[A-Za-z_][A-Za-z0-9_]{0,127}$`)
	errNotManaged   = errors.New("container is not managed by epicwing")
)

type PortMapping struct {
	Host      int    `json:"host"`
	Container int    `json:"container"`
	Proto     string `json:"proto"`
}

// ContainerSpec describes a container. MemoryMB and CPUs of 0 mean unlimited.
// Data mounts <policy data dir>/<name> at /home/container and runs the container
// as the agent's own user, so the files stay writable without root.
type ContainerSpec struct {
	Name     string            `json:"name"`
	Image    string            `json:"image"`
	Ports    []PortMapping     `json:"ports"`
	Env      map[string]string `json:"env"`
	MemoryMB int               `json:"memory_mb"`
	CPUs     float64           `json:"cpus"`
	Data     bool              `json:"data"`
}

// ContainerPolicy is set per node: which images may run and which host ports may be used.
type ContainerPolicy struct {
	AllowedImages []string
	PortMin       int
	PortMax       int
	ImageCaps     map[string][]string
	BindIP        string
	DataDir       string
}

type dockerRunner func(ctx context.Context, args ...string) (string, error)

type containerManager struct {
	policy   ContainerPolicy
	run      dockerRunner
	mkdir    func(path string, perm os.FileMode) error
	uid, gid int
}

func newContainerManager(policy ContainerPolicy) *containerManager {
	return &containerManager{
		policy: policy,
		run:    runDocker,
		mkdir:  os.MkdirAll,
		uid:    os.Getuid(),
		gid:    os.Getgid(),
	}
}

func runDocker(ctx context.Context, args ...string) (string, error) {
	ctx, cancel := context.WithTimeout(ctx, dockerTimeout)
	defer cancel()
	var out, errOut bytes.Buffer
	cmd := exec.CommandContext(ctx, "docker", args...)
	cmd.Stdout = &out
	cmd.Stderr = &errOut
	if err := cmd.Run(); err != nil {
		return "", fmt.Errorf("docker %s: %w: %s", args[0], err, strings.TrimSpace(errOut.String()))
	}
	return strings.TrimSpace(out.String()), nil
}

// validDataDir accepts a clean absolute path without characters that would break
// the --mount option.
func validDataDir(dir string) bool {
	return filepath.IsAbs(dir) && filepath.Clean(dir) == dir && dir != "/" &&
		!strings.ContainsAny(dir, ",\r\n\x00")
}

func (m *containerManager) dataPath(name string) string {
	return filepath.Join(m.policy.DataDir, name)
}

func (m *containerManager) validate(spec ContainerSpec) error {
	if !containerNameRe.MatchString(spec.Name) {
		return errors.New("invalid container name")
	}
	allowed := false
	for _, image := range m.policy.AllowedImages {
		if image == spec.Image {
			allowed = true
			break
		}
	}
	if !allowed {
		return fmt.Errorf("image %q is not on the allowlist", spec.Image)
	}
	if len(spec.Ports) > 32 {
		return errors.New("too many ports")
	}
	for _, p := range spec.Ports {
		if p.Host < m.policy.PortMin || p.Host > m.policy.PortMax {
			return fmt.Errorf("host port %d is outside the node's port range", p.Host)
		}
		if p.Container < 1 || p.Container > 65535 {
			return fmt.Errorf("invalid container port %d", p.Container)
		}
		if p.Proto != "tcp" && p.Proto != "udp" {
			return fmt.Errorf("invalid protocol %q", p.Proto)
		}
	}
	if len(spec.Env) > 64 {
		return errors.New("too many environment variables")
	}
	for k, v := range spec.Env {
		if !envKeyRe.MatchString(k) {
			return fmt.Errorf("invalid environment variable name %q", k)
		}
		if strings.ContainsAny(v, "\x00\r\n") || len(v) > 4096 {
			return fmt.Errorf("invalid value for %s", k)
		}
	}
	if spec.MemoryMB != 0 && (spec.MemoryMB < 16 || spec.MemoryMB > 65536) {
		return errors.New("memory limit must be 0 (unlimited) or between 16 and 65536 MB")
	}
	if spec.CPUs != 0 && (spec.CPUs < 0.1 || spec.CPUs > 64) {
		return errors.New("cpu limit must be 0 (unlimited) or between 0.1 and 64")
	}
	if spec.Data && !validDataDir(m.policy.DataDir) {
		return errors.New("the policy has no valid data_dir")
	}
	return nil
}

func (m *containerManager) createArgs(spec ContainerSpec) []string {
	args := []string{
		"create",
		"--name", spec.Name,
		"--label", managedLabel + "=true",
		"--cap-drop", "ALL",
		"--security-opt", "no-new-privileges",
		"--pids-limit", "512",
	}
	if spec.MemoryMB > 0 {
		args = append(args, "--memory", strconv.Itoa(spec.MemoryMB)+"m")
	}
	if spec.CPUs > 0 {
		args = append(args, "--cpus", strconv.FormatFloat(spec.CPUs, 'f', -1, 64))
	}
	if spec.Data {
		args = append(args,
			"--user", fmt.Sprintf("%d:%d", m.uid, m.gid),
			"--mount", "type=bind,src="+m.dataPath(spec.Name)+",dst="+containerHome,
			"-w", containerHome,
			"-e", "HOME="+containerHome,
			"--interactive", "--tty",
		)
	}
	for _, c := range m.policy.ImageCaps[spec.Image] {
		args = append(args, "--cap-add", c)
	}
	for _, p := range spec.Ports {
		args = append(args, "-p", fmt.Sprintf("%s:%d:%d/%s", m.bindAddr(), p.Host, p.Container, p.Proto))
	}
	keys := make([]string, 0, len(spec.Env))
	for k := range spec.Env {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	for _, k := range keys {
		args = append(args, "-e", k+"="+spec.Env[k])
	}
	return append(args, spec.Image)
}

// Create validates the spec and creates (does not start) a labelled container. Returns its ID.
func (m *containerManager) Create(ctx context.Context, spec ContainerSpec) (string, error) {
	if err := m.validate(spec); err != nil {
		return "", err
	}
	if spec.Data {
		if err := m.mkdir(m.dataPath(spec.Name), 0o750); err != nil {
			return "", fmt.Errorf("creating the data directory: %w", err)
		}
	}
	return m.run(ctx, m.createArgs(spec)...)
}

func (m *containerManager) requireManaged(ctx context.Context, name string) error {
	if !containerNameRe.MatchString(name) {
		return errors.New("invalid container name")
	}
	out, err := m.run(ctx, "inspect", "--format", `{{index .Config.Labels "`+managedLabel+`"}}`, name)
	if err != nil {
		return err
	}
	if out != "true" {
		return errNotManaged
	}
	return nil
}

// Status returns the Docker state (created, running, exited, ...) and the exit code.
func (m *containerManager) Status(ctx context.Context, name string) (string, int, error) {
	if !containerNameRe.MatchString(name) {
		return "", 0, errors.New("invalid container name")
	}
	format := `{{index .Config.Labels "` + managedLabel + `"}}|{{.State.Status}}|{{.State.ExitCode}}`
	out, err := m.run(ctx, "inspect", "--format", format, name)
	if err != nil {
		return "", 0, err
	}
	parts := strings.Split(out, "|")
	if parts[0] != "true" {
		return "", 0, errNotManaged
	}
	if len(parts) != 3 {
		return "", 0, fmt.Errorf("unexpected inspect output %q", out)
	}
	code, _ := strconv.Atoi(parts[2])
	return parts[1], code, nil
}

func (m *containerManager) Start(ctx context.Context, name string) error {
	if err := m.requireManaged(ctx, name); err != nil {
		return err
	}
	_, err := m.run(ctx, "start", name)
	return err
}

func (m *containerManager) Stop(ctx context.Context, name string) error {
	if err := m.requireManaged(ctx, name); err != nil {
		return err
	}
	_, err := m.run(ctx, "stop", "-t", strconv.Itoa(stopGraceSecs), name)
	return err
}

func (m *containerManager) Kill(ctx context.Context, name string) error {
	if err := m.requireManaged(ctx, name); err != nil {
		return err
	}
	_, err := m.run(ctx, "kill", name)
	return err
}

func (m *containerManager) Remove(ctx context.Context, name string) error {
	if err := m.requireManaged(ctx, name); err != nil {
		return err
	}
	_, err := m.run(ctx, "rm", "-f", name)
	return err
}
