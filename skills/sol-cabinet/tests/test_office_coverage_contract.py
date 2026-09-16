import importlib.util
from pathlib import Path
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("inspect_office", ROOT / "scripts" / "inspect_office.py")
office = importlib.util.module_from_spec(spec)
spec.loader.exec_module(office)


class OfficeCoverageContractTests(unittest.TestCase):
    def test_xlsx_reports_every_package_part_it_actually_reads(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "source.xlsx"
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
                    "xl/sharedStrings.xml",
                    f'<sst xmlns="{office.X[1:-1]}"><si><t>事实</t></si></sst>',
                )
                package.writestr(
                    "xl/worksheets/sheet1.xml",
                    f'<worksheet xmlns="{office.X[1:-1]}"><sheetData>'
                    '<row r="1"><c r="A1" t="s"><v>0</v></c></row>'
                    "</sheetData></worksheet>",
                )
            result = office.inspect(path)
            self.assertEqual(
                result["coverage"]["parts_read"],
                [
                    "xl/workbook.xml",
                    "xl/_rels/workbook.xml.rels",
                    "xl/sharedStrings.xml",
                    "xl/worksheets/sheet1.xml",
                ],
            )


if __name__ == "__main__":
    unittest.main()
