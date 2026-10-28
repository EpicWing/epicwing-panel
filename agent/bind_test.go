package main

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestBindAddrDefaultsToLoopback(t *testing.T) {
	m, _ := containerTestManager("true")
	if got := m.bindAddr(); got != "127.0.0.1" {
		t.Fatalf("got %q", got)
	}
}

func TestCreateArgsUseBindIP(t *testing.T) {
	m, calls := containerTestManager("true")
	m.policy.BindIP = "10.1.2.3"
	if _, err := m.Create(context.Background(), containerTestSpec()); err != nil {
		t.Fatal(err)
	}
	joined := strings.Join((*calls)[0], " ")
	if !strings.Contains(joined, "-p 10.1.2.3:25001:80/tcp") {
		t.Fatalf("missing bind address in %q", joined)
	}
	if strings.Contains(joined, "0.0.0.0") {
		t.Fatalf("must not bind to all interfaces: %q", joined)
	}
}

func TestValidBindIP(t *testing.T) {
	cases := map[string]bool{
		"127.0.0.1":      true,
		"0.0.0.0":        false,
		"999.1.1.1":      false,
		"::1":            false,
		"::ffff:7.7.7.7": false,
		"192.0.2.1":      false,
		"":               false,
		"localhost":      false,
	}
	for in, want := range cases {
		if got := validBindIP(in); got != want {
			t.Errorf("validBindIP(%q) = %v, want %v", in, got, want)
		}
	}
}

func TestPolicyFileBindIP(t *testing.T) {
	file := filepath.Join(t.TempDir(), "policy.json")
	write := func(s string) {
		if err := os.WriteFile(file, []byte(s), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	write(`{"allowed_images":["nginx:1.27"],"port_min":25000,"port_max":25100,"bind_ip":"127.0.0.1"}`)
	if p := loadPolicyFile(file); p.BindIP != "127.0.0.1" || p.PortMin != 25000 {
		t.Fatalf("unexpected policy %+v", p)
	}
	write(`{"allowed_images":["nginx:1.27"],"port_min":25000,"port_max":25100,"bind_ip":"0.0.0.0"}`)
	if p := loadPolicyFile(file); len(p.AllowedImages) != 0 || p.PortMin <= p.PortMax {
		t.Fatalf("an invalid bind_ip must deny everything: %+v", p)
	}
}
