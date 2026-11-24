# Changelog

## Unreleased

## 0.3.5-beta (2026-11-24)

### What's new

- Panel update: the update now waits until the panel answers on `/api/health` before it counts as done. Before, any answer counted, even an error page, so a broken update could stay in place
- Panel update: files that a release removed are now deleted from `/opt/epicwing/backend`, so no old code or old migrations stay behind. `.env` and the Python environment are kept
- Panel update: if the new panel does not start, the old code is now restored cleanly, without files from the new release left in between
- Panel update: rsync is now installed with the package manager of your system when it is missing. Before, this only worked on Debian and Ubuntu
- Appearance settings: the texts now come from the language file like all other texts
- Code comments and test messages are now all in English
- `scripts/update-frontend.sh` (for developers): only deploys a clean checkout of `origin/main`. Use `--force` to deploy something else on purpose

### Update

Panel (makes a database backup first, no database migration in this release):

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/EpicWing/epicwing-panel/main/scripts/install.sh) update panel
```

Updating the nodes is optional: the agent is the same as in 0.3.4-beta, only its version number changes. Nodes on 0.3.4-beta keep working with this panel. If you want the same version everywhere:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/EpicWing/epicwing-panel/main/scripts/install.sh) update node
```

### New install

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/EpicWing/epicwing-panel/main/scripts/install.sh) panel
```

Use a domain name for the panel, not an IP address, and give an e-mail for Let's Encrypt when the installer asks. Nodes need this to connect.

## 0.3.4-beta (2026-11-23)

### What's new

- New file editor: search and replace (Ctrl+F, Ctrl+H), code folding, matching brackets, several cursors with Alt+click and a highlighted current line. Ctrl+S still saves. The editor only loads when you open a file, so the server page does not get slower
- Password generator: when you create a user or reset a password, "Generate" fills in a strong 20-character password and shows it, so you can copy it right away
- Panel installer: now also runs on Rocky Linux, AlmaLinux and Fedora, Arch Linux and openSUSE, next to Debian and Ubuntu. Where the system ships an older Python or Node.js, the installer adds a current one, and it sets up PostgreSQL, nginx and SELinux the way each system needs
- Node installer: installs Docker by itself when it is missing. Pass `--skip-docker` if you prefer to manage Docker yourself
- Remote backups: the agent no longer follows redirects from the backup storage, so a backup only ever goes to the address you set

### Update

Panel (makes a database backup first, no database migration in this release):

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/EpicWing/epicwing-panel/main/scripts/install.sh) update panel
```

This release changes the agent, so please update your nodes as well:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/EpicWing/epicwing-panel/main/scripts/install.sh) update node
```

### New install

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/EpicWing/epicwing-panel/main/scripts/install.sh) panel
```

Use a domain name for the panel, not an IP address, and give an e-mail for Let's Encrypt when the installer asks. Nodes need this to connect.

## 0.3.3-beta (2026-11-21)

### What's new

- New server cards: a cleaner look with a status pill, icons for CPU, RAM and disk, and a small bar under each value that shows how close the server is to its CPU, RAM and disk limit. A value with no set limit shows no bar.
- The activity log now shows a user's chosen display name instead of the name taken from their e-mail address.

### Update

Panel (makes a database backup first, no database migration in this release):

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/EpicWing/epicwing-panel/main/scripts/install.sh) update panel
```

The agent has no changes in this release, so updating the nodes is optional:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/EpicWing/epicwing-panel/main/scripts/install.sh) update node
```

### New install

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/EpicWing/epicwing-panel/main/scripts/install.sh) panel
```

Use a domain name for the panel, not an IP address, and give an e-mail for Let's Encrypt when the installer asks. Nodes need this to connect.

## 0.3.2-beta (2026-11-19)

### What's new

- Help right where you need it: the pages for SSH keys, API keys, SFTP, access and backups open a short guide the first time you visit them. You can open it again any time with the help link on the page
- When your session ends, the panel takes you to the login page with a short note, instead of showing errors. After signing in you are back on the page you were on
- Tabs in the background no longer ask the panel for updates every few seconds. They refresh again as soon as you switch back. This takes load off the panel when many people have it open
- Node installer: when the panel can't be reached, it now says why. With an IP address instead of the domain, it tells you to use the domain name, because the certificate only fits the domain
- Panel installer: shows a warning when you install with an IP address only, because nodes need a domain name with a Let's Encrypt certificate
- From now on, releases are full releases instead of pre-releases

### Update

Panel (makes a database backup first, no database migration in this release):

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/EpicWing/epicwing-panel/main/scripts/install.sh) update panel
```

Nodes (run on every node):

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/EpicWing/epicwing-panel/main/scripts/install.sh) update node
```

The agent has no changes in this release, so updating the nodes is optional.

### New install

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/EpicWing/epicwing-panel/main/scripts/install.sh) panel
```

Use a domain name for the panel, not an IP address, and give an e-mail for Let's Encrypt when the installer asks. Nodes need this to connect.

## 0.3.1-beta (2026-11-18)

