# EpicWing Fortschritt

Stand: 2026-10-17 (Deadline: 2026-10-21)
Repo: /home/epicdev/forge, Branch: feature/server-install

## Ausgangszustand (Phase 0, geprüft 2026-10-17)
- Backend: 450 Tests grün (`cd backend && DATABASE_URL=postgresql+psycopg://test:test@127.0.0.1:1/test .venv/bin/python -m pytest -q`)
- Frontend: `npx vue-tsc --noEmit` grün
- Agent: `go build`, `go vet`, `go test ./...` grün
- Uncommittete Änderungen: S-01/B-04-Teilfix (AdminAuth für Eggs + Node-Commands), Review-Doku

## Prioritäten
1. Serverumzug: Runbook + Export/Import-Skripte (docs/MIGRATION.md, scripts/) — Ausführung nur nach Freigabe
2. Kernfunktionen verifizieren/reparieren (Launch, Reinstall, Rename, Files, Backups, Review-Befunde)
3. Offene Features: Backup-Transfer, Datenbanken, API-Keys, SSH-Keys, Avatar, Automations, Integrationstests

## Review-Befunde (docs/REVIEW-2026-10-17.md)
- S-01 Hoch: nodes.manage umgeht Server-Rechteprüfung via /api/nodes/{id}/commands → Fix: AdminAuth (uncommittet, Test fehlt)
- B-01 Hoch: container.install läuft in 90s-Timeout (Agent braucht bis 30 min) → offen
- B-02 Hoch: systemd-Unit Backup-Verzeichnis nicht in ReadWritePaths → offen
- S-02 Mittel: IP-Limiter/Audit über request.client.host (Reverse Proxy) → dokumentiert, Proxy fehlt im Repo
- S-03 Niedrig: stats-Frames nicht node-zugeordnet → offen
- B-03 Niedrig: Node-Trennung löscht Live-Statistik aller Server → offen
- B-04 Niedrig: Egg-Verwaltung an nodes.manage statt Admin → Fix uncommittet, Test fehlt
- B-05 Niedrig: create_allocations prüft Node-Portbereich nicht → offen
- B-06 Niedrig: add_member 404/409 Enumeration → offen

## Blockaden
- Produktivserver (Nordroot) offline, 1 Monat Sperre → keine echten Backups/Daten prübar
- S-02: Reverse-Proxy-Konfiguration nicht im Repo; Fix abhängig vom Zielsystem-Setup

## Entscheidungen
- S-01: run_command auf AdminAuth beschränken (einfacher und sicherer als server_access pro Containername; UI nutzt Server-Routen für Power-Aktionen)
- Tests laufen gegen SQLite im Speicher (conftest), Dummy-DATABASE_URL ist Absicht

## Update 2026-10-18
- Fertig und getestet: Backup-Transfer zwischen Servern derselben Node (Agent backup.copy, Route /transfer, Dialog), Avatar (Migration 0012, Settings, Seitenleiste, Timeline), Copyright-Footer, Admin-Navigation, Admin-Overview mit echten Daten, Locations.
- Live im Panel: Backend mit Migration 0012 und Frontend. Der Agent läuft noch ohne backup.copy (Rollout offen).
- Als Nächstes: Panel Settings (2FA-Pflicht), Monitoring-Reiter, Webhook-Benachrichtigungen mit Feed, API Keys.
- Panel settings (Name, Hilfe-Links) fertig und getestet, Migration 0013. Als Nächstes: 2FA-Pflicht, Monitoring-Reiter, Webhook-Benachrichtigungen, API Keys.
