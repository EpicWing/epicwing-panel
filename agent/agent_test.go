package main

import (
	"bytes"
	"crypto/ed25519"
	"crypto/rand"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestAuthMessageLayout(t *testing.T) {
	// Must match docs/agent-protocol.md and backend/app/agentlink/protocol.py.
	id := "11111111-2222-3333-4444-555555555555"
	nonce := bytes.Repeat([]byte{0xAB, '\n'}, 16)
	want := append([]byte("epicwing-agent-auth-v1\n"+id+"\n"), nonce...)
	if got := authMessage(id, nonce); !bytes.Equal(got, want) {
		t.Fatalf("auth message differs from the protocol:\n got %q\nwant %q", got, want)
	}
}

func TestSignatureVerifiesOnlyForTheSameNonce(t *testing.T) {
	pub, priv, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	id := "11111111-2222-3333-4444-555555555555"
	nonce := bytes.Repeat([]byte{7}, 32)
	sig := ed25519.Sign(priv, authMessage(id, nonce))
	if !ed25519.Verify(pub, authMessage(id, nonce), sig) {
		t.Fatal("signature should verify")
	}
	other := bytes.Repeat([]byte{8}, 32)
	if ed25519.Verify(pub, authMessage(id, other), sig) {
		t.Fatal("signature must not verify for another nonce")
	}
}

func TestParseCPULine(t *testing.T) {
	idle, total, err := parseCPULine("cpu  100 20 30 400 50 6 7 8 9 10")
	if err != nil {
		t.Fatal(err)
	}
	if idle != 450 || total != 621 {
		t.Fatalf("idle=%d total=%d, want 450 and 621", idle, total)
	}
	if _, _, err := parseCPULine("cpu0 1 2 3 4"); err == nil {
		t.Fatal("per-core line must be rejected")
	}
}

func TestParseMeminfo(t *testing.T) {
	in := "MemTotal:       24616960 kB\nMemFree:         1000 kB\nMemAvailable:   15858000 kB\n"
	total, avail, err := parseMeminfo(strings.NewReader(in))
	if err != nil {
		t.Fatal(err)
	}
	if total != 24616960 || avail != 15858000 {
		t.Fatalf("total=%d avail=%d", total, avail)
	}
	if _, _, err := parseMeminfo(strings.NewReader("MemTotal: 1 kB\n")); err == nil {
		t.Fatal("missing MemAvailable must be an error")
	}
}

func TestHeartbeatFromThisMachine(t *testing.T) {
	s := &sampler{}
	if _, err := s.heartbeat(); err != nil {
		t.Fatal(err)
	}
	beat, err := s.heartbeat()
	if err != nil {
		t.Fatal(err)
	}
	if beat.CPUTotal < 1 || beat.RAMTotalMB < 1 || beat.DiskTotalMB < 1 {
		t.Fatalf("totals must be at least 1: %+v", beat)
	}
	if beat.RAMUsedMB > beat.RAMTotalMB || beat.DiskUsedMB > beat.DiskTotalMB {
		t.Fatalf("used exceeds total: %+v", beat)
	}
	if beat.CPUPercent < 0 || beat.CPUPercent > 100 {
		t.Fatalf("cpu percent out of range: %v", beat.CPUPercent)
	}
}

func TestWSURL(t *testing.T) {
	cases := map[string]string{
		"http://127.0.0.1:8010":        "ws://127.0.0.1:8010/api/agent/ws",
		"https://panel.example.com/":   "wss://panel.example.com/api/agent/ws",
		"https://panel.example.com/x/": "wss://panel.example.com/x/api/agent/ws",
	}
	for in, want := range cases {
		got, err := wsURL(in)
		if err != nil || got != want {
			t.Errorf("wsURL(%q) = %q, %v; want %q", in, got, err, want)
		}
	}
	for _, bad := range []string{"ftp://x", "127.0.0.1:8010", "http://"} {
		if _, err := wsURL(bad); err == nil {
			t.Errorf("wsURL(%q) should fail", bad)
		}
	}
}

func TestConfigRoundTripAndNoOverwrite(t *testing.T) {
	_, priv, _ := ed25519.GenerateKey(rand.Reader)
	dir := filepath.Join(t.TempDir(), "agent")
	path := filepath.Join(dir, "config.json")
	cfg := newConfig("http://127.0.0.1:8010", "11111111-2222-3333-4444-555555555555", priv)

	if err := saveConfig(path, cfg); err != nil {
		t.Fatal(err)
	}
	if info, _ := os.Stat(path); info.Mode().Perm() != 0o600 {
		t.Errorf("config mode %o, want 600", info.Mode().Perm())
	}
	if info, _ := os.Stat(dir); info.Mode().Perm() != 0o700 {
		t.Errorf("config dir mode %o, want 700", info.Mode().Perm())
	}
	if err := saveConfig(path, cfg); !errors.Is(err, errConfigExists) {
		t.Fatalf("second save should fail with errConfigExists, got %v", err)
	}
	loaded, key, err := loadConfig(path)
	if err != nil {
		t.Fatal(err)
	}
	if loaded != cfg || !key.Equal(priv) {
		t.Fatal("loaded config differs from the saved one")
	}
}

func TestConfigRejectsOpenPermissions(t *testing.T) {
	_, priv, _ := ed25519.GenerateKey(rand.Reader)
	path := filepath.Join(t.TempDir(), "config.json")
	if err := saveConfig(path, newConfig("http://127.0.0.1:8010", "x", priv)); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(path, 0o644); err != nil {
		t.Fatal(err)
	}
	if _, _, err := loadConfig(path); err == nil {
		t.Fatal("a world-readable key file must be rejected")
	}
}
