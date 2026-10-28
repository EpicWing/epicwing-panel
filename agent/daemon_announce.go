package main

// announce schreibt eine EpicWing-Daemon-Zeile in die Konsole des Servers.
func (d *commandDispatcher) announce(name, msg string) {
	if d.console == nil || d.console.send == nil {
		return
	}
	d.console.send(daemonFrame(name, msg))
}
