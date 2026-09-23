from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def load_module(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {relative_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


classifier = load_module("sol_classifier_quality_validation", "scripts/classify_task.py")
office = load_module("sol_office_quality_validation", "scripts/inspect_office.py")
delivery_gate = load_module("sol_delivery_quality_validation", "scripts/delivery_gate.py")
CASES = json.loads(
    (ROOT / "tests" / "quality-validation-cases.json").read_text(encoding="utf-8")
)


class QualityValidationTests(unittest.TestCase):
    def test_validation_set_is_exactly_qv_01_to_qv_07(self):
        self.assertEqual(
            [case["id"] for case in CASES],
            [f"QV-{index:02d}" for index in range(1, 8)],
        )

    def test_version_file_uses_supported_stable_or_lab_format(self):
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        self.assertRegex(version, r"^\d+\.\d+\.\d+(?:-lab\.\d+)?$")

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

    def test_qv_04_word_source_is_preserved_during_inspection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source.docx"
            with zipfile.ZipFile(source, "w") as package:
                package.writestr(
                    "word/document.xml",
                    f'<w:document xmlns:w="{W}"><w:body><w:p><w:r><w:t>'
                    "原稿内容保持不变"
                    "</w:t></w:r></w:p></w:body></w:document>",
                )
            before = source.read_bytes()
            result = office.inspect(source)
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(result["source_sha256"], hashlib.sha256(before).hexdigest())
            self.assertEqual([record["text"] for record in result["records"]], ["原稿内容保持不变"])

    def test_qv_05_excel_source_preserves_structure_and_formula(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source.xlsx"
            with zipfile.ZipFile(source, "w") as package:
                package.writestr(
                    "xl/workbook.xml",
                    f'<workbook xmlns="{office.X[1:-1]}" xmlns:r="{office.R[1:-1]}">'
                    '<sheets><sheet name="监督台账" sheetId="1" r:id="rId1"/></sheets></workbook>',
                )
                package.writestr(
                    "xl/_rels/workbook.xml.rels",
                    f'<Relationships xmlns="{office.P[1:-1]}">'
                    '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/>'
                    "</Relationships>",
                )
                package.writestr(
                    "xl/worksheets/sheet1.xml",
                    f'<worksheet xmlns="{office.X[1:-1]}"><sheetData>'
                    '<row r="1"><c r="A1" t="inlineStr"><is><t>事项</t></is></c>'
                    '<c r="B1" t="inlineStr"><is><t>状态</t></is></c>'
                    '<c r="C1" t="inlineStr"><is><t>数量</t></is></c></row>'
                    '<row r="2"><c r="A2" t="inlineStr"><is><t>示例事项</t></is></c>'
                    '<c r="B2" t="inlineStr"><is><t>未完成</t></is></c><c r="C2"><v>2</v></c>'
                    '<c r="D2"><f>SUM(C2:C2)</f></c></row>'
                    "</sheetData></worksheet>",
                )
            before = source.read_bytes()
            result = office.inspect(source)
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(result["coverage"]["sheets"][0]["name"], "监督台账")
            formulas = [record.get("formula") for record in result["records"] if record.get("formula")]
            self.assertEqual(formulas, ["SUM(C2:C2)"])
            states = [record.get("state") for record in result["records"] if record.get("state")]
            self.assertIn("incomplete", states)

    def test_qv_06_complex_delivery_cannot_pass_with_a_missing_required_artifact(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report = root / "2026-09-16_报告_综合分析_v1.docx"
            ledger = root / "2026-09-16_台账_问题清单_v1.xlsx"
            report.write_bytes(b"report-candidate")
            ledger.write_bytes(b"ledger-candidate")

            task_card_path = root / "task-card.json"
            task_card = {
                "task_instance_id": "qv06-task",
                "deliverables": [
                    {
                        "artifact_id": "report",
                        "required": True,
                        "format": ".docx",
                        "target_role": "final",
                        "target_directory": str(root),
                        "filename_override": None,
                    },
                    {
                        "artifact_id": "ledger",
                        "required": True,
                        "format": ".xlsx",
                        "target_role": "final",
                        "target_directory": str(root),
                        "filename_override": None,
                    },
                ],
            }
            task_card_path.write_text(json.dumps(task_card, ensure_ascii=False), encoding="utf-8")

            artifact_hashes = {
                str(report): hashlib.sha256(report.read_bytes()).hexdigest(),
                str(ledger): hashlib.sha256(ledger.read_bytes()).hexdigest(),
            }
            review_path = root / "review.json"
            review = {
                "reviewer_id": "reviewer-qv06",
                "author_id": "lead-qv06",
                "verdict": "PASS",
                "must_fix": [],
                "candidate_sha256": artifact_hashes,
                "source_ref": "tool:reviewer-qv06/message:result-qv06",
            }
            review_path.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")

            contract = {
                "task_id": "qv06-task",
                "t_level": 6,
                "formal_normative_additions": False,
                "opening_notice": True,
                "summary_present": True,
                "incident_present": False,
                "timing": {
                    "started_at": "2026-09-16T01:00:00Z",
                    "ended_at": "2026-09-16T01:05:00Z",
                    "basis": "quality-validation-fixture",
                },
                "storage": {
                    "output_root": str(root),
                    "archive_status": "deferred",
                    "archive_reason": "temporary quality-validation fixture",
                },
                "task_card": {
                    "path": str(task_card_path),
                    "sha256": hashlib.sha256(task_card_path.read_bytes()).hexdigest(),
                },
                "artifacts": [
                    {
                        "artifact_id": "report",
                        "role": "final",
                        "path": str(report),
                        "sha256": artifact_hashes[str(report)],
                    },
                    {
                        "artifact_id": "ledger",
                        "role": "final",
                        "path": str(ledger),
                        "sha256": artifact_hashes[str(ledger)],
                    },
                ],
                "reviews": [
                    {
                        **review,
                        "evidence_path": str(review_path),
                        "evidence_sha256": hashlib.sha256(review_path.read_bytes()).hexdigest(),
                    }
                ],
                "retention": {
                    "process_root": None,
                    "temporary_files": [],
                    "retained_reason": {
                        str(task_card_path): "locked expected artifact contract",
                        str(review_path): "required review evidence",
                    },
                },
            }

            # Legacy fixture checks Expected/Actual only; deferred archive is never FINAL PASS.
            self.assertEqual(delivery_gate.check_components(contract)["state"], "PASS")
            self.assertEqual(delivery_gate.check(contract)["state"], "FAIL")
            contract["artifacts"] = [contract["artifacts"][0]]
            self.assertEqual(delivery_gate.check_components(contract)["state"], "FAIL")

    def test_qv_07_analysis_only_does_not_enter_file_delivery(self):
        case = next(item for item in CASES if item["id"] == "QV-07")
        result = classifier.classify(case["profile"])
        self.assertNotIn("office-artifact-skill", result["skill_routes"])
        self.assertFalse(case["profile"].get("office_artifact", False))
        self.assertEqual(case["profile"].get("file_count", 0), 0)


if __name__ == "__main__":
    unittest.main()
