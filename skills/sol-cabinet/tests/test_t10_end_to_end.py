from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import archive_originals
import classify_task
import delivery_gate
import evolve
import inspect_office
import inspect_office_batch

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def make_docx(path: Path, text: str) -> None:
    with zipfile.ZipFile(path, "w") as package:
        package.writestr(
            "word/document.xml",
            f'<w:document xmlns:w="{W}"><w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>',
        )


def make_xlsx(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as package:
        package.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{inspect_office.X[1:-1]}" xmlns:r="{inspect_office.R[1:-1]}">'
            '<sheets><sheet name="验证台账" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        package.writestr(
            "xl/_rels/workbook.xml.rels",
            f'<Relationships xmlns="{inspect_office.P[1:-1]}">'
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/>'
            "</Relationships>",
        )
        package.writestr(
            "xl/worksheets/sheet1.xml",
            f'<worksheet xmlns="{inspect_office.X[1:-1]}"><sheetData>'
            '<row r="1"><c r="A1" t="inlineStr"><is><t>阶段</t></is></c>'
            '<c r="B1" t="inlineStr"><is><t>完成</t></is></c></row>'
            "</sheetData></worksheet>",
        )


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_review(work: Path, reviewer: str, scope: str, artifact_ids: list[str], hashes: dict[str, str]) -> dict:
    review = {
        "reviewer_id": reviewer,
        "author_id": "final-lead",
        "verdict": "PASS",
        "must_fix": [],
        "review_scope": scope,
        "artifact_ids": artifact_ids,
        "candidate_sha256": hashes,
        "source_ref": f"tool:{reviewer}/message:lab-result",
    }
    path = work / f"{reviewer}.json"
    path.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")
    review["evidence_path"] = str(path)
    review["evidence_sha256"] = sha(path)
    return review


