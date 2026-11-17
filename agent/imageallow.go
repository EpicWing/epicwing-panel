package main

import "strings"

// imageAllowed reports whether a node may run this image. An entry is either an exact
// image ("nginx:1.27-alpine") or a path ending in "/*". "ghcr.io/ptero-eggs/*" allows
// every image below ghcr.io/ptero-eggs/, so servers from the marketplace do not need
// a new entry for each image.
func imageAllowed(allowed []string, image string) bool {
	for _, entry := range allowed {
		if entry == image {
			return true
		}
		prefix, ok := strings.CutSuffix(entry, "/*")
		if ok && strings.Contains(prefix, "/") && strings.HasPrefix(image, prefix+"/") {
			return true
		}
	}
	return false
}
