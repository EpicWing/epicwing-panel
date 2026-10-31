<p align="center">
  <img src="docs/assets/logo.svg" alt="EpicWing" width="72">
</p>

<h1 align="center">EpicWing</h1>

<p align="center">
  Self-hosted server management panel.<br>
  Run game servers and other services in isolated Docker containers.
</p>

<p align="center">
  <a href="https://github.com/EpicWing/epicwing-panel/actions/workflows/ci.yml"><img src="https://github.com/EpicWing/epicwing-panel/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/EpicWing/epicwing-panel" alt="MIT license"></a>
  <a href="https://github.com/EpicWing/epicwing-panel/releases"><img src="https://img.shields.io/github/v/release/EpicWing/epicwing-panel?include_prereleases" alt="Release"></a>
</p>

EpicWing is a self-hosted server management panel. Game servers and other services
each run in their own isolated Docker container on a node. The panel talks to a small Go agent on
each node.

**Status: beta.** Fine for small setups, not ready for large or multi-tenant hosting.
See [Limitations](#limitations).

## Installation at a glance

1. Create a PostgreSQL database and user.
2. Install the backend and fill in `.env`.
3. Build the frontend.
4. Run the backend as a systemd service.
5. Put nginx with TLS in front.
6. Add a node and install the agent with `scripts/install-node.sh`.

The details are in [Installation](#installation).

## Bundled eggs

Minecraft (Vanilla, Paper, Purpur, Fabric), Unturned and a static website. Pterodactyl-format egg files can be imported for everything else.

## Components

- **Panel backend:** FastAPI (Python 3.13), PostgreSQL or MariaDB, Alembic migrations
- **Panel frontend:** Vue 3, Vite, Tailwind
- **Agent:** Go, runs on every node and controls Docker, files, backups and SFTP

## Features

- Users, roles, 2FA (TOTP), API keys and SSH keys
- Nodes with Ed25519 agent authentication
- Servers, nests and eggs (imports and exports Pterodactyl-format egg files)
- Install, start, stop, restart, live console, auto restart
- File manager with direct transfers, SFTP
- Local backups, schedules, databases per server
- Notifications through Discord and email
- Traffic guard: detection of unusual incoming traffic and console floods with alerts

## Limitations

- **DDoS:** EpicWing only detects and reports unusual traffic. It blocks nothing, so use
  your provider's protection or a firewall for that.
- Tested on Debian 13 (x86_64) with systemd and Docker only.
- The panel runs as a single process. Schedules, rate limits and action locks
  are kept in memory, so do not run several workers.
- Backups are stored on the node. There is no S3 or cross-node storage yet.
- No built-in web hosting features (domains, vhosts, TLS). A site or app can run as a
  container if you have an egg for it, but you set up the reverse proxy and certificates yourself.
- Only the Minecraft EULA is handled. When a server stops because it is not accepted,
  the console offers a dialog that links the EULA and sets `eula=true` after a click.
  The panel does not record who accepted.
- The agent needs access to the Docker socket, which is equivalent to root on the
  node. Run nodes on dedicated machines.

## Installation

Tested on Debian 13 with systemd. You need Python 3.11 or newer (tested with 3.13), Node.js 20 or newer,
PostgreSQL 16 or newer and a reverse proxy (nginx) with a TLS certificate. Nodes need Docker.
The paths below are examples, adjust them to your setup.

### Quick install

The installer sets up PostgreSQL, nginx, the backend, the frontend, a systemd service,
TLS and the first administrator on a fresh machine. It is tested on Debian 13 (x86_64) only.
Run it once as root, from a checkout or an extracted release archive:

```bash
sudo bash scripts/install-panel.sh
```

It asks for the domain (or IP), the administrator e-mail and an optional e-mail for
Let's Encrypt. You can also pass them as options:

```bash
sudo bash scripts/install-panel.sh --domain panel.example.com --admin-email you@example.com --email you@example.com
```

For a Let's Encrypt certificate the domain must point to the machine and port 80 must be
reachable. Without `--email` the installer creates a self-signed certificate and browsers
show a warning. Do not run it on a machine that already runs EpicWing: it stops when it
finds an existing installation. The package output goes to `/var/log/epicwing-install.log`.
Add nodes afterwards with `scripts/install-node.sh`.

There is no minimum password length. Choose a long, unique password, because the
administrator account controls your servers.

#### Installation failed, what now?

The installer does not undo a partial installation. Read the end of
`/var/log/epicwing-install.log` and the message on screen, fix the cause, then remove
the leftovers and run the installer again:

```bash
systemctl stop epicwing-panel 2>/dev/null; systemctl disable epicwing-panel 2>/dev/null
runuser -u postgres -- psql -c 'DROP DATABASE IF EXISTS epicwing' -c 'DROP USER IF EXISTS epicwing'
rm -rf /opt/epicwing /var/www/epicwing-panel /etc/ssl/epicwing /etc/systemd/system/epicwing-panel.service \
  /etc/nginx/sites-available/epicwing-panel /etc/nginx/sites-enabled/epicwing-panel
systemctl daemon-reload && systemctl reload nginx
```

### Manual installation

The steps below do the same by hand.

### 1. Database

Create a PostgreSQL database and a user for the panel (pick your own password):

```bash
sudo -u postgres psql -c "CREATE USER forge WITH PASSWORD 'CHANGE_ME';" -c "CREATE DATABASE forge OWNER forge;"
```

On a normal installation PostgreSQL listens on port 5432, so use
`DATABASE_URL=postgresql+psycopg://forge:CHANGE_ME@localhost:5432/forge`.
The port 5433 in `.env.example` belongs to `deploy/docker-compose.dev.yml`, which starts a database for development.

### 2. Backend

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install .
cp ../.env.example .env
```

The backend reads `.env` from its working directory. Fill in at least:

- `DATABASE_URL`
- `EPICWING_SECRET_KEY` and `EPICWING_ENCRYPTION_KEY` (the generator commands are in `.env.example`)
- `EPICWING_ENV=production`
- `EPICWING_PUBLIC_URL`, the public address of the panel, e.g. `https://panel.example.com`

Without `EPICWING_PUBLIC_URL`, logins are rejected with "Origin not allowed." in production.

Create the tables and the first administrator:

```bash
.venv/bin/alembic upgrade head
.venv/bin/python -m app.cli create-admin --email you@example.com
```

The second command asks for the password twice.

Migrations don't run on their own, see [Updating](#updating).

### 3. Frontend

```bash
cd frontend
npm ci
npm run build
```

Copy the contents of `frontend/dist` to the directory nginx serves, e.g. `/var/www/epicwing-panel`.

### 4. Run the panel

Create the unprivileged user and give it the code:

```bash
useradd --system --home-dir /opt/epicwing --shell /usr/sbin/nologin epicwing
chown -R epicwing:epicwing /opt/epicwing/backend
```

Run the backend as a systemd service under that user. Use a single
process, do not add workers.

```ini
[Unit]
Description=EpicWing panel
After=network-online.target
Wants=network-online.target

[Service]
User=epicwing
WorkingDirectory=/opt/epicwing/backend
ExecStart=/opt/epicwing/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8010
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

### 5. Reverse proxy

nginx serves the frontend and forwards `/api/` to the backend. The console and the
agents use WebSockets, so the upgrade headers and the long timeouts are required.

```nginx
map $http_upgrade $epicwing_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 80;
    server_name panel.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name panel.example.com;
    # ssl_certificate and ssl_certificate_key go here

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
```

### 6. Nodes

Add a node in the admin area. `scripts/install-node.sh` installs the agent on the node.
The agent binary (`epicwing-agent-linux-amd64`) and its checksum file `SHA256SUMS` are attached to each
GitHub release. Install with `--url <release asset url> --sha256 <hash>`, or download the file
yourself and pass it with `--binary`.

Example for release v0.1.1-beta (run as root on the node, it asks for the enrollment token
shown in the admin area):

```bash
sudo bash scripts/install-node.sh --panel https://panel.example.com \
  --url https://github.com/EpicWing/epicwing-panel/releases/download/v0.1.1-beta/epicwing-agent-linux-amd64 \
  --sha256 14cdf04e94374ca651108450f2c0c29ceee4ace6c126aeb721cfc3c0e441434f
```

Docker must already be installed on the node.

## Updating

Back up the database first.

```bash
sudo -u postgres pg_dump -Fc YOUR_DB > /var/backups/epicwing-$(date +%F).dump
```

Then update the code and run this in `backend`:

```bash
.venv/bin/pip install .
.venv/bin/alembic upgrade head
systemctl restart epicwing-panel
```

Rebuild the frontend and copy `frontend/dist` to the nginx directory again. Update the
agent on your nodes so it matches the panel version.

To roll back, go back to the previous code and restore the dump:

```bash
systemctl stop epicwing-panel
sudo -u postgres pg_restore --clean --if-exists -d YOUR_DB /var/backups/epicwing-DATE.dump
```

Start the panel again afterwards. Everything created after the backup is gone.

## Production notes

- `EPICWING_ENV=production` also turns off `/docs` and `/openapi.json`.
- `EPICWING_ALLOWED_ORIGINS` is only needed if the panel is reachable under more than one address.
- Use HTTPS only.

## Development

See `scripts/dev.sh` for local work. Checks that CI runs:

- Backend: `ruff check .`, `ruff format --check .`, `python -m pytest -q`
- Agent: `go vet ./...`, `go test ./...`
- Frontend: `npx vue-tsc --noEmit`, `npm run build`

## Security

See [SECURITY.md](SECURITY.md) to report a vulnerability.

## License

[MIT](LICENSE). EpicWing imports Pterodactyl-format egg files for compatibility.
It is not affiliated with Pterodactyl. See `docs/LICENSING_AND_ATTRIBUTION.md`.
