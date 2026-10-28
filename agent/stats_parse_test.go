package main

import "testing"

func TestParseBytesDockerStatsFormat(t *testing.T) {
	cases := []struct {
		in   string
		want int64
		ok   bool
	}{
		{"0B", 0, true},
		{"860B", 860, true},
		{"1.5kB", 1500, true},
		{"2KiB", 2048, true},
		{"3MiB", 3 * 1024 * 1024, true},
		{"12 MiB", 12 * 1024 * 1024, true},
		{"1.212GiB", 1301375090, true},
		{"-", 0, false},
		{"", 0, false},
		{"abc", 0, false},
	}
	for _, c := range cases {
		got, ok := parseBytes(c.in)
		if got != c.want || ok != c.ok {
			t.Errorf("parseBytes(%q) = %d, %v; want %d, %v", c.in, got, ok, c.want, c.ok)
		}
	}
}

func TestParsePairDockerStats(t *testing.T) {
	used, limit := parsePair("1.212GiB / 23.48GiB")
	if used != 1301375090 {
		t.Errorf("used = %d", used)
	}
	if limit <= 23<<30 || limit >= 24<<30 {
		t.Errorf("limit = %d", limit)
	}
	rx, tx := parsePair("1.2kB / 3kB")
	if rx != 1200 || tx != 3000 {
		t.Errorf("rx, tx = %d, %d", rx, tx)
	}
}
