# Moving from Pterodactyl or Pelican

EpicWing reads the database of your old panel and copies users, nodes, allocations,
nests, eggs, servers, server variables and subusers. The old database is only read.

| Copied | Not copied |
|---|---|
| Users with their passwords (bcrypt, upgraded to argon2 at the first login) | Two-factor authentication, users set it up again |
| Nodes (as "pending"), locations, allocations, memory and disk limits | Server databases and database hosts |
| Nests, eggs and variables, including inherited config and install scripts | Backups, schedules, API keys, activity logs |
| Servers with the same UUID, limits, image, startup command and variables | |
| Subusers, with their permissions mapped to EpicWing permissions | |

## 1. Give EpicWing read access

On the old panel server, create a user that can only read:

```bash
mysql -u root -p -e "CREATE USER 'epicwing_import'@'127.0.0.1' IDENTIFIED BY 'a-long-password'; GRANT SELECT ON panel.* TO 'epicwing_import'@'127.0.0.1';"
```

On the EpicWing panel server, open an SSH tunnel to it, so MySQL stays closed to the internet:

```bash
ssh -f -N -L 3307:127.0.0.1:3306 root@old-panel.example.com
```

## 2. Dry run

```bash
cd /path/to/epicwing/backend
read -rsp "Pterodactyl DB password: " PW; echo
export PTERODACTYL_DB_URL="mysql+pymysql://epicwing_import:${PW}@127.0.0.1:3307/panel"
.venv/bin/python -m app.cli import-pterodactyl
```

Nothing is saved. Check the numbers, the warnings and the list of users with 2FA.
Passwords with `@`, `:` or `/` must be URL-encoded in the address.

## 3. Import

```bash
.venv/bin/python -m app.cli import-pterodactyl --apply
```

Running it again is safe. Users, nodes, eggs and servers that already exist are skipped.

## 4. Move each node

The report lists the commands per node. For every node:

1. Install the EpicWing agent with the enrollment token from **Admin → Nodes**.
2. Stop Wings: `systemctl stop wings && systemctl disable wings`
3. Copy the data of each server, for example
   `rsync -a /var/lib/pterodactyl/volumes/<uuid>/ /var/lib/epicwing/servers/<uuid>/`
4. In the panel, press **Install** on each server. The install script of the egg runs once,
   the copied files stay.

Allow the Docker images of the imported eggs on the node, otherwise the agent will not start them.
