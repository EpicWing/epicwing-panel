#!/usr/bin/env bash
# EpicWing panel installer for Debian 13 and Ubuntu 24.04 or newer.
# Installs PostgreSQL, nginx, Python and Node.js, builds the panel, runs it as a
# systemd service behind nginx with TLS and creates the first administrator.
# Run once as root on a fresh machine. The node agent is installed separately
# with scripts/install-node.sh.
set -euo pipefail

APP_USER="epicwing"
APP_DIR="/opt/epicwing"
WEB_DIR="/var/www/epicwing-panel"
DB_NAME="epicwing"
DB_USER="epicwing"
CONF="/etc/nginx/sites-available/epicwing-panel"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$APP_DIR/backend/.venv"

DOMAIN=""
ADMIN_EMAIL=""
LE_EMAIL=""

if [ -t 1 ]; then
  Y=$'\033[38;5;214m'; BO=$'\033[1m'; RE=$'\033[31m'; DI=$'\033[2m'; N=$'\033[0m'
else
  Y=""; BO=""; RE=""; DI=""; N=""
fi
LOG="/var/log/epicwing-install.log"
die() { printf '%sError:%s %s\n' "$RE" "$N" "$*" >&2; exit 1; }
info() { printf '%s▸%s %s\n' "$Y" "$N" "$*"; }
warn() { printf '%sWarning:%s %s\n' "$Y" "$N" "$*" >&2; }
quiet() {
  "$@" >>"$LOG" 2>&1 || { echo "Command failed: $*" >&2; tail -n 20 "$LOG" >&2; exit 1; }
}
banner() {
  printf '\n%s╭────────────────────────────────────────╮%s\n' "$Y" "$N"
  printf '%s│%s %s%-38s%s %s│%s\n' "$Y" "$N" "$BO" "EpicWing panel installer" "$N" "$Y" "$N"
  printf '%s│%s %s%-38s%s %s│%s\n' "$Y" "$N" "$DI" "Takes about five minutes" "$N" "$Y" "$N"
  printf '%s╰────────────────────────────────────────╯%s\n\n' "$Y" "$N"
}
need_value() { [ "$#" -ge 2 ] || die "$1 needs a value."; }
ask() {
  local reply=""
  if [ -t 0 ]; then read -r -p "$1" reply || true; fi
  printf '%s' "$reply"
}

usage() {
  cat <<'USAGE'
EpicWing panel installer (Debian 13 or Ubuntu 24.04+, run once as root)

Usage:
  install-panel.sh --domain <name> --admin-email <mail> [--email <mail>]

Options (anything you leave out is asked interactively):
  --domain <name>        Public name of the panel, e.g. panel.example.com
  --admin-email <mail>   E-mail address of the first administrator
  --email <mail>         Get a Let's Encrypt certificate (DNS must point here and
                         port 80 must be reachable). Without it a self-signed
                         certificate is created and browsers show a warning.
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --domain) need_value "$@"; DOMAIN="$2"; shift 2 ;;
    --admin-email) need_value "$@"; ADMIN_EMAIL="$2"; shift 2 ;;
    --email) need_value "$@"; LE_EMAIL="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

[ "$(id -u)" -eq 0 ] || die "Run this script as root."
if [ -z "$DOMAIN" ]; then DOMAIN="$(ask "Domain or IP of the panel (e.g. panel.example.com): ")"; fi
if [ -z "$ADMIN_EMAIL" ]; then ADMIN_EMAIL="$(ask "E-mail of the first administrator: ")"; fi
if [ -z "$LE_EMAIL" ] && [ -n "$DOMAIN" ] && ! [[ "$DOMAIN" =~ ^[0-9.]+$ ]]; then
  LE_EMAIL="$(ask "E-mail for Let's Encrypt (leave empty for a self-signed certificate): ")"
