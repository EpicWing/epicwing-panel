package main

import (
	"testing"
	"time"
)

func TestIPLimiterBlocksAfterMaxFails(t *testing.T) {
	l := newIPLimiter(3, time.Minute)
	for i := 0; i < 2; i++ {
		l.fail("1.2.3.4")
	}
	if l.blocked("1.2.3.4") {
		t.Fatal("blocked too early")
	}
	l.fail("1.2.3.4")
	if !l.blocked("1.2.3.4") {
		t.Fatal("should be blocked after 3 fails")
	}
	if l.blocked("5.6.7.8") {
		t.Fatal("other IP must not be blocked")
	}
}

func TestIPLimiterForgetsOldFails(t *testing.T) {
	now := time.Now()
	l := newIPLimiter(2, time.Minute)
	l.now = func() time.Time { return now }
	l.fail("1.2.3.4")
	l.fail("1.2.3.4")
	if !l.blocked("1.2.3.4") {
		t.Fatal("should be blocked")
	}
	now = now.Add(2 * time.Minute)
	if l.blocked("1.2.3.4") {
		t.Fatal("block should end after the window")
	}
	if len(l.fails) != 0 {
		t.Fatal("old entries should be removed")
	}
}
