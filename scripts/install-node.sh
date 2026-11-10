#!/usr/bin/env bash
# EpicWing node installer.
# Installs the node agent on this machine, sets up its hardened systemd unit and
# enrolls it with a panel. Run as root on the node. Safe to run again: an existing
# enrollment and policy are kept unless --force is given.
set -euo pipefail

AGENT_USER="epicwing"
BIN_DIR="/opt/epicwing"
CONF_DIR="/etc/epicwing-agent"
DATA_DIR="/var/lib/epicwing"
UNIT="/etc/systemd/system/epicwing-agent.service"

PANEL=""
TOKEN=""
BINARY=""
URL=""
SHA256=""
BIND_IP=""
FORCE=0

die() { echo "Error: $*" >&2; exit 1; }
info() { echo "==> $*"; }
need_value() { [ "$#" -ge 2 ] || die "$1 needs a value."; }

usage() {
  cat <<'USAGE'
EpicWing node installer

Usage:
  install-node.sh --panel <url> --binary <file> [options]
  install-node.sh --panel <url> --url <https-url> --sha256 <hash> [options]

Options:
  --panel <url>     Address of the panel as seen from this node (required)
  --binary <file>   Local agent binary to install
  --url <url>       Download the agent binary from this HTTPS address
  --sha256 <hash>   Expected SHA-256 of the binary
  --token <token>   Enrollment token (or set EPICWING_ENROLL_TOKEN; asked for if omitted)
  --bind-ip <ip>    IPv4 address game servers bind to (default: primary address)
  --force           Enroll again and replace the policy
  --insecure        Allow http:// for local tests only
  -h, --help        Show this help

The agent's enroll command takes the token as a command line argument, so it is
visible in the process list for a moment. Run this on a machine only you can
log in to, and pass the token with EPICWING_ENROLL_TOKEN or let the installer ask for it.
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --panel) need_value "$@"; PANEL="$2"; shift 2 ;;
    --binary) need_value "$@"; BINARY="$2"; shift 2 ;;
    --url) need_value "$@"; URL="$2"; shift 2 ;;
    --sha256) need_value "$@"; SHA256="$2"; shift 2 ;;
    --token) need_value "$@"; TOKEN="$2"; shift 2 ;;
    --bind-ip) need_value "$@"; BIND_IP="$2"; shift 2 ;;
    --force) FORCE=1; shift ;;
    --insecure) INSECURE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; die "Unknown option: $1" ;;
  esac
done

[ "$(id -u)" -eq 0 ] || die "Run this script as root."
[ -n "$PANEL" ] || { usage >&2; die "--panel is required."; }
case "$PANEL" in
  https://*) ;;
  http://*)
    [ "${INSECURE:-0}" = "1" ] || die "--panel must use https://. Use --insecure only for local tests: http:// sends commands and secrets unencrypted."
    echo "WARNING: using http:// without encryption (--insecure)." >&2 ;;
  *) die "--panel must start with https://" ;;
esac
PANEL="${PANEL%/}"
if [ -z "$BINARY" ] && [ -z "$URL" ] && [ ! -x "$BIN_DIR/epicwing-agent" ]; then
  die "Give the agent with --binary <file> or --url <https-url>."
fi
if [ -n "$URL" ]; then
  case "$URL" in
    https://*) ;;
    *) die "--url must start with https://" ;;
  esac
fi

# os-release in einer Subshell lesen, damit keine Variablen des Skripts ueberschrieben werden
OS_ID="$(. /etc/os-release 2>/dev/null; echo "${ID:-}")"
OS_NAME="$(. /etc/os-release 2>/dev/null; echo "${PRETTY_NAME:-unknown system}")"
case "$OS_ID" in
  debian|ubuntu) ;;
  *) echo "Warning: made for Debian and Ubuntu (found $OS_NAME)." >&2 ;;
esac
# Docker aus Snap kommt mit dem Datenverzeichnis nicht klar (Snap-Sandbox)
if command -v snap >/dev/null 2>&1 && snap list docker >/dev/null 2>&1; then
  die "Docker from snap is not supported. Install docker.io or Docker CE from the official repository."
