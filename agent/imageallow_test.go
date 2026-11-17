package main

import "testing"

func TestImageAllowed(t *testing.T) {
	allowed := []string{"nginx:1.27-alpine", "ghcr.io/ptero-eggs/*", "ghcr.io/*", "/*"}
	cases := map[string]bool{
		"nginx:1.27-alpine":                  true,
		"nginx:latest":                       false,
		"ghcr.io/ptero-eggs/apps:uptimekuma": true,
		"ghcr.io/ptero-eggs/yolks:java_25":   true,
		"ghcr.io/ptero-eggsx/evil:latest":    false,
		"ghcr.io/other/image:1":              false, // "ghcr.io/*" is too broad and ignored
		"docker.io/library/alpine:3":         false,
	}
	for image, want := range cases {
		if got := imageAllowed(allowed, image); got != want {
			t.Errorf("imageAllowed(%q) = %v, want %v", image, got, want)
		}
	}
}
