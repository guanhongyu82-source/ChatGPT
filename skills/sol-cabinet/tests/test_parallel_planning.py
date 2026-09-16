from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {relative_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


classifier = load_module("sol_classifier_parallel_planning", "scripts/classify_task.py")
CASES = json.loads((ROOT / "tests" / "quality-validation-cases.json").read_text(encoding="utf-8"))


def profile(case_id: str):
    return copy.deepcopy(next(item for item in CASES if item["id"] == case_id)["profile"])


class ParallelPlanningTests(unittest.TestCase):
    def test_qv_03_multi_source_ready_set_activates_parallel_execution_units(self):
        task = profile("QV-03")
        task.update(
            independent_work_units=3,
            parallel_benefit="positive",
            additional_execution_agent_budget=3,
        )

        result = classifier.classify(task)

        self.assertEqual(result["t_level"], 5)
        self.assertEqual(result["agents"]["independent_work_units"], 3)
        self.assertEqual(result["agents"]["additional_execution_agents"], 3)
        self.assertEqual(result["review"]["minimum_independent_reviewers"], 1)
        self.assertEqual(result["agents"]["planned"], 5)

    def test_qv_06_complex_task_uses_bounded_parallel_width_without_changing_t_level(self):
        task = profile("QV-06")
        task.update(
            independent_work_units=4,
            parallel_benefit="positive",
            additional_execution_agent_budget=3,
        )

        result = classifier.classify(task)

        self.assertEqual(result["t_level"], 6)
        self.assertEqual(result["agents"]["independent_work_units"], 4)
        self.assertEqual(result["agents"]["additional_execution_agents"], 3)
        self.assertTrue(result["review"]["required"])

    def test_positive_parallelism_does_not_remove_required_review(self):
        task = profile("QV-02")
        task.update(independent_work_units=2, parallel_benefit="positive")

        result = classifier.classify(task)

        self.assertTrue(result["review"]["required"])
        self.assertGreaterEqual(result["review"]["minimum_independent_reviewers"], 1)
        self.assertEqual(result["agents"]["additional_execution_agents"], 2)

    def test_unknown_parallel_benefit_keeps_work_with_final_lead(self):
        task = profile("QV-03")
        task.update(independent_work_units=3, parallel_benefit="unknown")

        result = classifier.classify(task)

        self.assertEqual(result["agents"]["additional_execution_agents"], 0)
        self.assertTrue(result["agents"]["unallocated_units_stay_with_lead"])

    def test_zero_available_slots_fails_closed_to_no_execution_fanout(self):
        task = profile("QV-03")
        task.update(
            independent_work_units=3,
            parallel_benefit="positive",
            available_subagent_slots=0,
        )

        result = classifier.classify(task)

        self.assertEqual(result["agents"]["additional_execution_agents"], 0)
        self.assertTrue(result["agents"]["review_execution_blocked"])

    def test_qv_01_remains_single_executor_even_under_speed_goal(self):
        task = profile("QV-01")

        result = classifier.classify(task)

        self.assertEqual(result["agents"]["additional_execution_agents"], 0)
        self.assertEqual(result["agents"]["planned"], 1)


if __name__ == "__main__":
    unittest.main()
