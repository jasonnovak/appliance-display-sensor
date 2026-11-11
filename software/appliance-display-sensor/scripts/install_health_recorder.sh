#!/usr/bin/env bash
# Opt-in recorder installation. Never starts, stops or restarts the sensor.
set -euo pipefail
export LC_ALL=C

usage() {
    printf '%s\n' 'Usage: bash scripts/install_health_recorder.sh [--user USER] [--interface wlan0] [--persistent-journal] [--dry-run]'
    printf '%s\n' 'Default: record locally every 30 seconds using the existing journal policy.'
    printf '%s\n' '--persistent-journal changes HOST-WIDE retention: 50 MiB cap, up to 7 days, 30-second sync.'
}
service_user="${SUDO_USER:-$(id -un)}"
interface=wlan0
persistent=false
dry_run=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --user|--interface)
            [[ $# -ge 2 ]] || { usage >&2; exit 2; }
            if [[ $1 == --user ]]; then service_user=$2; else interface=$2; fi
            shift 2 ;;
        --persistent-journal) persistent=true; shift ;;
        --dry-run) dry_run=true; shift ;;
        --help|-h) usage; exit 0 ;;
        *) usage >&2; exit 2 ;;
    esac
done
[[ $service_user =~ ^[a-zA-Z_][a-zA-Z0-9_-]*\$?$ ]] || { printf 'Invalid user name\n' >&2; exit 2; }
[[ $interface =~ ^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,14}$ ]] || { printf 'Invalid interface name\n' >&2; exit 2; }
[[ $(id -u "$service_user") -ne 0 ]] || { printf 'Choose a non-root --user\n' >&2; exit 2; }
service_group=$(id -gn "$service_user")
[[ $service_group =~ ^[a-zA-Z_][a-zA-Z0-9_-]*\$?$ ]] || { printf 'Invalid group name\n' >&2; exit 2; }
source_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project_dir=$(dirname -- "$source_dir")
packaging="$project_dir/packaging/systemd"
for file in appliance-display-health.service.in appliance-display-health.timer 90-appliance-display-diagnostics.conf; do
    [[ -f "$packaging/$file" ]] || { printf 'Missing packaging file: %s\n' "$file" >&2; exit 1; }
done
[[ -f "$source_dir/health_sample.py" ]] || { printf 'Missing sampler\n' >&2; exit 1; }
render_service() {
    sed -e "s|@SERVICE_USER@|$service_user|g" -e "s|@SERVICE_GROUP@|$service_group|g" \
        -e "s|@INTERFACE@|$interface|g" "$packaging/appliance-display-health.service.in"
}
if $dry_run; then
    printf 'DRY RUN: no files or services changed. User=%s Interface=%s\n' "$service_user" "$interface"
    render_service
    printf '\nTimer: every 30 seconds.\n'
    if $persistent; then
        printf 'HOST-WIDE journal policy requested:\n'
        cat "$packaging/90-appliance-display-diagnostics.conf"
    else
        printf 'Existing journal policy left unchanged.\n'
    fi
    exit 0
fi
if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
    args=(--user "$service_user" --interface "$interface")
    if $persistent; then args+=(--persistent-journal); fi
    exec sudo bash "$0" "${args[@]}"
fi
command -v systemd-analyze >/dev/null
[[ -x /usr/bin/python3 ]] || { printf 'Python 3 is required\n' >&2; exit 1; }
staging=$(mktemp -d)
trap 'rm -f -- "$staging/appliance-display-health.service" "$staging/appliance-display-health.timer"; rmdir -- "$staging"' EXIT
render_service > "$staging/appliance-display-health.service"
cp -- "$packaging/appliance-display-health.timer" "$staging/appliance-display-health.timer"
/usr/bin/python3 -c 'import ast, pathlib, sys; ast.parse(pathlib.Path(sys.argv[1]).read_text())' "$source_dir/health_sample.py"
systemd-analyze verify "$staging/appliance-display-health.service" "$staging/appliance-display-health.timer"

# Keep pre-upgrade copies of our own files only. Never vacuum or delete logs.
install -d -m 0700 /var/backups/appliance-display-health
backup=$(mktemp -d /var/backups/appliance-display-health/install-XXXXXXXX)
copy_owned_file() {
    local source=$1 destination=$2
    if [[ -e "$destination" || -L "$destination" ]]; then
        cp -a -- "$destination" "$backup/$(basename -- "$destination")"
    fi
    install -m 0644 -- "$source" "$destination"
}
install -d -m 0755 /usr/local/lib/appliance-display-sensor
# Stop only the old recorder before replacing its script; not the main sensor.
for unit in appliance-display-health.timer appliance-display-health.service; do
    if [[ $(systemctl show "$unit" -p LoadState --value) != not-found ]]; then
        systemctl stop "$unit"
    fi
done
copy_owned_file "$source_dir/health_sample.py" /usr/local/lib/appliance-display-sensor/health-sample.py
copy_owned_file "$staging/appliance-display-health.service" /etc/systemd/system/appliance-display-health.service
copy_owned_file "$staging/appliance-display-health.timer" /etc/systemd/system/appliance-display-health.timer
if $persistent; then
    install -d -m 0755 /etc/systemd/journald.conf.d
    copy_owned_file "$packaging/90-appliance-display-diagnostics.conf" /etc/systemd/journald.conf.d/90-appliance-display-diagnostics.conf
fi
systemctl daemon-reload
if $persistent; then
    systemctl restart systemd-journald.service
    journalctl --flush
fi
systemctl enable --now appliance-display-health.timer
systemctl start appliance-display-health.service
printf '\nHealth recorder installed. Sensor service and calibration were not changed.\nBackup: %s\n' "$backup"
systemctl --no-pager list-timers appliance-display-health.timer
journalctl -u appliance-display-health.service -n 2 --no-pager
