package main

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"testing"
)

func dispatchTestDispatcher(label string) (*commandDispatcher, *[][]string) {
	m, calls := containerTestManager(label)
	return &commandDispatcher{containers: m, slots: make(chan struct{}, maxOpenCommands)}, calls
}

func rawJSON(s string) json.RawMessage { return json.RawMessage(s) }

const dispatchCreateParams = `{"name":"web-1","image":"nginx:1.27","ports":[{"host":25001,"container":80,"proto":"tcp"}],"env":{},"memory_mb":256,"cpus":0.5}`

func TestDispatchCreate(t *testing.T) {
	d, _ := dispatchTestDispatcher("true")
	data, err := d.execute(context.Background(), "container.create", rawJSON(dispatchCreateParams))
	if err != nil {
		t.Fatal(err)
	}
	if data["id"] != "abc123" {
		t.Fatalf("unexpected data %v", data)
	}
}

func TestDispatchRejectsUnknownFields(t *testing.T) {
	d, calls := dispatchTestDispatcher("true")
	params := `{"name":"web-1","image":"nginx:1.27","ports":[],"env":{},"memory_mb":256,"cpus":0.5,"privileged":true}`
	if _, err := d.execute(context.Background(), "container.create", rawJSON(params)); err == nil {
		t.Fatal("expected an error")
	}
	if len(*calls) != 0 {
		t.Fatal("docker must not be called")
	}
}

func TestDispatchRefusesUnmanaged(t *testing.T) {
	d, _ := dispatchTestDispatcher("")
	_, err := d.execute(context.Background(), "container.remove", rawJSON(`{"name":"wings-1"}`))
	if !errors.Is(err, errNotManaged) {
		t.Fatalf("expected errNotManaged, got %v", err)
	}
}

func TestDispatchUnknownActionAndMissingParams(t *testing.T) {
	d, calls := dispatchTestDispatcher("true")
	if _, err := d.execute(context.Background(), "shell.run", rawJSON(`{}`)); err == nil {
		t.Fatal("expected an error for an unknown action")
	}
	if _, err := d.execute(context.Background(), "container.start", nil); err == nil {
		t.Fatal("expected an error for missing params")
	}
	if len(*calls) != 0 {
		t.Fatal("docker must not be called")
	}
}

func TestDispatchResultFrame(t *testing.T) {
	ok := resultFrame("1", map[string]any{"id": "x"}, nil)
	if ok["ok"] != true || ok["data"] == nil {
		t.Fatalf("unexpected %v", ok)
	}
	bad := resultFrame("2", nil, errors.New("boom"))
	if bad["ok"] != false || bad["error"] != "boom" {
		t.Fatalf("unexpected %v", bad)
	}
}

func TestDispatchPolicyFile(t *testing.T) {
	file := filepath.Join(t.TempDir(), "policy.json")

	if p := loadPolicyFile(file); len(p.AllowedImages) != 0 || p.PortMin <= p.PortMax {
		t.Fatalf("a missing file must deny everything: %+v", p)
	}

	good := `{"allowed_images":["nginx:1.27"],"port_min":25000,"port_max":25100}`
	if err := os.WriteFile(file, []byte(good), 0o600); err != nil {
		t.Fatal(err)
	}
	p := loadPolicyFile(file)
	if len(p.AllowedImages) != 1 || p.PortMin != 25000 || p.PortMax != 25100 {
		t.Fatalf("unexpected policy %+v", p)
	}

	bad := `{"allowed_images":["nginx:1.27"],"port_min":0,"port_max":0}`
	if err := os.WriteFile(file, []byte(bad), 0o600); err != nil {
		t.Fatal(err)
	}
	if p := loadPolicyFile(file); p.PortMin <= p.PortMax {
		t.Fatalf("an invalid range must deny every port: %+v", p)
	}
}