- Move a server to another node: new Transfer tab on the server page. The old node packs the files, the panel passes them on, the new node checks the SHA-256 sum and unpacks them. The database only switches to the new node at the very end, so a failed move leaves the server where it was. The files on the old node stay until you delete them. Extra ports have to be added again on the new node
- The move needs `EPICWING_PUBLIC_URL` in the panel's `.env` and agent 0.3.0 or newer on both nodes. The panel says so before it starts
- New server permissions "Delete server" and "Move to another node". Before, only admins could do both. Server owners have them like every other permission. API keys can do neither
- Every user can set a name under Settings → Profile. It is shown instead of the email address in the access list and the user list
- Agent: `allowed_images` in `/etc/epicwing-agent/policy.json` accepts entries that end in `/*`. `"ghcr.io/ptero-eggs/*"` allows every image from the Pterodactyl egg repositories, so marketplace templates no longer need one entry per image. Entries like `ghcr.io/*` are too broad and ignored. New nodes get the ptero-eggs entry by default

### Update

Panel. It makes a database backup first and runs the database migration 0030:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/EpicWing/epicwing-panel/main/scripts/install.sh) update panel
```

Every node:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/EpicWing/epicwing-panel/main/scripts/install.sh) update node
```

To allow all ptero-eggs images on a node that already exists, add `"ghcr.io/ptero-eggs/*"` to `allowed_images` in `/etc/epicwing-agent/policy.json` and restart the agent:

```bash
systemctl restart epicwing-agent
```

## 0.3.0-beta (2026-11-15)

- Backups in S3-compatible object storage (Admin → Infrastructure → Backup storage). Finished backups are uploaded in parts, restores download them first, downloads come straight from the bucket. The S3 keys stay in the panel, nodes only get presigned links that expire. Needs the new agent and the database migration 0027
- Docs: ARM64 nodes (Raspberry Pi 4/5, Oracle Ampere) are listed as supported. Eggs need images for ARM, SteamCMD games are usually x86_64 only
- Import from Pterodactyl and Pelican: `python -m app.cli import-pterodactyl` copies users, nodes, allocations, eggs, servers, server variables and subusers. Servers keep their UUID. Dry run by default, see [docs/MIGRATING.md](docs/MIGRATING.md)
- Login accepts bcrypt password hashes from Pterodactyl and Pelican and replaces them with argon2 at the first login
- Marketplace: install server templates (eggs) from reviewed catalogs that are pinned to a commit and checked by SHA-256. Areas for games, bots, apps, databases and voice, with search, sorting, tags, grid and list view. Installed templates show an update button when the catalog has a newer version. New templates are sent to support@epicwing.de and reviewed
- UI: no staggered page animation, no glowing status dots, no lifting cards, neutral help links, one card radius
- Colors `ink-500`, `ink-200` and `accent-300` are defined now. Before, texts with these classes showed in full brightness
- Official catalog: 43 server templates from the Pterodactyl egg repositories (MIT), among them SCP:SL, Rust, Counter-Strike 2, Valheim, Terraria, Palworld, Uptime Kuma, Gitea, MariaDB, PostgreSQL, Redis and TeamSpeak 6. They keep a link to their source
- Server settings: admins can delete a stopped server after typing its name. The container, files and databases are removed, the ports become free
- Command palette with Ctrl+K: jump to servers, nodes and pages, run actions and open GitHub, the docs and Discord
- Icons per type (game, bot, app, database, voice) in their own colors
- Update the panel with `bash <(curl -fsSL https://raw.githubusercontent.com/EpicWing/epicwing-panel/main/scripts/install.sh) update panel`. It makes a database backup first and runs the new database migrations
- Nodes: run `install.sh update node` on every node. The new agent is needed for backups in S3 storage
- Marketplace templates need their Docker images in `allowed_images` in `/etc/epicwing-agent/policy.json` on the node. The catalog repository lists them in `images.txt`

## 0.2.4-beta (2026-11-10)

- Server console: the output of a stopped server stays until the next start, so the reason for a quick crash is still visible. Before, it was cleared as soon as the container exited
- Servers that stop because the Minecraft EULA is not accepted show a dialog with an "Accept and start" button
- Access: panel admins see all eligible users when they add a user to a server and can filter by part of the email address. Other users still need the full email address. The dialog explains this now, instead of saying that no users are available
- Server page: CPU, RAM and uptime show right after a reload, not only with the next update
- Charts: the RAM and CPU charts follow the data instead of the memory limit and a fixed 1 percent, so small processes stay visible
- Update the panel with `bash <(curl -fsSL https://raw.githubusercontent.com/EpicWing/epicwing-panel/main/scripts/install.sh) update panel`. It makes a database backup first. This release has no new database migration
- Nodes: the agent has no changes, so no node update is needed

## 0.2.3-beta (2026-11-10)

- Installer: Ubuntu 24.04 works now, next to Debian 13. Newer Ubuntu releases are accepted, but not tested
- Panel installer: on Ubuntu, needrestart no longer stops apt with a question. A warning shows when ufw is on and may block ports 80 and 443
- Node installer: a warning shows on systems that are not Debian or Ubuntu. The installer stops when Docker comes from snap
- Bug report template: the example system is now Debian 13 or Ubuntu 24.04
- The version numbers in the frontend and the backend were still 0.2.1-beta. They are 0.2.3-beta now

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
