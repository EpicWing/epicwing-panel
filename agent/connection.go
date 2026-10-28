package main

import (
	"context"
	"crypto/ed25519"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"time"

	"github.com/coder/websocket"
)

const (
	heartbeatInterval = 10 * time.Second
	ioTimeout         = 10 * time.Second
	maxMessageBytes   = 16 * 1024
	nonceBytes        = 32
	statusReplaced    = websocket.StatusCode(1012)
)

var errAuthRejected = errors.New("the panel rejected the login")

func isReplaced(err error) bool {
	return websocket.CloseStatus(err) == statusReplaced
}

func readJSON(ctx context.Context, c *websocket.Conn, timeout time.Duration, v any) error {
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	typ, data, err := c.Read(ctx)
	if err != nil {
		return err
	}
	if typ != websocket.MessageText {
		return errors.New("unexpected binary frame")
	}
	return json.Unmarshal(data, v)
}

func writeJSON(ctx context.Context, c *websocket.Conn, timeout time.Duration, v any) error {
	data, err := json.Marshal(v)
	if err != nil {
		return err
	}
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	return c.Write(ctx, websocket.MessageText, data)
}

// session runs one connection: challenge, signed login, then heartbeats until
// the connection breaks or ctx ends. It returns nil only when ctx ended.
func session(ctx context.Context, url, nodeID string, key ed25519.PrivateKey, s *sampler) error {
	dialCtx, cancel := context.WithTimeout(ctx, 15*time.Second)
	conn, _, err := websocket.Dial(dialCtx, url, nil)
	cancel()
	if err != nil {
		return fmt.Errorf("connect: %w", err)
	}
	defer conn.CloseNow()
	conn.SetReadLimit(maxMessageBytes)

	var challenge struct {
		Type  string `json:"type"`
		Nonce string `json:"nonce"`
	}
	if err := readJSON(ctx, conn, ioTimeout, &challenge); err != nil {
		return fmt.Errorf("waiting for challenge: %w", err)
	}
	nonce, err := base64.StdEncoding.DecodeString(challenge.Nonce)
	if challenge.Type != "challenge" || err != nil || len(nonce) != nonceBytes {
		return errors.New("invalid challenge from the panel")
	}

	signature := ed25519.Sign(key, authMessage(nodeID, nonce))
	err = writeJSON(ctx, conn, ioTimeout, map[string]string{
		"type":      "auth",
		"node_id":   nodeID,
		"signature": base64.StdEncoding.EncodeToString(signature),
	})
	if err != nil {
		return fmt.Errorf("sending login: %w", err)
	}

	var reply struct {
		Type    string `json:"type"`
		Message string `json:"message"`
	}
	if err := readJSON(ctx, conn, ioTimeout, &reply); err != nil {
		if websocket.CloseStatus(err) == websocket.StatusPolicyViolation {
			return errAuthRejected
		}
		return fmt.Errorf("waiting for login result: %w", err)
	}
	if reply.Type != "auth_ok" {
		return fmt.Errorf("unexpected login answer: %q", reply.Type)
	}
	log.Print("connected and logged in")

	sessionCtx, cancel := context.WithCancel(ctx)
	defer cancel()
	dispatcher := newCommandDispatcher(loadContainerPolicy())
	send := func(frame map[string]any) {
		if err := writeJSON(sessionCtx, conn, ioTimeout, frame); err != nil && sessionCtx.Err() == nil {
			log.Printf("sending a %v frame: %v", frame["type"], err)
		}
	}
	dispatcher.console = newConsoleManager(sessionCtx, dispatcher.containers, send)
	go watchEvents(sessionCtx, send)

	readErr := make(chan error, 1)
	go func() { readErr <- readLoop(sessionCtx, conn, dispatcher) }()

	ticker := time.NewTicker(heartbeatInterval)
	defer ticker.Stop()
	for {
		beat, err := s.heartbeat()
		if err != nil {
			return fmt.Errorf("measuring: %w", err)
		}
		if err := writeJSON(sessionCtx, conn, ioTimeout, beat); err != nil {
			if ctx.Err() != nil {
				return nil
			}
			return fmt.Errorf("sending heartbeat: %w", err)
		}

		select {
		case <-ctx.Done():
			conn.Close(websocket.StatusNormalClosure, "agent stopping")
			return nil
		case err := <-readErr:
			if ctx.Err() != nil {
				return nil
			}
			return err
		case <-ticker.C:
		}
	}
}
