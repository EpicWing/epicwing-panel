#!/usr/bin/env bash
# EpicWing panel installer.
# Installs PostgreSQL, nginx, Python and Node.js, builds the panel, runs it as a
# systemd service behind nginx with TLS and creates the first administrator.
# Run once as root on a fresh machine. The node agent is installed separately
# with scripts/install-node.sh.
#
# Supported families: Debian/Ubuntu (apt), RHEL-like such as Rocky, AlmaLinux and
# Fedora (dnf), Arch (pacman) and openSUSE (zypper).
set -euo pipefail

APP_USER="epicwing"
APP_DIR="/opt/epicwing"
WEB_DIR="/var/www/epicwing-panel"
DB_NAME="epicwing"
DB_USER="epicwing"
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
EpicWing panel installer (run once as root)

Supported: Debian/Ubuntu, Rocky/AlmaLinux/Fedora, Arch, openSUSE.

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

# --------------------------------------------------------------------------
# Distribution / package manager abstraction
#
# PKG is one of: apt, dnf, pacman, zypper. Every distro-specific detail (package
# names, PostgreSQL data directory, nginx config layout, firewall) hangs off it.
# --------------------------------------------------------------------------
PKG=""
PG_DATA=""      # PostgreSQL data directory for this distro
detect_pkg() {
  if command -v apt-get >/dev/null 2>&1; then PKG=apt
  elif command -v dnf >/dev/null 2>&1; then PKG=dnf
  elif command -v zypper >/dev/null 2>&1; then PKG=zypper
  elif command -v pacman >/dev/null 2>&1; then PKG=pacman
  else die "No supported package manager found (need apt, dnf, zypper or pacman)."
  fi
  case "$PKG" in
    apt)          PG_DATA="" ;;                       # managed by pg_ctlcluster
    dnf|zypper)   PG_DATA="/var/lib/pgsql/data" ;;
    pacman)       PG_DATA="/var/lib/postgres/data" ;;
  esac
}

# Refresh the package index (so a fresh image can install at all).
pkg_refresh() {
  case "$PKG" in
    apt)    quiet apt-get update -qq ;;
    dnf)    quiet dnf -q -y makecache ;;
    zypper) quiet zypper --non-interactive --gpg-auto-import-keys refresh ;;
    pacman) quiet pacman -Sy --noconfirm ;;
  esac
}

# Install packages whose names are already mapped for this distro.
pkg_install() {
  case "$PKG" in
    apt)    quiet apt-get install -y -qq "$@" ;;
    dnf)    quiet dnf install -y -q "$@" ;;
    zypper) quiet zypper --non-interactive install -y "$@" ;;
    pacman) quiet pacman -S --needed --noconfirm "$@" ;;
  esac
}

# The base packages, with the right names per distro.
base_packages() {
  case "$PKG" in
    apt)    echo postgresql nginx python3 python3-venv python3-dev build-essential libpq-dev openssl curl rsync ca-certificates ;;
    dnf)    echo postgresql-server postgresql nginx python3 python3-devel gcc gcc-c++ make libpq-devel openssl curl rsync ca-certificates ;;
    zypper) echo postgresql-server postgresql nginx python3 python3-devel gcc gcc-c++ make libpq5 postgresql-devel openssl curl rsync ca-certificates ;;
    pacman) echo postgresql nginx python base-devel postgresql-libs openssl curl rsync ca-certificates ;;
  esac
}

# Debian/Ubuntu let the panel log in to PostgreSQL over localhost with a
# password out of the box. RHEL-likes, Arch and openSUSE ship "ident" for
# loopback TCP, which would reject the panel's password login. Switch the two
# loopback lines to scram-sha-256 so the password in DATABASE_URL works.
pg_allow_local_password() {
  [ "$PKG" = apt ] && return 0
  local hba="$PG_DATA/pg_hba.conf"
  [ -f "$hba" ] || return 0
  sed -ri 's|^(host[[:space:]]+all[[:space:]]+all[[:space:]]+127\.0\.0\.1/32[[:space:]]+)[A-Za-z0-9-]+|\1scram-sha-256|' "$hba"
  sed -ri 's|^(host[[:space:]]+all[[:space:]]+all[[:space:]]+::1/128[[:space:]]+)[A-Za-z0-9-]+|\1scram-sha-256|' "$hba"
  systemctl reload postgresql 2>/dev/null || systemctl restart postgresql 2>/dev/null || true
}

# Make sure PostgreSQL has an initialised cluster and is running.
# Only Debian/Ubuntu create and start it from the package automatically.
pg_ensure_running() {
  case "$PKG" in
    apt) : ;;
    dnf)
      if [ ! -s "$PG_DATA/PG_VERSION" ]; then
        info "Initialising the PostgreSQL database"
        quiet /usr/bin/postgresql-setup --initdb
      fi ;;
    zypper)
      # openSUSE initialises on first service start; do it by hand if missing.
      if [ ! -s "$PG_DATA/PG_VERSION" ]; then
        info "Initialising the PostgreSQL database"
        install -d -o postgres -g postgres -m 700 "$PG_DATA"
        quiet runuser -u postgres -- initdb --locale=C.UTF-8 -E UTF8 -D "$PG_DATA"
      fi ;;
    pacman)
      if [ ! -s "$PG_DATA/PG_VERSION" ]; then
        info "Initialising the PostgreSQL database"
        install -d -o postgres -g postgres -m 700 "$PG_DATA"
        quiet runuser -u postgres -- initdb --locale=C.UTF-8 -E UTF8 -D "$PG_DATA"
      fi ;;
  esac
  systemctl enable --now postgresql >/dev/null 2>&1 || die "Could not start PostgreSQL. Check: systemctl status postgresql"
  pg_allow_local_password
}

