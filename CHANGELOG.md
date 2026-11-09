# Changelog

## Unreleased

## 0.2.2-beta (2026-11-09)

- Server list: no colored edge on the cards, click the address to copy it, quieter labels, softer hover, more padding. The status glow is only on the status dot
- Server list: stopped servers show "Offline" instead of 0 cores and 0 MiB
- Server page: one status line instead of pills and tiles, a smaller title, and Stop is no longer the main button
- Sidebar: the main sidebar uses the same style as the server sidebar, without the colored left edge
- Charts: one theme-aware color palette (orange CPU, rose RAM, green download, violet upload) instead of scattered colors
- DDoS chart: hover with a dot on the line, a guide line and a tooltip with the full date and time. The time range is a dropdown now
- Light mode: better contrast for server names and the filter badge
- Panel: the Discord webhook URL is checked when the message is sent
- Panel: a failed database create no longer drops existing databases, and database, user and host names are matched completely
- CI: the workflow token is limited to read access

## 0.2.1-beta (2026-11-08)

- Node.js Discord bot egg: the Node.js 22 and 24 images are now in the default node policy, pinned by digest. Before, a Node.js bot could not start on a fresh node because its images were not allowed
- Node.js 20 is removed from the egg, it is end of life
- Existing nodes keep their old `policy.json`. Add `ghcr.io/ptero-eggs/yolks:nodejs_22` and `ghcr.io/ptero-eggs/yolks:nodejs_24` to `allowed_images` in `/etc/epicwing-agent/policy.json` and run `systemctl restart epicwing-agent`. Pinning them in `image_digests` is optional
- Agent: the "not on the allowlist" error now says that the image has to be added to `allowed_images` in `policy.json`
- Creating a node or issuing a new token now shows a ready install command with the token inside, instead of the bare token. The panel address in the command comes from the address bar, so open the panel through its real domain. The command needs this release or newer
- `install-node.sh` also reads the token from the `EPICWING_ENROLL_TOKEN` environment variable
- Admin guide: the node steps describe the new install command

## 0.2.0-beta (2026-11-07)

- Node limits: set a memory limit and a storage limit (GB) per node in the node settings. Empty means unlimited. The panel refuses new servers and limit changes that would go over what is left on the node, also when several requests arrive at the same time
- New database migration (0023): run `alembic upgrade head` when you update, and make a backup first
- Server settings: admins can edit memory, CPU and storage of a server
- Light mode with a theme switch (light, dark or system), plus several rounds of contrast and colour fixes
- Console: the output is cleared when the container exits and the offline line shows up on a stopped server
- Admin overview: stat cards link to their pages
- Admin activity page: shown inside the app layout again, so the sidebar and header are there
- Settings and server settings use two columns on wide screens
- Database pool settings are documented in `.env.example`, and the server and node lists support limit and offset
- Game servers now run in their own Docker network (`epicwing-servers`) with container-to-container traffic switched off. Ports and internet access work as before
- Servers get a swap limit equal to their memory limit, so they can't use more RAM than they were given
- Container logs are capped at 3 files of 10 MB
- All API routes now check for a login
- The agent is built with Go 1.26.10, x/crypto is updated
- Network, swap and log settings only apply to containers created after the update. Existing servers keep their old settings until they are recreated, a normal restart is not enough
- Not done yet: the admin overview doesn't show the node limits, and you can't set them while creating a node, only afterwards in the settings

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