fi
for cmd in systemctl docker curl runuser useradd usermod install sha256sum; do
  command -v "$cmd" >/dev/null 2>&1 || die "Required command not found: $cmd"
done
getent group docker >/dev/null || die "The group 'docker' does not exist. Install Docker first."
docker info >/dev/null 2>&1 || die "Docker is installed but not running."

code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "$PANEL/" 2>/dev/null || true)"
case "$code" in
  ""|000) die "The panel at $PANEL is not reachable from this node." ;;
esac

if [ -z "$BIND_IP" ]; then
  BIND_IP="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i <= NF; i++) if ($i == "src") { print $(i + 1); exit }}')" || true
fi
[ -n "$BIND_IP" ] || die "Could not detect the IP address. Pass --bind-ip."
case "$BIND_IP" in
  *[!0-9.]*) die "--bind-ip must be an IPv4 address." ;;
esac

info "Creating user and directories"
if ! id "$AGENT_USER" >/dev/null 2>&1; then
  useradd --system --user-group --home-dir "$DATA_DIR" \
    --shell "$(command -v nologin || echo /usr/sbin/nologin)" "$AGENT_USER"
fi
usermod -aG docker "$AGENT_USER"
install -d -o root -g root -m 755 "$BIN_DIR"
install -d -o "$AGENT_USER" -g "$AGENT_USER" -m 700 "$CONF_DIR"
install -d -o "$AGENT_USER" -g "$AGENT_USER" -m 750 "$DATA_DIR" "$DATA_DIR/servers"
install -d -o "$AGENT_USER" -g "$AGENT_USER" -m 700 "$DATA_DIR/backups"

if [ -n "$URL" ] || [ -n "$BINARY" ]; then
  tmp="$(mktemp)"
  trap 'rm -f "$tmp"' EXIT
  if [ -n "$URL" ]; then
    info "Downloading the agent"
    curl -fsSL --proto '=https' --tlsv1.2 --max-time 300 -o "$tmp" "$URL"
  else
    [ -f "$BINARY" ] || die "File not found: $BINARY"
    cp "$BINARY" "$tmp"
  fi
  if [ -n "$SHA256" ]; then
    echo "$SHA256  $tmp" | sha256sum -c --status - || die "Checksum of the agent does not match."
  elif [ -n "$URL" ]; then
    echo "Warning: no --sha256 given, the download is not verified." >&2
  fi
  info "Installing the agent to $BIN_DIR"
  install -m 0755 -o root -g root "$tmp" "$BIN_DIR/epicwing-agent.new"
  mv -f "$BIN_DIR/epicwing-agent.new" "$BIN_DIR/epicwing-agent"
fi
"$BIN_DIR/epicwing-agent" version >/dev/null 2>&1 || die "The agent binary does not run on this machine."

