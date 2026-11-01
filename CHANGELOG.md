# Changelog

## 0.1.5-beta (2026-11-01)

- The agent reports its real version (set at build time from the git tag), `update-agent.sh` does the same
- Admin overview: shows "unlimited" for empty totals, tighter spacing
- Issue and pull request templates
- Installer and docs point to v0.1.5-beta

## 0.1.4-beta (2026-11-01)

- Admin guide: friendlier texts, line icons, tip boxes, copy button
- Admin overview: help buttons back in the grid, singular wording fixed
- Installer and docs point to v0.1.4-beta

## 0.1.3-beta (2026-11-01)

Also covers 0.1.2-beta.

- In-panel guide for administrators
- All messages in the seed command, scripts, CLI and tests, and all code comments, in English
- Docs: CONTRIBUTING added, licensing and attribution shortened, credit for the bundled eggs, note on container images
- Internal planning files removed from the repository

## 0.1.1-beta (2026-10-31)

- One-command panel installer and node installer, one-line installer `scripts/install.sh`
- README shortened, details moved to `docs/INSTALL.md`, example command for the node installer
- New passwords need at least 8 characters
- Admin overview links to the docs and GitHub
- CLI messages in English, installer errors point to `docs/INSTALL.md`

## 0.1.0-beta (2026-11-01)

First public beta.

- Panel, Go agent and Vue frontend
- Users, roles, 2FA, API keys, SSH keys
- Nodes, servers, eggs, install, console, files, SFTP, backups, schedules
- Databases per server, notifications, auto restart
- Traffic guard with 60 minute history (detection and alerts only)
- Production mode disables the API documentation endpoints
