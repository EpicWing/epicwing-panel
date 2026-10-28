# EpicWing – Implementation Plan

## P0 – Releasefähigkeit herstellen

| Arbeitspaket | Ergebnis | Akzeptanz |
|---|---|---|
| P0.1 Quality gate | Ruff-Fehler und Formatabweichungen beheben; CI für Python, Vue, Go | `ruff check`, `ruff format --check`, pytest, typecheck, frontend tests, Go test/vet/build laufen grün |
| P0.2 Release provenance | Panel, Frontend und Agent mit Commit-/Versionsmetadaten bauen und ausliefern | Laufender Agent lässt sich eindeutig einem Release und Digest zuordnen |
| P0.3 Fresh install | Vollständiges Debian-Runbook/Script für DB, Panel, Migration, Build, systemd, Proxy, TLS und Secrets | Leerer Testhost wird ohne manuelle Geheimnisweitergabe installiert; Smoke-Login und Health grün |
| P0.4 Node integration | Eine isolierte Docker-Node enrollen und Lifecycle durchspielen | Create → install → console → start/stop → files → backup → restore → delete besteht |
| P0.5 Installer hardening | Image-Digests/Allowlist, Egress-Entscheidung, Limits, Logs und EULA-Policy | Bösartiges/unerlaubtes Image und unbekanntes Startup werden vor Ausführung abgewiesen |
| P0.6 Security regression | Rechte-Matrix, CSRF, API-Key, SFTP, Path-Traversal, Agent-Auth | Kein Test erlaubt Zugriff auf fremden Server oder fremdes Host-Dateisystem |

## P1 – Produktvertrag und Kompatibilität

| Arbeitspaket | Ergebnis | Akzeptanz |
|---|---|---|
| P1.1 Egg adapter | Offizielle Egg-Fixtures, Import/Export-Mapping, Warnungen, Version | Korpus round-tripped; jede Abweichung ist dokumentiert und testbar |
| P1.2 Lifecycle robustness | DB-/Distributed-Locks, Idempotency, Timeout-/Reconnect-State-Machine | Zwei parallele Aktionen ergeben genau einen gültigen Zustand |
| P1.3 Backup contract | Storage-Interface, Manifest/Hash, Retention, lokale und optional S3-Backends | Restore prüft Integrität; Cross-Node-Fehler hinterlassen keinen falschen `running`-Status |
| P1.4 SFTP production test | Externer OpenSSH-/SFTP-Client, Host-Key-Handling, Firewall/Port-Doku | Read-only, write, disabled user, ambiguous prefix und disconnect sind verifiziert |
| P1.5 API documentation | Versionierter OpenAPI-Snapshot, Auth-/Error-/WS-/Egg-Vertrag | Ein neuer Client kann Server und Console ohne Quellcode-Raten integrieren |
| P1.6 Proxy and mail | Trusted proxy, TLS, Mail provider, notification retries | Audit-IP und URLs stimmen hinter einem bekannten Proxy; Fehler sind sichtbar und retryfähig |

## P2 – Betrieb und UX

- Browser-E2E für Login, 2FA, Serveranlage, Installationsdialog/EULA, Console, Files, Backups und Admin.
- Accessibility-Smoke (Keyboard, Labels, Focus, Contrast) und mobile Breakpoint-Test.
- Metriken, strukturierte Logs, Korrelation-ID, Alerting für Agent offline, Install-/Backup-Fehler und Speichergrenzen.
- Python-Abhängigkeiten reproduzierbar locken; Container-/Agent-Builds mit SBOM und CVE-Prüfung.
- README, `PROGRESS.md`, `docs/architecture.md` und Changelog auf den aktuellen Stand bringen.

## P3 – Optionale Erweiterungen

- Remote-/S3-Backups und Cross-Node-Migration ausbauen.
- Öffentliche API-Client-SDKs und Webhooks.
- Webhosting nur als getrenntes Modul: Domainverwaltung, TLS/ACME, Webroots, Runtime-Isolation, Abuse- und DDoS-Modell.

## Empfohlene Reihenfolge

```text
Lint/CI → Release-Artefakte → Fresh install → echte Node-Integration
       → Security regression → Egg/Backup/SFTP contracts
       → Browser/a11y/Observability → optionale Erweiterungen
```

Kein Produktionscode wird im Rahmen dieses Audits automatisch geändert. Die nächsten Codeänderungen sollten je Arbeitspaket klein bleiben und jeweils mit Tests, Migrationen und Rollback-Hinweis geliefert werden.

