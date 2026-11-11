from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from threading import Event, RLock
from typing import Any

from appliance_display_sensor.config import DeviceConfig, MqttConfig
from appliance_display_sensor.models import ApplianceState
from appliance_display_sensor.runtime_health import ALIGNMENT_STATES, HEALTH_EXPIRE_SECONDS

LOGGER = logging.getLogger(__name__)
PUBLISH_TIMEOUT = 5.0


@dataclass(frozen=True)
class MqttMessage:
    topic: str
    payload: str
    retain: bool = True


def build_discovery_messages(
    device: DeviceConfig, mqtt: MqttConfig, *, include_diagnostics: bool = False,
) -> list[MqttMessage]:
    """Build appliance-neutral Home Assistant MQTT discovery messages."""

    state_topic = f"{mqtt.base_topic}/state"
    availability_topic = f"{mqtt.base_topic}/availability"
    device_metadata: dict[str, Any] = {
        "identifiers": [device.identifier],
        "name": device.name,
        "manufacturer": "Appliance Display Sensor",
        "model": "Optical display sensor",
    }

    common = {
        "state_topic": state_topic,
        "availability_topic": availability_topic,
        "payload_available": "online",
        "payload_not_available": "offline",
        "device": device_metadata,
        "has_entity_name": True,
    }

    entity_definitions = {
        "display_text": {
            "component": "sensor",
            "name": "Display text",
            "value_template": "{{ value_json.display_text | default('') }}",
            "icon": "mdi:counter",
        },
        "remaining_time": {
            "component": "sensor",
            "name": "Time remaining",
            "value_template": "{{ value_json.remaining_minutes }}",
            "device_class": "duration",
            "unit_of_measurement": "min",
            "icon": "mdi:timer-outline",
        },
        "estimated_finish": {
            "component": "sensor",
            "name": "Estimated finish",
            "value_template": "{{ value_json.estimated_finish }}",
            "device_class": "timestamp",
            "icon": "mdi:clock-end",
        },
        "status": {
            "component": "sensor",
            "name": "Status",
            "value_template": "{{ value_json.status }}",
            "icon": "mdi:state-machine",
        },
        "confidence": {
            "component": "sensor",
            "name": "Reading confidence",
            "value_template": "{{ (value_json.confidence * 100) | round(1) }}",
            "unit_of_measurement": "%",
            "icon": "mdi:check-decagram-outline",
        },
        "running": {
            "component": "binary_sensor",
            "name": "Running",
            "value_template": "{{ 'ON' if value_json.running else 'OFF' }}",
            "payload_on": "ON",
            "payload_off": "OFF",
            "icon": "mdi:progress-clock",
        },
    }

    if include_diagnostics:
        diagnostics = {
            "camera_status": {
                "name": "Camera status", "device_class": "enum",
                "options": ["waiting", "live", "stale", "error"],
                "value_template": "{{ value_json.camera_status }}",
                "icon": "mdi:camera",
            },
            "display_readability": {
                "name": "Display readability", "device_class": "enum",
                "options": ["waiting", "readable", "blank", "unreadable",
                            "calibrating", "stale", "error"],
                "value_template": "{{ value_json.display_readability }}",
                "icon": "mdi:eye-check-outline",
            },
            "last_readable": {
                "name": "Last readable display", "device_class": "timestamp",
                "value_template": "{{ value_json.last_readable }}",
            },
            "reading_age": {
                "name": "Reading age", "device_class": "duration",
                "unit_of_measurement": "s",
                "value_template": "{{ value_json.reading_age_seconds }}",
            },
            "frame_age": {
                "name": "Camera frame age", "device_class": "duration",
                "unit_of_measurement": "s", "enabled_by_default": False,
                "value_template": "{{ value_json.frame_age_seconds }}",
            },
            "reading_problem": {
                "component": "binary_sensor", "name": "Display reading problem",
                "device_class": "problem",
                "value_template": "{{ 'ON' if value_json.reading_problem else 'OFF' }}",
                "payload_on": "ON", "payload_off": "OFF",
            },
            "pi_temperature": {
                "name": "Pi temperature", "device_class": "temperature",
                "unit_of_measurement": "°C", "state_class": "measurement",
                "value_template": "{{ value_json.system.temperature_c }}",
            },
            "wifi_signal": {
                "name": "Wi-Fi signal", "device_class": "signal_strength",
                "unit_of_measurement": "dBm", "state_class": "measurement",
                "value_template": "{{ value_json.system.wifi_signal_dbm }}",
            },
            "available_memory": {
                "name": "Available memory", "unit_of_measurement": "MiB",
                "enabled_by_default": False,
                "value_template": "{{ value_json.system.memory_available_mb }}",
                "icon": "mdi:memory",
            },
            "mount_alignment": {
                "name": "Mount alignment", "device_class": "enum",
                "options": list(ALIGNMENT_STATES),
                "value_template": "{{ value_json.mount_alignment | default('error') }}",
                "icon": "mdi:camera-marker-outline",
            },
        }
        for object_id, definition in diagnostics.items():
            entity_definitions[object_id] = {
                "component": "sensor", "entity_category": "diagnostic",
                "state_topic": f"{mqtt.base_topic}/health",
                "expire_after": HEALTH_EXPIRE_SECONDS, **definition,
            }

    messages: list[MqttMessage] = []
    for object_id, definition in entity_definitions.items():
        component = definition["component"]
        payload = {**common, **definition}
        payload.pop("component")
        payload["unique_id"] = f"{device.identifier}_{object_id}"
        topic = f"{mqtt.discovery_prefix}/{component}/{device.identifier}/{object_id}/config"
        messages.append(MqttMessage(topic, json.dumps(payload, separators=(",", ":"))))
    return messages


