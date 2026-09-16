from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_classifier():
    spec = importlib.util.spec_from_file_location(
        "sol_classifier_quality_validation", ROOT / "scripts" / "classify_task.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load classify_task.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


classifier = load_classifier()
CASES = json.loads(
    (ROOT / "tests" / "quality-validation-cases.json").read_text(encoding="utf-8")
)


class QualityValidationTests(unittest.TestCase):
    def test_validation_set_is_exactly_qv_01_to_qv_07(self):
        self.assertEqual(
            [case["id"] for case in CASES],
            [f"QV-{index:02d}" for index in range(1, 8)],
        )

    def test_version_stays_1_5_2_during_validation(self):
        self.assertEqual((ROOT / "VERSION").read_text(encoding="utf-8").strip(), "1.5.2")

    def test_routing_matches_frozen_v1_5_2_baseline(self):
        for case in CASES:
            with self.subTest(case=case["id"]):
                result = classifier.classify(case["profile"])
                expected = case["expected"]
                self.assertEqual(result["t_level"], expected["t_level"])
                self.assertEqual(result["review"]["required"], expected["review"])
                self.assertEqual(
                    result["agents"]["additional_execution_agents"],
                    expected["additional_execution_agents"],
                )
                for route in expected["required_skill_routes"]:
                    self.assertIn(route, result["skill_routes"])
                for route in expected["forbidden_skill_routes"]:
                    self.assertNotIn(route, result["skill_routes"])

    def test_quality_validation_is_observation_only(self):
        dimensions = {
            "understanding",
            "routing",
            "quality",
            "delivery",
            "false_completion",
            "control_weight",
        }
        expected_hot_path_metrics = {
            "activated_rules",
            "loaded_modules",
            "decision_nodes",
            "serial_gates",
            "tool_calls",
            "l2_triggered",
            "duplicate_control_steps",
        }
        for case in CASES:
            with self.subTest(case=case["id"]):
                self.assertEqual(set(case["acceptance"]), dimensions)
                self.assertEqual(set(case["hot_path"]["observe"]), expected_hot_path_metrics)
                self.assertFalse(case["hot_path"]["optimize"])
                self.assertFalse(case["persisted_sensitive_content"])

    def test_qv_01_remains_lightweight(self):
        case = next(item for item in CASES if item["id"] == "QV-01")
        result = classifier.classify(case["profile"])
        self.assertLessEqual(result["t_level"], 2)
        self.assertFalse(result["review"]["required"])
        self.assertEqual(result["skill_routes"], [])
        self.assertEqual(result["agents"]["planned"], 1)

    def test_qv_02_formal_material_is_not_under_governed(self):
        case = next(item for item in CASES if item["id"] == "QV-02")
        result = classifier.classify(case["profile"])
        self.assertGreaterEqual(result["t_level"], 4)
        self.assertTrue(result["review"]["required"])
        self.assertGreaterEqual(result["review"]["minimum_independent_reviewers"], 1)

    def test_qv_07_analysis_only_does_not_enter_file_delivery(self):
        case = next(item for item in CASES if item["id"] == "QV-07")
        result = classifier.classify(case["profile"])
        self.assertNotIn("office-artifact-skill", result["skill_routes"])
        self.assertFalse(case["profile"].get("office_artifact", False))
        self.assertEqual(case["profile"].get("file_count", 0), 0)


if __name__ == "__main__":
    unittest.main()