fi
[ -n "$DOMAIN" ] && [ -n "$ADMIN_EMAIL" ] || { usage; exit 1; }
mail_re='^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$'
[[ "$ADMIN_EMAIL" =~ $mail_re ]] || die "The administrator e-mail address looks invalid."
if [ -n "$LE_EMAIL" ]; then [[ "$LE_EMAIL" =~ $mail_re ]] || die "The Let's Encrypt e-mail address looks invalid."; fi
[[ "$DOMAIN" =~ ^[A-Za-z0-9.-]+$ ]] || die "The domain may only contain letters, digits, dots and dashes."
[ -f "$SRC/backend/pyproject.toml" ] || die "Run this script from an EpicWing checkout or release archive."
[ ! -e "$APP_DIR/backend/.env" ] || die "$APP_DIR/backend/.env exists. EpicWing seems to be installed already, see Updating in the README."
[ ! -e "$CONF" ] || die "$CONF exists. EpicWing seems to be installed already."
if [ -r /etc/os-release ]; then . /etc/os-release; fi
case "${ID:-}:${VERSION_ID:-}" in
  debian:13|ubuntu:24.04|ubuntu:25.*|ubuntu:26.*) ;;
  *) warn "Made for Debian 13 and Ubuntu 24.04 or newer (found ${PRETTY_NAME:-unknown system})." ;;
esac
cd /tmp

banner
: > "$LOG"
info "Installing packages"
export DEBIAN_FRONTEND=noninteractive
quiet apt-get update -qq
PKGS=(postgresql nginx python3 python3-venv python3-dev build-essential libpq-dev openssl curl rsync ca-certificates)
if [ -n "$LE_EMAIL" ]; then PKGS+=(certbot python3-certbot-nginx); fi
quiet apt-get install -y -qq "${PKGS[@]}"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' || die "Python 3.11 or newer is required."
node_ok() { command -v node >/dev/null 2>&1 && node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 20 ? 0 : 1)'; }
if ! node_ok; then
  if [ "${ID:-}" = "ubuntu" ]; then
    info "Installing Node.js 22 from NodeSource (Ubuntu ships an older version)"
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - >/dev/null
    apt-get install -y -qq nodejs
  else
    apt-get install -y -qq nodejs npm
  fi
fi
node_ok || die "Node.js 20 or newer is required."
systemctl enable --now postgresql >/dev/null 2>&1 || true

info "Creating the service user and copying the code"
id "$APP_USER" >/dev/null 2>&1 || useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
install -d -m 0755 "$APP_DIR"
rsync -a --exclude '.venv' --exclude '.env' --exclude '__pycache__' --exclude '.pytest_cache' "$SRC/backend/" "$APP_DIR/backend/"

info "Installing the backend"
python3 -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip
(cd "$APP_DIR/backend" && "$VENV/bin/pip" install -q .)

info "Creating the database"
DB_PASS="$(openssl rand -hex 24)"
exists="$(runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'")"
[ -z "$exists" ] || die "The database user $DB_USER already exists."
runuser -u postgres -- psql -v ON_ERROR_STOP=1 -q <<SQL
CREATE USER $DB_USER WITH PASSWORD '$DB_PASS';
CREATE DATABASE $DB_NAME OWNER $DB_USER;
SQL

info "Writing the configuration"
SECRET="$("$VENV/bin/python" -c 'import secrets; print(secrets.token_urlsafe(48))')"
ENC="$("$VENV/bin/python" -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
umask 077
cat > "$APP_DIR/backend/.env" <<ENVFILE
DATABASE_URL=postgresql+psycopg://$DB_USER:$DB_PASS@localhost:5432/$DB_NAME
EPICWING_ENV=production
EPICWING_SECRET_KEY=$SECRET
EPICWING_ENCRYPTION_KEY=$ENC
EPICWING_PUBLIC_URL=https://$DOMAIN
ENVFILE
umask 022
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

info "Creating the tables"
cd "$APP_DIR/backend"
runuser -u "$APP_USER" -- "$VENV/bin/alembic" upgrade head
echo
info "Creating the first administrator (you choose the password now)"
created=0
for _ in 1 2 3; do
  if runuser -u "$APP_USER" -- "$VENV/bin/python" -m app.cli create-admin --email "$ADMIN_EMAIL"; then created=1; break; fi
  warn "The administrator was not created. Try again."
done
[ "$created" = 1 ] || die "Could not create the administrator. Remove the partial install (see docs/INSTALL.md) and run the installer again."

