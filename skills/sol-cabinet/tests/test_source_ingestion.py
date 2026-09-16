from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import source_ingestion


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SourceIngestionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.task = Path(self.temp.name).resolve() / "task"
        self.archive = self.task / "00_原稿"
        self.archive.mkdir(parents=True)

        self.paths = [
            self.archive / "原稿_正文_材料.txt",
            self.archive / "原稿_Word_材料.docx",
            self.archive / "原稿_Excel_材料.xlsx",
            self.archive / "原稿_补充_补充.txt",
        ]
        self.paths[0].write_text("项目=青山工程\n预算=100\n", encoding="utf-8")
        self.paths[1].write_bytes(b"docx-placeholder")
        self.paths[2].write_bytes(b"xlsx-placeholder")
        self.paths[3].write_text("期限=2026-12-31\n", encoding="utf-8")

        self.manifest = self.archive / "原稿清单.json"
        files = []
        roles = ["正文", "Word", "Excel", "补充"]
        for role, path in zip(roles, self.paths):
            digest = sha(path)
            files.append(
                {
                    "source_role": role,
                    "source_name": path.name.split("_", 2)[-1],
                    "archived_relative_path": str(path.relative_to(self.task)),
                    "source_sha256": digest,
                    "archived_sha256": digest,
                    "byte_identical": True,
                    "source_unmodified": True,
                    "status": "UNMODIFIED_BYTE_COPY",
                }
            )
        self.manifest.write_text(
            json.dumps({"schema_version": 1, "archive_state": "PASS", "files": files}, ensure_ascii=False),
            encoding="utf-8",
        )

    def fake_office_inspect(self, path: Path):
        path = Path(path)
        if path.suffix == ".docx":
            records = [{"locator": "word/document.xml:p[1]", "text": "责任部门=综合部"}]
        elif path.suffix == ".xlsx":
            records = [
                {"locator": "验证台账!A1", "text": "预算=120"},
                {"locator": "验证台账!A2", "text": "阶段=完成"},
            ]
        else:
            raise AssertionError(path)
        return {
            "parse_status": "PASS",
            "source_sha256": sha(path),
            "records": records,
        }

    def test_same_wave_ingestion_builds_traceable_evidence_and_conflicts(self):
        with mock.patch.object(source_ingestion.inspect_office, "inspect", side_effect=self.fake_office_inspect):
            result = source_ingestion.ingest_archive(self.task, self.manifest, max_workers=4)

        self.assertEqual(result["state"], "PASS")
        self.assertEqual(result["execution_mode"], "parallel")
        self.assertEqual(result["maximum_parallel_width"], 4)
        pack = result["evidence_pack"]
        self.assertEqual(len(pack["sources"]), 4)
        self.assertFalse(pack["unread"])
        self.assertTrue(all(item["state"] == "EXTRACTED" for item in pack["coverage"]))
        fact_text = {item["text"] for item in pack["facts"]}
        self.assertIn("项目=青山工程", fact_text)
        self.assertIn("责任部门=综合部", fact_text)
        self.assertIn("预算=100", fact_text)
        self.assertIn("预算=120", fact_text)
        budget = next(item for item in pack["conflicts"] if item["key"] == "预算")
        self.assertEqual(budget["values"], ["100", "120"])
        self.assertEqual(len(budget["evidence"]), 2)
        self.assertTrue(all(item["source_sha256"] for item in budget["evidence"]))

    def test_manifest_hash_change_fails_closed(self):
        self.paths[0].write_text("项目=已变化\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            source_ingestion.ingest_archive(self.task, self.manifest, max_workers=2)


if __name__ == "__main__":
    unittest.main()
