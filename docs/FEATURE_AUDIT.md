# EpicWing – Feature Audit

Stand: 2026-10-23  
Geprüftes Projekt: `/root/forge/forge` auf dem KVM, Branch `main`, HEAD `14b2dba`.  
Nicht verwendet: `/home/epicdev/forge` (separater Clone, Branch `feature/server-install`, uncommittete Änderungen).

## Bewertungslegende

| Status | Bedeutung |
|---|---|
| 1 | Vollständig implementiert und durch automatisierte und praxisnahe Tests belegt |
| 2 | Implementiert; Code- und Testsicht vorhanden, Live-/Release-Nachweis fehlt noch |
| 3 | Teilimplementiert oder mit relevanten Lücken |
| 4 | Angelegt, aber nicht belastbar funktionsfähig |
| 5 | Nicht implementiert |
| 6 | Unklar bzw. nicht nachweisbar |
| 7 | Bewusst außerhalb des EpicWing-Scopes |

Die Einstufung bewertet EpicWing selbst, nicht die Behauptung einer Pterodactyl-Kompatibilität. Ein grüner Unit-Test ersetzt keinen Test mit einer echten Node, Docker, SFTP-Verbindung, Reverse Proxy, Backup-Ziel oder Browser.

## Verifikation

| Bereich | Ergebnis |
|---|---|
| Backend | `716 passed`, 2 Warnungen, pytest |
| Frontend | `npm test`: 28 passed; `vue-tsc --noEmit`: erfolgreich; `npm audit --audit-level=high`: 0 Schwachstellen |
| Agent | `go test ./...`, `go vet ./...`, `go build ./...`: erfolgreich |
| Lint | Ruff: 12 Fehler; davon Imports, E501, B017 und ein ungenutzter Import |
| Format | Ruff: 49 Dateien würden formatiert |
| Runtime | `GET http://127.0.0.1:8010/api/health` → `200`, `{"status":"ok"}` |
| Arbeitsbaum | Vor der Dokumentation sauber; keine Produktionsänderung vorgenommen |

## Funktionsaudit

### A. Konto, Sicherheit und Rechte

| ID / Status | Erwartetes Verhalten | EpicWing-Nachweis und Vergleich | Lücken, Risiko, Aufwand, Priorität | Abnahmekriterium |
|---|---|---|---|---|
| A1 **2** – Login/Logout/Session | Sichere Browser-Session mit CSRF-Schutz, Passwortwechsel und Sperrstatus | `backend/app/api/auth.py`, `security/sessions.py`, Auth-Tests. Das entspricht dem Panel-Grundmuster, ist aber keine Pterodactyl-Wire-Kompatibilität. | Live-Cookie-/Proxy-Test fehlt; Mittel, P1 | Login, Logout, abgelaufene Session, CSRF und deaktivierter Benutzer werden gegen eine frische Installation geprüft. |
| A2 **2** – 2FA | TOTP einrichten, aktivieren, Recovery-Codes nutzen und deaktivieren | `two_factor.py`, `TwoFactorPanel.vue`, `test_two_factor.py` | Recovery-Code- und Clock-Drift-Matrix fehlt; Mittel, P1 | TOTP-Login funktioniert mit gültigem und ungültigem Code; jeder Recovery-Code ist einmalig. |
| A3 **2** – Rollen/Rechte | Globale und serverbezogene Rechte, Mitgliedschaft und Sichtbarkeit | `permissions.py`, `server_access.py`, `server_members.py`, Permission-Tests | Mehrere Worker benötigen DB-Sperren statt Prozess-Locks; Hoch, P0 | Jede kritische Serveraktion wird als Owner, Member, Read-only, Admin und Fremdnutzer getestet. |
| A4 **2** – API-Keys | Hashed Bearer-Key, read-only, Ablauf, Rotation/Löschen, Audit | `api_keys.py`, `security/apikeys.py`, Migration `0017`, `test_api_keys.py`, `test_api_key_access.py` | Nur ServerAuth akzeptiert Keys; OpenAPI-/Client-Vertrag fehlt; Niedrig, P1 | Token wird nur einmal angezeigt, nie geloggt, read-only blockiert Mutationen und Ablauf wird erzwungen. |
| A5 **2** – SSH-Key/SFTP | Öffentliche Keys speichern, Fingerprint prüfen, SFTP nur für erlaubte Server | `ssh_keys.py`, `services/sftp.py`, Agent `sftp.go`, `test_ssh_keys.py`, `test_sftp_auth.py` | Echter externer SFTP-Handshake, Host-Key-Rotation und Firewall fehlen; Hoch, P1 | Ein Schlüssel sieht nur genau einen berechtigten Server; Schreibrecht folgt `files.write`; abgelehnte Logins verraten keinen Grund. |
| A6 **2** – Audit/Activity | Aktionen, Akteur, Ziel, IP, API-Key-Kontext und Export | `audit.py`, `api/audit.py`, `test_audit.py` | Trusted-Proxy-IP-Regeln und Aufbewahrung fehlen; Mittel, P1 | Sicherheits- und Serveraktionen sind unveränderbar nachvollziehbar und enthalten keine Secrets. |

