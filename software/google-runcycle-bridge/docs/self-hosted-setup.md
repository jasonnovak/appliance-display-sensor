# Self-hosted Google bridge setup

An optional developer setup for your own home. Start after the optical sensor reliably
updates Home Assistant. No Android test app, phone debugging, Google Home API/MCP,
Google Sign-In client or AI subscription is part of this workflow.

The recommended host is HA OS. The bridge and tunnel run without your PC. The wizard
handles files and credentials; Google's console and phone account linking remain manual.
Official documentation checked 2026-10-27; labels can change. This first-install
workflow is experimental and still needs an independent clean-host trial.

## 1. Gather your settings

1. **Google project ID:** sign into [Google Home Developer Console](https://console.home.google.com/)
   with your Google Home account, create a project and Cloud-to-cloud integration.
   Record the project ID, not its display name or number. Choose integration name
   “Appliance Display Sensor” and your actual appliance type. Leave endpoints and credentials
   until step 6. Accept any required terms yourself.
2. **Permanent HTTPS hostname:** for example `appliances.example.com`, on a domain you control.
   The Cloudflare path needs an active DNS zone in your own Cloudflare account. You can use
   a separate domain instead of moving your existing website's DNS.
3. **MQTT connection:** broker hostname/IP as reachable FROM HA, port, username/password,
   and your sensor's exact `mqtt.base_topic`. Read the topic from sensor configuration;
   it is not a Home Assistant entity ID or discovery prefix. HA's Mosquitto app commonly
   uses hostname `core-mosquitto`. A dedicated login needs read access to `<base_topic>/state`,
   `/health`, and `/availability`. An HA user used for Mosquitto authentication need not be an administrator.
4. **HA transfer access:** Advanced SSH & Web Terminal with Python 3, the `ha` CLI,
   `/addons` and `/addon_configs` available. Use your configured authenticated Samba or
   SCP access to transfer files. No Docker CLI access or disabling protection mode is required.

The bridge implements its own OAuth server. **Do not create a Google Cloud web or Android
OAuth client for it.** The wizard generates the client credentials Google uses to call
your bridge. This is different from installing a Google Home SDK app.

## 2. Prepare a permanent tunnel

Create a remotely managed Cloudflare tunnel for this bridge. Copy its connector token
privately; copy only the token, not the complete Docker/run command. The wizard needs it.
No connector needs to run on your PC.

Create one published application route:

| Setting | Value |
| --- | --- |
| Public hostname | Your chosen name, such as `appliances.example.com` |
| Service type | HTTP |
| Internal service | `local-appliance-display-bridge:8767` |

The connector stays unhealthy until the HA app starts. Keep unmatched routes rejected.
Route only to the bridge, not HA port 8123, the camera page, MQTT, or an entire network.
The bridge supplies OAuth authentication. An extra interactive Access login or browser
challenge on its API/OAuth routes prevents Google calling it. Keep certificate validation
enabled. Use a named tunnel with a stable hostname, not a changing Quick Tunnel URL.
See [Cloudflare's guide](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/).

With an existing HTTPS proxy, leave the wizard's tunnel token blank. This omits the
tunnel app. Configure proxy connectivity yourself: bridge host port 8767 is disabled
by default. The two-app tunnel setup is the automated path documented here.

## 3. Run the offline wizard on your computer

Download the [public source release](https://github.com/jasonnovak/appliance-display-sensor/releases)
and extract it into your private user directory. Open a terminal **inside
`software/google-runcycle-bridge` in the extracted folder**, not the repository root
or Windows system32. If using a standalone bridge archive, open its root folder instead.

Windows PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe setup_self_hosted.py
```

Linux/macOS:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python setup_self_hosted.py
```

Enter your project ID, HTTPS origin, spoken name (such as **Dryer** or **Washer**), type,
room, MQTT details and optional tunnel token. Password/token entry is hidden. Choose
the broker's matching TLS setting and port (often 8883 for TLS). System-trusted MQTT
certificates are supported; private-CA or client-certificate brokers need additional
configuration outside this turnkey path.

Output defaults to `.local/self-hosted/`:

| File | Purpose |
| --- | --- |
| `google-console.txt` | Exact endpoints and generated OAuth credentials |
| `linking-credentials.txt` | Bridge username/password for the phone consent page |
| `install/` | Ready-to-transfer app sources and private configuration |
| `PRIVATE-ha-install.zip` | The install folder zipped for transfer |

**This entire output folder is private.** It is not the public release ZIP. Keep the
credential sheets in a password manager/protected user folder. Files use restricted
POSIX modes; Windows inherits your folder's ACLs. No secrets print to the console.
The wizard refuses an existing output directory instead of replacing credentials.

## 4. Install on HA OS

Transfer the contents of `install/` into a new folder on your HA host, for example
`/share/appliance-bridge-install/`. Alternatively transfer `PRIVATE-ha-install.zip` and
extract it there. Keep the credential sheets on your computer. Do not paste passwords
into shell commands or public support requests.

In Advanced SSH & Web Terminal:

```sh
cd /share/appliance-bridge-install
python3 install_ha.py
```

This previews the plan without changing anything. To install:

```sh
python3 install_ha.py --apply
```

The helper stages, installs and starts only these new apps:

- Source `/addons/appliance_display_bridge`; private `/addon_configs/local_appliance_display_bridge`.
- With a token: source `/addons/appliance_display_tunnel`; private `/addon_configs/local_appliance_display_tunnel`.

Existing installations/config folders are refused. This is **not an updater**. The helper
does not edit HA automations, the camera sensor, other apps or router rules. First image
builds need Internet and may take several minutes. If interrupted, follow
[recovery instructions](maintenance.md), rather than deleting private data to retry.

In HA **Settings → Apps**, confirm each app is **Running**, **Start on boot** is enabled,
and enable **Watchdog**. The bridge's name/type/room/origin should already match your inputs.
Host ports stay disabled. Verify the connector is healthy in Cloudflare. Include both
apps' data/configuration in HA backups. Remove the temporary shared transfer copy after
verification; keep a protected recovery copy if desired.

## 5. Check reachability

Open `https://YOUR-HOSTNAME/healthz`. Expected:

```json
{"ok": true, "service": "appliance-display-sensor"}
```

The bare `/` has no dashboard and can return 404. An unauthenticated POST to `/fulfillment`
must return 401. `/oauth/authorize` without Google's query parameters returns 400; this
is not a health test. `/healthz` proves reachability, not camera/MQTT health.

## 6. Configure Google

In your Cloud-to-cloud integration, copy values from your private `google-console.txt`:

- Integration name: Appliance Display Sensor (service branding, not the spoken device name).
- Device type: the chosen appliance. Included `bridge-icon.png` is a developer-test sample;
  public certification has separate branding requirements.
- Account linking: OAuth authorization-code flow, generated client ID and client secret.
- Authorization URL: `https://YOUR-HOSTNAME/oauth/authorize`.
- Token URL: `https://YOUR-HOSTNAME/oauth/token`.
- Fulfillment URL: `https://YOUR-HOSTNAME/fulfillment`.
- Scope: `appliance.read`. HTTP Basic or body client credentials are supported.
- Leave App Flip and local fulfillment unset.

Save. The accepted redirect is exactly
`https://oauth-redirect.googleusercontent.com/r/YOUR-PROJECT-ID`; project ID must match
the wizard. See [Google setup](https://developers.home.google.com/cloud-to-cloud/integration/create)
and [OAuth requirements](https://developers.home.google.com/cloud-to-cloud/project/authorization).

Google's 2026 migration changes App Flip/deep links; this guide starts directly in the
Google Home app and implements no App Flip. Other platform-specific redirect paths are
not implemented. If Google supplies a different redirect, review the
[migration guide](https://developers.home.google.com/cloud-to-cloud/account-linking-migration)
instead of disabling redirect checks. The reference phone flow was Android; iOS needs validation.

## 7. Link your account

Use the project's **Test** page to enable testing. If needed, enter Test/Retest until
the test suite offers account linking. In the phone Google Home app, use **Add device →
Works with Google** (labels vary), and find **[test] Appliance Display Sensor**.
On your own HTTPS consent page use the bridge-only login from `linking-credentials.txt`.
This is not your Google, HA or MQTT password.

Use the same Google account as the developer project. Additional testers need project
permissions and Google's test workflow; Home membership alone does not guarantee test
access. Follow [Google's testing guide](https://developers.home.google.com/cloud-to-cloud/test).
No user needs the project author's Google project, endpoint or credentials. You are
not applying for public certification through this personal installation flow.

## 8. Verify natural voice replies

1. Say **“Hey Google, sync my devices.”** Check the device name in Google Home.
2. With a blank display: **“How much time is left on the dryer?”** Expected: no timers
   set. Google chooses exact wording.
3. During a real countdown, compare the answer with the display. Try two speakers;
   only the speaker asked should reply. Check adaptive increases/decreases if possible.
4. Disable or rename any old Google routine/HA voice helper intercepting that phrase.
   Keep separate cycle-finished notifications enabled.
5. After a planned HA reboot, check recovery of the apps, tunnel and MQTT source.

After bridge restart, retained countdowns are deliberately ignored until a fresh state
update. “Not ready” means insufficient reliable evidence; “No timers” does not mean
completion. More details: [maintenance](maintenance.md).

Rename later through the bridge app's **Device name**, save/restart, then sync devices.
Stable identity and the OAuth link remain unchanged; no relinking is needed.
