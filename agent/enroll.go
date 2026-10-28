package main

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
)

type enrollRequest struct {
	Token        string `json:"token"`
	PublicKey    string `json:"public_key"`
	AgentVersion string `json:"agent_version"`
}

type enrollResponse struct {
	NodeID   string `json:"node_id"`
	NodeName string `json:"node_name"`
}

// enroll redeems the one-time token and registers the public key at the panel.
func enroll(ctx context.Context, panel, token string, pub ed25519.PublicKey) (enrollResponse, error) {
	var res enrollResponse
	body, err := json.Marshal(enrollRequest{
		Token:        token,
		PublicKey:    base64.StdEncoding.EncodeToString(pub),
		AgentVersion: version,
	})
	if err != nil {
		return res, err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, panel+"/api/agent/enroll", bytes.NewReader(body))
	if err != nil {
		return res, err
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return res, fmt.Errorf("cannot reach the panel: %w", err)
	}
	defer resp.Body.Close()
	data, err := io.ReadAll(io.LimitReader(resp.Body, 4096))
	if err != nil {
		return res, err
	}
	if resp.StatusCode != http.StatusCreated {
		return res, fmt.Errorf("panel answered %d: %s", resp.StatusCode, strings.TrimSpace(string(data)))
	}
	if err := json.Unmarshal(data, &res); err != nil || res.NodeID == "" {
		return res, fmt.Errorf("unexpected answer from the panel: %s", strings.TrimSpace(string(data)))
	}
	return res, nil
}
