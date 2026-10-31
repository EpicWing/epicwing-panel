package main

// announce writes an EpicWing daemon line to the console of the server.
func (d *commandDispatcher) announce(name, msg string) {
	if d.console == nil || d.console.send == nil {
		return
	}
	d.console.send(daemonFrame(name, msg))
}
