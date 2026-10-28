package main

import "net"

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