### B. Panel, Infrastruktur und Serverlebenszyklus

| ID / Status | Erwartetes Verhalten | EpicWing-Nachweis und Vergleich | Lücken, Risiko, Aufwand, Priorität | Abnahmekriterium |
|---|---|---|---|---|
| B1 **2** – Benutzer/Admin | Benutzerverwaltung, Deaktivierung, Passwort, Avatar, Admin-Übersicht | `admin.py`, `users.py`, `avatars.py`, Admin-Views | Browser-E2E und Betriebs-RBAC-Matrix fehlen; Mittel, P1 | Admin kann Konten verwalten; deaktivierte Konten verlieren Session, API-Key und SFTP-Zugriff. |
| B2 **2** – Nodes/Enrollment | Node anlegen, Token einmalig verwenden, Ed25519-Agent authentifizieren, Heartbeat | `nodes.py`, `agent_ws.py`, `docs/agent-protocol.md`, Agent-Protokoll | Keine reproduzierbare Install-/Upgrade-Prüfung für eine frische Node; Hoch, P0 | Node enrollt sich frisch, reconnectet, zeigt Ressourcen und wird bei Heartbeat-Timeout offline. |
| B3 **2** – Server CRUD | Server mit Egg, Variablen, Ressourcen und Allocations anlegen/bearbeiten/löschen | `servers.py`, `schemas/server.py`, Alembic `0001`–`0019`, Admin-Server-View | Lifecycle nur gegen reale Docker-Node ungetestet; Hoch, P0 | Race-Test für Allocation, Delete-Schutz und Rechte auf einer isolierten Node bestehen. |
| B4 **2** – Install/Reinstall | Installer-Container mit Allowlist, Limits, Mount und Live-Console; Server bleibt bis Erfolg gestoppt | `agent/docker.go`, `install_stream.go`, `docs/installer-security.md`, `test_console_install.py` | Egg-Skripte sind bewusst Code-Ausführung; Timeout-/Rollback-/Netzwerk-Matrix fehlt; Hoch, P0 | 100-s-Installation, Fehler, Abbruch und Reinstall setzen Panel-Status und Datenverzeichnis korrekt. |
| B5 **2** – Power/Status/Stats | Start, Stop, Restart, Kill, Remove, Zustände und Ressourcenwerte | `agent/docker.go`, `agent/registry`, `servers.py`, `ServerDetailView.vue` | Kein Langzeit-/Reconnect-Test und keine persistente Metrik; Mittel, P1 | Node-Reconnect synchronisiert Containerzustände ohne fremde Server zu übernehmen. |
| B6 **2** – Console | WebSocket-Ticket, Output, Input, Install-Stream, Reconnect | `console_ws.py`, `console_ws` tests, `ServerConsole.vue`, Commit `e5dea7c` | Browser-E2E, Backpressure und Log-Retention fehlen; Mittel, P1 | Parallele Zuschauer, reconnect während Installation und kontrollierte Eingabe funktionieren. |
| B7 **2** – Dateien | Dateiübersicht, Lesen/Schreiben, Upload/Download, Archivaktionen und SFTP | `FilesPanel.vue`, Server-Dateirouten, Agent-Datei-/SFTP-Code | Große Dateien, Symlink-/Quota-/Encoding-Matrix fehlt; Hoch, P1 | Pfad-Traversal, Symlink-Ausbruch, große Uploads und Rechte werden auf echter Node getestet. |
| B8 **2** – Allocations/Ports | IP/Port-Pools verwalten, zuweisen, Konflikt verständlich melden | `allocations.py`, `portguard.go`, Allocation-Tests | Portbereich/Proxy-Protocol/IPv6-Live-Test fehlt; Mittel, P1 | Ein belegter Port liefert `PORT_IN_USE`; parallele Claims bleiben atomar. |
| B9 **2** – Backups/Restore/Transfer | Erzeugen, Status, Download, Restore, Löschen und Transfer | `backups.py`, `agent/backup.go`, `BackupsPanel.vue`, Backup-Tests | S3/Remote-Storage und echte Cross-Node-Übung nicht nachgewiesen; Hoch, P0 | Backup wird auf Node A erstellt, Integrität geprüft, auf Ziel wiederhergestellt und bei Fehler sauber zurückgerollt. |
| B10 **2** – Schedules | Cron-Ausdruck, Tasks, Ausführung und UI | `schedules.py`, `SchedulesPanel.vue`, croniter, Schedule-Tests | Scheduler-Prozess/Leader-Election und DST-Matrix fehlen; Hoch, P1 | Ein Schedule läuft einmal, ist idempotent und erzeugt bei Node-Ausfall keinen Doppelstart. |
| B11 **2** – Datenbanken | Database-Hosts, MySQL/MariaDB-Datenbanken, Credentials/Rotation | `admin_database_hosts.py`, `server_databases.py`, `DatabasesPanel.vue` | Kein PostgreSQL-/Remote-DB-Vertrag und kein Live-DB-Integrationstest; Mittel, P1 | Create, rotate, delete und Host-Test funktionieren mit einem isolierten DB-Host. |
| B12 **2** – Eggs/Nests | Nests/Eggs CRUD, Variablen, Import/Export, Startup-Validierung | `eggs.py`, `services/eggio.py`, `EggsView.vue`, Egg-Tests | Pterodactyl-Egg-Korpus und alle Feldvarianten nicht verifiziert; Hoch, P0 | Offizielle Fixture-Sammlung wird importiert, exportiert und semantisch ohne Verlust round-tripped. |

