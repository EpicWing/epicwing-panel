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
  <a href="LICENSE"><img src="https://img.shields.io/github/license/EpicWing/epicwing-panel?v=2" alt="MIT license"></a>
  <a href="https://github.com/EpicWing/epicwing-panel/releases"><img src="https://img.shields.io/github/v/release/EpicWing/epicwing-panel?include_prereleases" alt="Release"></a>
  <img src="https://img.shields.io/badge/Debian-13-A81D33?logo=debian&logoColor=white" alt="Debian 13">
  <img src="https://img.shields.io/badge/status-beta-orange" alt="Beta">
  <a href="https://discord.gg/tc7xtNPsmh"><img src="https://img.shields.io/badge/Discord-Join-5865F2?logo=discord&logoColor=white" alt="Discord"></a>
</p>

<p align="center">
  <a href="#installation">Installation</a> ·
  <a href="#features">Features</a> ·
  <a href="#documentation">Documentation</a> ·
  <a href="#limitations">Limitations</a> ·
  <a href="CHANGELOG.md">Changelog</a>
</p>

EpicWing is a self-hosted server management panel. Game servers and other services
each run in their own isolated Docker container on a node. The panel talks to a small Go agent on
each node.

**Status: beta.** Fine for small setups, not ready for large or multi-tenant hosting.
See [Limitations](#limitations).

## Why EpicWing

- **Isolated by default:** every server runs in its own Docker container, in a separate network with container-to-container traffic switched off
- **Image allowlist:** a node only starts images you allowed, and they can be pinned by digest
- **Limits:** memory, swap and storage per server, and memory and storage limits per node
- **Verified installs:** the installer checks a SHA-256 checksum of the agent binary before it installs it
- **Login everywhere:** every API route needs a login, with two-factor authentication and a password reset that does not skip it

<!--
## Screenshots

Add images to docs/assets/ and remove this comment, for example:

![Server console](docs/assets/screenshot-console.png)
![Admin overview](docs/assets/screenshot-overview.png)
-->

## Requirements

- **Panel:** a fresh Debian 13 (x86_64) server with a domain or an IP, ports 80 and 443 open
- **Node:** Debian 13 (x86_64) with Docker already installed, and the enrollment token from the admin area
- Everything else (PostgreSQL, nginx, TLS, the agent) is set up by the installer

## Installation

Tested on Debian 13 (x86_64). On a fresh machine, as root:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/EpicWing/epicwing-panel/main/scripts/install.sh)
```

The script asks whether to install the panel or a node. The panel installer sets up
PostgreSQL, nginx, TLS and the first administrator. For a node you need the enrollment
token from the admin area, and Docker must already be installed. You can also name the
target directly:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/EpicWing/epicwing-panel/main/scripts/install.sh) node --panel https://panel.example.com
```

Options, the manual installation, updating and troubleshooting are in
[docs/INSTALL.md](docs/INSTALL.md).

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
- In-panel guide for administrators

## Documentation

- [Installation, updating and troubleshooting](docs/INSTALL.md)
- [Agent protocol](docs/agent-protocol.md)
- [Installer security](docs/installer-security.md)
- [Changelog](CHANGELOG.md)
- [Contributing](CONTRIBUTING.md)

## Limitations

- **DDoS:** EpicWing only detects and reports unusual traffic. It blocks nothing, so use
  your provider's protection or a firewall for that.
- Tested on Debian 13 (x86_64) with systemd and Docker only. The installer also accepts Ubuntu 24.04 or newer, but that is not tested.
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

## Development

See `scripts/dev.sh` for local work. Checks that CI runs:

- Backend: `ruff check .`, `ruff format --check .`, `python -m pytest -q`
- Agent: `go vet ./...`, `go test ./...`
- Frontend: `npx vue-tsc --noEmit`, `npm run build`

Bug reports and pull requests are welcome, see [CONTRIBUTING.md](CONTRIBUTING.md).

## Contact

- Support: [support@epicwing.de](mailto:support@epicwing.de)
- Abuse reports: [abuse@epicwing.de](mailto:abuse@epicwing.de)
- General questions and other inquiries: [info@epicwing.de](mailto:info@epicwing.de)
- Community: [Discord server](https://discord.gg/tc7xtNPsmh)

Bugs and feature requests belong in the [issue tracker](https://github.com/EpicWing/epicwing-panel/issues).

## Security

See [SECURITY.md](SECURITY.md) to report a vulnerability.

## License

[MIT](LICENSE). EpicWing imports Pterodactyl-format egg files for compatibility.
It is not affiliated with Pterodactyl. See `docs/LICENSING_AND_ATTRIBUTION.md`.