info "Building the frontend (this takes a minute)"
BUILD="$(mktemp -d)"
trap 'rm -rf "$BUILD"' EXIT
rsync -a --exclude node_modules --exclude dist "$SRC/frontend/" "$BUILD/"
(cd "$BUILD" && npm ci --no-audit --no-fund --loglevel=error && npm run build >/dev/null)
install -d -m 0755 "$WEB_DIR"
rsync -a --delete "$BUILD/dist/" "$WEB_DIR/"
chmod -R a+rX "$WEB_DIR"

info "Creating the systemd service"
cat > /etc/systemd/system/epicwing-panel.service <<UNIT
[Unit]
Description=EpicWing panel
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
User=$APP_USER
WorkingDirectory=$APP_DIR/backend
ExecStart=$VENV/bin/uvicorn app.main:app --host 127.0.0.1 --port 8010
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now epicwing-panel

info "Creating a self-signed certificate (replaced if Let's Encrypt works)"
install -d -m 0755 /etc/ssl/epicwing
if [[ "$DOMAIN" =~ ^[0-9.]+$ ]]; then SAN="IP:$DOMAIN"; else SAN="DNS:$DOMAIN"; fi
openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
  -keyout /etc/ssl/epicwing/key.pem -out /etc/ssl/epicwing/cert.pem \
  -subj "/CN=$DOMAIN" -addext "subjectAltName=$SAN" 2>/dev/null
chmod 600 /etc/ssl/epicwing/key.pem

info "Configuring nginx"
cat > "$CONF" <<'NGINX'
map $http_upgrade $epicwing_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 80;
    listen [::]:80;
    server_name @DOMAIN@;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name @DOMAIN@;
    ssl_certificate /etc/ssl/epicwing/cert.pem;
    ssl_certificate_key /etc/ssl/epicwing/key.pem;

    root /var/www/epicwing-panel;
    index index.html;
    client_max_body_size 16m;

    location /api/ {
        proxy_pass http://127.0.0.1:8010;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $epicwing_upgrade;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Host $host;
        proxy_buffering off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    location / {
        add_header Cache-Control "no-cache";
        add_header Strict-Transport-Security "max-age=31536000" always;
        add_header X-Frame-Options "DENY" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header Referrer-Policy "strict-origin-when-cross-origin" always;
        try_files $uri /index.html;
    }
}
NGINX
sed -i "s/@DOMAIN@/$DOMAIN/g" "$CONF"
ln -sf "$CONF" /etc/nginx/sites-enabled/epicwing-panel
nginx -t
systemctl reload nginx

if [ -n "$LE_EMAIL" ]; then
  info "Requesting a Let's Encrypt certificate"
  if certbot certonly --nginx -d "$DOMAIN" -m "$LE_EMAIL" --agree-tos --no-eff-email -n \
      --deploy-hook "systemctl reload nginx"; then
    sed -i "s|/etc/ssl/epicwing/cert.pem|/etc/letsencrypt/live/$DOMAIN/fullchain.pem|; s|/etc/ssl/epicwing/key.pem|/etc/letsencrypt/live/$DOMAIN/privkey.pem|" "$CONF"
    nginx -t
    systemctl reload nginx
  else
    warn "Let's Encrypt failed (DNS and port 80 must be reachable). Keeping the self-signed certificate."
  fi
fi

sleep 3
if ! systemctl is-active --quiet epicwing-panel; then
  journalctl -u epicwing-panel -n 20 --no-pager
  die "The panel service did not start."
fi
code="$(curl -sk -o /dev/null -w '%{http_code}' -H "Host: $DOMAIN" https://127.0.0.1/ || true)"
if [ "$code" != "200" ]; then
  warn "nginx answered HTTP $code on https://$DOMAIN/. Check nginx -t and journalctl -u epicwing-panel."
fi

cat <<DONE

${Y}${BO}✔ EpicWing is installed.${N}

  Panel:  https://$DOMAIN
  Login:  $ADMIN_EMAIL
  Config: $APP_DIR/backend/.env (keep a backup, it holds the encryption key)

Open ports 80 and 443 in your firewall. Add a node in the admin area, then run
scripts/install-node.sh on the node.
DONE
