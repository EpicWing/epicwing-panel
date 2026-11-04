#!/usr/bin/env bash
# EpicWing one-line installer for Debian 13 and Ubuntu 24.04 or newer.
#
#   bash <(curl -fsSL https://raw.githubusercontent.com/EpicWing/epicwing-panel/main/scripts/install.sh)
#   bash <(curl -fsSL https://raw.githubusercontent.com/EpicWing/epicwing-panel/main/scripts/install.sh) node
#   bash <(curl -fsSL https://raw.githubusercontent.com/EpicWing/epicwing-panel/main/scripts/install.sh) update panel
#   bash <(curl -fsSL https://raw.githubusercontent.com/EpicWing/epicwing-panel/main/scripts/install.sh) update node
#
# Downloads a fixed release, then runs install-panel.sh or install-node.sh from it.
# Options after "panel" or "node" are passed on to that script.
# Set EPICWING_SHA256 to check the downloaded archive against a checksum.
set -euo pipefail

VERSION="v0.1.8-beta"
REPO="EpicWing/epicwing-panel"
ARCHIVE_URL="https://github.com/$REPO/archive/refs/tags/$VERSION.tar.gz"
AGENT_BASE_URL="https://github.com/$REPO/releases/download/$VERSION/epicwing-agent-linux-"
# One checksum per CPU type. Fill in AGENT_SHA256_ARM64 after the arm64 file is
# built for the release: sha256sum epicwing-agent-linux-arm64
AGENT_SHA256_AMD64="040565ac89af3ce26f92568eba8276b5798f7977947bd5e8da8f3fa331a94161"
AGENT_SHA256_ARM64="c7425f1118ae8e410133485644f4cff6f8dbe72b9b6abb3dc30f66cede1268e7"

# Paths used by install-panel.sh
APP_USER="epicwing"
APP_DIR="/opt/epicwing"
WEB_DIR="/var/www/epicwing-panel"
DB_NAME="epicwing"
BACKUP_DIR="/var/backups/epicwing"

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
  install.sh update panel
  install.sh update node

  panel         Install the panel on this machine (options: see install-panel.sh --help)
  node          Install the agent on this machine (options: see install-node.sh --help)
  update panel  Update the panel: database backup, new code, migrations, restart.
                The old code is restored if the new panel does not start.
  update node   Replace the installed agent with the one from this release.
                The old file is kept as epicwing-agent.old and is restored
                if the new agent does not start.

Supported CPUs for the agent: amd64 and arm64 (64-bit operating system needed).
Without panel or node the script asks.
USAGE
}

# Sets ARCH, AGENT_URL and AGENT_SHA256 for the CPU type of this machine.
# dpkg reports the architecture of the installed system, so a Raspberry Pi with
# a 64-bit kernel but a 32-bit system (armhf) is recognised correctly.
detect_arch() {
  local dpkg_arch
  dpkg_arch="$(dpkg --print-architecture 2>/dev/null || true)"
  case "$dpkg_arch" in
    amd64) ARCH="amd64"; AGENT_SHA256="$AGENT_SHA256_AMD64" ;;
    arm64) ARCH="arm64"; AGENT_SHA256="$AGENT_SHA256_ARM64" ;;
    armhf|armel)
      die "This is a 32-bit ARM system ($dpkg_arch). The agent needs a 64-bit system, for example Raspberry Pi OS 64-bit." ;;
    *)
      die "Unsupported CPU type: ${dpkg_arch:-unknown}. The agent is built for amd64 and arm64." ;;
  esac
  [ -n "$AGENT_SHA256" ] || die "This release has no checksum for $ARCH."
  AGENT_URL="$AGENT_BASE_URL$ARCH"
}

# Downloads the release archive and unpacks it to $TMP/src.
fetch_source() {
  info "Downloading EpicWing $VERSION"
  curl -fsSL "$ARCHIVE_URL" -o "$TMP/epicwing.tar.gz" \
    || die "Download failed. Check your internet connection and that the repository is public."
  if [ -n "${EPICWING_SHA256:-}" ]; then
    echo "$EPICWING_SHA256  $TMP/epicwing.tar.gz" | sha256sum -c - >/dev/null \
      || die "Checksum of the download does not match."
  fi
  mkdir -p "$TMP/src"
  tar xzf "$TMP/epicwing.tar.gz" -C "$TMP/src" --strip-components=1
}

