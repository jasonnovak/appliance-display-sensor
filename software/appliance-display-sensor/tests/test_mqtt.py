from __future__ import annotations

import json
import sys
import unittest
from datetime import UTC, datetime
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

from appliance_display_sensor.config import DeviceConfig, MqttConfig
from appliance_display_sensor.models import ApplianceState
from appliance_display_sensor.runtime_health import ALIGNMENT_STATES
from appliance_display_sensor.publishers.mqtt import (
    MqttPublisher,
    build_discovery_messages,
    build_state_message,
)


class HomeAssistantDiscoveryTests(unittest.TestCase):
    def test_device_and_entity_names_are_generic_and_user_configured(self) -> None:
        device = DeviceConfig(
            identifier="upstairs-washer",
            name="Upstairs Washer",
            appliance_type="washer",
        )
        mqtt = MqttConfig(
            enabled=True,
            host="localhost",
            port=1883,
            username=None,
            password=None,
            base_topic="appliance_display_sensor/upstairs-washer",
            discovery_prefix="homeassistant",
        )

        messages = build_discovery_messages(device, mqtt)
        payloads = [json.loads(message.payload) for message in messages]

        self.assertTrue(all(payload["device"]["name"] == "Upstairs Washer" for payload in payloads))
        self.assertEqual(
            {payload["name"] for payload in payloads},
            {
                "Display text",
                "Time remaining",
                "Estimated finish",
                "Status",
                "Reading confidence",
                "Running",
            },
        )
        self.assertFalse(any("dryer" in message.payload.lower() for message in messages))

        state = ApplianceState(
            status="running",
            running=True,
            remaining_minutes=41,
            estimated_finish=datetime(2026, 8, 28, 12, 41, tzinfo=UTC),
            display_text="41",
            confidence=0.98,
        )
        state_message = build_state_message(device, mqtt, state)
        state_payload = json.loads(state_message.payload)

        self.assertEqual(
            state_message.topic,
            "appliance_display_sensor/upstairs-washer/state",
        )
        self.assertTrue(state_message.retain)
        self.assertEqual(state_payload["appliance_type"], "washer")
        self.assertEqual(state_payload["remaining_minutes"], 41)


class MqttRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.device = DeviceConfig(identifier="test-appliance", name="Test Appliance")
        self.config = MqttConfig(
            enabled=True, host="broker", port=1883, username=None, password=None,
            base_topic="appliances/test-appliance", discovery_prefix="homeassistant",
        )
        self.publisher = MqttPublisher(self.device, self.config)
        self.client = Mock()
        self.client.is_connected.return_value = True
        self.receipt = Mock(rc=0)
        self.client.publish.return_value = self.receipt
        self.client.loop_start.side_effect = self.reconnect
        paho = ModuleType("paho")
        mqtt = ModuleType("paho.mqtt")
        client_module = ModuleType("paho.mqtt.client")
        client_module.Client = Mock(return_value=self.client)
        client_module.CallbackAPIVersion = SimpleNamespace(VERSION2=2)
        paho.mqtt = mqtt
        mqtt.client = client_module
        modules = patch.dict(sys.modules, {
            "paho": paho, "paho.mqtt": mqtt, "paho.mqtt.client": client_module,
        })
        modules.start()
        self.addCleanup(modules.stop)
        self.addCleanup(self.publisher.close)

    def reconnect(self, reason_code: int = 0) -> None:
        self.client.on_connect(self.client, None, None, reason_code, None)

    def test_health_entities_are_diagnostics_with_expiry_on_separate_topic(self):
        messages = build_discovery_messages(self.device, self.config, include_diagnostics=True)
        payloads = [json.loads(m.payload) for m in messages]
        diagnostics = [p for p in payloads if p.get("entity_category") == "diagnostic"]
        self.assertEqual(len(diagnostics), 10)
        for payload in diagnostics:
            self.assertEqual(payload["state_topic"], "appliances/test-appliance/health")
            self.assertEqual(payload["expire_after"], 45)
            self.assertEqual(
                payload["availability_topic"], "appliances/test-appliance/availability",
            )
        self.assertEqual(len({p["unique_id"] for p in payloads}), 16)
        original = build_discovery_messages(self.device, self.config)
        self.assertEqual(messages[:6], original)

    def test_alignment_discovery_is_a_passive_expiring_enum_not_a_problem_alarm(self):
        messages = build_discovery_messages(self.device, self.config, include_diagnostics=True)
        message = next(m for m in messages if m.topic.endswith('/mount_alignment/config'))
        payload = json.loads(message.payload)
        self.assertEqual(payload['name'], 'Mount alignment')
        self.assertEqual(payload['device_class'], 'enum')
        self.assertEqual(payload['options'], list(ALIGNMENT_STATES))
        self.assertEqual(payload['unique_id'], 'test-appliance_mount_alignment')
        self.assertEqual(payload['state_topic'], 'appliances/test-appliance/health')
        self.assertEqual(payload['entity_category'], 'diagnostic')
        self.assertEqual(payload['expire_after'], 45)
        self.assertTrue(message.retain)  # Discovery retained; live health is not.
        self.assertNotIn('json_attributes_topic', payload)  # No image/geometry or age churn.
        self.assertNotIn('force_update', payload)
        self.assertNotIn('state_class', payload)
        self.assertIn("default('error')", payload['value_template'])

    def test_health_is_fresh_non_retained_non_blocking_and_never_cached_on_outage(self):
        self.publisher.diagnostics = True
        self.publisher.connect(background=True)
        self.client.publish.reset_mock()
        self.receipt.wait_for_publish.reset_mock()
        self.publisher.publish_health({"camera_status": "live"})
        self.client.publish.assert_called_once_with(
            "appliances/test-appliance/health", '{"camera_status":"live"}', qos=0, retain=False,
        )
        self.receipt.wait_for_publish.assert_not_called()
        self.client.is_connected.return_value = False
        self.client.publish.reset_mock()
        self.publisher.publish_health({"camera_status": "stale"})
        self.client.publish.assert_not_called()
        self.client.is_connected.return_value = True
        self.reconnect()
        self.assertFalse(any(c.args[0].endswith('/health')
                             for c in self.client.publish.call_args_list))
        self.publisher.close()
        self.client.publish.reset_mock()
        self.publisher.publish_health({"camera_status": "live"})
        self.client.publish.assert_not_called()

    def state(self, minutes: int = 5) -> ApplianceState:
        return ApplianceState(
            status="running", running=True, remaining_minutes=minutes,
            estimated_finish=datetime(2026, 9, 20, 12, minutes, tzinfo=UTC),
            display_text=str(minutes), confidence=0.96,
        )

    def test_reconnect_restores_unchanged_state_before_online(self) -> None:
        self.publisher.connect()
        self.publisher.publish_state(self.state())
        self.client.publish.reset_mock()
        self.receipt.wait_for_publish.reset_mock()

        # A broker/Wi-Fi disconnect must recover without another OCR transition.
        self.reconnect()

        calls = self.client.publish.call_args_list
        self.assertEqual(len(calls), 8)  # Six entities, last state, availability.
        self.assertEqual(calls[-2].args[0], "appliances/test-appliance/state")
        self.assertEqual(json.loads(calls[-2].args[1])["remaining_minutes"], 5)
        self.assertEqual(calls[-1].args, ("appliances/test-appliance/availability", "online"))
        self.assertTrue(all(call.kwargs == {"qos": 1, "retain": True} for call in calls))
        # Waiting inside the callback would deadlock the Paho network thread.
        self.receipt.wait_for_publish.assert_not_called()

    def test_background_start_does_not_block_camera_on_broker_failure(self) -> None:
        self.client.is_connected.return_value = False
        self.client.loop_start.side_effect = lambda: self.client.on_connect_fail(self.client, None)
        with patch.object(self.publisher._connect_done, "wait") as wait:
            self.publisher.connect(background=True)
        wait.assert_not_called()
        self.client.connect.assert_not_called()
        self.client.connect_async.assert_called_once_with("broker", 1883, keepalive=30)
        self.publisher.publish_state(self.state(4))
        self.assertFalse(self.publisher.health()["connected"])
        self.assertIn("unreachable", self.publisher.health()["error"])
        self.client.is_connected.return_value = True
        self.reconnect()
        self.assertTrue(self.publisher.health()["connected"])
        self.assertIsNone(self.publisher.health()["error"])
        self.assertEqual(
            json.loads(self.client.publish.call_args_list[-2].args[1])["remaining_minutes"], 4,
        )

    def test_outage_preserves_only_latest_accepted_state(self) -> None:
        self.publisher.connect()
        self.publisher.publish_state(self.state(5))
        self.client.is_connected.return_value = False
        self.client.publish.reset_mock()
        self.publisher.publish_state(self.state(4))
        self.publisher.publish_state(self.state(3))
        self.client.publish.assert_not_called()

        self.client.is_connected.return_value = True
        self.reconnect()
        state_call = self.client.publish.call_args_list[-2]
        self.assertEqual(json.loads(state_call.args[1])["remaining_minutes"], 3)

    def test_disconnect_during_publish_does_not_stop_camera_processing(self) -> None:
        self.publisher.connect()
        self.receipt.rc = 4
        self.receipt.wait_for_publish.reset_mock()
        self.publisher.publish_state(self.state(4))
        self.receipt.wait_for_publish.assert_not_called()
        self.receipt.rc = 0
        self.reconnect()
        state_call = self.client.publish.call_args_list[-2]
        self.assertEqual(json.loads(state_call.args[1])["remaining_minutes"], 4)

    def test_first_connection_sets_retained_will_and_online(self) -> None:
        self.publisher.connect()
        self.client.will_set.assert_called_once_with(
            "appliances/test-appliance/availability", "offline", qos=1, retain=True,
        )
        self.assertEqual(len(self.client.publish.call_args_list), 7)
        self.client.publish.assert_called_with(
            "appliances/test-appliance/availability", "online", qos=1, retain=True,
        )

    def test_rejected_connection_never_announces_online(self) -> None:
        self.client.is_connected.return_value = False
        self.client.loop_start.side_effect = lambda: self.reconnect(135)
        with self.assertRaisesRegex(RuntimeError, "connection refused"):
            self.publisher.connect()
        self.client.publish.assert_not_called()
        self.client.disconnect.assert_called_once()
        self.client.loop_stop.assert_called_once()
        self.assertIsNone(self.publisher._client)

    def test_missing_acknowledgement_times_out_and_cleans_up(self) -> None:
        self.client.loop_start.side_effect = None
        self.client.is_connected.return_value = False
        with (
            patch.object(self.publisher._connect_done, "wait", return_value=False) as wait,
            self.assertRaises(TimeoutError),
        ):
            self.publisher.connect()
        wait.assert_called_once_with(timeout=10.0)
        self.client.disconnect.assert_called_once()
        self.client.loop_stop.assert_called_once()

    def test_close_during_outage_does_not_publish_or_wait(self) -> None:
        self.publisher.connect()
        self.client.is_connected.return_value = False
        self.client.publish.reset_mock()
        self.receipt.wait_for_publish.reset_mock()
        self.publisher.close()
        self.client.publish.assert_not_called()
        self.receipt.wait_for_publish.assert_not_called()
        self.client.disconnect.assert_called_once()
        self.client.loop_stop.assert_called_once()

    def test_close_leaves_offline_even_if_callback_arrives_late(self) -> None:
        self.publisher.connect()
        self.client.publish.reset_mock()
        self.publisher.close()
        self.reconnect()
        self.client.publish.assert_called_once_with(
            "appliances/test-appliance/availability", "offline", qos=1, retain=True,
        )
        self.receipt.wait_for_publish.assert_called_with(timeout=5.0)


if __name__ == "__main__":
    unittest.main()
