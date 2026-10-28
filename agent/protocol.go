package main

import (
	"fmt"
	"net/url"
	"strings"
)

// authContext and the layout of authMessage must match docs/agent-protocol.md.
const authContext = "epicwing-agent-auth-v1\n"

// authMessage returns the bytes the agent signs: context, node ID as text,
// a newline and the raw nonce.
func authMessage(nodeID string, nonce []byte) []byte {
	msg := make([]byte, 0, len(authContext)+len(nodeID)+1+len(nonce))
	msg = append(msg, authContext...)
	msg = append(msg, nodeID...)
	msg = append(msg, '\n')
	msg = append(msg, nonce...)
	return msg
}

// normalizePanel checks the panel URL and removes a trailing slash.
func normalizePanel(panel string) (string, error) {
	u, err := url.Parse(strings.TrimSpace(panel))
	if err != nil {
		return "", fmt.Errorf("invalid panel URL: %w", err)
	}
	if (u.Scheme != "http" && u.Scheme != "https") || u.Host == "" {
		return "", fmt.Errorf("panel URL must look like http(s)://host[:port], got %q", panel)
	}
	u.RawQuery, u.Fragment = "", ""
	u.Path = strings.TrimRight(u.Path, "/")
	return u.String(), nil
}

// wsURL turns the panel URL into the WebSocket endpoint of the agent.
func wsURL(panel string) (string, error) {
	base, err := normalizePanel(panel)
	if err != nil {
		return "", err
	}
	u, _ := url.Parse(base)
	if u.Scheme == "https" {
		u.Scheme = "wss"
	} else {
		u.Scheme = "ws"
	}
	u.Path += "/api/agent/ws"
	return u.String(), nil
}
