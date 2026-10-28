# EpicWing – Compatibility Matrix

Stand: 2026-10-23. Diese Matrix trennt bewusst Daten-/Konzeptähnlichkeit von echter Wire- und Betriebs-Kompatibilität.

## Referenzsnapshot

- [Pterodactyl Panel](https://github.com/pterodactyl/panel): Panel-Referenz; Snapshot geprüft mit Release-Seite `v1.15.2`, `v2.0.0-beta.2` als Pre-Release.
- [Pterodactyl Wings](https://github.com/pterodactyl/wings): Go-Agent, Docker-Control-Plane und eingebauter SFTP-Server; Snapshot `v1.13.4`.
- [Pterodactyl Eggs](https://github.com/pterodactyl/game-eggs): Egg-/Install-Skript-Ökosystem, kein Panel-Backend.
- [Pyrodactyl alt](https://github.com/pyrohost/pyrodactyl): archiviert bzw. nicht mehr die belastbare aktuelle Quelle.
- [Pyrodactyl OSS](https://github.com/pyrodactyl-oss/pyrodactyl): ebenfalls mit Migrationshinweis/Archivstatus; die Quelle verweist weiter Richtung [Hydrodactyl](https://github.com/blueprintframework/hydrodactyl). Deshalb keine ungesicherte Behauptung über einen „aktuellen Pyrodactyl-Core“.
- [Pyrodactyl-Dokumentations-Changelog](https://github.com/pyrodactyl-oss/pyrodactyl-docs/blob/main/content/docs/pyrodactyl/changelog.mdx): beschreibt u. a. vollständige Wings-Unterstützung, per-Node-Backups, gemischte lokale/S3-Backups, lesbare Cron-Editoren und neue Eggs.

## Architekturvergleich

| Dimension | Pterodactyl | Pyrodactyl-Referenz | EpicWing | Kompatibilitätsstatus |
|---|---|---|---|---|
| Panel | PHP/Laravel/React-Ökosystem | PHP/Laravel/React-Fork-/Nachfolgeökosystem | FastAPI/SQLAlchemy + Vue 3/TypeScript | **5** – eigene APIs, kein Drop-in |
| Agent | Wings, Go, Docker, Panel-Protokoll | Wings-orientiert | eigener Go-Agent mit eigenem Ed25519-WebSocket-Protokoll | **5** – konzeptionell ähnlich, nicht protokollkompatibel |
| Datenbank | Panel-Schema und Laravel-Migrationen | Fork-/Nachfolgeschema | eigene Alembic-Migrationen `0001`–`0019` | **5** – keine Schema-Migration ohne Adapter |
| Auth/API | Panel-Session/API-Mechanismen | Fork-kompatible Erweiterungen | Cookie-Session + `ewk_` Bearer-Keys; ServerAuth | **3** – Integrationsadapter möglich, Client-Anpassung nötig |
| Egg | Pterodactyl-Egg JSON | weitgehend Wings-/Egg-orientiert | eigenes Import-/Export-Modell mit Nest, Egg und Variablen | **3** – Kernfelder vorhanden; vollständiges Korpus nicht bestätigt |
| SFTP | Wings-eigener SFTP-Pfad | Wings-Support dokumentiert | eigener Agent-SFTP-Server, Panel-Autorisierung pro Server | **3** – Verhalten ähnlich, Host-/Protokoll-Details müssen live geprüft werden |
| Backups | lokales/erweitertes Storage je Setup | laut Changelog lokal/S3 und per Node | Agent-Backup/Restore/Transfer, Storage-Vertrag noch begrenzt | **3** – lokale Flows vorhanden, S3/Cross-Node nicht belegt |
| Scheduler | Panel-Schedule-System | lesbarer Cron-Editor | eigener Schedule-/Task-Code mit `croniter` | **3** – semantisch vergleichbar, keine Daten-/API-Kompatibilität |
| Webhosting | Game-Server-Panel, kein allgemeines Webhosting | gleiches Produktfeld | keine belastbare Webhosting-Funktion | **7** – außerhalb des aktuellen Scopes |

## Objekt- und API-Matrix

| Pterodactyl-Konzept | EpicWing-Entsprechung | Erwartete Konvertierung | Status |
|---|---|---|---|
| User / Role / Permission | `User`, globale Rechte und `ServerPermission` | Rollen müssen explizit gemappt werden; Scope ist nicht 1:1 | **3** |
| Node | `Node`, Enrollment, Agent-WebSocket | FQDN, Ressourcen, Agent-Key und Status übersetzen | **3** |
| Server | `Server`, Owner, Member, Status | UUID, Node, Egg, Allocations, Variablen übersetzen | **3** |
| Allocation | `Allocation` | IP/Port/Protocol/Primary mappen; Konfliktregeln testen | **3** |
| Nest | `Nest` | Name/Description/UUID mappen | **2** |
| Egg | `Egg` + `EggVariable` | JSON-Feldmapping und Semantik prüfen; Installer-Policy separat | **3** |
| Egg variable | `EggVariable` | `env_variable`, defaults, visibility/editability, rules | **3** |
| Startup command | `Server.startup` plus Renderer | Placeholder-Sprache muss normalisiert werden | **3** |
| Server power | `container.start/stop/kill/restart` | kein Pterodactyl-Command- oder Auth-Adapter vorhanden | **5** |
| Console | `console/ticket` + eigener WS | Client muss Endpoint/Ticket/Frames neu implementieren | **5** |
| File manager | eigene Server-Dateirouten + SFTP | API-/Path-/Fehlersemantik ist neu | **5** |
| Backup | eigene Backup-Routen und Agent-Kommandos | Storage-/Archivformat und Transferprotokoll prüfen | **3** |
| Database | `DatabaseHost`, `ServerDatabase` | Host- und Credential-Modell neu | **5** |

## Egg-Kompatibilitäts-Gate

Aktuell darf EpicWing nicht als „Pterodactyl-Egg-kompatibel“ veröffentlicht werden, solange folgende Nachweise fehlen:

1. Import einer repräsentativen offiziellen Egg-Sammlung einschließlich Install-Container, Startup, variables, rules, script/config und optionalen Feldern.
2. Round-trip: Import → Speicherung → Export ohne Verlust sicherheitsrelevanter oder semantischer Felder.
3. Install-Test auf isolierter Node mit allowlisted images, Netzwerk, Ressourcenlimits und langen Skripten.
4. Negative Tests für unbekannte Placeholder, gefährliche Images, nicht erlaubte Shells, Pfad-Traversal und fehlende EULA-Zustimmung.
5. Dokumentierte Abweichung pro Feld; kein stilles Ignorieren unbekannter Daten.

## Schlussfolgerung

EpicWing kann sich an Pterodactyl-User und Eggs anlehnen, ist aber technisch eine eigene Plattform. Kompatibilität sollte als versionierter Import-/Export-Adapter mit Test-Fixtures geplant werden, nicht als Marketingannahme.

