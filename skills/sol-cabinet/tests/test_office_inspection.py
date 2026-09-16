import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('inspect_office', ROOT/'scripts/inspect_office.py')
office = importlib.util.module_from_spec(spec);spec.loader.exec_module(office)
W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'


class OfficeInspectionTests(unittest.TestCase):
    def test_state_does_not_match_completion_substrings(self):
        self.assertEqual(office.status_value('未完成'), 'incomplete')
        self.assertEqual(office.status_value('已完成'), 'complete')
        self.assertEqual(office.status_value(' 完成 '), 'complete')
        self.assertEqual(office.status_value('完成率90%'), 'unclassified')

    def test_docx_tables_headers_and_all_occurrences_preserve_source(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)/'source.docx'
            with zipfile.ZipFile(p, 'w') as z:
                z.writestr('word/document.xml', f'<w:document xmlns:w="{W}"><w:body><w:p><w:r><w:t>一、旧值旧值12</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>（一）12</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>')
                z.writestr('word/header1.xml', f'<w:hdr xmlns:w="{W}"><w:p><w:r><w:t>旧值12</w:t></w:r></w:p></w:hdr>')
            before = p.read_bytes();result = office.inspect(p, ['旧值'])
            self.assertEqual(p.read_bytes(), before)
            self.assertEqual(result['source_sha256'], hashlib.sha256(before).hexdigest())
            self.assertEqual(len(result['stale_candidates']), 3)
            self.assertEqual(len(result['numeric_occurrences']), 3)
            self.assertEqual(len(result['records']), 3)
            self.assertEqual(result['overall_verdict'], 'NOT_ASSESSED')

    def test_nested_textbox_not_duplicated_and_deleted_text_not_current_fact(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)/'source.docx'
            with zipfile.ZipFile(p, 'w') as z:
                z.writestr('word/document.xml', f'<w:document xmlns:w="{W}"><w:body><w:p><w:r><w:t>外层</w:t></w:r><w:txbxContent><w:p><w:r><w:t>文本框</w:t></w:r></w:p></w:txbxContent><w:del><w:r><w:delText>旧稿</w:delText></w:r></w:del></w:p></w:body></w:document>')
            result = office.inspect(p)
            self.assertEqual([x['text'] for x in result['records']], ['外层', '文本框'])
            self.assertEqual(result['coverage']['tracked_deletion_groups'], 1)

    def test_xlsx_keeps_formula_cache_and_exact_states(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)/'source.xlsx'
            with zipfile.ZipFile(p, 'w') as z:
                z.writestr('xl/workbook.xml', f'<workbook xmlns="{office.X[1:-1]}" xmlns:r="{office.R[1:-1]}"><sheets><sheet name="台账" sheetId="1" r:id="rId1"/></sheets></workbook>')
                z.writestr('xl/_rels/workbook.xml.rels', f'<Relationships xmlns="{office.P[1:-1]}"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
                z.writestr('xl/worksheets/sheet1.xml', f'<worksheet xmlns="{office.X[1:-1]}"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>未完成</t></is></c><c r="B1"><f>SUM(C1:C2)</f></c><c r="C1"><v>12</v></c></row></sheetData><mergeCells><mergeCell ref="A2:B2"/></mergeCells></worksheet>')
            raw = p.read_bytes();result = office.inspect(p)
            self.assertEqual(p.read_bytes(), raw)
            self.assertEqual(result['records'][0]['state'], 'incomplete')
            self.assertEqual(result['records'][1]['formula'], 'SUM(C1:C2)')
            self.assertFalse(result['records'][1]['formula_cache_present'])
            self.assertEqual(result['coverage']['sheets'][0]['merged_ranges'], ['A2:B2'])

    def test_corrupt_xml_and_dtd_fail_instead_of_binary_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)/'source.docx'
            for payload in ['not xml', '<!DOCTYPE x [<!ENTITY x "EXPAND">]><x>&x;</x>',
                            '<!DOCTYPE x [<!ENTITY x "EXPAND">]><x>&x;</x>'.encode('utf-16')]:
                with zipfile.ZipFile(p, 'w') as z:z.writestr('word/document.xml', payload)
                with self.assertRaises((ValueError, office.ET.ParseError)):office.inspect(p)
            p.write_bytes(b'not a zip')
            with self.assertRaises(zipfile.BadZipFile):office.inspect(p)

    def test_oversized_package_is_rejected_before_parsing(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)/'source.docx'
            with zipfile.ZipFile(p, 'w') as z:z.writestr('word/document.xml', 'x'*100)
            with self.assertRaises(ValueError):office.inspect(p, max_uncompressed_bytes=10)

    def test_unknown_and_strict_word_roots_are_not_empty_successes(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)/'source.docx'
            for xml in ['<unrelated/>', '<w:document xmlns:w="http://purl.oclc.org/ooxml/wordprocessingml/main"><w:body><w:p><w:r><w:t>正文</w:t></w:r></w:p></w:body></w:document>']:
                with zipfile.ZipFile(p, 'w') as z:z.writestr('word/document.xml', xml)
                with self.assertRaises(ValueError):office.inspect(p)
            with zipfile.ZipFile(p, 'w') as z:
                z.writestr('word/document.xml', f'<w:document xmlns:w="{W}"><w:body/></w:document>')
            self.assertEqual(office.inspect(p)['records'], [])

    def test_unrecognized_word_auxiliary_part_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)/'source.docx'
            with zipfile.ZipFile(p, 'w') as z:
                z.writestr('word/document.xml', f'<w:document xmlns:w="{W}"><w:body/></w:document>')
                z.writestr('word/header1.xml', '<unrelated/>')
            with self.assertRaises(ValueError):office.inspect(p)

    def test_wrong_workbook_worksheet_and_shared_string_roots_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)/'source.xlsx'
            valid = {
                'xl/workbook.xml': f'<workbook xmlns="{office.X[1:-1]}" xmlns:r="{office.R[1:-1]}"><sheets><sheet name="空表" sheetId="1" r:id="rId1"/></sheets></workbook>',
                'xl/_rels/workbook.xml.rels': f'<Relationships xmlns="{office.P[1:-1]}"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
                'xl/worksheets/sheet1.xml': f'<worksheet xmlns="{office.X[1:-1]}"><sheetData/></worksheet>',
                'xl/sharedStrings.xml': f'<sst xmlns="{office.X[1:-1]}"/>',
            }
            for part in valid:
                with self.subTest(part=part), zipfile.ZipFile(p, 'w') as z:
                    for name,xml in valid.items():z.writestr(name, '<unrelated/>' if name == part else xml)
                with self.assertRaises(ValueError):office.inspect(p)
            with zipfile.ZipFile(p, 'w') as z:
                for name,xml in valid.items():z.writestr(name, xml)
            self.assertEqual(office.inspect(p)['records'], [])


if __name__ == '__main__':unittest.main()