from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import inspect_office as office
import inspect_office_batch as batch

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def make_docx(path: Path, text: str):
    with zipfile.ZipFile(path, "w") as package:
        package.writestr(
            "word/document.xml",
            f'<w:document xmlns:w="{W}"><w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>',
        )


def make_xlsx(path: Path):
    with zipfile.ZipFile(path, "w") as package:
        package.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{office.X[1:-1]}" xmlns:r="{office.R[1:-1]}">'
            '<sheets><sheet name="台账" sheetId="1" r:id="rId1"/></sheets></workbook>',
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
            '<c r="B1" t="inlineStr"><is><t>进行中</t></is></c></row>'
            "</sheetData></worksheet>",
        )


class OfficeBatchInspectionTests(unittest.TestCase):
    def test_parallel_batch_preserves_input_order_and_bytes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "a.docx"
            second = root / "b.docx"
            third = root / "c.xlsx"
            make_docx(first, "甲")
            make_docx(second, "乙")
            make_xlsx(third)
            paths = [first, second, third]
            before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}

            result = batch.inspect_many(paths, max_workers=3)

            self.assertEqual(result["parse_status"], "PASS")
            self.assertEqual(result["execution_mode"], "process_parallel")
            self.assertEqual(result["maximum_parallel_width"], 3)
            self.assertEqual([item["path"] for item in result["items"]], [str(path) for path in paths])
            self.assertTrue(all(item["result"]["parse_status"] == "PASS" for item in result["items"]))
            after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
            self.assertEqual(after, before)

    def test_one_blocked_file_fails_closed_without_hiding_other_results(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            good = root / "good.docx"
            bad = root / "bad.docx"
            make_docx(good, "可读")
            bad.write_bytes(b"not-a-zip")

            result = batch.inspect_many([good, bad], max_workers=2)

            self.assertEqual(result["parse_status"], "BLOCKED")
            self.assertEqual(result["items"][0]["result"]["parse_status"], "PASS")
            self.assertEqual(result["items"][1]["result"]["parse_status"], "BLOCKED")

    def test_process_infrastructure_failure_falls_back_to_same_serial_checks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "a.docx"
            second = root / "b.docx"
            make_docx(first, "甲")
            make_docx(second, "乙")
            paths = [first, second]
            before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}

            with patch.object(batch, "ProcessPoolExecutor", side_effect=RuntimeError("spawn unavailable")):
                result = batch.inspect_many(paths, max_workers=2)

            self.assertEqual(result["parse_status"], "PASS")
            self.assertEqual(result["execution_mode"], "serial_fallback")
            self.assertEqual(result["requested_parallel_width"], 2)
            self.assertEqual(result["maximum_parallel_width"], 1)
            self.assertEqual(result["parallel_fallback_reason"], "RuntimeError")
            self.assertTrue(all(item["result"]["parse_status"] == "PASS" for item in result["items"]))
            after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
            self.assertEqual(after, before)

    def test_single_worker_remains_available_for_serial_baseline(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "a.docx"
            second = root / "b.docx"
            make_docx(first, "甲")
            make_docx(second, "乙")

            result = batch.inspect_many([first, second], max_workers=1)

            self.assertEqual(result["parse_status"], "PASS")
            self.assertEqual(result["execution_mode"], "serial")
            self.assertEqual(result["maximum_parallel_width"], 1)
            self.assertEqual(result["file_count"], 2)
            self.assertGreaterEqual(result["serial_work_seconds"], 0)
            self.assertGreaterEqual(result["wall_clock_seconds"], 0)


if __name__ == "__main__":
    unittest.main()
