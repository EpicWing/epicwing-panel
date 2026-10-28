# EpicWing – Licensing and Attribution

## Grundsatz

Dieses Dokument ist keine Rechtsberatung und trifft keine Lizenzentscheidung für EpicWing. Es hält fest, was vor einer Veröffentlichung geklärt werden muss. Der aktuelle Quellcode ist eine eigene Python-/Vue-/Go-Implementierung; aus diesem Audit folgt kein Nachweis, dass Pterodactyl-Code kopiert wurde. Ähnliche Produktkonzepte sind keine Lizenzübernahme, konkrete kopierte Codebestandteile wären es.

## Referenzprojekte

| Projekt | Quelle | Für EpicWing relevant |
|---|---|---|
| Pterodactyl Panel | [GitHub](https://github.com/pterodactyl/panel) | Nur Code, Assets, Texte oder Snippets übernehmen, wenn die konkrete `LICENSE` und NOTICE das erlauben; Lizenzdatei im Release-Snapshot prüfen. |
| Pterodactyl Wings | [GitHub](https://github.com/pterodactyl/wings) | Die Repo-Seite weist Wings als MIT-Projekt aus. Bei Übernahme von Code/Dateien Copyright- und Lizenzhinweise erhalten. |
| Pterodactyl Eggs | [GitHub](https://github.com/pterodactyl/game-eggs) | Egg-Dateien und Install-Skripte können eigene Herkunft/Lizenzen haben. Jede importierte Fixture einzeln attribuieren; Eggs sind zudem ausführbarer Code. |
| Pyrodactyl alt | [GitHub](https://github.com/pyrohost/pyrodactyl) | Archiv-/Nachfolgehinweis beachten; nicht als aktuelle Primärquelle behandeln. |
| Pyrodactyl OSS | [GitHub](https://github.com/pyrodactyl-oss/pyrodactyl) | Repo weist Apache-2.0 aus; konkrete Übernahmen brauchen NOTICE-/Attributionsprüfung. |
| Pyrodactyl docs | [GitHub](https://github.com/pyrodactyl-oss/pyrodactyl-docs) | Dokumentation, Bilder und Texte sind separat zu prüfen; nicht ungeprüft kopieren. |

## Vor Veröffentlichung auszuführende Prüfungen

- [ ] Für Panel, Wings, Eggs, Pyrodactyl und alle tatsächlich verwendeten Assets die `LICENSE`, `NOTICE`, Copyright-Header und Unterlizenzen archivieren.
- [ ] `git log`, Diff- und Herkunftsprüfung für alle aus Referenzprojekten übernommenen Dateien durchführen.
- [ ] Wenn Code übernommen wurde: Originaldatei, Commit, SPDX-Identifier, Copyright-Hinweis und Änderungen dokumentieren.
- [ ] Wenn nur ein Egg/Install-Skript übernommen wurde: Herkunft, Skript-Lizenz, Image-Lizenz und Drittanbieter-Downloads dokumentieren.
- [ ] Frontend-Icons, Fonts, Bilder, Code-Snippets und npm-/PyPI-/Go-Abhängigkeiten inventarisieren.
- [ ] SBOM sowie `pip`-, npm- und Go-Lizenzbericht erzeugen; transitive Lizenzen einschließen.
- [ ] Security- und Export-/Redistribution-Anforderungen der abhängigen Images und Eggs prüfen.

## Lizenzentscheidung für EpicWing

Noch offen. Zwei übliche Optionen für eine eigenständige Implementierung:

- MIT: sehr kurze, permissive Lizenz mit Copyright-/Permission-Hinweis.
- Apache-2.0: permissiv mit ausführlicheren Patent- und NOTICE-Regeln.

Die Entscheidung muss zur tatsächlichen Herkunft des Codes, zu verwendeten Eggs/Assets und zum gewünschten Redistribution-Modell passen. Bis dahin sollte EpicWing keine Lizenz im README behaupten, die nicht mit einer Root-`LICENSE` und den Notices übereinstimmt.

## Sicherheits- und Lizenzgrenze

Eine Lizenz erlaubt nicht automatisch den sicheren Betrieb eines Install-Skripts, Docker-Images, Mods oder Downloads. Für Eggs gelten daher zwei getrennte Gates: rechtliche Herkunft/Lizenz und technische Vertrauenswürdigkeit. Kein Egg darf nur wegen einer permissiven Lizenz ohne Admin-Recht, Image-Allowlist und isolierten Install-Test ausgeführt werden.


## Geprüft am 2026-10-23

- Das offizielle Egg-Repository ist `https://github.com/pterodactyl/game-eggs`. Die zuvor genannte Adresse `pterodactyl/eggs` existiert nicht (HTTP 404).
- Die `LICENSE` im geladenen Archiv von `pterodactyl/game-eggs` ist MIT, "Copyright (c) 2024 Pterodactyl team and contributors". Einzelne Eggs können abweichende Hinweise enthalten, sie wurden nicht einzeln geprüft.
- Die sechs Eggs in `backend/fixtures/eggs/` stammen aus der eigenen Datenbank, ihre Herkunft ist noch nicht je Datei dokumentiert.
