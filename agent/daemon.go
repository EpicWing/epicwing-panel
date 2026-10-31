package main

// Meldungen des EpicWing-Daemons in der Server-Konsole: gelbes, fettes Präfix wie bei
// Pterodactyl, danach der Text. CRLF, damit das Terminal im Panel sauber umbricht.
const daemonPrefix = "\x1b[33m\x1b[1m[EpicWing Daemon]\x1b[0m "

func daemonLine(msg string) string {
	return daemonPrefix + msg + "\r\n"
}

// daemonFrame is the console frame that the panel shows like normal container output.
func daemonFrame(name, msg string) map[string]any {
	return map[string]any{"type": "console", "name": name, "data": daemonLine(msg)}
}
