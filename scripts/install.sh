#!/usr/bin/env bash
# EpicWing one-line installer for Debian 13 and Ubuntu 24.04 or newer.
#
#   bash <(curl -fsSL https://raw.githubusercontent.com/EpicWing/epicwing-panel/main/scripts/install.sh)
#   bash <(curl -fsSL https://raw.githubusercontent.com/EpicWing/epicwing-panel/main/scripts/install.sh) node
#
# Downloads a fixed release, then runs install-panel.sh or install-node.sh from it.
# Options after "panel" or "node" are passed on to that script.
# Set EPICWING_SHA256 to check the downloaded archive against a checksum.
set -euo pipefail

VERSION="v0.1.1-beta"
REPO="EpicWing/epicwing-panel"
ARCHIVE_URL="https://github.com/$REPO/archive/refs/tags/$VERSION.tar.gz"
AGENT_URL="https://github.com/$REPO/releases/download/$VERSION/epicwing-agent-linux-amd64"
AGENT_SHA256="14cdf04e94374ca651108450f2c0c29ceee4ace6c126aeb721cfc3c0e441434f"

if [ -t 1 ]; then
  Y=$'\033[38;5;214m'; RE=$'\033[31m'; N=$'\033[0m'
else
  Y=""; RE=""; N=""
fi
die() { printf '%sError:%s %s\n' "$RE" "$N" "$*" >&2; exit 1; }
info() { printf '%s▸%s %s\n' "$Y" "$N" "$*"; }

usage() {
  cat <<'USAGE'
EpicWing installer (Debian 13 or Ubuntu 24.04+, run as root)

Usage:
  install.sh [panel|node] [options]

  panel   Install the panel on this machine (options: see install-panel.sh --help)
  node    Install the agent on this machine (options: see install-node.sh --help)

Without panel or node the script asks.
USAGE
}

[ "$(id -u)" -eq 0 ] || die "Run this as root."
command -v apt-get >/dev/null 2>&1 || die "Only Debian and Ubuntu are supported."

MODE=""
case "${1:-}" in
  panel|node) MODE="$1"; shift ;;
  -h|--help) usage; exit 0 ;;
esac

if [ -z "$MODE" ]; then
  [ -t 0 ] || die "Say what to install: install.sh panel or install.sh node"
  printf 'What do you want to install?\n  1) Panel (the web interface)\n  2) Node (the agent for a game server machine)\n'
  read -r -p "Choose [1/2]: " choice
  case "$choice" in
    1) MODE="panel" ;;
    2) MODE="node" ;;
    *) die "Please enter 1 or 2." ;;
  esac
fi

if ! command -v curl >/dev/null 2>&1 || ! command -v tar >/dev/null 2>&1; then
  info "Installing curl and tar"
  apt-get update -qq && apt-get install -y -qq curl tar ca-certificates >/dev/null
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

info "Downloading EpicWing $VERSION"
curl -fsSL "$ARCHIVE_URL" -o "$TMP/epicwing.tar.gz" \
  || die "Download failed. Check your internet connection and that the repository is public."

if [ -n "${EPICWING_SHA256:-}" ]; then
  echo "$EPICWING_SHA256  $TMP/epicwing.tar.gz" | sha256sum -c - >/dev/null \
    || die "Checksum of the download does not match."
fi

mkdir -p "$TMP/src"
tar xzf "$TMP/epicwing.tar.gz" -C "$TMP/src" --strip-components=1
[ -f "$TMP/src/scripts/install-$MODE.sh" ] || die "The download does not contain install-$MODE.sh."

ARGS=("$@")
if [ "$MODE" = "node" ]; then
  have_binary=0
  for a in "${ARGS[@]+"${ARGS[@]}"}"; do
    case "$a" in --url|--binary) have_binary=1 ;; esac
  done
  if [ "$have_binary" -eq 0 ]; then
    ARGS+=(--url "$AGENT_URL" --sha256 "$AGENT_SHA256")
  fi
fi

rc=0
bash "$TMP/src/scripts/install-$MODE.sh" "${ARGS[@]+"${ARGS[@]}"}" || rc=$?
exit "$rc"
