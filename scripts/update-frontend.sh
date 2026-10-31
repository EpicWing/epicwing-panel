#!/bin/bash
# Builds the frontend and swaps the served version in one step.
set -euo pipefail
cd "$(dirname "$0")/../frontend"
npm run build
mkdir -p /var/www
rm -rf /var/www/epicwing-panel.new /var/www/epicwing-panel.old
cp -r dist /var/www/epicwing-panel.new
chmod -R a+rX /var/www/epicwing-panel.new
[ -d /var/www/epicwing-panel ] && mv /var/www/epicwing-panel /var/www/epicwing-panel.old
mv /var/www/epicwing-panel.new /var/www/epicwing-panel
echo "Frontend ausgeliefert: /var/www/epicwing-panel"
