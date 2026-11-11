# Raspberry Pi setup

The reference runtime is Raspberry Pi OS Lite (64-bit) on a Raspberry Pi Zero 2 W. Use Raspberry
Pi Imager to configure the hostname, operator account, Wi-Fi, locale, and SSH before first boot.

## Prepare the runtime

Clone the public repository onto the Pi and enter the sensor component:

```console
git clone https://github.com/jasonnovak/appliance-display-sensor.git
cd appliance-display-sensor/software/appliance-display-sensor
bash scripts/bootstrap_pi.sh
```

The bootstrap script:

1. installs the Raspberry Pi OS builds of NumPy, OpenCV, Paho MQTT, PyYAML, and Picamera2;
2. creates `.venv` with `--system-site-packages`, which Picamera2 requires to use the matching
   `libcamera` bindings supplied by Raspberry Pi OS;
3. installs Appliance Display Sensor and its remaining Python dependencies; and
4. runs the camera-independent unit tests.

Using the OS Picamera2 package is intentional. Installing Picamera2 independently with `pip` can
produce a version that is incompatible with the operating system's `libcamera` bindings.
The editable project build also uses Raspberry Pi OS's `setuptools` and `wheel` packages without
build isolation, avoiding an unnecessary dependency on PyPI or piwheels during bootstrap.

## Re-enter the environment

For a later interactive session:

```console
cd ~/appliance-display-sensor/software/appliance-display-sensor
source .venv/bin/activate
python -m unittest discover -s tests -v
```

The camera does not need to be connected for bootstrap or unit testing. Once it is installed, use
the Raspberry Pi camera utilities to verify hardware detection before calibrating the application.

## Create your local camera configuration

From `software/appliance-display-sensor` in the extracted repository, after bootstrap:

```sh
cp configs/example-picamera2.yaml config.local.yaml
.venv/bin/python -m appliance_display_sensor --config config.local.yaml --no-mqtt
```

Open `http://PI_ADDRESS:8090/` on your trusted LAN. The example starts the camera
and setup page with MQTT off and synthetic boxes; it cannot read your display until
you set rotation, display/digit alignment and optical settings. Follow
[browser calibration](browser-calibration.md). Auto exposure/focus are starting
settings only; lock suitable values after testing bright and dim conditions.
Stop the foreground process with Ctrl+C before installing or starting the service.

Edit the local configuration's device name, unique identifier, MQTT base topic and
broker settings before enabling MQTT. Configure H:MM only for a three-position
hour/minute display, and set its actual terminal text. Never publish this local file.

## Live camera smoke test

After creating a local Picamera2 configuration, process a finite number of frames without MQTT:

```console
cd ~/appliance-display-sensor/software/appliance-display-sensor
.venv/bin/python -m appliance_display_sensor \
  --config config.local.yaml --max-frames 3 --no-mqtt --compact
```

The reference Camera Module 3 results and provisional settings are recorded in
[camera validation](camera-validation.md).

## Guided browser calibration

On a trusted local network, enable the setup page in the local configuration:

```yaml
calibration:
  enabled: true
  host: 0.0.0.0
  port: 8090
```

After the service starts, open `http://PI_ADDRESS:8090/`. Preview changes pause MQTT state
transitions, and Save and apply creates `config.local.yaml.bak` before atomically replacing the
configuration. Full instructions and security notes are in
[Browser calibration](browser-calibration.md).

## MQTT credentials

The official Home Assistant Mosquitto broker requires authentication. Create a dedicated,
non-administrator Home Assistant user for this device, then put only its password in the ignored
file referenced by `mqtt.password_file`. Do not use the reserved usernames `homeassistant` or
`addons`.

```console
cd ~/appliance-display-sensor/software/appliance-display-sensor
mkdir -p secrets
chmod 700 secrets
read -rsp "MQTT password: " mqtt_password
printf '%s' "$mqtt_password" > secrets/mqtt_password
unset mqtt_password
chmod 600 secrets/mqtt_password
```

Enable MQTT in `config.local.yaml`, set the broker host, username, and password-file path, then run
another finite smoke test before installing the service.

## Install the boot service

The installer renders a systemd unit for the current project path and the user who invoked sudo,
creates a service-writable `debug/` directory, grants the service access to its configuration
directory for calibrated saves and rollback copies, and restarts an existing installation so unit
changes take effect. It then enables and starts the service:

```console
bash scripts/install_service.sh
```

Inspect the service and follow its bounded system journal with:

```console
systemctl status appliance-display-sensor.service
journalctl -u appliance-display-sensor.service -f
```

## Optional outage history

For local, passive 30-second system samples that remain available when the sensor stops, use
the separate [health-history recorder](health-history.md). Its installer has a dry-run mode,
backs up existing recorder files and does not restart the main sensor. Recording and host-wide
persistent journal storage are separate opt-ins; neither is enabled by the main installer.

## Later software updates

Use the [source-update and rollback workflow](runtime-updates.md) for reviewed runtime-only
changes. It provides a read-only change plan, tests with the installed environment and recoverable
backups while leaving calibration and credentials alone. Dependency/service/schema changes need
separate review; the tool is not an OS updater.
