# Appliance Display Sensor Google Bridge

Optional read-only Google countdown answers. This local app runs alongside the
sensor and MQTT broker; it does not control an appliance or publish MQTT commands.

For first installation use the release's docs/self-hosted-setup.md and offline
setup_self_hosted.py wizard. It generates unique private configuration and an HA
install bundle. Do not copy someone else's credentials, endpoints or grants.

## Configuration

Device name is what Google should recognize, for example Dryer or Washer. After
changing name/type/room, save, restart, and ask Google to sync devices. Stable IDs
and the existing account link remain unchanged. Activity is reported as running.
Set Public HTTPS address to your permanent origin, without an OAuth path.

Keep the host port disabled with the bundled tunnel. Route only your chosen public
hostname to local-appliance-display-bridge:8767. This app needs no HA/Supervisor API,
host-network or privileged access.

Private app configuration contains bridge.json and grants.sqlite3. Include both,
app data and saved options in protected HA backups. Never publish them. Fresh setup
refuses existing installations; upgrades must preserve this configuration and IDs.

A fresh blank display reports no timer set when alignment is verified or its check
is disabled/not configured. Unreadable/uncertain observations report not ready;
network/camera failure reports offline. Blank never means completion. Google's
spoken wording is outside this app's control. After startup, retained countdowns
are ignored until fresh evidence arrives.

Account links do not expire after 90 days. Valid legacy refresh grants migrate on
startup; expired or revoked grants are not revived. Unlinking revokes access, and
access tokens remain limited to one hour.
