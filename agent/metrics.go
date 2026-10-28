package main

import (
	"bufio"
	"errors"
	"fmt"
	"io"
	"math"
	"os"
	"runtime"
	"strconv"
	"strings"
	"syscall"
)

type heartbeat struct {
	Type         string  `json:"type"`
	CPUTotal     int     `json:"cpu_total"`
	RAMTotalMB   int64   `json:"ram_total_mb"`
	DiskTotalMB  int64   `json:"disk_total_mb"`
	CPUPercent   float64 `json:"cpu_percent"`
	RAMUsedMB    int64   `json:"ram_used_mb"`
	DiskUsedMB   int64   `json:"disk_used_mb"`
	AgentVersion string  `json:"agent_version"`
}

// sampler remembers the last CPU counters, because the load is a difference
// between two readings.
type sampler struct {
	prevIdle, prevTotal uint64
	primed              bool
}

// parseCPULine reads the aggregate "cpu" line of /proc/stat. Total is the sum of
// user, nice, system, idle, iowait, irq, softirq and steal; idle includes iowait.
func parseCPULine(line string) (idle, total uint64, err error) {
	f := strings.Fields(line)
	if len(f) < 5 || f[0] != "cpu" {
		return 0, 0, fmt.Errorf("unexpected /proc/stat line: %q", line)
	}
	for i := 1; i < len(f) && i <= 8; i++ {
		v, err := strconv.ParseUint(f[i], 10, 64)
		if err != nil {
			return 0, 0, err
		}
		total += v
		if i == 4 || i == 5 {
			idle += v
		}
	}
	return idle, total, nil
}

func readCPU() (idle, total uint64, err error) {
	f, err := os.Open("/proc/stat")
	if err != nil {
		return 0, 0, err
	}
	defer f.Close()
	sc := bufio.NewScanner(f)
	if !sc.Scan() {
		return 0, 0, errors.New("/proc/stat is empty")
	}
	return parseCPULine(sc.Text())
}

// cpuPercent returns the total load of all cores since the last call (0 to 100).
// The first call only primes the counters and returns 0.
func (s *sampler) cpuPercent() (float64, error) {
	idle, total, err := readCPU()
	if err != nil {
		return 0, err
	}
	prevIdle, prevTotal, primed := s.prevIdle, s.prevTotal, s.primed
	s.prevIdle, s.prevTotal, s.primed = idle, total, true
	if !primed || total <= prevTotal || idle < prevIdle {
		return 0, nil
	}
	dt, di := total-prevTotal, idle-prevIdle
	if di > dt {
		return 0, nil
	}
	return math.Round(float64(dt-di)/float64(dt)*1000) / 10, nil
}

func parseMeminfo(r io.Reader) (totalKB, availKB uint64, err error) {
	var haveTotal, haveAvail bool
	sc := bufio.NewScanner(r)
	for sc.Scan() {
		f := strings.Fields(sc.Text())
		if len(f) < 2 {
			continue
		}
		switch f[0] {
		case "MemTotal:":
			totalKB, err = strconv.ParseUint(f[1], 10, 64)
			haveTotal = true
		case "MemAvailable:":
			availKB, err = strconv.ParseUint(f[1], 10, 64)
			haveAvail = true
		}
		if err != nil {
			return 0, 0, err
		}
	}
	if err := sc.Err(); err != nil {
		return 0, 0, err
	}
	if !haveTotal || !haveAvail {
		return 0, 0, errors.New("MemTotal or MemAvailable missing in /proc/meminfo")
	}
	return totalKB, availKB, nil
}

func readMeminfo() (totalKB, availKB uint64, err error) {
	f, err := os.Open("/proc/meminfo")
	if err != nil {
		return 0, 0, err
	}
	defer f.Close()
	return parseMeminfo(f)
}

func diskUsage(path string) (totalMB, usedMB int64, err error) {
	var st syscall.Statfs_t
	if err := syscall.Statfs(path, &st); err != nil {
		return 0, 0, err
	}
	bs := uint64(st.Bsize)
	total := uint64(st.Blocks) * bs
	used := (uint64(st.Blocks) - uint64(st.Bfree)) * bs
	return int64(total >> 20), int64(used >> 20), nil
}

func (s *sampler) heartbeat() (heartbeat, error) {
	cpu, err := s.cpuPercent()
	if err != nil {
		return heartbeat{}, fmt.Errorf("cpu: %w", err)
	}
	totalKB, availKB, err := readMeminfo()
	if err != nil {
		return heartbeat{}, fmt.Errorf("memory: %w", err)
	}
	diskTotal, diskUsed, err := diskUsage("/")
	if err != nil {
		return heartbeat{}, fmt.Errorf("disk: %w", err)
	}
	var ramUsedKB uint64
	if availKB < totalKB {
		ramUsedKB = totalKB - availKB
	}
	return heartbeat{
		Type:         "heartbeat",
		CPUTotal:     max(1, runtime.NumCPU()),
		RAMTotalMB:   max(1, int64(totalKB/1024)),
		DiskTotalMB:  max(1, diskTotal),
		CPUPercent:   cpu,
		RAMUsedMB:    int64(ramUsedKB / 1024),
		DiskUsedMB:   diskUsed,
		AgentVersion: version,
	}, nil
}
