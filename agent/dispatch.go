package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"strings"
	"sync"

	"github.com/coder/websocket"
)

const (
	maxOpenCommands   = 8
	maxResultErrorLen = 1000
	policyFileName    = "policy.json"
)

// panelFrame is every message the panel can send after the login.
type panelFrame struct {
	Type    string          `json:"type"`
	Message string          `json:"message"`
	ID      string          `json:"id"`
	Action  string          `json:"action"`
	Params  json.RawMessage `json:"params"`
}

type policyFile struct {
	AllowedImages []string            `json:"allowed_images"`
	PortMin       int                 `json:"port_min"`
	PortMax       int                 `json:"port_max"`
	ImageCaps     map[string][]string `json:"image_caps"`
	BindIP        string              `json:"bind_ip"`
	DataDir       string              `json:"data_dir"`
}

// loadContainerPolicy reads policy.json next to the config file.
func loadContainerPolicy() ContainerPolicy {
	return loadPolicyFile(filepath.Join(filepath.Dir(configPath()), policyFileName))
}

// loadPolicyFile returns an empty policy (no image, no port) when the file is
// missing or invalid, so the agent then refuses to create containers.
func loadPolicyFile(file string) ContainerPolicy {
	deny := ContainerPolicy{PortMin: 1, PortMax: 0}
	data, err := os.ReadFile(file)
	if err != nil {
		log.Printf("no container policy (%v), creating containers is disabled", err)
		return deny
	}
	var p policyFile
	if err := json.Unmarshal(data, &p); err != nil {
		log.Printf("invalid %s (%v), creating containers is disabled", file, err)
		return deny
	}
	if p.PortMin < 1 || p.PortMax > 65535 || p.PortMin > p.PortMax {
		log.Printf("invalid port range in %s, creating containers is disabled", file)
		return ContainerPolicy{AllowedImages: p.AllowedImages, PortMin: 1, PortMax: 0}
	}
	if !validImageCaps(p.ImageCaps, p.AllowedImages) {
		log.Printf("invalid image_caps in %s, creating containers is disabled", file)
		return deny
	}
	if p.BindIP != "" && !validBindIP(p.BindIP) {
		log.Printf("invalid bind_ip in %s, creating containers is disabled", file)
		return deny
	}
	if p.DataDir == "" {
		p.DataDir = defaultDataDir
	}
	if !validDataDir(p.DataDir) {
		log.Printf("invalid data_dir in %s, creating containers is disabled", file)
		return deny
	}
	return ContainerPolicy{
		AllowedImages: p.AllowedImages,
		PortMin:       p.PortMin,
		PortMax:       p.PortMax,
		ImageCaps:     p.ImageCaps,
		BindIP:        p.BindIP,
		DataDir:       p.DataDir,
	}
}

type commandDispatcher struct {
	mu         sync.Mutex
	slots      chan struct{}
	containers *containerManager
	console    *consoleManager
}

func newCommandDispatcher(policy ContainerPolicy) *commandDispatcher {
	return &commandDispatcher{
		slots:      make(chan struct{}, maxOpenCommands),
		containers: newContainerManager(policy),
	}
}

func decodeParams(raw json.RawMessage, v any) error {
	if len(raw) == 0 {
		return errors.New("missing params")
	}
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.DisallowUnknownFields()
	if err := dec.Decode(v); err != nil {
		return fmt.Errorf("invalid params: %w", err)
	}
	return nil
}