# Picks a Python 3.11+ interpreter. Rocky/AlmaLinux 9 and openSUSE Leap ship an
# older python3, so a newer one is installed next to it there.
PYTHON=""
find_python() {
  local candidate
  for candidate in python3 python3.13 python3.12 python3.11; do
    if command -v "$candidate" >/dev/null 2>&1 &&
       "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
      PYTHON="$(command -v "$candidate")"
      return 0
    fi
  done
  return 1
}

ensure_python() {
  find_python && return 0
  case "$PKG" in
    dnf)    pkg_install python3.12 python3.12-devel || pkg_install python3.11 python3.11-devel || true ;;
    zypper) pkg_install python312 python312-devel || pkg_install python311 python311-devel || true ;;
  esac
  find_python || die "Python 3.11 or newer is required but could not be installed automatically."
  info "Using $PYTHON"
}

# node_ok succeeds when a recent enough Node.js is already on PATH.
node_ok() { command -v node >/dev/null 2>&1 && node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 20 ? 0 : 1)'; }

# Install Node.js 20+ for this distro.
install_node() {
  node_ok && return 0
  case "$PKG" in
    apt)
      if [ "${ID:-}" = "ubuntu" ]; then
        info "Installing Node.js 22 from NodeSource (Ubuntu ships an older version)"
        curl -fsSL https://deb.nodesource.com/setup_22.x | bash - >/dev/null
        quiet apt-get install -y -qq nodejs
      else
        pkg_install nodejs npm
      fi ;;
    dnf)
      # Rocky/AlmaLinux 9 default to Node.js 16; newer versions come as module
      # streams. Fedora and EL10 have no modules and ship a current version.
      if dnf -q module list nodejs >/dev/null 2>&1; then
        info "Enabling the Node.js 22 module stream"
        quiet dnf -y module reset nodejs || true
        quiet dnf -y module enable nodejs:22 || quiet dnf -y module enable nodejs:20 || true
        if command -v node >/dev/null 2>&1; then quiet dnf -y distro-sync nodejs npm || true; fi
      fi
      pkg_install nodejs npm || true
      if ! node_ok; then
        info "Installing Node.js 22 from NodeSource"
        quiet dnf -y remove nodejs npm || true
        curl -fsSL https://rpm.nodesource.com/setup_22.x | bash - >/dev/null
        quiet dnf install -y -q nodejs
      fi ;;
    pacman)
      pkg_install nodejs npm ;;
    zypper)
      pkg_install nodejs22 npm22 || pkg_install nodejs20 npm20 || pkg_install nodejs npm || true ;;
  esac
  node_ok || die "Node.js 20 or newer is required but could not be installed automatically. Install it and run the installer again."
}

# Install certbot (and, on RHEL-likes other than Fedora, the EPEL repository it lives in).
install_certbot() {
  case "$PKG" in
    apt)    pkg_install certbot python3-certbot-nginx ;;
    dnf)    [ "${ID:-}" = "fedora" ] || pkg_install epel-release
            pkg_install certbot python3-certbot-nginx ;;
    pacman) pkg_install certbot certbot-nginx ;;
    zypper) pkg_install certbot python3-certbot-nginx ;;
  esac
}

# A firewall warning that names the tool the distro actually uses.
warn_firewall() {
  if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q 'Status: active'; then
    warn "ufw is active. Allow ports 80 and 443 (ufw allow 80,443/tcp), or the panel will not be reachable."
  elif command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld 2>/dev/null; then
    warn "firewalld is active. Open the ports: firewall-cmd --permanent --add-service=http --add-service=https && firewall-cmd --reload"
  fi
}

# Where this distro keeps nginx server blocks.
#   Debian/Ubuntu: sites-available + a symlink into sites-enabled
#   everything else: a single file in conf.d (already included by nginx.conf)
nginx_conf_target() {
  if [ -d /etc/nginx/sites-available ] && [ -d /etc/nginx/sites-enabled ]; then
    echo /etc/nginx/sites-available/epicwing-panel
  else
    echo /etc/nginx/conf.d/epicwing-panel.conf
  fi
}

# Arch has no conf.d and does not include it, so add both when needed.
ensure_nginx_include() {
  [ -d /etc/nginx/sites-enabled ] && return 0
  install -d -m 755 /etc/nginx/conf.d
  if ! grep -qE 'include[[:space:]]+(/etc/nginx/)?conf\.d/\*\.conf' /etc/nginx/nginx.conf; then
    sed -i '0,/^[[:space:]]*http[[:space:]]*{/s//&\n    include \/etc\/nginx\/conf.d\/*.conf;/' /etc/nginx/nginx.conf
  fi
}

