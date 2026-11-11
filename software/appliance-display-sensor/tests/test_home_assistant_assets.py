from __future__ import annotations

import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


class BlueprintLoader(yaml.SafeLoader):
    pass


def _input_constructor(loader: BlueprintLoader, node: yaml.Node) -> dict[str, str]:
    return {"input": loader.construct_scalar(node)}


BlueprintLoader.add_constructor("!input", _input_constructor)


class HomeAssistantAssetTests(unittest.TestCase):
    def test_completion_blueprint_uses_running_to_complete_transition(self) -> None:
        path = (
            ROOT
            / "homeassistant"
            / "blueprints"
            / "automation"
            / "appliance_display_sensor"
            / "completion_actions.yaml"
        )
        document = yaml.load(path.read_text(encoding="utf-8"), Loader=BlueprintLoader)

        self.assertEqual(document["blueprint"]["domain"], "automation")
        self.assertEqual(document["triggers"][0]["from"], "running")
        self.assertEqual(document["triggers"][0]["to"], "complete")
        self.assertEqual(document["actions"], {"input": "completion_actions"})


if __name__ == "__main__":
    unittest.main()
