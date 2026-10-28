package main

import (
	"regexp"
	"strings"
)

var digestRe = regexp.MustCompile(`^sha256:[0-9a-f]{64}$`)

// validImageDigests checks that every pinned tag is on the allowlist and that
// every digest has the form sha256:<64 hex characters>.
func validImageDigests(digests map[string]string, images []string) bool {
	for tag, digest := range digests {
		known := false
		for _, image := range images {
			if image == tag {
				known = true
				break
			}
		}
		if !known || !digestRe.MatchString(digest) {
			return false
		}
	}
	return true
}

// pinnedImage returns repo@digest for a pinned tag and the tag itself otherwise.
func pinnedImage(tag string, digests map[string]string) string {
	digest, ok := digests[tag]
	if !ok {
		return tag
	}
	repo := tag
	if i := strings.LastIndex(tag, ":"); i > strings.LastIndex(tag, "/") {
		repo = tag[:i]
	}
	return repo + "@" + digest
}

func (m *containerManager) pinned(image string) string {
	return pinnedImage(image, m.policy.ImageDigests)
}
