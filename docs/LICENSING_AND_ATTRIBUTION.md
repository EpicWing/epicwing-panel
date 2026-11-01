# Licensing and attribution

EpicWing is released under the MIT license. See [LICENSE](../LICENSE), Copyright (c) 2026 EpicWing.

## Our code

The panel (Python, Vue) and the node agent (Go) are written for EpicWing. Dependencies (Python, npm, Go) keep their own licenses.

## Bundled eggs

The six eggs in `backend/fixtures/eggs/` (Minecraft, Unturned and a static website) are based on eggs from [pterodactyl/game-eggs](https://github.com/pterodactyl/game-eggs). That repository is licensed under MIT, Copyright (c) 2024 Pterodactyl team and contributors. Some eggs also use `ghcr.io/ptero-eggs` images and install scripts. We treat all six as third-party work and keep the notice in [`backend/fixtures/eggs/NOTICE.md`](../backend/fixtures/eggs/NOTICE.md). Individual eggs can carry their own notices. The node installer also pulls container images from ghcr.io (`pterodactyl/installers`, `pyrodactyl-oss/images`). Those images have their own terms.

## Egg files

EpicWing can import and export eggs in the Pterodactyl egg file format for compatibility. EpicWing is not affiliated with Pterodactyl or Pyrodactyl. All names belong to their owners.

## Eggs and security

A permissive license does not make an egg safe. Install scripts and container images run on your nodes, so review an egg before you import it, no matter where it comes from.
