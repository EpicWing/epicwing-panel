package main

import (
	"context"
	"os/exec"
	"strconv"
	"strings"
	"time"
)

const statsInterval = 2 * time.Second

func parsePercent(value string) (float64, bool) {
	value = strings.TrimSpace(strings.TrimSuffix(value, "%"))
	n, err := strconv.ParseFloat(value, 64)
	return n, err == nil
}

func parseBytes(value string) (int64, bool) {
	value = strings.TrimSpace(value)
	if value == "" || value == "-" {
		return 0, false
	}
	// docker stats prints "1.212GiB" without a space before the unit.
	split := strings.IndexFunc(value, func(r rune) bool {
		return (r < '0' || r > '9') && r != '.'
	})
	number, unit := value, ""
	if split >= 0 {
		number, unit = value[:split], strings.TrimSpace(value[split:])
	}
	n, err := strconv.ParseFloat(number, 64)
	if err != nil {
		return 0, false
	}
	multiplier := float64(1)
	switch strings.ToLower(unit) {
	case "kb":
		multiplier = 1000
	case "kib":
		multiplier = 1024
	case "mb":
		multiplier = 1000 * 1000
	case "mib":
		multiplier = 1024 * 1024
	case "gb":
		multiplier = 1000 * 1000 * 1000
	case "gib":
		multiplier = 1024 * 1024 * 1024
	case "tb":
		multiplier = 1000 * 1000 * 1000 * 1000
	case "tib":
		multiplier = 1024 * 1024 * 1024 * 1024
	}
	return int64(n * multiplier), true
}

func parsePair(value string) (int64, int64) {
	parts := strings.SplitN(value, " / ", 2)
	left, _ := parseBytes(parts[0])
	if len(parts) == 1 {
		return left, 0
	}
	right, _ := parseBytes(parts[1])
	return left, right
}

func (c *consoleManager) statsLoop(ctx context.Context, name string) {
	ticker := time.NewTicker(statsInterval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			c.sampleStats(ctx, name)
		}
	}
}

func (c *consoleManager) statsAllLoop(ctx context.Context) {
	ticker := time.NewTicker(statsInterval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			names, err := c.containers.ManagedNames(ctx)
			if err != nil {
				continue
			}
			for _, name := range names {
				c.sampleStats(ctx, name)
			}
		}
	}
}

func (c *consoleManager) sampleStats(ctx context.Context, name string) {
	state, _, err := c.containers.Status(ctx, name)
	if err != nil || state != "running" {
		return
	}
	out, err := runDocker(ctx, "stats", "--no-stream", "--format", "{{.CPUPerc}}|{{.MemUsage}}|{{.NetIO}}", name)
	if err != nil {
		return
	}
	fields := strings.SplitN(strings.TrimSpace(out), "|", 3)
	if len(fields) != 3 {
		return
	}
	cpu, ok := parsePercent(fields[0])
	if !ok {
		return
	}
	memoryUsed, memoryLimit := parsePair(fields[1])
	networkRx, networkTx := parsePair(fields[2])
	c.send(map[string]any{
		"type": "stats", "name": name, "cpu_percent": cpu,
		"memory_used_bytes": memoryUsed, "memory_limit_bytes": memoryLimit,
		"disk_used_bytes": c.diskUsage(name), "network_rx_bytes": networkRx,
		"network_tx_bytes": networkTx,
	})
}

func (c *consoleManager) diskUsage(name string) int64 {
	path := c.containers.dataPath(name)
	output, err := exec.Command("du", "-sb", path).Output()
	if err != nil {
		return 0
	}
	value := strings.Fields(string(output))
	if len(value) == 0 {
		return 0
	}
	bytes, err := strconv.ParseInt(value[0], 10, 64)
	if err != nil {
		return 0
	}
	return bytes
}
