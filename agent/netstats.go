package main

import (
	"context"
	"os"
	"strconv"
	"strings"
)

// containerNetCounters holds cumulative network counters of one container. They are
// read from the container's own network namespace (/proc/<pid>/net). The values only
// grow until the container restarts, so the panel works with the difference between
// two samples.
type containerNetCounters map[string]int64

// procNetKeys maps entries of /proc/<pid>/net/snmp and /proc/<pid>/net/netstat to the
// short names sent to the panel.
var procNetKeys = map[string]string{
	"Ip.InReceives":          "ip_in_receives",
	"Ip.InHdrErrors":         "ip_in_hdr_errors",
	"Ip.InAddrErrors":        "ip_in_addr_errors",
	"Ip.ReasmReqds":          "ip_reasm_reqds",
	"Icmp.InMsgs":            "icmp_in_msgs",
	"Icmp.InEchos":           "icmp_in_echos",
	"Tcp.InSegs":             "tcp_in_segs",
	"Tcp.PassiveOpens":       "tcp_passive_opens",
	"Tcp.AttemptFails":       "tcp_attempt_fails",
	"Tcp.EstabResets":        "tcp_estab_resets",
	"Tcp.InErrs":             "tcp_in_errs",
	"TcpExt.SyncookiesSent":  "tcp_syncookies_sent",
	"TcpExt.ListenOverflows": "tcp_listen_overflows",
	"TcpExt.ListenDrops":     "tcp_listen_drops",
	"Udp.InDatagrams":        "udp_in_datagrams",
	"Udp.NoPorts":            "udp_no_ports",
	"Udp.InErrors":           "udp_in_errors",
	"Udp.RcvbufErrors":       "udp_rcvbuf_errors",
}

// procNetDevColumns are the columns of /proc/<pid>/net/dev that are sent. The byte
// counters already come from docker stats.
var procNetDevColumns = map[string]int{
	"rx_packets": 1,
	"rx_errors":  2,
	"rx_dropped": 3,
	"tx_packets": 9,
	"tx_errors":  10,
	"tx_dropped": 11,
}

// parseProcNetDev adds up all interfaces except the loopback.
func parseProcNetDev(text string, out containerNetCounters) {
	for _, line := range strings.Split(text, "\n") {
		name, rest, found := strings.Cut(line, ":")
		if !found || strings.TrimSpace(name) == "lo" {
			continue
		}
		fields := strings.Fields(rest)
		if len(fields) < 12 {
			continue
		}
		for key, column := range procNetDevColumns {
			if n, err := strconv.ParseInt(fields[column], 10, 64); err == nil {
				out[key] += n
			}
		}
	}
}

// parseProcNetTable reads the paired "Proto: names" and "Proto: values" lines of
// /proc/<pid>/net/snmp and /proc/<pid>/net/netstat into "Proto.Name" keys.
func parseProcNetTable(text string) map[string]int64 {
	out := map[string]int64{}
	var names []string
	proto := ""
	for _, line := range strings.Split(text, "\n") {
		head, rest, found := strings.Cut(line, ":")
		if !found {
			continue
		}
		fields := strings.Fields(rest)
		if names == nil || head != proto {
			proto, names = head, fields
			continue
		}
		for i, value := range fields {
			if i >= len(names) {
				break
			}
			if n, err := strconv.ParseInt(value, 10, 64); err == nil {
				out[head+"."+names[i]] = n
			}
		}
		names = nil
	}
	return out
}

func buildNetCounters(dev, snmp, netstat string) containerNetCounters {
	out := containerNetCounters{}
	parseProcNetDev(dev, out)
	table := parseProcNetTable(snmp)
	for key, value := range parseProcNetTable(netstat) {
		table[key] = value
	}
	for from, to := range procNetKeys {
		if value, ok := table[from]; ok {
			out[to] = value
		}
	}
	return out
}

// readContainerNet returns nil if the container has no process or its namespace
// cannot be read.
func readContainerNet(ctx context.Context, name string) containerNetCounters {
	out, err := runDocker(ctx, "inspect", "-f", "{{.State.Pid}}", name)
	if err != nil {
		return nil
	}
	pid, err := strconv.Atoi(strings.TrimSpace(out))
	if err != nil || pid <= 0 {
		return nil
	}
	base := "/proc/" + strconv.Itoa(pid) + "/net/"
	dev, err := os.ReadFile(base + "dev")
	if err != nil {
		return nil
	}
	snmp, _ := os.ReadFile(base + "snmp")
	netstat, _ := os.ReadFile(base + "netstat")
	return buildNetCounters(string(dev), string(snmp), string(netstat))
}
