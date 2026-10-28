# Installer trust model

Egg install scripts are stored in the database and executed on the node inside
a short-lived installer container.

- The container runs as root with `--cap-drop ALL` and only `CHOWN`,
  `DAC_OVERRIDE` and `FOWNER` added, plus `no-new-privileges` and a PID limit.
- Only the server's data directory is mounted (as `/mnt/server` and
  `/home/container`). No other host path is visible.
- After the script finishes, the wrapper `chown`s the data directory to the
  runtime user (the agent's uid/gid). A failing `chown` fails the install.
- The installer image and shell come from the egg and must be on the node's
  image allow-list. The shell name is validated against `shellEntrypointRe`.
- Anyone who can edit an egg can run arbitrary code as root inside that
  container, with network access. Restrict egg editing to administrators.