func (d *commandDispatcher) execute(ctx context.Context, action string, params json.RawMessage) (map[string]any, error) {
	if strings.HasPrefix(action, "console.") {
		return d.console.execute(ctx, action, params)
	}
	switch action {
	case "container.create":
		var spec ContainerSpec
		if err := decodeParams(params, &spec); err != nil {
			return nil, err
		}
		id, err := d.containers.Create(ctx, spec)
		if err != nil {
			return nil, err
		}
		return map[string]any{"id": id}, nil
	case "container.install":
		var spec InstallSpec
		if err := decodeParams(params, &spec); err != nil {
			return nil, err
		}
		logs, err := d.containers.Install(ctx, spec)
		data := map[string]any{}
		if logs != "" {
			data["output"] = logs
		}
		return data, err
	case "container.start", "container.stop", "container.kill", "container.remove", "container.status":
		var p struct {
			Name    string `json:"name"`
			Command string `json:"command"`
		}
		if err := decodeParams(params, &p); err != nil {
			return nil, err
		}
		if p.Command != "" && action != "container.stop" {
			return nil, errors.New("command is only valid for container.stop")
		}
		switch action {
		case "container.start":
			if bkJobs.isBusy(p.Name) {
				return nil, errors.New("a backup operation is running for this server")
			}
			d.announce(p.Name, "Server marked as starting...")
			return nil, d.containers.Start(ctx, p.Name)
		case "container.stop":
			return nil, d.containers.StopWithCommand(ctx, p.Name, p.Command)
		case "container.kill":
			return nil, d.containers.Kill(ctx, p.Name)
		case "container.status":
			state, code, err := d.containers.Status(ctx, p.Name)
			if err != nil {
				return nil, err
			}
			return map[string]any{"state": state, "exit_code": code}, nil
		default:
			return nil, d.containers.Remove(ctx, p.Name)
		}
	default:
		return nil, fmt.Errorf("unknown action %q", action)
	}
}

// lockFree lists the actions that must not wait for other commands: a stop can take
// up to 40 seconds and kill is the way out when it hangs.
func lockFree(action string) bool {
	return action == "container.stop" || action == "container.kill"
}

func resultFrame(id string, data map[string]any, err error) map[string]any {
	frame := map[string]any{"type": "result", "id": id, "ok": err == nil}
	if err != nil {
		msg := err.Error()
		if len(msg) > maxResultErrorLen {
			msg = strings.ToValidUTF8(msg[:maxResultErrorLen], "")
		}
		frame["error"] = msg
	} else if data != nil {
		frame["data"] = data
	}
	return frame
}

func (d *commandDispatcher) run(ctx context.Context, conn *websocket.Conn, f panelFrame) {
	var frame map[string]any
	select {
	case d.slots <- struct{}{}:
		defer func() { <-d.slots }()
		var data map[string]any
		var err error
		if strings.HasPrefix(f.Action, "file.") {
			data, err = d.executeFile(f.Action, f.Params)
		} else if strings.HasPrefix(f.Action, "backup.") {
			data, err = d.executeBackup(f.Action, f.Params)
		} else if lockFree(f.Action) {
			data, err = d.execute(ctx, f.Action, f.Params)
		} else {
			d.mu.Lock()
			data, err = d.execute(ctx, f.Action, f.Params)
			d.mu.Unlock()
		}
		if err != nil {
			log.Printf("command %s (%s) failed: %v", f.ID, f.Action, err)
		}
		frame = resultFrame(f.ID, data, err)
	default:
		frame = resultFrame(f.ID, nil, errors.New("too many open commands"))
	}
	if err := writeJSON(ctx, conn, ioTimeout, frame); err != nil {
		log.Printf("sending result for %s: %v", f.ID, err)
	}
}

// readLoop reads every frame from the panel until the connection breaks. The panel
// answers each heartbeat, so silence for three intervals means the connection is dead.
func readLoop(ctx context.Context, conn *websocket.Conn, d *commandDispatcher) error {
	for {
		var f panelFrame
		if err := readJSON(ctx, conn, 3*heartbeatInterval, &f); err != nil {
			return fmt.Errorf("reading from the panel: %w", err)
		}
		switch f.Type {
		case "heartbeat_ack":
		case "error":
			log.Printf("the panel rejected a message: %s", f.Message)
		case "command":
			go d.run(ctx, conn, f)
		}
	}
}
