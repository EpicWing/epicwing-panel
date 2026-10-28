package main

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestImageCapsAddedToCreateArgs(t *testing.T) {
	m, calls := containerTestManager("true")
	m.policy.ImageCaps = map[string][]string{"nginx:1.27": {"CHOWN", "SETUID"}}
	if _, err := m.Create(context.Background(), containerTestSpec()); err != nil {
		t.Fatal(err)
	}
	joined := strings.Join((*calls)[0], " ")
	for _, want := range []string{"--cap-drop ALL", "--cap-add CHOWN", "--cap-add SETUID"} {
		if !strings.Contains(joined, want) {
			t.Errorf("missing %q in %q", want, joined)
		}
	}
	if strings.Contains(joined, "--cap-add SETGID") {
		t.Errorf("unexpected capability in %q", joined)
	}
}

func TestNoCapsWithoutPolicyEntry(t *testing.T) {
	m, calls := containerTestManager("true")
	if _, err := m.Create(context.Background(), containerTestSpec()); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(strings.Join((*calls)[0], " "), "--cap-add") {
		t.Fatal("no capability may be added without a policy entry")
	}
}

func TestValidImageCaps(t *testing.T) {
	images := []string{"nginx:1.27"}
	cases := map[string]struct {
		caps map[string][]string
		want bool
	}{
		"empty":            {nil, true},
		"allowed":          {map[string][]string{"nginx:1.27": {"CHOWN", "SETUID", "SETGID"}}, true},
		"sys_admin":        {map[string][]string{"nginx:1.27": {"SYS_ADMIN"}}, false},
		"all":              {map[string][]string{"nginx:1.27": {"ALL"}}, false},
		"lowercase":        {map[string][]string{"nginx:1.27": {"chown"}}, false},
		"image not listed": {map[string][]string{"alpine:3": {"CHOWN"}}, false},
	}
	for name, tc := range cases {
		t.Run(name, func(t *testing.T) {
			if got := validImageCaps(tc.caps, images); got != tc.want {
				t.Fatalf("got %v, want %v", got, tc.want)
			}
		})
	}
}

func TestPolicyFileWithImageCaps(t *testing.T) {
	file := filepath.Join(t.TempDir(), "policy.json")
	write := func(s string) {
		if err := os.WriteFile(file, []byte(s), 0o600); err != nil {
			t.Fatal(err)
		}
	}

	write(`{"allowed_images":["nginx:1.27"],"port_min":25000,"port_max":25100,"image_caps":{"nginx:1.27":["CHOWN"]}}`)
	p := loadPolicyFile(file)
	if len(p.ImageCaps["nginx:1.27"]) != 1 || p.PortMin != 25000 {
		t.Fatalf("unexpected policy %+v", p)
	}

	write(`{"allowed_images":["nginx:1.27"],"port_min":25000,"port_max":25100,"image_caps":{"nginx:1.27":["SYS_ADMIN"]}}`)
	if p := loadPolicyFile(file); len(p.AllowedImages) != 0 || p.PortMin <= p.PortMax {
		t.Fatalf("an invalid capability must deny everything: %+v", p)
	}
}
