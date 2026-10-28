#!/usr/bin/env bash
# Baut den Agent, testet ihn, installiert ihn nach /opt/epicwing und startet den Dienst neu.
set -euo pipefail
cd "$(dirname "$0")/../agent"
go test ./...
tmp="$(mktemp)"
CGO_ENABLED=0 go build -trimpath -o "$tmp" .
install -d -m 0755 /opt/epicwing
install -m 0755 -o root -g root "$tmp" /opt/epicwing/epicwing-agent
rm -f "$tmp"
systemctl restart epicwing-agent
echo "Agent $(/opt/epicwing/epicwing-agent version) installiert und neu gestartet"
