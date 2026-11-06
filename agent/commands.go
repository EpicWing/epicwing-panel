package main

import (
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"errors"
	"flag"
	"fmt"
	"log"
	mrand "math/rand/v2"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"
)

const (
	minBackoff = time.Second
	maxBackoff = 60 * time.Second
)

func cmdEnroll(args []string) error {
	fs := flag.NewFlagSet("enroll", flag.ContinueOnError)
	panel := fs.String("panel", "", "panel base URL, e.g. http://127.0.0.1:8010")
	token := fs.String("token", os.Getenv("EPICWING_ENROLL_TOKEN"), "enrollment token (or env EPICWING_ENROLL_TOKEN)")
	cfgPath := fs.String("config", configPath(), "path of the config file")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if *panel == "" || *token == "" {
		return errors.New("--panel and --token are required")
	}
	base, err := normalizePanel(*panel)
	if err != nil {
		return err
	}
	if _, err := os.Stat(*cfgPath); err == nil {
		return fmt.Errorf("%w: %s", errConfigExists, *cfgPath)
	}

	pub, priv, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		return err
	}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	res, err := enroll(ctx, base, *token, pub)
	if err != nil {
		return err
	}
	nodeID := strings.ToLower(res.NodeID)
	if err := saveConfig(*cfgPath, newConfig(base, nodeID, priv)); err != nil {
		return fmt.Errorf("enrolled as %q, but saving the config failed (the token is used up, create a new node): %w", res.NodeName, err)
	}
	fmt.Printf("Enrolled as node %q (%s)\nConfig written to %s\n", res.NodeName, nodeID, *cfgPath)
	return nil
}

func cmdRun(args []string) error {
	fs := flag.NewFlagSet("run", flag.ContinueOnError)
	cfgPath := fs.String("config", configPath(), "path of the config file")
	if err := fs.Parse(args); err != nil {
		return err
	}
	cfg, key, err := loadConfig(*cfgPath)
	if err != nil {
		return err
	}
	url, err := wsURL(cfg.Panel)
	if err != nil {
		return err
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	s := &sampler{}
	_, _ = s.cpuPercent() // prime the CPU counters
	log.Printf("epicwing-agent %s, node %s, panel %s", version, cfg.NodeID, cfg.Panel)
	if err := ensureServerNetwork(ctx, runDocker); err != nil {
		log.Printf("server network: %v (new servers use the default network)", err)
	}

	backoff := minBackoff
	for ctx.Err() == nil {
		started := time.Now()
		err := session(ctx, url, cfg.NodeID, key, s)
		if ctx.Err() != nil {
			break
		}
		if time.Since(started) > 30*time.Second {
			backoff = minBackoff
		}
		wait := backoff
		switch {
		case errors.Is(err, errAuthRejected):
			// The panel blocks an IP after 10 failed logins in 15 minutes.
			// Every 2 minutes gives at most 8 attempts in that window.
			wait = 2 * time.Minute
		case isReplaced(err):
			wait = 30 * time.Second
		default:
			backoff = min(backoff*2, maxBackoff)
		}
		wait += mrand.N(time.Second)
		log.Printf("disconnected: %v; retrying in %s", err, wait.Round(time.Second))
		select {
		case <-ctx.Done():
		case <-time.After(wait):
		}
	}
	log.Print("stopped")
	return nil
}
