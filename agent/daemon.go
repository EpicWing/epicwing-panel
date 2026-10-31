package main

// Messages from the EpicWing daemon in the server console: yellow, bold prefix like in
// Pterodactyl, then the text. CRLF so the terminal in the panel wraps cleanly.
const daemonPrefix = "\x1b[33m\x1b[1m[EpicWing Daemon]\x1b[0m "

func daemonLine(msg string) string {
	return daemonPrefix + msg + "\r\n"
}

// daemonFrame is the console frame that the panel shows like normal container output.
func daemonFrame(name, msg string) map[string]any {
	return map[string]any{"type": "console", "name": name, "data": daemonLine(msg)}
}