update_node() {
  local bin="/opt/epicwing/epicwing-agent" old new
  [ -x "$bin" ] || die "No agent found at $bin. Install it first: install.sh node"
  detect_arch

  old="$("$bin" version 2>/dev/null || echo unknown)"
  info "Downloading agent $VERSION ($ARCH)"
  curl -fsSL "$AGENT_URL" -o "$TMP/agent" \
    || die "Download failed. Nothing was changed."
  echo "$AGENT_SHA256  $TMP/agent" | sha256sum -c - >/dev/null \
    || die "Checksum of the download does not match. Nothing was changed."
  chmod 0755 "$TMP/agent"

  if [ "$(sha256sum "$bin" | cut -d' ' -f1)" = "$AGENT_SHA256" ]; then
    info "The agent is already up to date ($old)."
    return 0
  fi

  new="$("$TMP/agent" version 2>/dev/null)" \
    || die "The new agent could not be started here (wrong CPU type, or /tmp is mounted noexec). Nothing was changed."

  info "Keeping the old agent as $bin.old"
  cp -p "$bin" "$bin.old"
  install -m 0755 -o root -g root "$TMP/agent" "$bin"

  info "Restarting epicwing-agent"
  systemctl restart epicwing-agent || true
  sleep 3
  if ! systemctl is-active --quiet epicwing-agent; then
    printf '%sThe new agent did not start. Restoring the old one.%s\n' "$RE" "$N" >&2
    install -m 0755 -o root -g root "$bin.old" "$bin"
    systemctl restart epicwing-agent || true
    die "Update failed, the old agent ($old) was restored. Check: journalctl -u epicwing-agent -n 50"
  fi
  info "Agent updated: $old -> $new"
}

