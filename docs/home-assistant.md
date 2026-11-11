# Home Assistant setup

The Pi integrates using Home Assistant's existing MQTT integration. There is no
custom HA integration or HACS package to install for local countdown entities.

[Discuss the project on the Home Assistant Community forum](https://community.home-assistant.io/t/appliance-display-sensor-read-a-dryer-countdown-with-a-pi-camera-and-mqtt/1034072).

1. Set up an MQTT broker and Home Assistant MQTT integration.
2. Follow [Pi setup](../software/appliance-display-sensor/docs/raspberry-pi-setup.md)
   to configure the broker, a unique device identifier/base topic and credentials.
3. Confirm the device and countdown/health entities appear. Assign the device to
   your room/area, then add the entities you want to a dashboard.
4. Use the [entity and automation guide](../software/appliance-display-sensor/docs/home-assistant.md)
   for completion, availability and adaptive estimates.

## Optional blueprints

Files are in [the blueprint directory](../software/appliance-display-sensor/homeassistant/blueprints/automation/appliance_display_sensor).
Copy the YAML files into your HA configuration's
`blueprints/automation/appliance_display_sensor/` directory, reload automations as
needed, and create an automation from the chosen blueprint. Select your actual
entities and actions; examples cannot know your entity IDs or phone names.

- `completion_actions.yaml`: actions after confirmed completion.
- `health_alerts.yaml`: configurable sustained camera/readability fault actions.
- `health_alerts_android.yaml`: optional Android high-priority notification variant.
- `estimate_changes.yaml`: alerts for significant adaptive finish-estimate revisions.

Import into your Home Assistant installation:

- [Completion actions](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fjasonnovak%2Fappliance-display-sensor%2Fblob%2Fmain%2Fsoftware%2Fappliance-display-sensor%2Fhomeassistant%2Fblueprints%2Fautomation%2Fappliance_display_sensor%2Fcompletion_actions.yaml)
- [Health alerts](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fjasonnovak%2Fappliance-display-sensor%2Fblob%2Fmain%2Fsoftware%2Fappliance-display-sensor%2Fhomeassistant%2Fblueprints%2Fautomation%2Fappliance_display_sensor%2Fhealth_alerts.yaml)
- [Android health alerts](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fjasonnovak%2Fappliance-display-sensor%2Fblob%2Fmain%2Fsoftware%2Fappliance-display-sensor%2Fhomeassistant%2Fblueprints%2Fautomation%2Fappliance_display_sensor%2Fhealth_alerts_android.yaml)
- [Estimate changes](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fjasonnovak%2Fappliance-display-sensor%2Fblob%2Fmain%2Fsoftware%2Fappliance-display-sensor%2Fhomeassistant%2Fblueprints%2Fautomation%2Fappliance_display_sensor%2Festimate_changes.yaml)

Do not replace an existing working completion automation without checking for
duplicate notifications. Optional alerts remain disabled until the owner creates them.

## Google speakers

For a countdown reply on the speaker asked, use the separate
[Google bridge guide](../software/google-runcycle-bridge/docs/self-hosted-setup.md).
Its HA OS apps run the bridge and optional Cloudflare tunnel; the Pi reader still
publishes MQTT. Existing Google routines with the same phrase must be disabled or
renamed so they do not intercept native queries. Completion broadcasts are separate.
