# Appliance Display Sensor — optional Google voice bridge

Ask **“Hey Google, how much time is left on the dryer?”** and receive a native answer on the speaker you asked. This self-hosted bridge exposes the camera sensor's MQTT countdown through Google's read-only RunCycle trait. It does not control appliances or broadcast across the house.

**Start here: [self-hosted setup](docs/self-hosted-setup.md).** The offline wizard generates unique credentials, an exact Google Console settings sheet, and a private HA OS installation bundle. No editing Python, importing secrets from a Pi, phone debugging, Android test app, Google Home API/MCP access, or Google AI subscription is part of this path.

## What you need

- A working Appliance Display Sensor publishing state, health and availability to MQTT.
- An always-on HA OS host (amd64 or aarch64) and a Google/Nest speaker.
- A Google Home Developer Console project owned by you, used in test mode.
- A stable HTTPS hostname. The documented route uses your own Cloudflare domain and named tunnel, without router port forwarding.
- A computer with Python 3.11+ for the one-time wizard.

The core sensor, HA dashboard and completion notifications work without this bridge. This adds a Google-dependent voice feature. Domain registration and any hosting costs are yours; the project does not supply a hosted service or shared credentials.

## Status and scope

Experimental, one household and one appliance per bridge. The reference dryer has answered an active countdown on the requesting speaker. After moving to HA OS, idle responses and the natural “the dryer” phrase were confirmed. Active-countdown retesting on that permanent host and full host-reboot recovery remain pending. The first-install tools are tested with simulated HA folders, not on a second clean HA host.

Name, room and appliance type are configurable. Dryer, washer, dishwasher, oven, microwave and vacuum types have schema tests; only the dryer has a real-speaker check. The activity word is **running**. A numeric display alone does not identify a physical cycle phase.

This is not a certified, publicly listed Works with Google integration. Each installer creates their own developer project; only its authorized accounts can find its test integration. Google's requirements and console behavior may change.

## Data and behavior

Camera sensor → local MQTT → bridge on HA OS → HTTPS tunnel → Google → requested speaker.

- Shares device name, room, availability and remaining seconds; no camera images.
- Preserves adaptive time jumps. Never runs a second timer or infers completion.
- Fresh blank display: no timer set when mount checking is aligned or disabled/not configured.
- Unreadable/uncertain reading: not ready. Camera or broker outage: offline.
- Ignores retained state after startup; waits for fresh evidence before reporting a countdown.
- Fresh explicit completion is distinct from blank. HA can hold historical completion while the bridge has no current readable countdown.
- No MQTT publishing, appliance controls or bridge-app access to the HA API.

The HTTPS address is discoverable. Linking needs a separate bridge login; API requests need OAuth tokens. Access tokens expire after one hour; refresh grants remain valid until unlink/revocation. Secrets and grants stay in private persistent app configuration. The public health endpoint only reports service availability.

## Tools

| File | Purpose |
| --- | --- |
| `setup_self_hosted.py` | Offline credential and private-install-bundle wizard |
| `install_ha.py` | Preview or perform first installation from that private bundle |
| `build_release.py` | Build the allowlisted public source ZIP |
| `build_ha_app.py` | Build source-only HA app ZIPs for maintainers |
| `configure_device.py` | Change standalone configuration metadata |
| `ha_app/`, `ha_tunnel/` | Minimal local HA apps with no inbound host ports |

See [maintenance](docs/maintenance.md) and [release preparation](docs/releasing.md). The wizard output must never be attached to a public release. The public ZIP and private install ZIP are different artifacts.

## License

Original software, setup tools, documentation and project artwork are licensed
under [Apache-2.0](LICENSE). See [NOTICE](NOTICE) and [third-party components](THIRD_PARTY.md).
The mount/case designs use CERN-OHL-P-2.0 and are not included in this bridge ZIP.
