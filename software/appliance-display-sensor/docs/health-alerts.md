# Optional Home Assistant health alerts

The [health-alerts blueprint](../homeassistant/blueprints/automation/appliance_display_sensor/health_alerts.yaml)
can run actions you choose when the existing health diagnostics report a prolonged problem.
It requires Home Assistant 2024.10 or newer and the sensor's live-camera health entities.
It is separate from completion notifications, the Pi health-history recorder, and Codex reminders.
Nothing is enabled merely by installing/upgrading the Pi software or copying this blueprint.

## Android phone version with high-priority delivery

Use [Android priority health alerts](../homeassistant/blueprints/automation/appliance_display_sensor/health_alerts_android.yaml)
for a built-in phone picker and notification. It keeps the same fault detection as the generic
blueprint. Select your Android Companion App device; additional actions are optional. Use one
version per sensor unless duplicate alerts are intentional. Neither version is enabled here.

Both fault notifications request `priority: high` and default to `ttl: 0`, following the
[Companion App's Android delivery guidance](https://companion.home-assistant.io/docs/notifications/critical-notifications/).
These settings address sleep-related push delays; they do not guarantee delivery or override
Do Not Disturb, silent mode or notification permissions. No alarm stream, forced sound or
critical iOS interruption is configured. Android notification-channel preferences still apply.
The picker lists mobile-app devices, so select Android, not an iPhone.

**Zero TTL means deliver immediately or discard.** A phone without a usable connection may miss
the alert. The **Offline delivery window** input can instead allow a short queue (for example,
300 seconds), still with high priority. Such a queued message might arrive after the fault has
cleared. See [FCM message lifespan](https://firebase.google.com/docs/cloud-messaging/customize-messages/setting-message-lifespan).
There is no resend loop. Local Push does not use these cloud-push delivery options.

Push priority is separate from the intentional 120-second camera-fault confirmation delay and
the additional unreadability delay. Those remain configurable to avoid alerts for brief hiccups.
For this version, copy/import `health_alerts_android.yaml` instead of `health_alerts.yaml`, choose
**Appliance Display Sensor - Android priority health alerts**, select your phone, and optionally
add other actions. The phone notification already includes the explanatory title/message;
there is no need to enter a notify service name or duplicate it in Additional actions.
Live HA import and a real delivery test with the phone idle/screen off still need validation.

## What it watches

| Fault | Default timing | What clears the condition |
| --- | --- | --- |
| Camera or connection | Camera status stays `stale`, `error`, `unavailable` or `unknown` for 120 seconds | Status leaves that group, normally to `live` or `waiting` |
| Unreadable display | Display reading problem stays `on`, with Camera status `live`, for another 60 seconds | The problem turns off or the camera stops reporting `live` |

The device already requires 60 seconds of continuous unreadability before the problem entity
turns on. The default reading alert is therefore about two minutes after that unreadability
begins, plus heartbeat timing. A lost connection may take the existing 45-second health expiry
or broker availability detection before the camera fault delay begins.

Both alert types can be enabled separately and their delays changed. Each type runs once after
its condition stays true for the delay. A change from `stale` to `unavailable`, for example,
does not reset or retrigger the same camera-fault episode. A cleared and recurring fault can
alert again. The two types are independent, so an unreadability episode followed by an outage
can produce two alerts. No repeating reminders, periodic polling, or recovery messages are added.

Blank screens and calibration previews do not turn the reading-problem entity on. Reading age
is not used, since it legitimately increases when the display is off. A misplaced box that
reads entirely blank can still escape this warning. These alerts do not prove the appliance is
running, stopped, stalled or complete; they are not safety-critical monitoring.

Home Assistant's template triggers respond to changes. Pending delays reset on HA restart or
automation reload; do not rely on a pre-existing fault producing an immediate alert. It may
need to clear and recur. See the official [template trigger behavior and restart limitation](https://www.home-assistant.io/docs/automation/trigger/#template-trigger).
If Home Assistant itself is down, it cannot send these alerts. This blueprint intentionally
does not add persistent helpers or startup polling to work around those limits.

## Install and choose actions

1. Copy `homeassistant/blueprints/automation/appliance_display_sensor/health_alerts.yaml` into
   Home Assistant's configuration directory at
   `blueprints/automation/appliance_display_sensor/health_alerts.yaml`, using your normal file
   editor or file transfer access. This is the **HA host**, not the camera Pi's project directory.
   If replacing a prior copy, keep a backup first. The repository is not assumed to have a
   public URL, so don't paste a local filesystem path into HA's URL-import field.
2. In **Settings → Automations & scenes → Blueprints**, locate
   **Appliance Display Sensor - optional health alerts**, reloading blueprints if needed, and
   create an automation from it.
3. Choose **Camera status** and **Display reading problem** from the same sensor device. Do not
   choose the appliance's ordinary **Status** or **Running** entity.
4. Set the display name, enable the desired fault types, and choose delays.
5. Choose the actions in HA's action editor. A phone notification, dashboard notice, or existing
   script is optional; no destination is selected for you. Save/enable only when ready.

Use these variables in the action's message/title fields (switch to YAML when necessary):

- `{{ health_message }}`: a plain-language explanation and next check;
- `{{ health_title }}`: your chosen label plus a short health description;
- `{{ health_reason }}`: `camera_or_connection` or `unreadable`.

For example, a dashboard-only persistent notice can use:

```yaml
- action: persistent_notification.create
  data:
    title: "{{ health_title }}"
    message: "{{ health_message }}"
```

For a phone notice, choose your actual `notify.mobile_app_...` action rather than copying an
unverified entity or recipient. Keep actions short: two action runs may execute in parallel;
additional overlapping runs are dropped. Existing notices are not automatically dismissed
when the fault clears. Your existing dryer-finished automation remains separate and unchanged.
Blueprint inputs and user-selected actions follow the official
[blueprint schema](https://www.home-assistant.io/docs/blueprint/schema/).

## Validate safely

First verify the selected diagnostic entities on the HA device page: Camera status should be
`live`, and Display reading problem should be off during a readable countdown, normal blank
screen, or calibration preview. The blueprint's **Run actions** button intentionally does
nothing without a real trigger, avoiding a misleading test alert. Test the chosen notification
action separately with an explicit test message if desired.

During a planned maintenance window, allow a known disconnect to exceed the configured delay
and inspect the automation trace and selected destination. Do not disturb the camera or stop a
working sensor during laundry merely to force an alert. A short disconnect should not alert.
Live HA schema/import validation, notification delivery, restart behavior and real fault timing
remain installation checks; repository tests cover YAML structure and template truth tables,
not Home Assistant's actual event loop or phone delivery.

Disable or delete just the automation to stop health alerts. No Pi restart, optical settings
change, helper cleanup, or completion-automation change is needed.
