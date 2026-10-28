#!/bin/bash
# egg-name: SCP SL
# SCP:SL SteamCMD install script (based on the ptero-eggs steamcmd template)
set -euo pipefail

: "${SRCDS_APPID:?SRCDS_APPID is not set}"
STEAM_USER="${STEAM_USER:-}"
STEAM_PASS="${STEAM_PASS:-}"
STEAM_AUTH="${STEAM_AUTH:-}"
if [[ -z "$STEAM_USER" || -z "$STEAM_PASS" ]]; then
    echo "steam user is not set, using anonymous login"
    STEAM_USER=anonymous
    STEAM_PASS=""
    STEAM_AUTH=""
fi

SERVER_DIR=/mnt/server
mkdir -p "$SERVER_DIR/steamcmd" "$SERVER_DIR/steamapps"

cd /tmp
curl -fsSL -o steamcmd.tar.gz https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz
tar -xzf steamcmd.tar.gz -C "$SERVER_DIR/steamcmd"
cd "$SERVER_DIR/steamcmd"
export HOME="$SERVER_DIR"

args=(+force_install_dir "$SERVER_DIR" +login "$STEAM_USER")
if [[ "$STEAM_USER" != "anonymous" ]]; then args+=("$STEAM_PASS"); fi
if [[ -n "$STEAM_AUTH" ]]; then args+=("$STEAM_AUTH"); fi
if [[ "${WINDOWS_INSTALL:-0}" == "1" ]]; then args+=(+@sSteamCmdForcePlatformType windows); fi
args+=(+app_update "$SRCDS_APPID")
if [[ -n "${SRCDS_BETAID:-}" ]]; then args+=(-beta "$SRCDS_BETAID"); fi
if [[ -n "${SRCDS_BETAPASS:-}" ]]; then args+=(-betapassword "$SRCDS_BETAPASS"); fi
# shellcheck disable=SC2206
args+=(${INSTALL_FLAGS:-})
args+=(validate +quit)

./steamcmd.sh "${args[@]}"

mkdir -p "$SERVER_DIR/.steam/sdk32" "$SERVER_DIR/.steam/sdk64" "$SERVER_DIR/.config"
cp -v linux32/steamclient.so "$SERVER_DIR/.steam/sdk32/steamclient.so"
cp -v linux64/steamclient.so "$SERVER_DIR/.steam/sdk64/steamclient.so"

if [[ ! -f "$SERVER_DIR/LocalAdmin" ]]; then
    echo "LocalAdmin not found after installation" >&2
    exit 1
fi
chmod +x "$SERVER_DIR/LocalAdmin"

echo "-----------------------------------------"
echo "Installation completed"
echo "-----------------------------------------"
