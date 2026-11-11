"""Blueprint structure and template truth tables, without sending HA actions."""
import unittest
from pathlib import Path
from types import SimpleNamespace

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
        "appliance_display_sensor/health_alerts.yaml")


def blueprint():
    return yaml.load(PATH.read_text(encoding="utf-8"), Loader=BlueprintLoader)


def android_blueprint():
    return yaml.load(PATH.with_name("health_alerts_android.yaml").read_text(encoding="utf-8"),
                     Loader=BlueprintLoader)


class AndroidHealthBlueprintTests(unittest.TestCase):
    def test_priority_delivery_is_in_both_fault_branches(self):
        doc = android_blueprint()
        inputs = doc["blueprint"]["input"]
        self.assertNotIn("default", inputs["notify_device"])
        self.assertEqual(inputs["notify_device"]["selector"]["device"]["filter"],
                         [{"integration": "mobile_app"}])
        self.assertEqual(inputs["notification_ttl"]["default"], 0)
        self.assertEqual(inputs["health_actions"]["default"], [])
        for branch in doc["actions"][0]["choose"]:
            action = branch["sequence"][1]
            self.assertEqual(action["device_id"], {"input": "notify_device"})
            self.assertEqual(action["domain"], "mobile_app")
            self.assertEqual(action["type"], "notify")
            self.assertEqual(action["data"],
                             {"priority": "high", "ttl": {"input": "notification_ttl"}})
            self.assertEqual(action["message"], "{{ health_message }}")
            self.assertEqual(action["title"], "{{ health_title }}")
            self.assertTrue(action["continue_on_error"])
            self.assertEqual(branch["sequence"][-1], {"sequence": {"input": "health_actions"}})

    def test_fault_logic_and_messages_match_generic_blueprint(self):
        generic, android = blueprint(), android_blueprint()
        for key in ("triggers", "trigger_variables", "variables", "conditions", "mode", "max"):
            self.assertEqual(android[key], generic[key], key)
        branches = zip(generic["actions"][0]["choose"], android["actions"][0]["choose"])
        for original, phone in branches:
            self.assertEqual(phone["conditions"], original["conditions"])
            self.assertEqual(phone["sequence"][0], original["sequence"][0])

    def test_no_forced_sound_or_unrequested_destinations(self):
        doc = android_blueprint()
        def check(node):
            if isinstance(node, dict):
                if set(node) == {"input"}:
                    self.assertIn(node["input"], doc["blueprint"]["input"])
                for key, value in node.items():
                    self.assertNotIn(key, {"channel", "importance", "push", "media_stream"})
                    check(value)
            elif isinstance(node, list):
                for value in node:
                    check(value)
        check(doc)


class HealthBlueprintStructureTests(unittest.TestCase):
    def test_all_inputs_defined_and_actions_are_user_selected(self):
        doc = blueprint()
        inputs = doc["blueprint"]["input"]
        def check(value):
            if isinstance(value, dict):
                if set(value) == {"input"}:
                    self.assertIn(value["input"], inputs)
                else:
                    for child in value.values():
                        check(child)
            elif isinstance(value, list):
                for child in value:
                    check(child)
        check(doc)
        self.assertNotIn("default", inputs["health_actions"])
        for branch in doc["actions"][0]["choose"]:
            self.assertEqual(branch["sequence"][-1], {"sequence": {"input": "health_actions"}})

    def test_fault_holds_use_templates_not_periodic_polling(self):
        doc = blueprint()
        self.assertEqual([item["trigger"] for item in doc["triggers"]], ["template", "template"])
        self.assertEqual(doc["triggers"][0]["for"], {"seconds": {"input": "camera_wait_seconds"}})
        self.assertEqual(doc["triggers"][1]["for"], {"seconds": {"input": "reading_wait_seconds"}})
        self.assertEqual(doc["blueprint"]["input"]["camera_wait_seconds"]["default"], 120)
        self.assertEqual(doc["blueprint"]["input"]["reading_wait_seconds"]["default"], 60)
        self.assertEqual(doc["mode"], "parallel")
        self.assertEqual(doc["max"], 2)


@unittest.skipIf(Environment is None, "Install dev extras for Jinja template checks")
class HealthBlueprintTemplateTests(unittest.TestCase):
    def setUp(self):
        self.doc = blueprint()
        self.env = Environment(undefined=StrictUndefined)

    def render(self, template, camera="live", problem="off", **variables):
        states = {"sensor.camera": camera, "binary_sensor.problem": problem}
        context = dict(watched_camera="sensor.camera", watched_problem="binary_sensor.problem",
                       camera_entity="sensor.camera", problem_entity="binary_sensor.problem",
                       camera_enabled=True, reading_enabled=True, device_label="Dryer",
                       states=lambda entity: states.get(entity, "unknown"),
                       is_state=lambda entity, value: states.get(entity) == value)
        context.update(variables)
        return self.env.from_string(template).render(context).strip()

    def test_camera_fault_states_form_one_continuous_predicate(self):
        template = self.doc["triggers"][0]["value_template"]
        for camera in ("stale", "error", "unavailable", "unknown"):
            self.assertEqual(self.render(template, camera=camera), "True")
        for camera in ("live", "waiting"):
            self.assertEqual(self.render(template, camera=camera), "False")
        self.assertEqual(self.render(template, camera="stale", camera_enabled=False), "False")

    def test_reading_alert_needs_live_camera_and_confirmed_problem(self):
        template = self.doc["triggers"][1]["value_template"]
        for camera in ("live", "waiting", "stale", "error", "unavailable", "unknown"):
            for problem in ("on", "off", "unknown", "unavailable"):
                expected = str(camera == "live" and problem == "on")
                self.assertEqual(self.render(template, camera=camera, problem=problem), expected)
        self.assertEqual(self.render(template, problem="on", reading_enabled=False), "False")

    def test_actions_recheck_state_and_manual_run_is_safe(self):
        camera_branch, reading_branch = self.doc["actions"][0]["choose"]
        for branch, reason in ((camera_branch, "camera_or_connection"),
                               (reading_branch, "unreadable")):
            template = branch["conditions"][0]["value_template"]
            self.assertEqual(self.render(template), "False")  # No trigger on manual Run actions.
            trigger = SimpleNamespace(id=reason)
            self.assertEqual(self.render(template, trigger=trigger), "False")  # recovered
            self.assertEqual(self.render(template, camera="stale" if branch is camera_branch
                                         else "live", problem="on", trigger=trigger), "True")
            self.assertEqual(self.render(template, camera="stale", problem="on",
                                         trigger=SimpleNamespace(id="other")), "False")

    def test_messages_do_not_claim_appliance_completion(self):
        for branch in self.doc["actions"][0]["choose"]:
            values = branch["sequence"][0]["variables"]
            message = self.render(values["health_message"])
            self.assertIn("Dryer", message)
            self.assertIn("does not", message)
            self.assertIn(values["health_reason"], {"unreadable", "camera_or_connection"})
            self.assertIn("Dryer", self.render(values["health_title"]))


if __name__ == "__main__":
    unittest.main()