# SELinux (Rocky, AlmaLinux, Fedora) blocks nginx from reaching the panel on
# 127.0.0.1:8010 and from reading freshly copied files unless this is set.
allow_selinux() {
  command -v getenforce >/dev/null 2>&1 || return 0
  [ "$(getenforce 2>/dev/null)" = "Disabled" ] && return 0
  setsebool -P httpd_can_network_connect 1 >/dev/null 2>&1 \
    || warn "Could not allow nginx network access under SELinux. Run: setsebool -P httpd_can_network_connect 1"
  if command -v restorecon >/dev/null 2>&1; then restorecon -R "$WEB_DIR" >/dev/null 2>&1 || true; fi
}

[ "$(id -u)" -eq 0 ] || die "Run this script as root."
if [ -z "$DOMAIN" ]; then DOMAIN="$(ask "Domain or IP of the panel (e.g. panel.example.com): ")"; fi
if [ -z "$ADMIN_EMAIL" ]; then ADMIN_EMAIL="$(ask "E-mail of the first administrator: ")"; fi
if [[ "$DOMAIN" =~ ^[0-9.]+$ ]]; then
  warn "With an IP address the panel gets a self-signed certificate. That is fine to try it out, but nodes can only connect to a panel with a domain name and a Let's Encrypt certificate."
fi
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

if [ -r /etc/os-release ]; then . /etc/os-release; fi
detect_pkg
NGINX_CONF="$(nginx_conf_target)"
[ ! -e "$NGINX_CONF" ] || die "$NGINX_CONF exists. EpicWing seems to be installed already."
cd /tmp

banner
: > "$LOG"
info "Installing packages (package manager: $PKG)"
if [ "$PKG" = apt ]; then
  export DEBIAN_FRONTEND=noninteractive
  # Ubuntu: needrestart should not prompt during apt
  export NEEDRESTART_MODE=a
  export NEEDRESTART_SUSPEND=1
fi
pkg_refresh
# shellcheck disable=SC2046
pkg_install $(base_packages)
ensure_python
install_node
warn_firewall
pg_ensure_running

info "Creating the service user and copying the code"
id "$APP_USER" >/dev/null 2>&1 || useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
install -d -m 0755 "$APP_DIR"
rsync -a --exclude '.venv' --exclude '.env' --exclude '__pycache__' --exclude '.pytest_cache' "$SRC/backend/" "$APP_DIR/backend/"

info "Installing the backend"
"$PYTHON" -m venv "$VENV"
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

# Make sure nginx is enabled (on non-Debian it is not started by the package).
systemctl enable --now nginx >/dev/null 2>&1 || true

info "Creating a self-signed certificate (replaced if Let's Encrypt works)"
install -d -m 0755 /etc/ssl/epicwing
if [[ "$DOMAIN" =~ ^[0-9.]+$ ]]; then SAN="IP:$DOMAIN"; else SAN="DNS:$DOMAIN"; fi
openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
  -keyout /etc/ssl/epicwing/key.pem -out /etc/ssl/epicwing/cert.pem \
  -subj "/CN=$DOMAIN" -addext "subjectAltName=$SAN" 2>/dev/null
chmod 600 /etc/ssl/epicwing/key.pem

info "Configuring nginx ($NGINX_CONF)"
ensure_nginx_include
cat > "$NGINX_CONF" <<'NGINX'
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
sed -i "s/@DOMAIN@/$DOMAIN/g" "$NGINX_CONF"
# Debian/Ubuntu: enable the site through the sites-enabled symlink.
if [ -d /etc/nginx/sites-enabled ]; then
  ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/epicwing-panel
fi
# Some distros ship a default server on port 80 that would shadow ours.
if [ -e /etc/nginx/sites-enabled/default ]; then rm -f /etc/nginx/sites-enabled/default; fi
if [ -e /etc/nginx/conf.d/default.conf ]; then mv -f /etc/nginx/conf.d/default.conf /etc/nginx/conf.d/default.conf.disabled; fi
# On some distros the main nginx.conf ships its own server{} block on :80.
# We only touch it if it clearly still holds the stock block, to avoid surprises.
if ! nginx -t >/dev/null 2>&1; then
  warn "nginx -t failed with the stock configuration. Check /etc/nginx/nginx.conf for a conflicting default server block on port 80 or 443."
fi
allow_selinux
nginx -t
systemctl reload nginx

if [ -n "$LE_EMAIL" ]; then
  info "Requesting a Let's Encrypt certificate"
  install_certbot
  if certbot certonly --nginx -d "$DOMAIN" -m "$LE_EMAIL" --agree-tos --no-eff-email -n \
      --deploy-hook "systemctl reload nginx"; then
    sed -i "s|/etc/ssl/epicwing/cert.pem|/etc/letsencrypt/live/$DOMAIN/fullchain.pem|; s|/etc/ssl/epicwing/key.pem|/etc/letsencrypt/live/$DOMAIN/privkey.pem|" "$NGINX_CONF"
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
