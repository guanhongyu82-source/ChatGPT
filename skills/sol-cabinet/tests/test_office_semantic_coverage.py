"""Real OOXML packages through production inspector and canonical ingestion."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
from xml.sax.saxutils import quoteattr

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import inspect_office
import source_ingestion

OFFICE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
PACKAGE = "http://schemas.openxmlformats.org/package/2006/relationships/"
CORE = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
APP = "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
DC = "http://purl.org/dc/elements/1.1/"
CT_CORE = "application/vnd.openxmlformats-package.core-properties+xml"
CT_APP = "application/vnd.openxmlformats-officedocument.extended-properties+xml"


class OfficeSemanticCoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.task = Path(self.temp.name)
        self.archive = self.task / "00_原稿"
        self.archive.mkdir()

    def package(self, extra=None, relationships=(), suffix=".docx"):
        self.path = self.archive / ("原稿_SOURCE_source" + suffix)
        if suffix == ".docx":
            parts = {"word/document.xml": (
                f'<w:document xmlns:w={quoteattr(inspect_office.W[1:-1])}><w:body/></w:document>',
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml")}
            root_target = "word/document.xml"
        else:
            parts = {
                "xl/workbook.xml": (
                    f'<workbook xmlns={quoteattr(inspect_office.X[1:-1])} xmlns:r={quoteattr(OFFICE[:-1])}>'
                    '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>',
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"),
                "xl/worksheets/sheet1.xml": (
                    f'<worksheet xmlns={quoteattr(inspect_office.X[1:-1])}><sheetData/></worksheet>',
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"),
                "xl/_rels/workbook.xml.rels": (
                    f'<Relationships xmlns={quoteattr(PACKAGE[:-1])}><Relationship Id="rId1" '
                    f'Type={quoteattr(OFFICE + "worksheet")} Target="worksheets/sheet1.xml"/></Relationships>',
                    "application/vnd.openxmlformats-package.relationships+xml"),
            }
            root_target = "xl/workbook.xml"
        parts.update(extra or {})
        rels = [(OFFICE + "officeDocument", root_target), *relationships]
        types = [f'<Types xmlns={quoteattr(source_ingestion.CONTENT_TYPES_NS[1:-1])}>',
                 '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>']
        for name, (_, content_type) in parts.items():
            types.append(f'<Override PartName={quoteattr("/" + name)} ContentType={quoteattr(content_type)}/>')
        types.append("</Types>")
        with zipfile.ZipFile(self.path, "w") as z:
            z.writestr("[Content_Types].xml", "".join(types))
            z.writestr("_rels/.rels", f'<Relationships xmlns={quoteattr(PACKAGE[:-1])}>' + "".join(
                f'<Relationship Id={quoteattr("rId" + str(i))} Type={quoteattr(kind)} Target={quoteattr(target)}/>'
                for i, (kind, target) in enumerate(rels)) + "</Relationships>")
            for name, (xml, _) in parts.items():
                z.writestr(name, xml)
        digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.manifest = self.archive / "原稿清单.json"
        self.manifest.write_text(json.dumps({"schema_version": 1, "archive_state": "PASS", "files": [{
            "source_role": "SOURCE", "source_name": "source" + suffix,
            "archived_relative_path": "00_原稿/" + self.path.name,
            "size_bytes": self.path.stat().st_size,
            "source_sha256": digest, "archived_sha256": digest,
            "byte_identical": True, "source_unmodified": True, "status": "UNMODIFIED_BYTE_COPY",
        }]}))
        return inspect_office.inspect(self.path)

    def ingest(self):
        return source_ingestion.ingest_archive(self.task, self.manifest)

    def test_empty_docx_description_is_extracted_into_evidence(self):
        inspected = self.package({"docProps/core.xml": (
            f'<cp:coreProperties xmlns:cp={quoteattr(CORE)} xmlns:dc={quoteattr(DC)}>'
            '<dc:description>唯一源事实</dc:description></cp:coreProperties>', CT_CORE)},
            [(PACKAGE + "metadata/core-properties", "docProps/core.xml")])
        self.assertEqual(len(inspected["records"]), 1)
        self.assertIn("docProps/core.xml", inspected["coverage"]["parts_read"])
        result = self.ingest()
        self.assertEqual(result["state"], "PASS")
        fact = result["evidence_pack"]["facts"][0]
        self.assertEqual(fact["text"], "唯一源事实")
        self.assertIn("docProps/core.xml:", fact["locator"])
        self.assertIn(DC + "}description[1]/text()", fact["locator"])
        self.assertTrue(fact["source_sha256"])

    def test_app_company_manager_and_vectors_are_extracted_for_both_formats(self):
        for suffix in (".docx", ".xlsx"):
            with self.subTest(suffix=suffix):
                inspected = self.package({"docProps/app.xml": (
                    f'<Properties xmlns={quoteattr(APP)} xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
                    '<Company>单位甲</Company><Manager>负责人乙</Manager><TitlesOfParts>'
                    '<vt:vector size="2" baseType="lpstr"><vt:lpstr>标题一</vt:lpstr>'
                    '<vt:lpstr>标题二</vt:lpstr></vt:vector></TitlesOfParts></Properties>', CT_APP)},
                    [(OFFICE + "extended-properties", "docProps/app.xml")], suffix)
                self.assertIn("docProps/app.xml", inspected["coverage"]["parts_read"])
                result = self.ingest()
                self.assertEqual(result["state"], "PASS")
                facts = result["evidence_pack"]["facts"]
                self.assertTrue({"单位甲", "负责人乙", "标题一", "标题二"} <= {f["text"] for f in facts})
                self.assertEqual(len({r["locator"] for r in facts}), len(facts))
                self.assertTrue(all(f["locator"].startswith("docProps/app.xml:") for f in facts))

    def test_all_property_text_and_attributes_are_inventoried(self):
        self.package({"docProps/core.xml": (
            f'<cp:coreProperties xmlns:cp={quoteattr(CORE)} xmlns:dc={quoteattr(DC)} xmlns:e="urn:extension">'
            '<dc:title>标题</dc:title><dc:subject>主题</dc:subject><dc:creator>作者</dc:creator>'
            '<cp:keywords>关键词</cp:keywords><e:other e:meaning="属性事实">扩展文本</e:other>尾部文本'
            '</cp:coreProperties>', CT_CORE)})
        result = self.ingest()
        self.assertEqual(result["state"], "PARTIAL")
        self.assertTrue(any("semantic-gap" in u for u in result["evidence_pack"]["unread"]))
        self.assertEqual({f["text"] for f in result["evidence_pack"]["facts"]},
                         {"标题", "主题", "作者", "关键词", "属性事实", "扩展文本", "尾部文本"})

    def test_empty_properties_do_not_create_false_partial(self):
        self.package({
            "docProps/core.xml": (f'<coreProperties xmlns={quoteattr(CORE)}><keywords>  </keywords></coreProperties>', CT_CORE),
            "docProps/app.xml": (f'<Properties xmlns={quoteattr(APP)}><Company/></Properties>', CT_APP),
        }, [(PACKAGE + "metadata/core-properties", "docProps/core.xml"),
            (OFFICE + "extended-properties", "docProps/app.xml")])
        result = self.ingest()
        self.assertEqual(result["state"], "PASS")
        self.assertEqual(result["evidence_pack"]["facts"], [])
        self.assertEqual(result["evidence_pack"]["unread"], [])

    def test_property_field_names_are_text_not_unevaluated_word_fields(self):
        self.package({"docProps/core.xml": (
            f'<cp:coreProperties xmlns:cp={quoteattr(CORE)} xmlns:dc={quoteattr(DC)}>'
            '<dc:description>Documentation of fldSimple instrText fldChar XML elements</dc:description>'
            '</cp:coreProperties>', CT_CORE)})
        result = self.ingest()
        self.assertEqual(result["state"], "PASS")
        self.assertEqual(len(result["evidence_pack"]["facts"]), 1)
        self.assertEqual(result["evidence_pack"]["unread"], [])

    def test_actual_word_field_elements_remain_unread(self):
        for tag in ("fldSimple", "instrText", "fldChar"):
            with self.subTest(tag=tag):
                self.package({"word/document.xml": (
                    f'<w:document xmlns:w={quoteattr(inspect_office.W[1:-1])}>'
                    f'<w:body><w:p><w:{tag}/></w:p></w:body></w:document>',
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml")})
                result = self.ingest()
                self.assertEqual(result["state"], "PARTIAL")
                self.assertTrue(any("docx-fields-not-evaluated" in u for u in result["evidence_pack"]["unread"]))

    def test_unread_properties_cannot_get_format_exemption(self):
        inspected = self.package({"docProps/core.xml": (
            f'<coreProperties xmlns={quoteattr(CORE)}><keywords>事实</keywords></coreProperties>', CT_CORE)})
        inspected["coverage"]["parts_read"].remove("docProps/core.xml")
        inspected["coverage"]["parts_complete"].remove("docProps/core.xml")
        self.assertTrue(any("docProps/core.xml" in item for item in
                            source_ingestion._office_unread(self.path, inspected, "source")))

    def test_malformed_property_root_is_rejected(self):
        with self.assertRaises(ValueError):
            self.package({"docProps/app.xml": ('<Properties><Company>事实</Company></Properties>', CT_APP)})

    def test_custom_theme_and_styles_relationships_fail_closed(self):
        for kind, target, content_type in (
            ("theme", "word/theme/theme1.xml", source_ingestion.THEME_CONTENT_TYPE),
            ("styles", "word/styles.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"),
        ):
            with self.subTest(kind=kind):
                uri = "https://example.test/application-semantic/" + kind
                namespace = inspect_office.DRAWING if kind == "theme" else inspect_office.W
                self.package({target: (f'<{kind} xmlns={quoteattr(namespace[1:-1])}/>', content_type)}, [(uri, target)])
                self.assertIsNone(source_ingestion._relationship_kind(uri))
                result = self.ingest()
                self.assertEqual(result["state"], "PARTIAL")
                self.assertEqual(result["evidence_pack"]["coverage"][0]["state"], "UNREAD")
                unread = result["evidence_pack"]["unread"]
                self.assertTrue(any(target in u for u in unread))
                self.assertTrue(any(uri in u for u in unread))

    def test_official_theme_and_styles_relationships_remain_pass(self):
        self.package({
            "word/theme/theme1.xml": (f'<a:theme xmlns:a={quoteattr(inspect_office.DRAWING[1:-1])}/>', source_ingestion.THEME_CONTENT_TYPE),
            "word/styles.xml": (f'<w:styles xmlns:w={quoteattr(inspect_office.W[1:-1])}/>', "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"),
        }, [(OFFICE + "theme", "word/theme/theme1.xml"), (OFFICE + "styles", "word/styles.xml")])
        self.assertEqual(self.ingest()["state"], "PASS")

    def test_unknown_type_targeting_already_read_part_remains_unread(self):
        self.package(relationships=[("urn:custom:document", "word/document.xml")])
        result = self.ingest()
        self.assertEqual(result["state"], "PARTIAL")
        self.assertTrue(any("urn:custom:document" in u for u in result["evidence_pack"]["unread"]))

    def test_uri_lookalikes_and_unsupported_strict_are_not_trusted(self):
        for uri in (OFFICE + "theme/", OFFICE + "theme?x=1", OFFICE.replace("http:", "https:") + "theme",
                    "theme", " theme", OFFICE + "Theme", "http://purl.oclc.org/ooxml/officeDocument/relationships/theme"):
            with self.subTest(uri=uri):
                self.package({"word/theme/theme1.xml": (f'<a:theme xmlns:a={quoteattr(inspect_office.DRAWING[1:-1])}/>', source_ingestion.THEME_CONTENT_TYPE)},
                             [(uri, "word/theme/theme1.xml")])
                self.assertEqual(self.ingest()["state"], "PARTIAL")


    def test_unsupported_word_elements_and_attributes_leave_internal_gaps(self):
        for fragment in ('<w:noBreakHyphen/>', '<w:sym w:font="Wingdings" w:char="F041"/>',
                         '<w:cr/>', '<w:futureVisible/>', '<w:rPr><w:vanish/></w:rPr>',
                         '<w:t w:unknown="semantic">value</w:t>'):
            with self.subTest(fragment=fragment):
                inspected = self.package({"word/document.xml": (
                    f'<w:document xmlns:w={quoteattr(inspect_office.W[1:-1])}>'
                    f'<w:body><w:p><w:r><w:t>普通文本</w:t>{fragment}</w:r></w:p></w:body></w:document>',
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml")})
                self.assertIn("word/document.xml", inspected["coverage"]["parts_read"])
                self.assertNotIn("word/document.xml", inspected["coverage"]["parts_complete"])
                self.assertTrue(inspected["coverage"]["semantic_gaps"])
                result = self.ingest()
                self.assertEqual(result["state"], "PARTIAL")
                self.assertTrue(any("semantic-gap" in u for u in result["evidence_pack"]["unread"]))
                self.assertTrue(any("普通文本" in f["text"] for f in result["evidence_pack"]["facts"]))

    def test_worksheet_header_footer_and_unknown_children_are_not_covered(self):
        for fragment in ('<headerFooter><oddHeader>唯一页眉事实</oddHeader></headerFooter>',
                         '<headerFooter><evenFooter>页脚事实</evenFooter></headerFooter>',
                         '<futureSemantic>未知事实</futureSemantic>'):
            with self.subTest(fragment=fragment):
                inspected = self.package({"xl/worksheets/sheet1.xml": (
                    f'<worksheet xmlns={quoteattr(inspect_office.X[1:-1])}>'
                    '<sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>正文</t></is></c></row></sheetData>'
                    + fragment + '</worksheet>',
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml")}, suffix=".xlsx")
                self.assertIn("xl/worksheets/sheet1.xml", inspected["coverage"]["parts_read"])
                self.assertNotIn("xl/worksheets/sheet1.xml", inspected["coverage"]["parts_complete"])
                result = self.ingest()
                self.assertEqual(result["state"], "PARTIAL")
                self.assertTrue(any("semantic-gap" in u for u in result["evidence_pack"]["unread"]))

    def test_date_style_serial_and_implicit_default_style_are_partial(self):
        for style_attribute in (' s="1"', ''):
            with self.subTest(style_attribute=style_attribute):
                self.package({
                    "xl/worksheets/sheet1.xml": (
                        f'<worksheet xmlns={quoteattr(inspect_office.X[1:-1])}>'
                        f'<sheetData><row r="1"><c r="A1"{style_attribute}><v>45292</v></c></row></sheetData></worksheet>',
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"),
                    "xl/styles.xml": (
                        f'<styleSheet xmlns={quoteattr(inspect_office.X[1:-1])}>'
                        '<cellXfs count="2"><xf numFmtId="14"/><xf numFmtId="14" applyNumberFormat="1"/></cellXfs></styleSheet>',
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"),
                }, [(OFFICE + "styles", "xl/styles.xml")], suffix=".xlsx")
                result = self.ingest()
                self.assertEqual(result["state"], "PARTIAL")
                self.assertIn("45292", {f["text"] for f in result["evidence_pack"]["facts"]})
                self.assertTrue(any("unsupported-format-or-default-interpretation" in u
                                    for u in result["evidence_pack"]["unread"]))

    def test_rich_string_formatting_and_row_attributes_are_unsupported(self):
        cases = [
            '<row r="1" hidden="1"><c r="A1"><v>12</v></c></row>',
            '<row r="1"><c r="A1" t="inlineStr"><is><r><rPr><vertAlign val="superscript"/></rPr>'
            '<t>2</t></r></is></c></row>',
            '<row r="1"><c r="A1" t="b"><v>1</v></c></row>',
        ]
        for cells in cases:
            with self.subTest(cells=cells):
                self.package({"xl/worksheets/sheet1.xml": (
                    f'<worksheet xmlns={quoteattr(inspect_office.X[1:-1])}><sheetData>{cells}</sheetData></worksheet>',
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml")}, suffix=".xlsx")
                self.assertEqual(self.ingest()["state"], "PARTIAL")

    def test_supported_word_text_tabs_and_breaks_still_pass(self):
        inspected = self.package({"word/document.xml": (
            f'<w:document xmlns:w={quoteattr(inspect_office.W[1:-1])}>'
            '<w:body><w:p><w:r><w:t>甲</w:t><w:tab/><w:t>乙</w:t><w:br/>'
            '<w:t xml:space="preserve"> 丙 </w:t></w:r></w:p></w:body></w:document>',
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml")})
        self.assertEqual(inspected["records"][0]["text"], "甲\t乙\n 丙 ")
        self.assertEqual(inspected["coverage"]["semantic_gaps"], [])
        self.assertEqual(inspected["coverage"]["parts_complete"], inspected["coverage"]["parts_read"])
        result = self.ingest()
        self.assertEqual(result["state"], "PASS")
        self.assertEqual(result["evidence_pack"]["facts"][0]["text"], inspected["records"][0]["text"])

    def test_supported_inline_shared_strings_and_plain_numbers_still_pass(self):
        inspected = self.package({
            "xl/worksheets/sheet1.xml": (
                f'<worksheet xmlns={quoteattr(inspect_office.X[1:-1])}>'
                '<sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>内联</t></is></c>'
                '<c r="B1" t="s"><v>0</v></c><c r="C1"><v>12.5</v></c></row></sheetData></worksheet>',
                "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"),
            "xl/sharedStrings.xml": (
                f'<sst xmlns={quoteattr(inspect_office.X[1:-1])} count="1" uniqueCount="1"><si><t>共享</t></si></sst>',
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"),
        }, [(OFFICE + "sharedStrings", "xl/sharedStrings.xml")], suffix=".xlsx")
        self.assertEqual(inspected["coverage"]["semantic_gaps"], [])
        result = self.ingest()
        self.assertEqual(result["state"], "PASS")
        self.assertEqual({f["text"] for f in result["evidence_pack"]["facts"]}, {"内联", "共享", "12.5"})

    def test_parts_read_without_semantic_contract_cannot_claim_complete(self):
        for key in ("semantic_surface", "semantic_gaps", "parts_complete"):
            with self.subTest(key=key):
                inspected = self.package()
                inspected["coverage"].pop(key)
                with self.assertRaises(ValueError):
                    source_ingestion._office_unread(self.path, inspected, "source")

    def test_semantic_completeness_cannot_contradict_internal_gaps(self):
        inspected = self.package()
        inspected["coverage"]["semantic_gaps"] = [{"part": "word/document.xml", "locator": "word/document.xml:p[1]",
                                                   "reason": "unhandled"}]
        with self.assertRaises(ValueError):
            source_ingestion._office_unread(self.path, inspected, "source")

    def test_official_relationship_type_must_match_the_parsed_target(self):
        self.package(relationships=[(OFFICE + "comments", "word/document.xml")])
        result = self.ingest()
        self.assertEqual(result["state"], "PARTIAL")
        self.assertTrue(any("relationship-part-type-mismatch" in u for u in result["evidence_pack"]["unread"]))



    def test_parsed_part_custom_content_type_cannot_claim_supported_semantics(self):
        self.package({"word/document.xml": (
            f'<w:document xmlns:w={quoteattr(inspect_office.W[1:-1])}><w:body/></w:document>',
            "application/x-custom-semantics+xml")})
        result = self.ingest()
        self.assertEqual(result["state"], "PARTIAL")
        self.assertTrue(any("unsupported-part-content-type" in u for u in result["evidence_pack"]["unread"]))

    def test_duplicate_cell_identity_cannot_hide_interpretation_ambiguity(self):
        self.package({"xl/worksheets/sheet1.xml": (
            f'<worksheet xmlns={quoteattr(inspect_office.X[1:-1])}>'
            '<sheetData><row r="1"><c r="A1"><v>12</v></c><c r="A1"><v>13</v></c></row></sheetData></worksheet>',
            "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml")}, suffix=".xlsx")
        result = self.ingest()
        self.assertEqual(result["state"], "PARTIAL")
        self.assertTrue(any("ambiguous-cell-reference" in u for u in result["evidence_pack"]["unread"]))



if __name__ == "__main__":
    unittest.main()
