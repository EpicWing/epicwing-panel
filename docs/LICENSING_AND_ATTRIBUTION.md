# EpicWing – Licensing and Attribution

## Basic idea

This document is not legal advice. It lists what we checked about licenses and where our ideas and files come from.

The source code of EpicWing is our own work in Python, Vue and Go. The audit found no sign that Pterodactyl code was copied. A similar product idea is not a license problem. Copied code would be.

## Reference projects

| Project | Source | What it means for EpicWing |
|---|---|---|
| Pterodactyl Panel | [GitHub](https://github.com/pterodactyl/panel) | Only take code, assets, texts or snippets if the `LICENSE` and NOTICE of that release allow it. Check the license file of the exact release. |
| Pterodactyl Wings | [GitHub](https://github.com/pterodactyl/wings) | The repo page says Wings is MIT. If we take code or files, we keep the copyright and license notices. |
| Pterodactyl Eggs | [GitHub](https://github.com/pterodactyl/game-eggs) | Egg files and install scripts can have their own origin and license. Credit every imported egg on its own. Eggs are also code that runs. |
| Pyrodactyl (old) | [GitHub](https://github.com/pyrohost/pyrodactyl) | This repo is archived and has a successor. Do not use it as the main source. |
| Pyrodactyl OSS | [GitHub](https://github.com/pyrodactyl-oss/pyrodactyl) | The repo says Apache-2.0. If we take anything, check NOTICE and attribution. |
| Pyrodactyl docs | [GitHub](https://github.com/pyrodactyl-oss/pyrodactyl-docs) | Docs, images and texts need a separate check. Do not copy them without checking. |

## Checks before a release

- [ ] For Panel, Wings, Eggs, Pyrodactyl and every asset we really use: save the `LICENSE`, `NOTICE`, copyright headers and sublicenses.
- [ ] Check `git log` and the diffs for every file that came from a reference project.
- [ ] If code was taken: write down the original file, commit, SPDX identifier, copyright notice and our changes.
- [ ] If only an egg or install script was taken: write down where it came from, the script license, the image license and third-party downloads.
- [ ] List all frontend icons, fonts, images, code snippets and npm, PyPI and Go dependencies.
- [ ] Create an SBOM and license reports for pip, npm and Go. Include indirect dependencies.
- [ ] Check security and redistribution rules of the images and eggs we depend on.

## License of EpicWing

Decided: EpicWing uses the MIT license (see `LICENSE`, Copyright (c) 2026 EpicWing).

The license only covers our own code. Dependencies (Python, npm, Go) keep their own licenses. Pterodactyl eggs are only imported as a format. The audit found that no Pterodactyl code was taken.

## Security and license are two different things

A license does not make an install script, Docker image, mod or download safe to run. So every egg has to pass two separate gates: legal origin and license, and technical trust. No egg may run only because its license is permissive. It also needs an admin permission, an image allowlist and an isolated install test.

## Checked on 2026-10-23

- The official egg repository is `https://github.com/pterodactyl/game-eggs`. The address we used before, `pterodactyl/eggs`, does not exist (HTTP 404).
- The `LICENSE` in the downloaded archive of `pterodactyl/game-eggs` is MIT, "Copyright (c) 2024 Pterodactyl team and contributors". Single eggs can have different notices. We did not check them one by one.
- The six eggs in `backend/fixtures/eggs/` are based on eggs from `pterodactyl/game-eggs` (MIT). Some also use the `ghcr.io/ptero-eggs` images and install scripts. We treat all six as third-party work. The notice is in `backend/fixtures/eggs/NOTICE.md`.
- Eggs that we write ourselves will be marked as EpicWing eggs and listed separately.
