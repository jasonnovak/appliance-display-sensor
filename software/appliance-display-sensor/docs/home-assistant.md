# Home Assistant integration

Appliance Display Sensor publishes one MQTT device with generic entities beneath the configured
device name. For a device named `Dryer Display Sensor`, the default entity IDs are:

| Entity | Example entity ID | Purpose |
| --- | --- | --- |
| Display text | `sensor.dryer_display_sensor_display_text` | Exact accepted text such as `41`, `1:10`, or `End` |
| Time remaining | `sensor.dryer_display_sensor_time_remaining` | Numeric duration in minutes |
| Estimated finish | `sensor.dryer_display_sensor_estimated_finish` | Timestamp recalculated from the latest appliance estimate |
| Status | `sensor.dryer_display_sensor_status` | `running`, `complete`, or `unknown` |
| Running | `binary_sensor.dryer_display_sensor_running` | Convenience on/off state |
| Reading confidence | `sensor.dryer_display_sensor_reading_confidence` | Decoder confidence as a percentage |

Home Assistant may add a numeric suffix if an entity ID is already occupied. Confirm the actual
IDs on the device page before copying an automation.

## Availability and connection recovery

All entities share the retained MQTT availability topic. If every entity shows `Unavailable`
while the calibration page recognizes a valid display, check MQTT connectivity and the
`<base_topic>/availability` message. An unreadable display normally produces a status of `unknown`;
an `offline` availability message makes every entity unavailable, even with a valid retained state.

After every MQTT connection or reconnection, the sensor republishes discovery, its latest accepted
state (when available), and `online` availability using retained QoS 1 messages. This restores Home
Assistant after a network interruption or broker restart without waiting for a different countdown
value. Accepted readings during an outage replace the cached state, so recovery sends the latest
reading. Graceful shutdown and the broker's last will mark the sensor `offline`.

## Live camera health and readability

Live Picamera2 capture automatically discovers these additional entities on the same device,
under **Diagnostics**. No setup page needs to be open, and reporting works with calibration
disabled. Replay and single-image commands do not create health diagnostics.

| Diagnostic | Meaning |
| --- | --- |
| Camera status | `waiting`, `live`, `stale`, or `error` |
| Display readability | `readable`, `blank`, `unreadable`, `calibrating`, `waiting`, `stale`, or `error` |
| Last readable display | UTC timestamp of the most recent saved-mode frame interpreted as a countdown or configured terminal message |
| Reading age | Seconds since that readable frame; unknown until the first reading after startup |
| Display reading problem | On after 60 seconds of continuously unreadable saved-mode frames; off after a readable frame, blank, calibration, or stale/error condition |
| Pi temperature | CPU temperature in °C, independent of the appliance temperature |
| Wi-Fi signal | `wlan0` signal in dBm; not a packet-loss measurement |
| Camera frame age | Seconds since processing the latest frame; disabled by default |
| Available memory | Available RAM in MiB; disabled by default |
| Mount alignment | Optional static-anchor status; `not_configured` until a reference is chosen |

The heartbeat publishes every 10 seconds on `<base_topic>/health`. It runs independently of
capture, so a stalled camera can report `stale` while the service and broker connection remain
alive. The stale threshold is 15 seconds or three configured frame intervals, whichever is longer.
Frame age measures completed frame processing, so a processing stall is also reported as stale.
These diagnostic states expire after 45 seconds without a heartbeat. Health messages are not
retained or queued for reconnect; an old healthy snapshot must not be revived after an outage.
This follows Home Assistant's [MQTT expiry guidance](https://www.home-assistant.io/integrations/sensor.mqtt/#expire_after).
Existing countdown states retain their original behaviour and are not cleared by diagnostics.

`blank` means the decoder found all digit positions blank, not proof that the appliance is off.
A badly misaligned crop can also appear blank. A normal blank screen after `End` does not raise
a reading problem. Reading age will naturally grow while the display is off, so do not alert
on age alone. `unreadable` includes invalid patterns and digits that cannot be interpreted in the
selected countdown format. It reflects the latest frame even when stabilization still holds an
older countdown. Valid pattern recognition does not guarantee the reading matches the appliance.

Calibration tests report `calibrating`, reset the unreadable timer, and do not update the last
saved-mode readable timestamp. Timestamps/ages reset on service restart. Missing system
measurements remain unknown rather than reporting zero. A capture error normally also causes
the service to exit/restart, at which point MQTT availability takes precedence.

No notifications are enabled automatically. The optional [health-alerts blueprint](health-alerts.md)
provides separate camera/connection and unreadable-display alerts, configurable delays, and
user-selected actions. It groups camera fault states into one episode, avoids alerts based on
reading age or a normal blank screen, and does not add recurring reminders. Import and enable
an automation only after choosing the entities and desired actions. Keep completion alerts tied
to the appliance **Status**, not these diagnostic entities.