def build_state_message(
    device: DeviceConfig,
    mqtt: MqttConfig,
    state: ApplianceState,
) -> MqttMessage:
    payload = json.dumps(
        state.to_dict(appliance_type=device.appliance_type),
        separators=(",", ":"),
    )
    return MqttMessage(f"{mqtt.base_topic}/state", payload)


class MqttPublisher:
    def __init__(self, device: DeviceConfig, config: MqttConfig, *, diagnostics: bool = False):
        self.device = device
        self.config = config
        self.diagnostics = diagnostics
        self._client: Any | None = None
        self._last_state_message: MqttMessage | None = None
        self._lock = RLock()
        self._connect_done = Event()
        self._connection_error: str | None = None
        self._closing = False

    def _on_connect(
        self, client: Any, userdata: Any, flags: Any, reason_code: Any, properties: Any,
    ) -> None:
        # Paho invokes this for the initial connection AND automatic reconnects.
        # Never wait for publishes here: this callback runs on the network thread.
        with self._lock:
            if self._closing:
                return
            if reason_code != 0:
                self._connection_error = f"MQTT connection refused: {reason_code}"
                LOGGER.warning("%s", self._connection_error)
                self._connect_done.set()
                return
            self._connection_error = None
            for message in build_discovery_messages(
                self.device, self.config, include_diagnostics=self.diagnostics,
            ):
                client.publish(message.topic, message.payload, qos=1, retain=message.retain)
            if self._last_state_message is not None:
                message = self._last_state_message
                client.publish(message.topic, message.payload, qos=1, retain=message.retain)
            client.publish(f"{self.config.base_topic}/availability", "online", qos=1, retain=True)
            LOGGER.info("MQTT connected; restored discovery, state, and availability")
            self._connect_done.set()

    def _on_disconnect(
        self, client: Any, userdata: Any, flags: Any, reason_code: Any, properties: Any,
    ) -> None:
        if not self._closing:
            LOGGER.warning("MQTT disconnected (%s); waiting for automatic reconnect", reason_code)

    def _on_connect_fail(self, client: Any, userdata: Any) -> None:
        with self._lock:
            self._connection_error = "Broker unreachable; retrying. Check network and DNS."

    def health(self) -> dict[str, object]:
        """Public connection status, deliberately excluding hostnames and credentials."""
        with self._lock:
            return {
                "enabled": self.config.enabled,
                "connected": bool(self._client and self._client.is_connected()),
                "error": self._connection_error,
            }

    def connect(self, *, background: bool = False) -> None:
        if self._client is not None:
            return
        try:
            import paho.mqtt.client as mqtt_client
        except ImportError as exc:  # pragma: no cover - dependency error path
            raise RuntimeError("paho-mqtt is required when MQTT publishing is enabled") from exc

        client = mqtt_client.Client(
            mqtt_client.CallbackAPIVersion.VERSION2,
            client_id=f"appliance-display-sensor-{self.device.identifier}",
        )
        if self.config.username:
            client.username_pw_set(self.config.username, self.config.password)

        availability_topic = f"{self.config.base_topic}/availability"
        client.will_set(availability_topic, "offline", qos=1, retain=True)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_connect_fail = self._on_connect_fail
        self._closing = False
        self._connection_error = None
        self._connect_done.clear()
        self._client = client
        try:
            if background:
                # Camera/setup must remain usable even when guest-network DNS or
                # broker access is unavailable. Paho retries on its network thread.
                client.reconnect_delay_set(min_delay=2, max_delay=60)
                client.connect_async(self.config.host, self.config.port, keepalive=30)
                client.loop_start()
                return
            client.connect(self.config.host, self.config.port, keepalive=30)
            client.loop_start()
            if not self._connect_done.wait(timeout=10.0):
                raise TimeoutError("Timed out waiting for MQTT connection acknowledgement")
            if self._connection_error is not None:
                raise RuntimeError(self._connection_error)
        except BaseException:
            self.close()
            raise

    def publish_state(self, state: ApplianceState) -> None:
        if self._client is None:
            self.connect()
        message = build_state_message(self.device, self.config, state)
        with self._lock:
            self._last_state_message = message
            client = self._client
            if client is None or self._closing or not client.is_connected():
                # Keep only the latest accepted reading during an outage. The
                # reconnect callback sends it even if the display never changes.
                return
            info = client.publish(message.topic, message.payload, qos=1, retain=message.retain)
        if info.rc == 4:  # MQTT_ERR_NO_CONN: connection dropped during publish.
            return
        info.wait_for_publish(timeout=PUBLISH_TIMEOUT)

    def publish_health(self, payload: dict[str, object]) -> None:
        """Send only a fresh heartbeat, without queueing or replaying outage history."""
        message = json.dumps(payload, separators=(",", ":"), allow_nan=False)
        with self._lock:
            client = self._client
            if not self.diagnostics or client is None or self._closing or not client.is_connected():
                return
            # QoS 0 avoids stale queued messages being delivered after an outage;
            # non-retained state works with HA's expire_after freshness timeout.
            client.publish(f"{self.config.base_topic}/health", message, qos=0, retain=False)

    def close(self) -> None:
        with self._lock:
            if self._client is None:
                return
            client = self._client
            self._closing = True
            self._client = None
            self._last_state_message = None
        try:
            if client.is_connected():
                availability_topic = f"{self.config.base_topic}/availability"
                info = client.publish(availability_topic, "offline", qos=1, retain=True)
                if info.rc == 0:
                    info.wait_for_publish(timeout=PUBLISH_TIMEOUT)
        finally:
            try:
                client.disconnect()
            finally:
                client.loop_stop()

    def publish(self, state: ApplianceState) -> None:
        """Publish one state using a short-lived connection."""

        self.connect()
        try:
            self.publish_state(state)
        finally:
            self.close()

    def __enter__(self) -> "MqttPublisher":
        self.connect()
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()
