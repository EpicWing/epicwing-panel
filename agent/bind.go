package main

import (
	"fmt"
	"net"
)

// defaultBindIP is used when the policy names no address, so published ports are
// never exposed on all interfaces by accident.
const defaultBindIP = "127.0.0.1"

func (m *containerManager) bindAddr() string {
	if m.policy.BindIP == "" {
		return defaultBindIP
	}
	return m.policy.BindIP
}

// validBindIP accepts a plain IPv4 address that exists on this host and is not 0.0.0.0.
func validBindIP(s string) bool {
	ip := net.ParseIP(s)
	if ip == nil || ip.To4() == nil || ip.IsUnspecified() || ip.String() != s {
		return false
	}
	addrs, err := net.InterfaceAddrs()
	if err != nil {
		return false
	}
	for _, a := range addrs {
		if n, ok := a.(*net.IPNet); ok && n.IP.Equal(ip) {
			return true
		}
	}
	return false
}

// checkPortIP checks the address a port is published on. An empty address means the
// policy's own address. A bind_ip set in the policy is the only address allowed.
func (m *containerManager) checkPortIP(ip string) error {
	if ip == "" {
		return nil
	}
	if !validBindIP(ip) {
		return fmt.Errorf("address %q cannot be used for published ports on this node", ip)
	}
	if m.policy.BindIP != "" && ip != m.policy.BindIP {
		return fmt.Errorf("address %q does not match the node's bind_ip", ip)
	}
	return nil
}

// portAddr returns the address one port is published on.
func (m *containerManager) portAddr(p PortMapping) string {
	if p.IP != "" {
		return p.IP
	}
	return m.bindAddr()
}
