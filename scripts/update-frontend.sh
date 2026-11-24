#!/bin/bash
# Builds the frontend and swaps the served version in one step.
#
# Only runs from a clean checkout whose HEAD is origin/main, so an old copy
# or a feature branch is never deployed by accident. --force skips the
# check (for example to roll back to an older tag on purpose).
set -euo pipefail
cd "$(dirname "$0")/../frontend"

die() { echo "Error: $*" >&2; exit 1; }

if [ "${1:-}" != "--force" ]; then
  top="$(git rev-parse --show-toplevel 2>/dev/null)" || die "Not a git checkout."
  [ -z "$(git status --porcelain)" ] \
    || die "$top has uncommitted changes. Commit or discard them first."
  git fetch -q origin main || die "Could not fetch origin/main."
  head="$(git rev-parse HEAD)"
  main="$(git rev-parse origin/main)"
  [ "$head" = "$main" ] \
    || die "$top is at $(git rev-parse --short HEAD) ($(git rev-parse --abbrev-ref HEAD)), not origin/main ($(git rev-parse --short origin/main)). Use --force to deploy it anyway."
  echo "Deploying $(git describe --tags --always) from $top"
fi

npm run build
mkdir -p /var/www
rm -rf /var/www/epicwing-panel.new /var/www/epicwing-panel.old
cp -r dist /var/www/epicwing-panel.new
chmod -R a+rX /var/www/epicwing-panel.new
[ -d /var/www/epicwing-panel ] && mv /var/www/epicwing-panel /var/www/epicwing-panel.old
mv /var/www/epicwing-panel.new /var/www/epicwing-panel
echo "Frontend deployed to /var/www/epicwing-panel"