POLICY="$CONF_DIR/policy.json"
if [ ! -f "$POLICY" ] || [ "$FORCE" -eq 1 ]; then
  info "Writing $POLICY (bind address $BIND_IP)"
  # Every image used by a bundled egg must be listed in allowed_images.
  # Also pin images by hash in image_digests, otherwise the image runs unpinned by its tag.
  cat > "$POLICY" <<POLICYEOF
{
  "allowed_images": [
    "nginx:1.27-alpine",
    "ghcr.io/ptero-eggs/yolks:mono_latest",
    "ghcr.io/ptero-eggs/yolks:java_22",
    "ghcr.io/ptero-eggs/yolks:java_25",
    "ghcr.io/ptero-eggs/yolks:python_3.12",
    "ghcr.io/ptero-eggs/yolks:nodejs_22",
    "ghcr.io/ptero-eggs/yolks:nodejs_24",
    "ghcr.io/pyrodactyl-oss/images:java_25",
    "ghcr.io/ptero-eggs/steamcmd:debian",
    "ghcr.io/pterodactyl/installers:alpine",
    "ghcr.io/ptero-eggs/installers:alpine",
    "ghcr.io/parkervcp/installers:alpine",
    "ghcr.io/ptero-eggs/installers:debian"
  ],
  "image_digests": {
    "ghcr.io/ptero-eggs/yolks:mono_latest": "sha256:327404b6358bdc3b558587713b21fbc1719c10b369a38f32b33045954ab4627b",
    "ghcr.io/ptero-eggs/yolks:python_3.12": "sha256:196fee6764133099f82971c8e2fced2f0075c94930e90860c43f5e6619a7d575",
    "ghcr.io/ptero-eggs/yolks:nodejs_22": "sha256:23e4eeec6706fad7d0486081ffdd6fd26d745802d34bee3e101b86d8758cce69",
    "ghcr.io/ptero-eggs/yolks:nodejs_24": "sha256:5c5a3e74fb39f25c2dc65851ca7255d7e739af54d94c6df46cdb91a496ee51f4",
    "ghcr.io/ptero-eggs/yolks:java_22": "sha256:3d71f6ebbfdae46e46d39b499533b7829e2272cb84b4950164110f6c6bddd27c",
    "ghcr.io/ptero-eggs/yolks:java_25": "sha256:afbe93630fc543361cd463630335fc04d799d52e1e87ca8d87005938e0508ad2",
    "ghcr.io/ptero-eggs/steamcmd:debian": "sha256:c8a93dc0e256d1dba10aed6a0d8d6e739d4f1809f4e3b7428d0c01adc6e6e68b",
    "ghcr.io/ptero-eggs/installers:debian": "sha256:084e7a28d9902d054b35bcad7c547bcd3b5739040b9e0f5bfe63bb18ce021423"
  },
  "port_min": 1024,
  "port_max": 65535,
  "bind_ip": "$BIND_IP",
  "data_dir": "$DATA_DIR/servers",
  "image_caps": {
    "nginx:1.27-alpine": ["CHOWN", "SETUID", "SETGID"]
  }
}
POLICYEOF
  chown "root:$AGENT_USER" "$POLICY"
  chmod 640 "$POLICY"
else
  info "Keeping the existing $POLICY"
fi

info "Writing the systemd unit"
cat > "$UNIT" <<'UNITEOF'
[Unit]
Description=EpicWing node agent
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
User=epicwing
Group=epicwing
SupplementaryGroups=docker
Environment=EPICWING_AGENT_CONFIG=/etc/epicwing-agent/config.json
Environment=DOCKER_CONFIG=/etc/epicwing-agent/docker-none
ExecStart=/opt/epicwing/epicwing-agent run
Restart=always
RestartSec=5

# Hardening: the agent may only write below /var/lib/epicwing and gets no new privileges.
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/var/lib/epicwing
ProtectHome=true
PrivateTmp=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true

[Install]
WantedBy=multi-user.target
UNITEOF
systemctl daemon-reload

CONFIG="$CONF_DIR/config.json"
if [ -f "$CONFIG" ] && [ "$FORCE" -eq 0 ]; then
  info "Already enrolled, keeping $CONFIG (use --force to enroll again)"
else
  # Take the token from the environment if --token was not given
  [ -n "$TOKEN" ] || TOKEN="${EPICWING_ENROLL_TOKEN:-}"
  if [ -z "$TOKEN" ]; then
    [ -t 0 ] || die "No token given and no terminal to ask on."
    read -rs -p "Enrollment token: " TOKEN
    echo
  fi
  [ -n "$TOKEN" ] || die "No token given."
  if [ -f "$CONFIG" ]; then
    mv "$CONFIG" "$CONFIG.bak-$(date +%Y%m%d-%H%M%S)"
  fi
  info "Enrolling with $PANEL"
  runuser -u "$AGENT_USER" -- "$BIN_DIR/epicwing-agent" enroll \
    --panel "$PANEL" --token "$TOKEN" --config "$CONFIG"
  TOKEN=""
  unset EPICWING_ENROLL_TOKEN
fi

info "Starting the agent"
systemctl enable epicwing-agent >/dev/null 2>&1
systemctl restart epicwing-agent
sleep 3
if ! systemctl is-active --quiet epicwing-agent; then
  journalctl -u epicwing-agent -n 20 --no-pager || true
  die "The agent did not start."
fi

echo
echo "Done. The node should show as online in the panel."
echo "Open the ports of your game servers in the firewall, for example:"
echo "  ufw allow 7777/udp"
echo "Docker publishes ports itself. If a server is not reachable although it runs,"
echo "check: iptables -S DOCKER-USER"
