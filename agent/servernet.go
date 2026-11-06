package main

import (
	"context"
	"fmt"
	"sync/atomic"
)

// serverNetworkName is the Docker network for game servers. Containers in it cannot
// reach each other (enable_icc=false), and it is separate from the default bridge.
const serverNetworkName = "epicwing-servers"

var serverNetwork atomic.Value

// currentServerNetwork is empty until ensureServerNetwork has succeeded.
func currentServerNetwork() string {
	s, _ := serverNetwork.Load().(string)
	return s
}

// ensureServerNetwork creates the server network if it does not exist yet.
func ensureServerNetwork(ctx context.Context, run dockerRunner) error {
	if _, err := run(ctx, "network", "inspect", serverNetworkName); err == nil {
		serverNetwork.Store(serverNetworkName)
		return nil
	}
	if _, err := run(ctx, "network", "create", "--ipv6",
		"-o", "com.docker.network.bridge.enable_icc=false", serverNetworkName); err != nil {
		return fmt.Errorf("creating network %s: %w", serverNetworkName, err)
	}
	serverNetwork.Store(serverNetworkName)
	return nil
}