update_panel() {
  local venv="$APP_DIR/backend/.venv" old stamp dump codebak ok
  cd /tmp
  [ -f "$APP_DIR/backend/.env" ] || die "No panel found in $APP_DIR. Install it first: install.sh panel"
  [ -x "$venv/bin/alembic" ] || die "The Python environment in $venv is missing or broken."
  command -v npm >/dev/null 2>&1 || die "npm is missing, the frontend cannot be built."
  command -v rsync >/dev/null 2>&1 || apt-get install -y -qq rsync >/dev/null

  old="$(cat "$APP_DIR/VERSION" 2>/dev/null || echo unknown)"
  fetch_source
  [ -f "$TMP/src/backend/pyproject.toml" ] || die "The download does not look like an EpicWing release."

  stamp="$(date +%Y-%m-%d-%H%M%S)"
  install -d -m 0700 "$BACKUP_DIR"
  dump="$BACKUP_DIR/db-$stamp.dump"
  codebak="$BACKUP_DIR/backend-$stamp.tar.gz"

  info "Backing up the database: $dump"
  runuser -u postgres -- pg_dump -Fc "$DB_NAME" > "$dump" \
    || die "Database backup failed. Nothing was changed."
  [ -s "$dump" ] || die "Database backup is empty. Nothing was changed."
  chmod 600 "$dump"

  info "Backing up the code: $codebak"
  tar czf "$codebak" -C "$APP_DIR" --exclude='backend/.venv' --exclude='__pycache__' backend \
    || die "Code backup failed. Nothing was changed."
  chmod 600 "$codebak"

  # Build first, so a broken build does not cause any downtime.
  info "Building the frontend (this takes a minute)"
  rsync -a --exclude node_modules --exclude dist "$TMP/src/frontend/" "$TMP/fe/"
  (cd "$TMP/fe" && npm ci --no-audit --no-fund --loglevel=error && npm run build >/dev/null) \
    || die "Frontend build failed. Nothing was changed."

  rollback() {
    printf '%sRestoring the old code.%s\n' "$RE" "$N" >&2
    systemctl stop epicwing-panel || true
    tar xzf "$codebak" -C "$APP_DIR"
    chown -R "$APP_USER:$APP_USER" "$APP_DIR/backend"
    (cd "$APP_DIR/backend" && "$venv/bin/pip" install -q .) || true
    systemctl start epicwing-panel || true
  }

  info "Stopping the panel"
  systemctl stop epicwing-panel

  info "Copying the new code"
  rsync -a --exclude '.venv' --exclude '.env' --exclude '__pycache__' --exclude '.pytest_cache' \
    "$TMP/src/backend/" "$APP_DIR/backend/"
  chown -R "$APP_USER:$APP_USER" "$APP_DIR/backend"

  info "Installing dependencies"
  (cd "$APP_DIR/backend" && "$venv/bin/pip" install -q .) \
    || { rollback; die "Installing dependencies failed. The old code was restored."; }

  info "Running database migrations"
  (cd "$APP_DIR/backend" && runuser -u "$APP_USER" -- "$venv/bin/alembic" upgrade head) \
    || { rollback; die "Migration failed. The old code was restored. Database backup: $dump"; }

  info "Starting the panel"
  systemctl start epicwing-panel
  ok=0
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    sleep 2
    if systemctl is-active --quiet epicwing-panel \
       && [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8010/ || true)" != "000" ]; then
      ok=1; break
    fi
  done
  if [ "$ok" -ne 1 ]; then
    journalctl -u epicwing-panel -n 30 --no-pager || true
    rollback
    die "The new panel did not start. The old code was restored. If it complains about the database, restore the backup: systemctl stop epicwing-panel; runuser -u postgres -- pg_restore --clean --if-exists -d $DB_NAME $dump; systemctl start epicwing-panel"
  fi

  info "Installing the new frontend"
  install -d -m 0755 "$WEB_DIR"
  rsync -a --delete "$TMP/fe/dist/" "$WEB_DIR/"
  chmod -R a+rX "$WEB_DIR"
  echo "$VERSION" > "$APP_DIR/VERSION"

  # Keep only the 5 newest backups of each kind.
  ls -1t "$BACKUP_DIR"/db-*.dump 2>/dev/null | tail -n +6 | xargs -r rm -f --
  ls -1t "$BACKUP_DIR"/backend-*.tar.gz 2>/dev/null | tail -n +6 | xargs -r rm -f --

  info "Panel updated: $old -> $VERSION"
  info "Backups are in $BACKUP_DIR. Nodes are not touched: run 'install.sh update node' on each node."
}

[ "$(id -u)" -eq 0 ] || die "Run this as root."
command -v apt-get >/dev/null 2>&1 || die "Only Debian and Ubuntu are supported."

MODE=""
UPDATE=0
case "${1:-}" in
  panel|node) MODE="$1"; shift ;;
  update|--update)
    UPDATE=1; shift
    case "${1:-}" in
      node) MODE="node"; shift ;;
      panel) MODE="panel"; shift ;;
      *) die "Say what to update: install.sh update panel or install.sh update node" ;;
    esac
    ;;
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

if [ "$UPDATE" -eq 1 ]; then
  if [ "$MODE" = "node" ]; then update_node; else update_panel; fi
  exit 0
fi

fetch_source
[ -f "$TMP/src/scripts/install-$MODE.sh" ] || die "The download does not contain install-$MODE.sh."

ARGS=("$@")
if [ "$MODE" = "node" ]; then
  have_binary=0
  for a in "${ARGS[@]+"${ARGS[@]}"}"; do
    case "$a" in --url|--binary) have_binary=1 ;; esac
  done
  if [ "$have_binary" -eq 0 ]; then
    detect_arch
    ARGS+=(--url "$AGENT_URL" --sha256 "$AGENT_SHA256")
  fi
fi

rc=0
bash "$TMP/src/scripts/install-$MODE.sh" "${ARGS[@]+"${ARGS[@]}"}" || rc=$?
exit "$rc"
