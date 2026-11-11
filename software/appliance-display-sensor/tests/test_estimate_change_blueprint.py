"""Estimate-alert YAML and template cases; does not send notifications or emulate HA's loop."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest

import yaml

try:
    from jinja2 import Environment, StrictUndefined
except ImportError:
    Environment = None


class BlueprintLoader(yaml.SafeLoader):
    pass


BlueprintLoader.add_constructor(
    "!input", lambda loader, node: {"input": loader.construct_scalar(node)}
)
PATH = (Path(__file__).resolve().parents[1] / "homeassistant/blueprints/automation/"
        "appliance_display_sensor/estimate_changes.yaml")


def blueprint():
    return yaml.load(PATH.read_text(encoding="utf-8"), Loader=BlueprintLoader)


class EstimateBlueprintStructureTests(unittest.TestCase):
    def test_inputs_are_resolved_and_no_destinations_are_preselected(self):
        doc = blueprint()
        inputs = doc["blueprint"]["input"]
        def visit(value):
            if isinstance(value, dict):
                if set(value) == {"input"}:
                    self.assertIn(value["input"], inputs)
                else:
                    for child in value.values():
                        visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)
        visit(doc)
        for name in ("finish_entity", "status_entity", "camera_entity", "readability_entity",
                     "estimate_actions"):
            self.assertNotIn("default", inputs[name])
        self.assertEqual(doc["actions"][-2]["sequence"], {"input": "estimate_actions"})
        self.assertTrue(doc["actions"][-2]["continue_on_error"])
        self.assertNotIn("device_id:", PATH.read_text())
        self.assertNotIn("notify.", PATH.read_text())

    def test_only_state_changes_trigger_and_cooldown_drops_not_queues(self):
        doc = blueprint()
        self.assertEqual(doc["triggers"], [{"trigger": "state", "entity_id":
                                          {"input": "finish_entity"}, "to": None}])
        self.assertEqual(doc["mode"], "single")
        self.assertEqual(doc["max_exceeded"], "silent")
        self.assertEqual(doc["actions"][-1]["delay"],
                         {"minutes": {"input": "cooldown_minutes"}})
        inputs = doc["blueprint"]["input"]
        self.assertEqual(inputs["change_minutes"]["default"], 10)
        self.assertEqual(inputs["cooldown_minutes"]["default"], 15)
        self.assertEqual(inputs["confirmation_seconds"]["default"], 10)
        self.assertEqual(inputs["change_direction"]["default"], "both")
        self.assertNotIn("last_triggered", PATH.read_text())

    def test_final_rechecks_match_initial_guards(self):
        steps = {step["alias"]: step for step in blueprint()["actions"]}
        for first, second in (("Require a continuous healthy countdown",
                               "Recheck continuity before actions"),
                              ("Require a significant change", "Recheck the latest change")):
            self.assertEqual(steps[first]["value_template"], steps[second]["value_template"])
        wait = steps["Wait briefly or cancel on a fault"]
        self.assertEqual(wait["timeout"], {"seconds": {"input": "confirmation_seconds"}})
        self.assertTrue(wait["continue_on_timeout"])
        self.assertEqual(steps["Read the latest estimate"]["variables"]["estimate_finish"],
                         "{{ states(finish_entity) }}")


class StateStore(dict):
    def __call__(self, entity):
        return self[entity].state if entity in self else "unknown"


def timestamp(value, default=None):
    try:
        if isinstance(value, datetime):
            return value.timestamp()
        if isinstance(value, (int, float)):
            return float(value)
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError, AttributeError):
        return default


@unittest.skipIf(Environment is None, "Install dev extras for Jinja template checks")
class EstimateBlueprintTemplateTests(unittest.TestCase):
    def setUp(self):
        self.steps = {step["alias"]: step for step in blueprint()["actions"]}
        self.env = Environment(undefined=StrictUndefined)
        self.clock = datetime(2026, 10, 18, 19, 0, tzinfo=timezone.utc)
        self.states = StateStore()
        for entity, value in (("status", "running"), ("camera", "live"),
                              ("readability", "readable"), ("finish", self.finish(40))):
            self.states[f"sensor.{entity}"] = SimpleNamespace(
                state=value, last_changed=self.clock - timedelta(minutes=5))
        self.context = {
            "finish_entity": "sensor.finish", "status_entity": "sensor.status",
            "camera_entity": "sensor.camera", "readability_entity": "sensor.readability",
            "states": self.states, "is_state": lambda entity, value: self.states(entity) == value,
            "has_value": lambda entity: self.states(entity) not in {"unknown", "unavailable"},
            "as_timestamp": timestamp, "now": lambda: self.clock,
            "as_datetime": datetime.fromisoformat, "as_local": lambda value: value,
            "device_label": "Dryer", "change_minutes": 10, "change_direction": "both",
            "previous_finish": self.finish(30), "estimate_finish": self.finish(40),
            "comparison_started": (self.clock - timedelta(minutes=1)).timestamp(),
        }

    def finish(self, minutes):
        return (self.clock + timedelta(minutes=minutes)).isoformat()

    def render(self, template, **variables):
        return self.env.from_string(template).render(self.context | variables).strip()

    def guard(self, name, **variables):
        return self.render(self.steps[name]["value_template"], **variables).lower() == "true"

    def trigger(self, old=None, new=None):
        return SimpleNamespace(
            platform="state",
            from_state=SimpleNamespace(state=old or self.finish(30),
                                       last_changed=self.clock - timedelta(minutes=1)),
            to_state=SimpleNamespace(state=new or self.finish(40)),
        )

    def test_manual_actions_and_creation_removal_are_not_alerts(self):
        name = "Require a real timestamp transition"
        self.assertFalse(self.guard(name))
        for trigger in (None, {}, SimpleNamespace(platform="event"),
                        SimpleNamespace(platform="state"),
                        SimpleNamespace(platform="state", from_state=None, to_state=None)):
            self.assertFalse(self.guard(name, trigger=trigger))
        self.assertTrue(self.guard(name, trigger=self.trigger()))
        self.assertFalse(self.guard(name, trigger=self.trigger(self.finish(30), self.finish(30))))
        for value in ("unknown", "unavailable", "bad time"):
            self.assertFalse(self.guard(name, trigger=self.trigger(value)))
            self.assertFalse(self.guard(name, trigger=self.trigger(new=value)))

    def test_normal_ticks_and_small_rounding_drift_are_ignored(self):
        # 30m at 19:00 and 29m at 19:01 both predict 19:30. Small sampling jitter is allowed.
        for shift in (0, 0.02, -0.02, 1, -1, 9.99, -9.99):
            self.assertFalse(self.guard("Require a significant change",
                                        estimate_finish=self.finish(30 + shift)))

    def test_both_directions_exact_boundary_and_direction_filter(self):
        for shift in (-20, -10, 10, 20):
            for direction in ("both", "earlier", "later"):
                expected = direction == "both" or (shift > 0) == (direction == "later")
                self.assertEqual(self.guard("Require a significant change",
                                           estimate_finish=self.finish(30 + shift),
                                           change_direction=direction), expected)
        self.assertFalse(self.guard("Require a significant change", change_direction="invalid"))
        self.assertFalse(self.guard("Require a significant change", change_minutes=11))

    def test_absolute_timestamps_avoid_timezone_and_midnight_confusion(self):
        self.assertFalse(self.guard("Require a significant change",
                                    previous_finish="2026-10-18T23:55:00+00:00",
                                    estimate_finish="2026-10-18T18:55:00-05:00"))
        self.assertTrue(self.guard("Require a significant change",
                                   previous_finish="2026-10-18T23:55:00+00:00",
                                   estimate_finish="2026-10-19T00:10:00+00:00"))

    def test_missing_invalid_and_unbounded_dates_are_rejected(self):
        for value in (None, "unknown", "unavailable", "", "bad", float("inf"), float("nan"),
                      "1990-01-01T00:00:00+00:00", "2100-01-01T00:00:00+00:00"):
            self.assertFalse(self.guard("Require a significant change", estimate_finish=value))
            self.assertFalse(self.guard("Require a significant change", previous_finish=value))

    def test_health_faults_blank_complete_and_calibration_block_comparison(self):
        name = "Require a continuous healthy countdown"
        self.assertTrue(self.guard(name))
        for entity, values in (("status", ("complete", "unknown", "unavailable")),
                               ("camera", ("waiting", "stale", "error", "unavailable")),
                               ("readability", ("blank", "unreadable", "calibrating", "stale"))):
            state = self.states[f"sensor.{entity}"]
            original = state.state
            for value in values:
                state.state = value
                self.assertFalse(self.guard(name), (entity, value))
            state.state = original

    def test_recent_start_or_recovery_cannot_reuse_old_baseline(self):
        for entity in ("status", "camera", "readability"):
            state = self.states[f"sensor.{entity}"]
            original = state.last_changed
            state.last_changed = self.clock - timedelta(seconds=30)
            self.assertFalse(self.guard("Require a continuous healthy countdown"))
            # Older than 60s, but recovery occurred after the old estimate: still unsafe.
            state.last_changed = self.clock - timedelta(seconds=90)
            older_baseline = (self.clock - timedelta(minutes=2)).timestamp()
            self.assertFalse(self.guard("Require a continuous healthy countdown",
                                        comparison_started=older_baseline))
            state.last_changed = original

    def test_confirmation_can_cancel_on_fault_even_if_it_later_recovers(self):
        condition = self.steps["Wait briefly or cancel on a fault"]["wait_for_trigger"][0]
        self.assertEqual(self.render(condition["value_template"]), "False")
        for entity, fault in (("status", "complete"), ("camera", "error"),
                              ("readability", "blank"), ("finish", "unavailable")):
            state = self.states[f"sensor.{entity}"]
            previous = state.state
            state.state = fault
            self.assertEqual(self.render(condition["value_template"]), "True")
            state.state = previous
        self.assertTrue(self.guard("Stop if the wait was cancelled",
                                   wait=SimpleNamespace(trigger=None)))
        self.assertFalse(self.guard("Stop if the wait was cancelled",
                                    wait=SimpleNamespace(trigger={"platform": "template"})))

    def test_latest_estimate_not_trigger_snapshot_is_used_after_wait(self):
        self.assertTrue(self.guard("Require a significant change"))
        self.states["sensor.finish"].state = self.finish(31)
        value = self.render(self.steps["Read the latest estimate"]["variables"]["estimate_finish"])
        self.assertFalse(self.guard("Recheck the latest change", estimate_finish=value))
        self.states["sensor.finish"].state = self.finish(45)
        value = self.render(self.steps["Read the latest estimate"]["variables"]["estimate_finish"])
        self.assertTrue(self.guard("Recheck the latest change", estimate_finish=value))

    def test_message_is_estimate_not_completion_and_exposes_action_variables(self):
        for minute, direction in ((40, "later"), (20, "earlier")):
            variables = {"estimate_finish": self.finish(minute)}
            for key, template in self.steps["Describe the change"]["variables"].items():
                variables[key] = self.render(template, **variables)
            self.assertEqual(variables["estimate_direction"], direction)
            self.assertEqual(float(variables["estimate_change_minutes"]), 10)
            message = self.render(self.steps["Build the message"]["variables"]["estimate_message"],
                                  **variables)
            self.assertIn("Dryer now estimates", message)
            self.assertIn(direction, message)
            self.assertIn("not a completion alert", message)


if __name__ == "__main__":
    unittest.main()
