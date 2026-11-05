package main

import (
	"net"
	"sync"
	"time"
)

const (
	// Max rejected key tries per IP inside the window.
	sftpMaxFails   = 20
	sftpFailWindow = 10 * time.Minute
	// Safety cap so the table cannot grow without limit.
	sftpLimiterMaxIPs = 10000
)

// ipLimiter counts rejected logins per IP address.
type ipLimiter struct {
	mu     sync.Mutex
	max    int
	window time.Duration
	now    func() time.Time
	fails  map[string][]time.Time
}

func newIPLimiter(max int, window time.Duration) *ipLimiter {
	return &ipLimiter{max: max, window: window, now: time.Now, fails: map[string][]time.Time{}}
}

// recent drops old entries for one IP and returns what is left.
func (l *ipLimiter) recent(ip string) []time.Time {
	cutoff := l.now().Add(-l.window)
	list := l.fails[ip]
	i := 0
	for i < len(list) && list[i].Before(cutoff) {
		i++
	}
	list = list[i:]
	if len(list) == 0 {
		delete(l.fails, ip)
		return nil
	}
	l.fails[ip] = list
	return list
}

// blocked tells if this IP made too many failed tries lately.
func (l *ipLimiter) blocked(ip string) bool {
	l.mu.Lock()
	defer l.mu.Unlock()
	return len(l.recent(ip)) >= l.max
}

// fail records one rejected try.
func (l *ipLimiter) fail(ip string) {
	l.mu.Lock()
	defer l.mu.Unlock()
	if _, known := l.fails[ip]; !known && len(l.fails) >= sftpLimiterMaxIPs {
		for other := range l.fails {
			l.recent(other)
		}
		if len(l.fails) >= sftpLimiterMaxIPs {
			return
		}
	}
	l.recent(ip)
	l.fails[ip] = append(l.fails[ip], l.now())
}

// sftpRemoteIP returns the IP part of a network address.
func sftpRemoteIP(addr net.Addr) string {
	if addr == nil {
		return ""
	}
	host, _, err := net.SplitHostPort(addr.String())
	if err != nil {
		return addr.String()
	}
	return host
}
