package main

import "testing"

const testDigest = "sha256:3d71f6ebbfdae46e46d39b499533b7829e2272cb84b4950164110f6c6bddd27c"

func TestPinnedImage(t *testing.T) {
	d := map[string]string{"ghcr.io/ptero-eggs/yolks:java_22": testDigest}
	if got := pinnedImage("ghcr.io/ptero-eggs/yolks:java_22", d); got != "ghcr.io/ptero-eggs/yolks@"+testDigest {
		t.Errorf("pinned: %s", got)
	}
	if got := pinnedImage("nginx:1.27-alpine", d); got != "nginx:1.27-alpine" {
		t.Errorf("unpinned: %s", got)
	}
}

func TestValidImageDigests(t *testing.T) {
	images := []string{"a/b:c"}
	if !validImageDigests(map[string]string{"a/b:c": testDigest}, images) {
		t.Error("valid digest rejected")
	}
	if validImageDigests(map[string]string{"a/b:c": "sha256:abc"}, images) {
		t.Error("short digest accepted")
	}
	if validImageDigests(map[string]string{"x/y:z": testDigest}, images) {
		t.Error("tag outside the allowlist accepted")
	}
}