### C. Betrieb, UX und Produktgrenzen

| ID / Status | Erwartetes Verhalten | EpicWing-Nachweis und Vergleich | Lücken, Risiko, Aufwand, Priorität | Abnahmekriterium |
|---|---|---|---|---|
| C1 **2** – Admin-Einstellungen/Health | Panel, Mail, Benachrichtigungen, Locations, Health | `admin_mail.py`, `admin_notifications.py`, `panel.py`, `health.py` | Mail-Provider, Secret-Rotation und Alerting nicht live geprüft; Mittel, P1 | Health enthält keine Secrets, Mail-Test ist fehlertolerant, Konfiguration ist auditierbar. |
| C2 **2** – DDoS-Anzeige | Netzwerk-Samples, Verlauf, Level und Gründe sichtbar machen | `server_ddos.py`, `ddos_detect.py`, `ddos_store.py`, DDoS-Tests, `DdosPanel.vue` | Das ist Erkennung/Anzeige, keine DDoS-Mitigation oder Scrubbing; Hoch, P0 | Messlücken, Offline-Zustand und Schwellwerte liefern deterministische Ergebnisse; Scope bleibt klar dokumentiert. |
| C3 **3** – EULA/Regeln | Installationsblock bis zur ausdrücklichen Zustimmung, zunächst Minecraft | Commits `57e803d` und aktuelle Server-UI implementieren generischen Dialog; keine globale EULA-Engine erkennbar | Egg-Metadaten, Audit und Wiederholung über Reinstall müssen vereinheitlicht werden; Mittel, P1 | Ein Egg kann eine Zustimmung verlangen; ohne Zustimmung kein Install; Zustimmung ist versioniert und auditierbar. |
| C4 **3** – Responsive/Accessibility/i18n | Tastaturbedienung, mobile Layouts, klare Fehlermeldungen, Übersetzungen | Vue 3, Tailwind, `vue-i18n`, Views/Components vorhanden | Kein automatisiertes a11y-, Browser- oder Screenreader-Gate; Mittel, P2 | WCAG-Basisprüfung, Keyboard-Flow und mobile Breakpoints sind Teil der CI-/Release-Prüfung. |
| C5 **3** – Installation/Updates | Frische Installation, Migration, Agent-Update, Rollback, Reverse Proxy | `scripts/install-node.sh`, `update-agent.sh`, systemd-Unit, Dev-Compose vorhanden | Kein vollständiger Panel-Installer, keine Release-Artefakte/Signaturen/rollbackfähige Runbooks; Hoch, P0 | Debian-Neuinstallation wird aus leerem Host reproduzierbar ausgeführt und rücksetzbar dokumentiert. |
| C6 **5** – Webhosting | Websites, Domains, Subdomains, Webroots, TLS, vHosts, PHP/Node-Runtimes | In `backend`, `frontend`, `agent`, `deploy`, `scripts` keine belastbare Implementierung gefunden | Nicht Teil des aktuellen Produkts; Vermischung mit Game-Server-Rechten wäre ein Sicherheitsrisiko; Groß, P3 | Nur nach eigener Architekturentscheidung und separatem Threat Model als neues Produktmodul abnehmen. |

## Release-Fazit

EpicWing ist kein unfertiger Stub: Auth, Rechte, Node-Agent, Serverlebenszyklus, Eggs, Dateien, Backups, Schedules, DB-Verwaltung, API-/SSH-Keys und DDoS-Anzeige sind im aktuellen Code sichtbar. Es ist aber noch kein belegter Pterodactyl-/Pyrodactyl-Ersatz. Der Release wird derzeit durch fehlende Live-Integrationsnachweise, fehlende reproduzierbare Installation und die rote Ruff-Prüfung blockiert.

