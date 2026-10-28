package main

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"log"
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
	installTimeout = 30 * time.Minute
	stopGraceSecs  = 30
	containerHome  = "/home/container"
	installerRoot  = "/mnt/server"
	defaultDataDir = "/var/lib/epicwing/servers"
)

var (
	containerNameRe   = regexp.MustCompile(`^[a-z0-9][a-z0-9_.-]{0,62}$`)
	shellEntrypointRe = regexp.MustCompile(`^[A-Za-z0-9_./-]+$`)
	envKeyRe          = regexp.MustCompile(`^[A-Za-z_][A-Za-z0-9_]{0,127}$`)
	errNotManaged     = errors.New("container is not managed by epicwing")
)

type PortMapping struct {
	Host      int    `json:"host"`
	Container int    `json:"container"`
	Proto     string `json:"proto"`
	IP        string `json:"ip"`
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

type InstallSpec struct {
	Name                string            `json:"name"`
	Image               string            `json:"image"`
	InstallerImage      string            `json:"installer_image"`
	InstallerEntrypoint string            `json:"installer_entrypoint"`
	Env                 map[string]string `json:"env"`
	MemoryMB            int               `json:"memory_mb"`
	CPUs                float64           `json:"cpus"`
	InstallScript       string            `json:"install_script"`
}

// ContainerPolicy is set per node: which images may run and which host ports may be used.
type ContainerPolicy struct {
	AllowedImages []string
	PortMin       int
	PortMax       int
	ImageCaps     map[string][]string
	ImageDigests  map[string]string
	BindIP        string
	DataDir       string
}

type dockerRunner func(ctx context.Context, args ...string) (string, error)

type containerManager struct {
	policy   ContainerPolicy
	run      dockerRunner
	mkdir    func(path string, perm os.FileMode) error
	uid, gid int
	// inputWriter, stopPoll and stopWait are only set in tests; zero values mean the defaults.
	inputWriter func(ctx context.Context, name, line string) error
	stopPoll    time.Duration
	stopWait    time.Duration
	// portProbe is only set in tests; nil means probePort.
	portProbe portProbe
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
	return runDockerTimeout(ctx, dockerTimeout, args...)
}

func runDockerTimeout(ctx context.Context, timeout time.Duration, args ...string) (string, error) {
	ctx, cancel := context.WithTimeout(ctx, timeout)
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

func (m *containerManager) validateInstall(spec InstallSpec) error {
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
	installerAllowed := false
	for _, image := range m.policy.AllowedImages {
		if image == spec.InstallerImage {
			installerAllowed = true
			break
		}
	}
	if !installerAllowed {
		return fmt.Errorf("installer image %q is not on the allowlist", spec.InstallerImage)
	}
	if spec.InstallerEntrypoint == "" || !shellEntrypointRe.MatchString(spec.InstallerEntrypoint) {
		return errors.New("invalid installer entrypoint")
	}
	if len(spec.InstallScript) == 0 || len(spec.InstallScript) > 65535 || strings.ContainsRune(spec.InstallScript, '\x00') {
		return errors.New("invalid install script")
	}
	if spec.MemoryMB != 0 && (spec.MemoryMB < 16 || spec.MemoryMB > 65536) {
		return errors.New("memory limit must be 0 or between 16 and 65536 MB")
	}
	if spec.CPUs != 0 && (spec.CPUs < 0.1 || spec.CPUs > 64) {
		return errors.New("cpu limit must be 0 or between 0.1 and 64")
	}
	if !validDataDir(m.policy.DataDir) {
		return errors.New("the policy has no valid data_dir")
	}
	return nil
}

// Install runs an egg script in a short-lived installer container against the
// server's data directory. The server container itself stays stopped.
func (m *containerManager) Install(ctx context.Context, spec InstallSpec) (string, error) {
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
	cmd := exec.CommandContext(ctx, "docker", args...)
	cmd.Stdin = strings.NewReader(spec.InstallScript)
	cmd.Stdout = &out
	cmd.Stderr = &errOut
	if err := cmd.Run(); err != nil {
		logs := strings.TrimSpace(out.String() + "\n" + errOut.String())
		if len(logs) > 4000 {
			logs = logs[len(logs)-4000:]
		}
		return logs, fmt.Errorf("install failed: %w: %s", err, logs)
	}
	return strings.TrimSpace(out.String()), nil
}

// installWrapper runs the egg install script and then hands the installed
// files to the runtime user. Positional parameters: $0 is the configured
// shell, $1 the script path, $2 the owner (uid:gid), $3 the target directory.
// The script's exit status is preserved; a failing chown turns an otherwise
// successful install into a failure, so the server never starts with files
// the runtime user cannot write.
const installWrapper = `cat > /tmp/epicwing-install.sh || exit 1; "$0" "$1"; rc=$?; chown -R "$2" "$3" || { [ "$rc" -eq 0 ] && rc=1; }; exit "$rc"`

func (m *containerManager) installArgs(spec InstallSpec) []string {
	args := []string{
		"run", "--rm", "--name", spec.Name + "-install",
		"--cap-drop", "ALL", "--security-opt", "no-new-privileges",
		"--cap-add", "CHOWN", "--cap-add", "DAC_OVERRIDE", "--cap-add", "FOWNER",
		"--pids-limit", "512", "--interactive",
		"--mount", "type=bind,src=" + m.dataPath(spec.Name) + ",dst=" + containerHome,
		// Pterodactyl installation eggs conventionally write to /mnt/server,
		// while EpicWing runtime containers use /home/container. Mount the same
		// controlled server directory at both paths for installer compatibility.
		"--mount", "type=bind,src=" + m.dataPath(spec.Name) + ",dst=" + installerRoot,
		"--workdir", containerHome,
		"--entrypoint", spec.InstallerEntrypoint,
	}
	if spec.MemoryMB > 0 {
		args = append(args, "--memory", strconv.Itoa(spec.MemoryMB)+"m")
	}
	if spec.CPUs > 0 {
		args = append(args, "--cpus", strconv.FormatFloat(spec.CPUs, 'f', -1, 64))
	}
	keys := make([]string, 0, len(spec.Env))
	for k := range spec.Env {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	for _, k := range keys {
		args = append(args, "--env", k+"="+spec.Env[k])
	}
	// Run the script with the same shell selected for the installer image.
	// Imported Pterodactyl eggs commonly contain Bash syntax and must not be
	// forced through /bin/sh (which is dash in the Debian installer image).
	args = append(args,
		m.pinned(spec.InstallerImage),
		"-c", installWrapper,
		spec.InstallerEntrypoint,
		"/tmp/epicwing-install.sh",
		fmt.Sprintf("%d:%d", m.uid, m.gid),
		installerRoot,
	)

	return args
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
		if err := m.checkPortIP(p.IP); err != nil {
			return err
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
		args = append(args, "-p", fmt.Sprintf("%s:%d:%d/%s", m.portAddr(p), p.Host, p.Container, p.Proto))
	}
	keys := make([]string, 0, len(spec.Env))
	for k := range spec.Env {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	for _, k := range keys {
		args = append(args, "-e", k+"="+spec.Env[k])
	}
	return append(args, m.pinned(spec.Image))
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

func (m *containerManager) ManagedNames(ctx context.Context) ([]string, error) {
	out, err := m.run(ctx, "ps", "-a", "--filter", "label="+managedLabel, "--format", "{{.Names}}")
	if err != nil {
		return nil, err
	}
	var names []string
	for _, line := range strings.Split(out, "\n") {
		name := strings.TrimSpace(line)
		if name != "" && containerNameRe.MatchString(name) {
			names = append(names, name)
		}
	}
	sort.Strings(names)
	return names, nil
}

func (m *containerManager) Start(ctx context.Context, name string) error {
	if err := m.requireManaged(ctx, name); err != nil {
		return classifyDockerError(err)
	}
	// Check the host ports first: a busy port is common while a server is moved from
	// another panel, and docker's own error text is not something users should see.
	if err := m.checkPorts(ctx, name); err != nil {
		return err
	}
	_, err := m.run(ctx, "start", name)
	return classifyDockerError(err)
}

const (
	stopFallbackSecs = 10
	defaultStopWait  = 30 * time.Second
	defaultStopPoll  = 500 * time.Millisecond
)

// Stop stops the container with docker stop (SIGTERM, SIGKILL after the grace period).
func (m *containerManager) Stop(ctx context.Context, name string) error {
	return m.StopWithCommand(ctx, name, "")
}

// StopWithCommand sends the egg's stop command into the console and waits for the
// container to exit. If it keeps running or the command cannot be written, it falls
// back to docker stop. Without a usable command it behaves like Stop.
func (m *containerManager) StopWithCommand(ctx context.Context, name, command string) error {
	if err := m.requireManaged(ctx, name); err != nil {
		return err
	}
	grace := stopGraceSecs
	if command != "" {
		if !validConsoleInput(command) {
			log.Printf("invalid stop command for %s, using docker stop", name)
		} else {
			if m.stopViaCommand(ctx, name, command) {
				return nil
			}
			grace = stopFallbackSecs
		}
	}
	_, err := m.run(ctx, "stop", "-t", strconv.Itoa(grace), name)
	return err
}

func (m *containerManager) writeLine(ctx context.Context, name, line string) error {
	if m.inputWriter != nil {
		return m.inputWriter(ctx, name, line)
	}
	return attachWrite(ctx, dockerSocket, name, line+"\n")
}

// stopViaCommand reports whether the container is stopped after the command.
func (m *containerManager) stopViaCommand(ctx context.Context, name, command string) bool {
	state, _, err := m.Status(ctx, name)
	if err != nil {
		return false
	}
	if state != "running" {
		return true
	}
	if err := m.writeLine(ctx, name, command); err != nil {
		log.Printf("stop command for %s failed: %v", name, err)
		return false
	}
	wait, poll := m.stopWait, m.stopPoll
	if wait <= 0 {
		wait = defaultStopWait
	}
	if poll <= 0 {
		poll = defaultStopPoll
	}
	begin := time.Now()
	deadline := begin.Add(wait)
	for time.Now().Before(deadline) {
		sleepCtx(ctx, poll)
		if ctx.Err() != nil {
			return false
		}
		state, _, err := m.Status(ctx, name)
		if err != nil {
			return false
		}
		if state != "running" {
			log.Printf("%s stopped via console command in %s", name, time.Since(begin).Round(time.Millisecond))
			return true
		}
	}
	log.Printf("%s did not stop within %s after the stop command, falling back to docker stop", name, wait)
	return false
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
