package main

import "testing"

// Values from a real container; the TcpExt and IpExt lines are shortened.
const testNetDev = `Inter-|   Receive                                                |  Transmit
 face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed
    lo:   54284     466    0    0    0     0          0         0    54284     466    0    0    0     0       0          0
  eth0: 85972125    7691    0    0    0     0          0         0   937922    5882    0    0    0     0       0          0
`

const testNetSnmp = `Ip: Forwarding DefaultTTL InReceives InHdrErrors InAddrErrors ForwDatagrams InUnknownProtos InDiscards InDelivers OutRequests OutDiscards OutNoRoutes ReasmTimeout ReasmReqds ReasmOKs ReasmFails FragOKs FragFails FragCreates OutTransmits
Ip: 1 64 7878 0 0 0 0 0 7873 6058 0 0 0 0 0 0 0 0 0 6058
Icmp: InMsgs InErrors InCsumErrors InDestUnreachs InTimeExcds InParmProbs InSrcQuenchs InRedirects InEchos InEchoReps InTimestamps InTimestampReps InAddrMasks InAddrMaskReps OutMsgs OutErrors OutRateLimitGlobal OutRateLimitHost OutDestUnreachs OutTimeExcds OutParmProbs OutSrcQuenchs OutRedirects OutEchos OutEchoReps OutTimestamps OutTimestampReps OutAddrMasks OutAddrMaskReps
Icmp: 5 0 0 5 0 0 0 0 0 0 0 0 0 0 6 0 0 0 6 0 0 0 0 0 0 0 0 0 0
Tcp: RtoAlgorithm RtoMin RtoMax MaxConn ActiveOpens PassiveOpens AttemptFails EstabResets CurrEstab InSegs OutSegs RetransSegs InErrs OutRsts InCsumErrors
Tcp: 1 200 120000 -1 74 2 0 42 3 3593 1764 0 0 58 0
Udp: InDatagrams NoPorts InErrors OutDatagrams RcvbufErrors SndbufErrors InCsumErrors IgnoredMulti MemErrors
Udp: 4277 6 0 4301 0 0 0 0 0
`

const testNetstat = `TcpExt: SyncookiesSent SyncookiesRecv SyncookiesFailed ListenOverflows ListenDrops
TcpExt: 7 0 0 3 5
IpExt: InNoRoutes InOctets
IpExt: 0 85908155
`

func TestBuildNetCounters(t *testing.T) {
	got := buildNetCounters(testNetDev, testNetSnmp, testNetstat)
	want := map[string]int64{
		"rx_packets":           7691, // the loopback (466) is not counted
		"tx_packets":           5882,
		"rx_dropped":           0,
		"ip_in_receives":       7878,
		"icmp_in_msgs":         5,
		"tcp_in_segs":          3593,
		"tcp_passive_opens":    2,
		"tcp_estab_resets":     42,
		"tcp_syncookies_sent":  7,
		"tcp_listen_overflows": 3,
		"tcp_listen_drops":     5,
		"udp_in_datagrams":     4277,
		"udp_no_ports":         6,
		"udp_in_errors":        0,
		"udp_rcvbuf_errors":    0,
	}
	for key, value := range want {
		have, ok := got[key]
		if !ok {
			t.Errorf("missing counter %s", key)
			continue
		}
		if have != value {
			t.Errorf("%s = %d, want %d", key, have, value)
		}
	}
}

func TestBuildNetCountersEmpty(t *testing.T) {
	if got := buildNetCounters("", "", ""); len(got) != 0 {
		t.Errorf("expected no counters, got %v", got)
	}
}
