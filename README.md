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

## Production notes

- Set `EPICWING_ENV=production` (this disables `/docs` and `/openapi.json`).
- Set `EPICWING_ALLOWED_ORIGINS` to the address of your panel.
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
