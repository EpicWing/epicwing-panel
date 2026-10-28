package main

import "strconv"

// daemonStateMessage übersetzt einen Zustands-Frame in die Daemon-Zeile der Konsole.
func daemonStateMessage(frame map[string]any) (string, bool) {
	switch frame["state"] {
	case "running":
		return "Container started", true
	case "exited":
		code, _ := frame["exit_code"].(int)
		if code != 0 {
			return "Server marked as offline (exit code " + strconv.Itoa(code) + ")", true
		}
		return "Server marked as offline", true
	}
	return "", false
}
