# EpicWing

EpicWing is a game server management panel. Every server runs in its own
isolated Docker container on a node. The panel talks to a small Go agent on
each node.

**Status: beta.** EpicWing is usable for small setups but is not production-ready
for large or multi-tenant hosting. See [Limitations](#limitations).

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

- **DDoS:** EpicWing detects and reports unusual traffic. It does **not** block or
  mitigate attacks. Use your provider's or firewall's protection for that.
- Tested on Debian 13 (x86_64) with systemd and Docker only.
- The panel runs as a single process. Schedules, rate limits and action locks
  are kept in memory, so do not run several workers.
- Backups are stored on the node. There is no S3 or cross-node storage yet.
- No web hosting features (domains, vhosts, TLS).
- The agent needs access to the Docker socket, which is equivalent to root on the
  node. Run nodes on dedicated machines.

## Installation

Tested on Debian 13 with systemd. You need Python 3.11 or newer (tested with 3.13), Node.js 20 or newer,
PostgreSQL 16 and a reverse proxy (nginx) with a TLS certificate. Nodes need Docker.
The paths below are examples, adjust them to your setup.

### 1. Database

Create a PostgreSQL database and a user for the panel. For development,
`deploy/docker-compose.dev.yml` starts one.

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

Create the tables and the first administrator. Migrations do not run
automatically, run the first command again after every update:

```bash
.venv/bin/alembic upgrade head
.venv/bin/python -m app.cli create-admin --email you@example.com
```

The second command asks for the password twice. After an update, run
`.venv/bin/pip install .` and `.venv/bin/alembic upgrade head` again.

### 3. Frontend

```bash
cd frontend
npm ci
npm run build
```

Copy the contents of `frontend/dist` to the directory nginx serves, e.g. `/var/www/epicwing-panel`.

### 4. Run the panel

Run the backend as a systemd service under an unprivileged user. Use a single
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
        try_files $uri /index.html;
    }
}
```

### 6. Nodes

Add a node in the admin area. `scripts/install-node.sh` installs the agent on the node.

## Production notes

- Set `EPICWING_ENV=production` (this disables `/docs` and `/openapi.json`).
- Set `EPICWING_PUBLIC_URL` to the public address of your panel, e.g. `https://panel.example.com`. Logins from any other origin are rejected in production. `EPICWING_ALLOWED_ORIGINS` is optional and only for additional origins.
- Serve the panel over HTTPS only.

## Development

See `scripts/dev.sh` for local work. Checks that CI runs:

- Backend: `ruff check .`, `ruff format --check .`, `python -m pytest -q`
- Agent: `go vet ./...`, `go test ./...`
- Frontend: `npx vue-tsc --noEmit`, `npm run build`

Copy `.env.example` to `.env` and adjust it.

## Security

See [SECURITY.md](SECURITY.md) to report a vulnerability.

## License

[MIT](LICENSE). EpicWing imports Pterodactyl-format egg files for compatibility.
It is not affiliated with Pterodactyl. See `docs/LICENSING_AND_ATTRIBUTION.md`.
