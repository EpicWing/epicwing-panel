# Changelog

## Unreleased

- Bundled eggs for PaperStream (Paper fork) and PaperProxy (Velocity fork with BungeeCord plugin support)

## 0.1.7-beta (2026-11-03)

- Password reset by e-mail: a "Forgot password?" link on the sign-in page. It only shows up when the e-mail settings are saved and `EPICWING_PUBLIC_URL` is set
- The reset link works for 30 minutes and only once, signs out every session of the account and does not skip 2FA. The answer is the same for known and unknown addresses, and requests are rate limited
- New database migration (0021): run `alembic upgrade head` when you update
- Server page: click the address to copy it (also works without HTTPS)
- Admin guide: new part about the password reset
- Version numbers in the panel, the backend and the frontend match the release

## 0.1.6-beta (2026-11-02)

- Settings: list of active sessions (without IP addresses), aligned cards
- Access tab: permission presets in the form, tabs and settings buttons are hidden without permission, clearer manager preset and admin hint
- Agent: golang.org/x/crypto updated to 0.52.0
- All code comments in English, empty architecture doc removed
- Docs: Discord link, contact addresses and badges, README requirements
- Installer and docs point to v0.1.6-beta

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