An Android-specific variant adds a Companion App phone picker and built-in high-priority
notifications (`priority: high`, default `ttl: 0`). Its offline expiry is configurable, and it
does not override Do Not Disturb. See [delivery settings and tradeoffs](health-alerts.md#android-phone-version-with-high-priority-delivery)
before enabling it. Use either the generic or Android variant to avoid duplicate alerts.

## Optional mount-alignment diagnostic

Live-camera discovery includes **Mount alignment**, an enabled diagnostic enum on the same
10-second, non-retained health heartbeat with 45-second expiry. It reports the existing setup-page
static-anchor check; adding the entity does not capture a reference, change calibration, reject
readings, move the camera, or enable alerts. No anchor pixels, coordinates, or match scores are
published. The original countdown/completion entities and existing alerts are unchanged.

Choose a distinctive fixed label/texture in **Align the display → Bumped-camera warning** and
confirm the physical alignment before saving a reference. Keep digits/indicators out of it and
validate it with room lights both on and off. A dark room may make a static label uncheckable even
while illuminated digits remain readable. This feature checks the chosen anchor, not digit accuracy.

| Entity value | Meaning |
| --- | --- |
| `not_configured` | No reference chosen; not an assertion that alignment is good |
| `disabled` | Setup/alignment monitoring is disabled for this camera run |
| `checking` | Waiting for sufficient fresh checks |
| `aligned` | Recent checks matched the saved anchor within its movement tolerance |
| `moved` | Repeated checks detected movement; inspect the mount and display boxes |
| `uncheckable` | Anchor too dark, missing, blurred, or ambiguous; no current match claim |
| `movement_unverified` | A movement warning is still latched, but the anchor is now uncheckable |
| `paused` | Calibration preview or settings handoff; no live saved-mode alignment claim |
| `needs_reference` | Saved optics/geometry no longer match the reference |
| `reference_unavailable` | The saved reference could not be loaded; replace it explicitly |
| `stale` | Camera or alignment checks are no longer fresh |
| `error` | Alignment reporting failed; other health fields can still be delivered |

Loss of the heartbeat/availability makes the HA entity `unavailable` as usual, independently of
these values. A stale or uncheckable result must not be interpreted as “no movement.” The monitor's
latched warning remains intact through uncheckable images; it clears only through its existing
confirmed-return/reference-reset behavior, and is not persisted across service restarts. Saved
references do persist. Allow fresh checks after restart.

The current health-alert blueprints do **not** act on this entity. Validate the anchor first before
creating a separate optional notification automation. Follow the [MQTT sensor enum and expiry
contract](https://www.home-assistant.io/integrations/sensor.mqtt/) if adapting discovery.

## Completion notification

Trigger on the stabilized status transition rather than on `remaining_minutes: 0`. Some
appliances display zero while they are still sensing or cooling, whereas a configured terminal
message such as `End` is authoritative.

```yaml
alias: Dryer finished - display sensor
description: Notify when the optical display sensor confirms the cycle is complete.
mode: single
triggers:
  - trigger: state
    entity_id: sensor.dryer_display_sensor_status
    from: running
    to: complete
conditions: []
actions:
  - action: notify.mobile_app_your_phone
    data:
      title: Dryer
      message: The dryer has finished
```

The explicit `running` to `complete` transition prevents a retained completed state from sending
a duplicate alert after Home Assistant or the display sensor restarts. Completion latching keeps
the status at `complete` after a short-lived terminal message disappears and the appliance panel
goes blank.

The repository also includes an importable
[completion-actions blueprint](../homeassistant/blueprints/automation/appliance_display_sensor/completion_actions.yaml).
It asks the user to select the Status entity and then uses Home Assistant's normal action editor
for one or more notifications, announcements, or other completion actions.

Temperature, vibration, or power automations can be retained as disabled fallbacks while the
optical installation is validated. Avoid enabling two completion notifiers unless duplicate
alerts are intentional.

## Adaptive cycles

Sensor-controlled appliances may revise the displayed estimate in either direction. Automations
should treat `Time remaining` and `Estimated finish` as live estimates, not monotonic timers. The
`Status` transition remains the reliable completion trigger.

## Voice access

### Home Assistant Assist

Expose the remaining-time and status entities to Assist under **Settings > Voice assistants >
Expose**. Give them short aliases such as `dryer time remaining` and `dryer status`. Assist can
then use the current Home Assistant state from the companion app or supported Assist hardware.

### Google Assistant and Google Home

For native countdown replies on the speaker asked, use the optional
[self-hosted RunCycle bridge](../../google-runcycle-bridge/docs/self-hosted-setup.md).
It reads MQTT and runs on HA OS with your own Google developer integration and
HTTPS endpoint. The core sensor and HA notifications work without it.

The reference system answered an active countdown on the requesting speaker before
migration, and idle queries work on the permanent HA host. Active-countdown retesting
on that host and reboot recovery remain open in the release checklist. Each installer
must complete their own Google project registration and account linking.

A routine that turns on a helper and broadcasts an HA-generated message is a
separate legacy workaround. It does not identify the requesting speaker. Disable or
rename any routine using the native countdown phrase to avoid interception; keep
independent completion alerts if desired. The earlier Android broadcast experiment
is not part of the installation and is not included in the public release.

## Optional finish-estimate changes

For a notice when an adaptive cycle significantly moves its predicted finish earlier or later,
use the separate [estimate-change blueprint](estimate-change-alerts.md). It distinguishes finish
revisions from normal countdown ticks and checks health/continuity before your chosen actions.
It is optional and does not replace or change the completion automation.

## Privacy

MQTT discovery publishes decoded state, not full camera frames. Diagnostic images remain local to
the display-sensor host unless the user deliberately exports them.
