# Optional finish-estimate change alerts

The `estimate_changes.yaml` automation blueprint runs your chosen actions when a running
appliance's predicted finish moves significantly earlier or later. It uses the existing MQTT
entities; no new Pi service, helper, camera setting or notification destination is required.
The blueprint file alone does nothing. It has not been enabled or configured for a recipient.

## What it compares

It compares **finish timestamps**, not the decreasing number of minutes left:

| Observation | Predicted finish | Result at the default threshold |
| --- | --- | --- |
| 30 minutes left at 19:00 | 19:30 | Starting estimate; no alert |
| 29 minutes left at 19:01 | 19:30 | Normal tick; no alert |
| 42 minutes left at 19:02 | 19:44 | 14 minutes later; eligible |

Defaults are a **10-minute change**, either direction, a **10-second recheck**, and a
**15-minute quiet period after actions finish**. All four are selectable. Only a qualifying
change starts the recheck; there is no periodic polling or reminder. Multiple small changes
do not accumulate into an alert. During the recheck, the latest estimate is compared with the
estimate before the qualifying change; it need not remain exactly the same timestamp.

To avoid unreliable comparisons:

- Appliance Status must be `running`, Camera status `live`, and Display readability `readable`.
  Each must have remained in that state for at least 60 seconds, and since before the previous
  estimate was received. The first estimate after a cycle start, reconnect or readability
  interruption can be skipped deliberately. These checks use HA state-change times.
- Missing, unavailable or invalid timestamps are ignored. Timestamps outside a sanity window
  of one day in the past to seven days in the future are rejected. Keep HA and Pi clocks correct.
- A health/readability fault, completion, or unavailable estimate during the recheck cancels it.
  The final check also rejects recovery that broke continuity, and changes that reverted below
  the threshold or outside the selected direction.
- The automation runs in `single` mode. Changes during confirmation/actions/quiet time are not
  queued or replayed later. The quiet period also spans a new cycle. Set it to zero to remove the
  extra quiet period, and keep your actions short. HA restart/reload cancels waits and quiet time.

This is an **estimate notification, not completion or a stalled-cycle alarm**. It cannot tell a
real adaptive-cycle revision from a manually changed timer or a confidently misread display.
Normal drying can legitimately add or subtract time. Your existing completion automation and
the sensor's `End` confirmation/latching remain unchanged. No appliance controls are operated.

## Install when wanted

1. Copy `homeassistant/blueprints/automation/appliance_display_sensor/estimate_changes.yaml`
   into the **Home Assistant host's**
   `/config/blueprints/automation/appliance_display_sensor/estimate_changes.yaml`, using your
   normal file access. Back up any prior copy first. Copying it to the camera Pi does not install
   it in HA. A local path is not a public URL for HA's blueprint-import dialog.
2. Open **Settings → Automations & scenes → Blueprints**, reload if necessary, and create an
   automation from **Appliance Display Sensor - optional finish estimate changes**.
3. Select **Estimated finish**, **Status**, **Camera status** and **Display readability** from
   the same sensor device. Do not substitute Running, Time remaining, or Reading confidence.
4. Choose the label, threshold, direction, recheck delay and quiet period.
5. Choose your actions in the normal HA action editor. Save/enable only when ready. No phone or
   speaker is selected for you. Disable/delete this automation to stop these notices.

The blueprint follows HA's [blueprint schema](https://www.home-assistant.io/docs/blueprint/schema/),
[state triggers](https://www.home-assistant.io/docs/automation/trigger/) and
[single-mode behavior](https://www.home-assistant.io/docs/automation/modes/).

Available action variables:

- `estimate_title`, `estimate_message`: ready-to-use text;
- `estimate_direction`: `earlier` or `later`;
- `estimate_change_minutes`: absolute finish-time shift, rounded to one decimal;
- `previous_finish`, `estimate_finish`: old and rechecked ISO timestamps.

A dashboard-only action needs no phone selection:

```yaml
- action: persistent_notification.create
  data:
    title: "{{ estimate_title }}"
    message: "{{ estimate_message }}"
```

For an Android Companion App phone, choose its actual `notify.mobile_app_...` action. The
following is an **example placeholder**, not an existing recipient:

```yaml
- action: notify.mobile_app_your_phone
  data:
    title: "{{ estimate_title }}"
    message: "{{ estimate_message }}"
    data:
      priority: high
      ttl: 0
```

High priority requests prompt delivery; TTL zero requests immediate delivery or discard, so an
offline phone can miss it. A nonzero TTL permits delayed delivery of an estimate that may already
have changed again. Neither setting bypasses DND or removes the deliberate recheck/quiet delays.
These are Android-specific settings; see the official
[Companion notification documentation](https://companion.home-assistant.io/docs/notifications/critical-notifications/#android).
Ordinary action failures continue into the quiet period; configuration/template errors can still
stop a run. No notification retry loop is added.

## Validate without disrupting laundry

Repository checks cover YAML structure and template cases: normal ticks, both directions,
threshold boundaries, timezone offsets/midnight, invalid dates, startup/recovery, a reverted
estimate, completion/fault cancellation and manual runs. They do not validate HA's actual event
loop, blueprint import or phone delivery. These remain installation checks.

**Run actions** deliberately does nothing without a real estimate-change trigger. Test a selected
notification action separately using a clearly marked test message. When enabled, inspect its
trace during the next normal adaptive load and compare against the physical display. An entire
load without a large qualifying change should produce no estimate-change notice. Do not move
the camera, force timer changes, or run a special load just to provoke an alert.
