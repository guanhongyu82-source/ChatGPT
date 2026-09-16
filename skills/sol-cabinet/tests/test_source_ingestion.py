from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
import zipfile
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
            source_name = path.name.split("_", 2)[-1]
            files.append(
                {
                    "source_role": role,
                    "source_name": source_name,
                    "archived_relative_path": f"00_原稿/原稿_{role}_{source_name}",
                    "size_bytes": path.stat().st_size,
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

    def _refresh_manifest_entry(self, index: int) -> None:
        data = json.loads(self.manifest.read_text(encoding="utf-8"))
        path = self.paths[index]
        digest = sha(path)
        data["files"][index]["size_bytes"] = path.stat().st_size
        data["files"][index]["source_sha256"] = digest
        data["files"][index]["archived_sha256"] = digest
        self.manifest.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def _write_xlsx_package(self, extra_parts: dict[str, str | bytes] | None = None) -> None:
        path = self.paths[2]
        with zipfile.ZipFile(path, "w") as package:
            package.writestr("[Content_Types].xml", "<Types/>")
            package.writestr("_rels/.rels", "<Relationships/>")
            package.writestr("xl/workbook.xml", "<workbook/>")
            package.writestr("xl/_rels/workbook.xml.rels", "<Relationships/>")
            package.writestr("xl/worksheets/sheet1.xml", "<worksheet/>")
            for name, payload in (extra_parts or {}).items():
                package.writestr(name, payload)
        self._refresh_manifest_entry(2)

    def fake_office_inspect(self, path: Path):
        path = Path(path)
        if path.suffix == ".docx":
            records = [{"locator": "word/document.xml:p[1]", "text": "责任部门=综合部"}]
            coverage = {
                "parts_read": ["word/document.xml"],
                "tracked_deletion_groups": 0,
                "limitations": ["图片未OCR", "字段未更新", "未完成视觉渲染核验"],
            }
        elif path.suffix == ".xlsx":
            records = [
                {"locator": "验证台账!A1", "text": "预算=120"},
                {"locator": "验证台账!A2", "text": "阶段=完成"},
            ]
            coverage = {
                "parts_read": [
                    "xl/workbook.xml",
                    "xl/_rels/workbook.xml.rels",
                    "xl/worksheets/sheet1.xml",
                ],
                "sheets": [{"name": "验证台账", "part": "xl/worksheets/sheet1.xml", "formula_count": 0}],
                "limitations": ["公式只读未重算，缓存可能过期", "图片与图表未视觉核验", "未完成视觉渲染核验"],
            }
        else:
            raise AssertionError(path)
        return {
            "parse_status": "PASS",
            "source_sha256": sha(path),
            "records": records,
            "coverage": coverage,
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
        office_coverage = [item for item in pack["coverage"] if item["inspection_coverage"] is not None]
        self.assertEqual(len(office_coverage), 2)
        self.assertTrue(all(item["inspection_coverage"]["limitations"] for item in office_coverage))
        fact_text = {item["text"] for item in pack["facts"]}
        self.assertIn("项目=青山工程", fact_text)
        self.assertIn("责任部门=综合部", fact_text)
        self.assertIn("预算=100", fact_text)
        self.assertIn("预算=120", fact_text)
        budget = next(item for item in pack["conflicts"] if item["key"] == "预算")
        self.assertEqual(budget["values"], ["100", "120"])
        self.assertEqual(len(budget["evidence"]), 2)
        self.assertTrue(all(item["source_sha256"] for item in budget["evidence"]))

    def test_actual_office_gap_marks_source_and_ingestion_partial(self):
        def inspect_with_unread(path: Path):
            result = self.fake_office_inspect(path)
            if Path(path).suffix == ".docx":
                result["coverage"]["tracked_deletion_groups"] = 1
            return result

        with mock.patch.object(source_ingestion.inspect_office, "inspect", side_effect=inspect_with_unread):
            result = source_ingestion.ingest_archive(self.task, self.manifest, max_workers=4)
        self.assertEqual(result["state"], "PARTIAL")
        self.assertTrue(any("tracked-deletions-not-extracted" in item for item in result["evidence_pack"]["unread"]))
        self.assertIn("PARTIAL", {item["state"] for item in result["evidence_pack"]["coverage"]})

    def test_unparsed_semantic_xlsx_parts_fail_closed_by_default(self):
        cases = [
            "xl/comments1.xml",
            "xl/threadedComments/threadedComment1.xml",
            "xl/pivotTables/pivotTable1.xml",
            "customXml/item1.xml",
        ]
        for part in cases:
            with self.subTest(part=part):
                self._write_xlsx_package({part: "<semantic/>"})
                with mock.patch.object(source_ingestion.inspect_office, "inspect", side_effect=self.fake_office_inspect):
                    result = source_ingestion.ingest_archive(self.task, self.manifest, max_workers=4)
                self.assertEqual(result["state"], "PARTIAL")
                self.assertTrue(
                    any(part in item for item in result["evidence_pack"]["unread"]),
                    result["evidence_pack"]["unread"],
                )
                xlsx_coverage = next(
                    item
                    for item in result["evidence_pack"]["coverage"]
                    if item["inspection_coverage"] and "sheets" in item["inspection_coverage"]
                )
                self.assertEqual(xlsx_coverage["state"], "PARTIAL")

    def test_known_structural_and_format_parts_do_not_create_false_partial(self):
        self._write_xlsx_package(
            {
                "xl/styles.xml": "<styleSheet/>",
                "xl/theme/theme1.xml": "<theme/>",
                "xl/printerSettings/printerSettings1.bin": b"print-settings",
                "docProps/core.xml": "<coreProperties/>",
                "docProps/app.xml": "<Properties/>",
            }
        )
        with mock.patch.object(source_ingestion.inspect_office, "inspect", side_effect=self.fake_office_inspect):
            result = source_ingestion.ingest_archive(self.task, self.manifest, max_workers=4)
        self.assertEqual(result["state"], "PASS")
        self.assertFalse(result["evidence_pack"]["unread"])

    def test_inspector_must_report_concrete_parts_read(self):
        def malformed_inspect(path: Path):
            result = self.fake_office_inspect(path)
            result["coverage"].pop("parts_read", None)
            return result

        with mock.patch.object(source_ingestion.inspect_office, "inspect", side_effect=malformed_inspect):
            with self.assertRaises(ValueError):
                source_ingestion.ingest_archive(self.task, self.manifest, max_workers=4)

    def test_manifest_hash_change_fails_closed(self):
        self.paths[0].write_text("项目=已变化\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            source_ingestion.ingest_archive(self.task, self.manifest, max_workers=2)

    def test_noncanonical_manifest_path_is_rejected(self):
        alternate = self.task / "claimed-pass.json"
        alternate.write_bytes(self.manifest.read_bytes())
        with self.assertRaises(ValueError):
            source_ingestion.ingest_archive(self.task, alternate, max_workers=2)

    def test_manifest_entry_must_be_canonical_archive_member(self):
        outside = self.task / "材料.txt"
        outside.write_bytes(self.paths[0].read_bytes())
        data = json.loads(self.manifest.read_text(encoding="utf-8"))
        data["files"][0]["archived_relative_path"] = "材料.txt"
        self.manifest.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(ValueError):
            source_ingestion.ingest_archive(self.task, self.manifest, max_workers=2)

    def test_manifest_schema_must_match_archive_writer_exactly(self):
        data = json.loads(self.manifest.read_text(encoding="utf-8"))
        data["unexpected"] = True
        self.manifest.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(ValueError):
            source_ingestion.ingest_archive(self.task, self.manifest, max_workers=2)

    def test_manifest_size_and_role_invariants_are_enforced(self):
        data = json.loads(self.manifest.read_text(encoding="utf-8"))
        data["files"][0]["size_bytes"] += 1
        self.manifest.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(ValueError):
            source_ingestion.ingest_archive(self.task, self.manifest, max_workers=2)

        data["files"][0]["size_bytes"] -= 1
        data["files"][0]["source_role"] = "bad/role"
        self.manifest.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(ValueError):
            source_ingestion.ingest_archive(self.task, self.manifest, max_workers=2)


if __name__ == "__main__":
    unittest.main()
