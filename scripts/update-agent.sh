#!/usr/bin/env bash
# Builds and tests the agent, installs it to /opt/epicwing and restarts the service.
set -euo pipefail
cd "$(dirname "$0")/../agent"

go test ./...
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
version="$(git describe --tags --always 2>/dev/null || echo dev)"
version="${version#v}"
CGO_ENABLED=0 go build -trimpath -ldflags "-X main.version=$version" -o "$tmp" .

install -d -m 0755 /opt/epicwing
install -m 0755 -o root -g root "$tmp" /opt/epicwing/epicwing-agent
systemctl restart epicwing-agent
echo "Agent $(/opt/epicwing/epicwing-agent version) installed and restarted"
