# EpicWing – Architecture Gaps

## Wichtigste Lücken

| Priorität | Lücke | Evidenz / Auswirkung | Ziel |
|---|---|---|---|
| P0 | Kein reproduzierbarer Production-Releasepfad | Repo enthält Dev-Compose, Node-Skripte und systemd-Agent, aber keinen vollständigen Panel-Installer, Reverse-Proxy-Stack, versionierte Release-Artefakte oder Rollback-Runbook | Fresh-Host-Installation und Upgrade als automatisierter, signierter Ablauf |
| P0 | Agent-Provenienz | Backend lebt unter `/root/forge/forge`, der laufende Agent unter `/opt/epicwing/epicwing-agent`; Version/Commit-Zuordnung wurde nicht als Release-Artefakt belegt | Panel, Agent und Frontend tragen dieselbe nachvollziehbare Release-Version |
| P0 | Qualitätsgate rot | 716 Backend-Tests bestehen, aber Ruff meldet 12 Fehler; 49 Dateien sind nicht formatiert | CI muss Test, Ruff, Typecheck, Build, Go test/vet/build und Security Checks blockieren |
| P0 | Live-Integration fehlt | Health ist erreichbar, aber kein echter Install-, Power-, SFTP-, Backup- oder Cross-Node-Test wurde durchgeführt | Isolierte Test-Node mit Docker und externem SFTP/Backup-Client |
| P0 | Installer-Trust | Egg-Skripte führen absichtlich Code im Installer-Container aus; Allowlist ist vorhanden, aber Supply-Chain, Image-Pinning, Signatur und Netzwerk-Egress sind nicht als Releasepolicy festgelegt | Vertrauensmodell, Digest-Pinning, Audit und Quarantäne dokumentieren |
| P1 | Prozess-Locks | `servers.py` nutzt einen Prozess-lokalen `asyncio.Lock`; bei mehreren Uvicorn-Workern oder Instanzen kann dieselbe Serveraktion parallel starten | DB-/Distributed-Lock plus Idempotency-Key |
| P1 | Reverse-Proxy-Vertrag | Audit-/Rate-Limit-IP nutzt teilweise `request.client.host`; ohne vertrauenswürdige Proxy-Liste kann IP falsch oder spoofbar sein | Trusted proxy hops, Forwarded-Header-Regeln und Tests |
| P1 | Backup-Storage | Lokale Backup-Aktionen sind sichtbar; S3/Remote-Storage, Integritätsmanifest, Retention und Cross-Node-Wiederherstellung sind nicht belegt | Storage-Adapter, Hash/Manifest, Retention und Restore-Tests |
| P1 | Egg-Wire-Kompatibilität | Import/Export existiert, aber kein offizielles Fixture-Korpus oder Feldmatrix | Versionierter Adapter und Kompatibilitätsmatrix |
| P1 | API-Vertrag | FastAPI erzeugt OpenAPI, aber im Repo fehlt ein versionierter, veröffentlichter API-/Client-Vertrag und Changelog | `/api/v1`-Strategie oder explizite stabile Contract-Version |
| P1 | Datenbankbetrieb | Alembic-Migrationen vorhanden, jedoch kein dokumentierter Backup-/Restore-/Downgrade-Prozess und kein Python-Lockfile | Migration preflight, rollback policy, reproduzierbare Abhängigkeiten |
| P2 | Observability | Live-Stats und Health vorhanden; kein vollständiger Alerting-, Log-, Trace- und Audit-Retention-Vertrag | Metriken, Korrelation-ID, redigierte Logs, SLOs |
| P2 | UI-Qualität | Vue/i18n/Responsive-Komponenten vorhanden, aber kein Browser-E2E- oder Accessibility-Gate | Playwright/A11y-Smoke und mobile/keyboard acceptance |
| P2 | Dokumentationsdrift | README behauptet frühe Entwicklung; `PROGRESS.md` und alter Review referenzieren ältere Stände | README, Progress, Protokoll und Release-Docs gemeinsam aktualisieren |
| P3 | Webhosting | Domains, vHosts, TLS, Webroots und Web-Runtimes sind nicht implementiert | Als separates Produktmodul mit eigenem Threat Model behandeln; nicht heimlich in Serverrechte mischen |

## Architekturregeln, die vor dem Release festgeschrieben werden sollten

Mangels `AGENTS.md` gibt es aktuell keine repositoryweite Arbeitsregeldatei. Vorschlag:

- Produktionsänderungen nur nach reproduzierbarem Test und mit klarer Migrations-/Rollback-Notiz.
- Keine Secrets, `.env`-Werte, privaten Schlüssel oder produktiven Tokens in Git, Logs, Audit oder Dokumentation.
- Jede neue Agent-Aktion benötigt Panel-Autorisierung, stabile Fehlercodes, Timeout, Idempotenz und einen Negativtest.
- Jeder Dateipfad wird gegen Traversal, Symlink-Ausbruch, Quota und Berechtigung geprüft.
- Egg-/Installer-Änderungen sind Admin-only, auditierbar und auf allowlisted Image-Digests begrenzt.
- DB-Schemaänderungen brauchen Alembic-Migration, Upgrade-Test und dokumentierte Downgrade-Entscheidung.
- Änderungen an API, WebSocket-Frames oder Egg-Feldern brauchen versionierte Contract-Tests.
- CI muss Python, Frontend und Go vollständig prüfen; ein grüner Teilbereich reicht nicht für Release.

## Zielbild

```text
Browser / API client
        |
  Reverse proxy + TLS + trusted headers
        |
FastAPI panel ---- PostgreSQL/Alembic
        |
  authenticated outbound WebSocket
        |
Go agent ---- Docker ---- server containers
   |  \---- SFTP (external port, SSH keys)
   \------- backup/file operations
```

Die Grenzen müssen explizit bleiben: Das Panel entscheidet Identität und Rechte; der Agent validiert nochmals seine erlaubten Aktionen; Docker isoliert Container; externe SFTP-/Backup-/Proxy-Komponenten haben eigene Betriebs- und Sicherheitsverträge.

