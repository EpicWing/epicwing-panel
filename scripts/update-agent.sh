#!/usr/bin/env bash
# Builds and tests the agent, installs it to /opt/epicwing and restarts the service.
set -euo pipefail
cd "$(dirname "$0")/../agent"

go test ./...
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
CGO_ENABLED=0 go build -trimpath -o "$tmp" .

install -d -m 0755 /opt/epicwing
install -m 0755 -o root -g root "$tmp" /opt/epicwing/epicwing-agent
systemctl restart epicwing-agent
echo "Agent $(/opt/epicwing/epicwing-agent version) installed and restarted"
