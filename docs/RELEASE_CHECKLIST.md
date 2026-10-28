# EpicWing – Release Checklist

Status dieses Audits: **nicht release-ready**. Die Checkboxen sind bewusst nicht als erledigt markiert, solange nur Quellcode- und Unit-Test-Nachweise vorliegen.

## Scope und Herkunft

- [ ] Release-Commit, Branch und Tag festgelegt.
- [ ] Verifiziert, dass Release aus `/root/forge/forge` und nicht aus `/home/epicdev/forge` gebaut wird.
- [ ] Panel-, Frontend- und Agent-Version/Commit sind aufeinander abgestimmt.
- [ ] Keine Secrets, `.env`-Inhalte, privaten Schlüssel, Passwörter oder Tokens in Artefakten, Logs und Docs.
- [ ] Lizenzdateien, Third-Party-Notices und Changelog geprüft.

## Build und automatisierte Qualität

- [ ] `backend/.venv/bin/pytest -q` grün.
- [ ] `ruff check .` grün.
- [ ] `ruff format --check .` grün.
- [ ] `npm test` und `vue-tsc --noEmit` grün.
- [ ] `npm run build` grün.
- [ ] `npm audit --audit-level=high` ohne High/Critical.
- [ ] `go test ./...`, `go vet ./...`, `go build ./...` grün.
- [ ] Container-/Go-/Python-Artefakte reproduzierbar und mit SBOM/CVE-Bericht gebaut.

## Frische Installation und Upgrade

- [ ] Leerer Debian-Testhost erfolgreich installiert.
- [ ] PostgreSQL, Alembic-Migrationen und Backup/Restore des Panel-DB-Schemas geprüft.
- [ ] Reverse Proxy, TLS, WebSocket-Upgrade und trusted proxy headers geprüft.
- [ ] systemd-Agent läuft mit least privilege, Docker-Zugriff und beschreibbarem Datenpfad.
- [ ] Agent enrollment ist single-use, Ablauf und Revoke funktionieren.
- [ ] Update und Rollback wurden tatsächlich ausgeführt.

## Funktionale Smoke-Tests

- [ ] Login, Logout, Passwortwechsel, 2FA und Recovery-Code.
- [ ] Admin-/Member-/Read-only-/deaktivierter Benutzer und Serverrechte.
- [ ] API-Key create, one-time display, read-only, expiry, revoke, audit.
- [ ] SSH-Key add/delete, SFTP read/write, denied access and host key.
- [ ] Node online/offline/reconnect and resource heartbeat.
- [ ] Server create, allocation conflict, install, console, start/stop/restart/kill/remove.
- [ ] Files list/read/write/upload/download/archive and traversal/symlink checks.
- [ ] Backup create/status/download/restore/delete and interrupted transfer.
- [ ] Schedule once, retry, DST and node-offline behavior.
- [ ] Database host test/create/rotate/delete.
- [ ] Egg import/export round-trip with official fixture corpus.
- [ ] EULA/rules dialog blocks and records consent before install.
- [ ] DDoS detection handles samples, stale data and offline status; mitigation scope is documented.

## Observability und Sicherheit

- [ ] No secret appears in application logs or audit details.
- [ ] Request correlation ID, error code and user-facing error mapping exist.
- [ ] Alerts for agent offline, failed install, failed backup, disk/memory limits.
- [ ] Rate limits, proxy IP parsing and authentication-failure behavior are tested.
- [ ] Installer images are allowlisted/pinned and network permissions documented.
- [ ] File and SFTP paths cannot escape the server data root.
- [ ] Multi-worker/multi-instance locking and retry semantics are tested.

## Rollout und Rückfall

- [ ] Maintenance window and operator owner documented.
- [ ] Database backup verified by restore, not only by file existence.
- [ ] Rollback artifact and database compatibility decision documented.
- [ ] Canary node/user group selected.
- [ ] Stop criteria and incident contact defined.
- [ ] Post-release health, agent heartbeat, install, console, SFTP and backup observed.

## Current blockers

1. Ruff is red: 12 errors; formatting check reports 49 files.
2. No fresh-host, real-Docker-node, external-SFTP or end-to-end backup proof.
3. No complete production installer/update/rollback contract.
4. Pterodactyl Egg compatibility has not been proven with a fixture corpus.
5. Documentation and current source have drifted (`README.md`, `PROGRESS.md`, old review).


## Nachträge aus dem Betrieb

- [ ] GSLT-Token und alle in Chats, Logs oder Screenshots gezeigten Tokens neu erzeugen.
- [ ] `policy.json` jeder Node enthält die Images aller mitgelieferten Eggs. `install-node.sh` schreibt sie nur bei einer Neuinstallation, bestehende Nodes müssen ergänzt und der Agent neu gestartet werden.
- [ ] Mitgelieferte Eggs in `backend/fixtures/eggs/` mit Herkunft und Lizenz je Datei dokumentiert.
- [ ] Agent-Binary auf allen Nodes auf dem Stand des Panels (Port-Check beim Start).
- [ ] Egg-Seed (`seed-eggs` und Autostart auf leerer DB) auf einer frischen Installation getestet.
- [ ] EULA-Dialog: Verhalten mit der Zeile "EULA/rules dialog" oben abgeglichen (er erscheint nach dem Abbruch, er sperrt den Install nicht).
