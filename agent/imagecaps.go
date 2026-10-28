package main

// allowedCaps is the upper limit for capabilities a policy may grant to an image.
// Everything else (SYS_ADMIN, NET_ADMIN, ALL, ...) makes the whole policy invalid.
var allowedCaps = map[string]bool{
	"CHOWN":            true,
	"SETUID":           true,
	"SETGID":           true,
	"DAC_OVERRIDE":     true,
	"FOWNER":           true,
	"NET_BIND_SERVICE": true,
	"KILL":             true,
}

// validImageCaps reports whether every entry belongs to an allowed image and only
// names capabilities from allowedCaps.
func validImageCaps(caps map[string][]string, images []string) bool {
	for image, list := range caps {
		known := false
		for _, allowed := range images {
			if allowed == image {
				known = true
				break
			}
		}
		if !known {
			return false
		}
		for _, c := range list {
			if !allowedCaps[c] {
				return false
			}
		}
	}
	return true
}
