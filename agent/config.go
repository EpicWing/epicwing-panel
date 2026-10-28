package main

import (
	"crypto/ed25519"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"net"
	"net/url"
	"os"
	"path/filepath"
)

const defaultConfigPath = "/etc/epicwing-agent/config.json"

var errConfigExists = errors.New("config file already exists, refusing to overwrite the key")

// Config is stored on the node. PrivateKey is the base64 encoded Ed25519 seed.
type Config struct {
	Panel      string `json:"panel"`
	NodeID     string `json:"node_id"`
	PrivateKey string `json:"private_key"`
}

func configPath() string {
	if p := os.Getenv("EPICWING_AGENT_CONFIG"); p != "" {
		return p
	}
	return defaultConfigPath
}

func newConfig(panel, nodeID string, key ed25519.PrivateKey) Config {
	return Config{
		Panel:      panel,
		NodeID:     nodeID,
		PrivateKey: base64.StdEncoding.EncodeToString(key.Seed()),
	}
}

// saveConfig writes the file with mode 0600 and never replaces an existing one.
func saveConfig(path string, c Config) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	data, err := json.MarshalIndent(c, "", "  ")
	if err != nil {
		return err
	}
	f, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
	if err != nil {
		if errors.Is(err, fs.ErrExist) {
			return fmt.Errorf("%w: %s", errConfigExists, path)
		}
		return err
	}
	if _, err := f.Write(append(data, '\n')); err != nil {
		f.Close()
		os.Remove(path)
		return err
	}
	if err := f.Close(); err != nil {
		os.Remove(path)
		return err
	}
	return nil
}

func loadConfig(path string) (Config, ed25519.PrivateKey, error) {
	var c Config
	info, err := os.Stat(path)
	if err != nil {
		return c, nil, err
	}
	if info.Mode().Perm()&0o077 != 0 {
		return c, nil, fmt.Errorf("%s is readable by others (mode %o), expected 0600", path, info.Mode().Perm())
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return c, nil, err
	}
	if err := json.Unmarshal(data, &c); err != nil {
		return c, nil, fmt.Errorf("invalid config: %w", err)
	}
	seed, err := base64.StdEncoding.DecodeString(c.PrivateKey)
	if err != nil || len(seed) != ed25519.SeedSize {
		return c, nil, errors.New("invalid private key in config")
	}
	if c.Panel == "" || c.NodeID == "" {
		return c, nil, errors.New("config is missing panel or node_id")
	}
	if err := checkPanelURL(c.Panel); err != nil {
		return c, nil, err
	}
	return c, ed25519.NewKeyFromSeed(seed), nil
}

// checkPanelURL only lets the agent talk to the panel over https. Plain http is
// accepted for the local machine, and elsewhere only with EPICWING_AGENT_INSECURE=1.
func checkPanelURL(raw string) error {
	u, err := url.Parse(raw)
	if err != nil || u.Host == "" {
		return fmt.Errorf("invalid panel address %q", raw)
	}
	switch u.Scheme {
	case "https":
		return nil
	case "http":
		host := u.Hostname()
		if ip := net.ParseIP(host); host == "localhost" || (ip != nil && ip.IsLoopback()) {
			return nil
		}
		if os.Getenv("EPICWING_AGENT_INSECURE") == "1" {
			return nil
		}
		return fmt.Errorf("panel address must use https:// (http is only allowed for localhost or with EPICWING_AGENT_INSECURE=1)")
	}
	return fmt.Errorf("panel address must start with https://")
}
