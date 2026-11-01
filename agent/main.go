// Command epicwing-agent is the node agent of the EpicWing hosting panel.
package main

import (
	"fmt"
	"os"
)

var version = "dev"

func usage() {
	fmt.Fprintln(os.Stderr, `Usage:
  epicwing-agent enroll --panel <url> --token <token> [--config <path>]
  epicwing-agent run [--config <path>]
  epicwing-agent version`)
}

func main() {
	if len(os.Args) < 2 {
		usage()
		os.Exit(2)
	}
	var err error
	switch os.Args[1] {
	case "enroll":
		err = cmdEnroll(os.Args[2:])
	case "run":
		err = cmdRun(os.Args[2:])
	case "version":
		fmt.Println(version)
	default:
		usage()
		os.Exit(2)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
}
