#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_DIR="$(dirname -- "$SCRIPT_DIR")"
CONFIG_PATH="$(readlink -f "${1:-$PROJECT_DIR/config.local.yaml}")"
CONFIG_DIR="$(dirname -- "$CONFIG_PATH")"
SERVICE_NAME="appliance-display-sensor.service"
TEMPLATE_PATH="$PROJECT_DIR/packaging/systemd/$SERVICE_NAME.in"

if [[ ! -f "$CONFIG_PATH" ]]; then
    printf 'Configuration file not found: %s\n' "$CONFIG_PATH" >&2
    exit 1
fi

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    # Invoke Bash explicitly so installation also works when the executable bit
    # was not preserved while copying or extracting the project.
    exec sudo bash "$0" "$CONFIG_PATH"
fi

SERVICE_USER="${SUDO_USER:-$(id -un)}"
SERVICE_GROUP="$(id -gn "$SERVICE_USER")"
install -d -m 0750 -o "$SERVICE_USER" -g "$SERVICE_GROUP" "$PROJECT_DIR/debug"
TEMP_SERVICE="$(mktemp)"
trap 'rm -f "$TEMP_SERVICE"' EXIT

sed \
    -e "s|@SERVICE_USER@|$SERVICE_USER|g" \
    -e "s|@SERVICE_GROUP@|$SERVICE_GROUP|g" \
    -e "s|@PROJECT_DIR@|$PROJECT_DIR|g" \
    -e "s|@CONFIG_PATH@|$CONFIG_PATH|g" \
    -e "s|@CONFIG_DIR@|$CONFIG_DIR|g" \
    "$TEMPLATE_PATH" > "$TEMP_SERVICE"

install -m 0644 "$TEMP_SERVICE" "/etc/systemd/system/$SERVICE_NAME"
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"
systemctl --no-pager --full status "$SERVICE_NAME"
