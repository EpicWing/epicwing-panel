# Contributing to EpicWing

Thanks for your interest in EpicWing. Bug reports, ideas and pull requests are welcome.

## Reporting bugs and ideas

Open an issue on GitHub. For a bug, please include:

- the EpicWing version (or commit) and your operating system
- the steps to reproduce the problem
- relevant log output (panel, agent or browser console)

Security problems do not belong in a public issue. Please follow [SECURITY.md](SECURITY.md) instead.

## Development setup

The README has a Development section. In short, `scripts/dev.sh` starts the backend (port 8010) and the frontend (port 5183) for local work.

## Before you open a pull request

Please make sure these checks pass:

- Backend: `ruff check .`, `ruff format --check .` and `pytest` (run in `backend/`)
- Agent: `go vet ./...`, `go test ./...` and `gofmt -l .` (run in `agent/`)
- Frontend: `npm test` (run in `frontend/`)
- Shell scripts: `shellcheck -S warning scripts/*.sh`

## Code style

- Code, comments, commit messages and user-facing texts are written in English.
- Keep changes small and focused. One topic per pull request.
- Add a new dependency only when it is really needed, and explain why in the pull request.
- Features that are not implemented yet must be recognizable as such in the code and in the UI.
- Add or update tests when behavior changes.

## License

By contributing, you agree that your contribution is licensed under the license of this project (see [LICENSE](LICENSE)).
