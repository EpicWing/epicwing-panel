package main

import "testing"

func TestCheckPortIP(t *testing.T) {
	cases := []struct {
		name   string
		bindIP string
		ip     string
		ok     bool
	}{
		{"empty uses the policy address", "", "", true},
		{"loopback exists on every host", "", "127.0.0.1", true},
		{"unspecified address", "", "0.0.0.0", false},
		{"ipv6", "", "::1", false},
		{"not a plain address", "", "127.0.0.1 ", false},
		{"not on this host", "", "203.0.113.7", false},
		{"differs from the pinned bind_ip", "198.51.100.1", "127.0.0.1", false},
		{"pinned bind_ip and no address", "198.51.100.1", "", true},
	}
	for _, c := range cases {
		m := &containerManager{policy: ContainerPolicy{BindIP: c.bindIP}}
		err := m.checkPortIP(c.ip)
		if (err == nil) != c.ok {
			t.Errorf("%s: err = %v, want ok = %v", c.name, err, c.ok)
		}
	}
}

func TestPortAddr(t *testing.T) {
	m := &containerManager{policy: ContainerPolicy{}}
	if got := m.portAddr(PortMapping{}); got != defaultBindIP {
		t.Errorf("without address: got %q, want %q", got, defaultBindIP)
	}
	if got := m.portAddr(PortMapping{IP: "10.0.0.5"}); got != "10.0.0.5" {
		t.Errorf("with address: got %q", got)
	}
	m = &containerManager{policy: ContainerPolicy{BindIP: "10.0.0.9"}}
	if got := m.portAddr(PortMapping{}); got != "10.0.0.9" {
		t.Errorf("with policy address: got %q", got)
	}
}