class T10EndToEndLaboratoryTests(unittest.TestCase):
    def test_t10_full_chain_reaches_delivery_observation_and_stop_boundary(self):
        if sys.platform != "darwin":
            self.skipTest("T10 laboratory chain requires the target-compatible macOS maintenance boundary")
        scratch = Path("/Users/macbook/ChatGPT/.scratch")
        self.assertTrue(scratch.is_dir(), "canonical scratch root required")

        profile = {
            "file_count": 4,
            "input_size_kb": 800,
            "deliverable_count": 2,
            "steps": 12,
            "complexity": 3,
            "multi_angle": True,
            "multi_source": True,
            "fact_risk": True,
            "formal_publish": True,
            "office_artifact": True,
            "multiple_deliverables": True,
            "multi_stage": True,
            "long_running": True,
            "system_build": True,
            "needs_review": True,
            "independent_work_units": 4,
            "parallel_benefit": "positive",
            "available_subagent_slots": 6,
            "additional_execution_agent_budget": 3,
            "materials_state": "READY",
        }
        classification = classify_task.classify(profile)
        self.assertEqual(classification["t_level"], 10)
        self.assertEqual(classification["review"]["minimum_independent_reviewers"], 2)
        self.assertEqual(classification["agents"]["additional_execution_agents"], 3)
        self.assertTrue(classification["execution"]["current_stage_may_proceed"])

        with tempfile.TemporaryDirectory(dir=scratch) as temp_dir:
            base = Path(temp_dir).resolve()
            task = base / "task"
            task.mkdir()
            sources = base / "sources"
            sources.mkdir()
            outputs = task / "outputs"
            outputs.mkdir()
            work = task / "work"
            work.mkdir()

            source_text = sources / "材料.txt"
            source_docx = sources / "材料.docx"
            source_xlsx = sources / "材料.xlsx"
            source_pdf = sources / "材料.pdf"
            source_text.write_text("实验室 T10 来源文本。", encoding="utf-8")
            make_docx(source_docx, "实验室 T10 Word 来源")
            make_xlsx(source_xlsx)
            source_pdf.write_bytes(b"%PDF-1.4\n% laboratory-source-only\n%%EOF\n")
            input_paths = [source_text, source_docx, source_xlsx, source_pdf]
            input_hashes = {str(path): sha(path) for path in input_paths}

            archived = archive_originals.archive_originals(
                task,
                [("正文", source_text), ("Word", source_docx), ("Excel", source_xlsx), ("PDF", source_pdf)],
                allow_test_output=True,
            )
            self.assertEqual(archived["state"], "PASS")
            self.assertEqual(archived["archived_count"], 4)
            self.assertEqual({str(path): sha(path) for path in input_paths}, input_hashes)
            manifest_path = task / "00_原稿" / "原稿清单.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["archive_state"], "PASS")
            self.assertEqual(len(manifest["files"]), 4)
            self.assertTrue(all(item["byte_identical"] and item["source_unmodified"] for item in manifest["files"]))
            self.assertEqual(len({item["source_sha256"] for item in manifest["files"]}), 4)

            doc = outputs / "2026-09-16_报告_实验室验证_v1.docx"
            ledger = outputs / "2026-09-16_台账_验证清单_v1.xlsx"
            make_docx(doc, "T10 完整链路实验室成品")
            make_xlsx(ledger)
            output_hashes_before = {str(doc): sha(doc), str(ledger): sha(ledger)}
            inspection = inspect_office_batch.inspect_many([doc, ledger], max_workers=1)
            self.assertEqual(inspection["parse_status"], "PASS")
            self.assertEqual(inspection["execution_mode"], "serial")
            self.assertTrue(all(item["result"]["source_unchanged"] for item in inspection["items"]))
            self.assertEqual({str(doc): sha(doc), str(ledger): sha(ledger)}, output_hashes_before)

            task_card = task / "task-card.json"
            card = {
                "task_instance_id": "task-" + "a" * 32,
                "deliverables": [
                    {
                        "artifact_id": "report",
                        "required": True,
                        "format": ".docx",
                        "target_role": "final",
                        "target_directory": str(outputs),
                        "filename_override": None,
                    },
                    {
                        "artifact_id": "ledger",
                        "required": True,
                        "format": ".xlsx",
                        "target_role": "final",
                        "target_directory": str(outputs),
                        "filename_override": None,
                    },
                ],
                "source_archive": {
                    "source_files_present": True,
                    "source_asset_count": 4,
                    "required": True,
                    "state": "PASS",
                    "task_archive_relative_path": "00_原稿",
                    "manifest_relative_path": "00_原稿/原稿清单.json",
                    "verified_count": 4,
                    "gate_code": "PASS",
                },
                "resource_plan": {
                    "independent_units": ["txt", "docx", "xlsx", "pdf"],
                    "parallel_benefit": "positive",
                    "available_subagent_slots": 6,
                    "additional_execution_agent_budget": 3,
                    "quota_data": "lab-fixture",
                },
                "evidence_pack": {
                    "sources": [
                        {
                            "source_id": f"source-{index+1}",
                            "source_sha256": item["source_sha256"],
                            "locator_scheme": "format-native",
                        }
                        for index, item in enumerate(manifest["files"])
                    ],
                    "coverage": ["txt-body", "docx-structure", "xlsx-structure", "pdf-archived-source"],
                    "facts": [],
                    "conflicts": [],
                    "unread": ["pdf-content-extraction-not-mechanically-tested-by-repository-fixture"],
                },
            }
            task_card.write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")

            all_hashes = {str(doc): sha(doc), str(ledger): sha(ledger)}
            doc_hash = {str(doc): all_hashes[str(doc)]}
            ledger_hash = {str(ledger): all_hashes[str(ledger)]}
            reviews = [
                write_review(work, "reviewer-doc-1", "artifact", ["report"], doc_hash),
                write_review(work, "reviewer-doc-2", "artifact", ["report"], doc_hash),
                write_review(work, "reviewer-ledger-1", "artifact", ["ledger"], ledger_hash),
                write_review(work, "reviewer-ledger-2", "artifact", ["ledger"], ledger_hash),
                write_review(work, "reviewer-cross", "cross_artifact", ["report", "ledger"], all_hashes),
            ]
            retained = {review["evidence_path"]: "T10 required independent review evidence" for review in reviews}
            contract = {
                "task_id": card["task_instance_id"],
                "t_level": 10,
                "formal_normative_additions": True,
                "opening_notice": True,
                "summary_present": True,
                "incident_present": False,
                "timing": {
                    "started_at": "2026-09-16T04:00:00+00:00",
                    "ended_at": "2026-09-16T04:10:00+00:00",
                    "basis": "synthetic-laboratory-chain",
                },
                "storage": {
                    "output_root": str(outputs),
                    "archive_status": "deferred",
                    "archive_reason": "laboratory fixture keeps the task tree until test cleanup",
                },
                "task_card": {"path": str(task_card), "sha256": sha(task_card)},
                "artifacts": [
                    {"artifact_id": "report", "role": "final", "path": str(doc), "sha256": sha(doc)},
                    {"artifact_id": "ledger", "role": "final", "path": str(ledger), "sha256": sha(ledger)},
                ],
                "reviews": reviews,
                "retention": {
                    "process_root": str(work),
                    "temporary_files": [],
                    "retained_reason": retained,
                },
            }
            gate = delivery_gate.check(contract)
            self.assertEqual(gate["state"], "PASS", gate["issues"])

            evolution_root = task / "evolution-fixture"
            evidence_dir = evolution_root / "capture"
            evidence_dir.mkdir(parents=True)
            evidence_id = "EV-" + "b" * 32
            task_id = "task-" + "c" * 32
            artifact = evidence_dir / "serial-wait.log"
            artifact.write_text("SYNTHETIC T10 laboratory scheduling witness; no business content.\n", encoding="utf-8")
            capture = {
                "evidence_id": evidence_id,
                "task_instance_id": task_id,
                "failure_type": "serial-wait",
                "artifact_path": artifact.name,
                "artifact_sha256": sha(artifact),
                "source": "executor-capture",
                "sanitized": True,
            }
            (evidence_dir / f"{evidence_id}.json").write_text(json.dumps(capture), encoding="utf-8")
            incident = {
                "incident_id": "INC-" + "d" * 32,
                "time": "2026-09-16T04:11:00+00:00",
                "failure_type": "serial-wait",
                "cause": "execution_failure",
                "impact": "ordinary",
                "evidence": [evidence_id],
                "capabilities": ["orchestration"],
                "repeated": False,
                "hits": 1,
                "permission": "record",
            }
            recorded = evolve.record(incident, root=evolution_root, evidence=evidence_dir)
            self.assertEqual(recorded, {"status": "RECORDED", "EVO": None})
            status = evolve.status(evolution_root)
            self.assertEqual(status["status"], "NEEDS_ATTENTION")
            self.assertEqual(status["pending_incident_count"], 1)
            self.assertEqual(status["incidents"][0]["failure_type"], "serial-wait")
            self.assertFalse(list((evolution_root / "memory-evolution" / "proposals").glob("EVO-*.json")))

            stopped = classify_task.classify({**profile, "stage_complete": True, "next_stage_authorized": True})
            self.assertEqual(stopped["t_level"], 10)
            self.assertFalse(stopped["execution"]["current_stage_may_proceed"])
            self.assertEqual(stopped["execution"]["next_action"], "reclassify-authorized-next-stage")


if __name__ == "__main__":
    unittest.main()
