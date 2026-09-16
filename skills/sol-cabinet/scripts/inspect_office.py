#!/usr/bin/env python3
"""Read-only DOCX/XLSX structure and source-located text inventory.

No rendering, Office application, network, macro execution or file mutation.
Parsing success is never a content-quality or visual-layout verdict.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import posixpath
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
X = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
P = '{http://schemas.openxmlformats.org/package/2006/relationships}'


def status_value(value):
    """Exact normalized state, not substring matching or inferred completion."""
    return {'完成': 'complete', '已完成': 'complete', '未完成': 'incomplete',
            '进行中': 'in-progress', '待核实': 'unknown', '未开始': 'not-started'}.get(str(value).strip(), 'unclassified')


def _xml(z, name):
    raw = z.read(name)
    # OOXML does not need DTDs; reject entity declarations instead of expanding them.
    normalized = raw.replace(b'\x00', b'').upper()
    if b'<!DOCTYPE' in normalized or b'<!ENTITY' in normalized:
        raise ValueError('DTD/entity declarations are not supported')
    return ET.fromstring(raw)


# This is a text-inventory grammar, not an OOXML renderer. Unknown elements,
# attributes, placement and interpretation dependencies always leave a gap.
SEMANTIC_SURFACE = 'sol-office-text-v1'
XML_SPACE = '{http://www.w3.org/XML/1998/namespace}space'


def _grammar(namespace, rows):
    return {namespace + name: ({namespace + child for child in children.split()}, attrs)
            for name, children, attrs in rows}


WORD_SURFACE = _grammar(W, [
    ('document', 'body', {}), ('body', 'p', {}),
    ('hdr', 'p', {}), ('ftr', 'p', {}),
    ('p', 'r', {}), ('r', 't tab br', {}),
    ('t', '', {XML_SPACE: {'default', 'preserve'}}),
    ('tab', '', {}), ('br', '', {W + 'type': {'textWrapping'}}),
])
SHEET_SURFACE = _grammar(X, [
    ('workbook', 'sheets', {}), ('sheets', 'sheet', {}),
    ('sheet', '', {'name': None, 'sheetId': None, R + 'id': None, 'state': {'visible'}}),
    ('worksheet', 'sheetData', {}), ('sheetData', 'row', {}),
    ('row', 'c', {'r': None}), ('c', 'v is', {'r': None, 't': {'n', 's', 'inlineStr'}}),
    ('v', '', {}), ('is', 't r', {}), ('t', '', {XML_SPACE: {'default', 'preserve'}}),
    ('sst', 'si', {'count': None, 'uniqueCount': None}), ('si', 't r', {}), ('r', 't', {}),
])


def _semantic_gaps(tree, part, grammar, text_tags):
    gaps = []

    def gap(locator, reason):
        gaps.append({'part': part, 'locator': f'{part}:{locator}', 'reason': reason})

    def walk(node, locator):
        rule = grammar.get(node.tag)
        if rule is None:
            gap(locator, 'unsupported-element')
        else:
            children, attrs = rule
            for name, value in node.attrib.items():
                if name not in attrs or (attrs[name] is not None and value not in attrs[name]):
                    gap(locator + '/@' + name, 'unsupported-attribute-or-value')
            for child in node:
                if child.tag not in children:
                    gap(locator + '/' + child.tag, 'unsupported-child')
        if node.tag not in text_tags and node.text and node.text.strip():
            gap(locator + '/text()', 'unsupported-text-position')
        if node.tail and node.tail.strip():
            gap(locator + '/tail()', 'unsupported-tail-text')
        counts = {}
        for child in node:
            counts[child.tag] = counts.get(child.tag, 0) + 1
            walk(child, f'{locator}/{child.tag}[{counts[child.tag]}]')
        # These containers are singular in the supported grammar.
        singles = {W + 'document': {W + 'body'}, X + 'workbook': {X + 'sheets'},
                   X + 'worksheet': {X + 'sheetData'}, X + 'c': {X + 'v', X + 'is'},
                   X + 'si': {X + 't'}, X + 'is': {X + 't'}, X + 'r': {X + 't'}}
        if any(counts.get(tag, 0) > 1 for tag in singles.get(node.tag, ())):
            gap(locator, 'ambiguous-repeated-container')
        if node.tag in {X + 'si', X + 'is'} and counts.get(X + 't') and counts.get(X + 'r'):
            gap(locator, 'ambiguous-string-representation')
        if node.tag == X + 'sheet' and any(not node.get(key) for key in ('name', 'sheetId', R + 'id')):
            gap(locator, 'missing-sheet-identity')
        if node.tag == X + 'row':
            row = node.get('r', '')
            if not re.fullmatch(r'[1-9][0-9]*', row):
                gap(locator, 'missing-or-invalid-row-reference')
            if any(re.sub(r'^[A-Z]+', '', c.get('r', '')) != row for c in node.findall(X + 'c')):
                gap(locator, 'cell-row-reference-mismatch')
        if node.tag == X + 'c':
            ref, kind = node.get('r', ''), node.get('t', 'n')
            if not re.fullmatch(r'[A-Z]+[1-9][0-9]*', ref):
                gap(locator, 'missing-or-invalid-cell-reference')
            values, inline = node.findall(X + 'v'), node.findall(X + 'is')
            if (values and inline) or (kind == 'inlineStr' and values) or (kind != 'inlineStr' and inline):
                gap(locator, 'cell-type-content-mismatch')
            if kind == 'n' and values and not re.fullmatch(
                    r'[-+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[Ee][-+]?[0-9]+)?', values[0].text or ''):
                gap(locator, 'unsupported-numeric-storage')

    walk(tree, tree.tag + '[1]')
    return gaps


# Nonempty formatting/control parts can affect interpretation (including default
# styles). v1.5.4 does not interpret them. Only an empty, canonical XML container
# is proven inert; a known name or relationship alone never proves coverage.
FORMAT_ROOTS = {
    'word/styles.xml': W + 'styles', 'word/settings.xml': W + 'settings',
    'word/webSettings.xml': W + 'webSettings', 'word/fontTable.xml': W + 'fonts',
    'word/numbering.xml': W + 'numbering', 'xl/styles.xml': X + 'styleSheet',
    'xl/calcChain.xml': X + 'calcChain',
}
DRAWING = '{http://schemas.openxmlformats.org/drawingml/2006/main}'


def _format_coverage(z, suffix):
    parts, gaps = [], []
    prefix = 'word/' if suffix == '.docx' else 'xl/'
    for part in sorted(z.namelist()):
        if not part.startswith(prefix):
            continue
        expected = FORMAT_ROOTS.get(part)
        if re.fullmatch(prefix + r'theme/theme[0-9]+\.xml', part):
            expected = DRAWING + 'theme'
        if expected is None:
            continue
        tree = _xml(z, part)
        parts.append(part)
        if tree.tag != expected or tree.attrib or len(tree) or (tree.text and tree.text.strip()):
            gaps.append({'part': part, 'locator': part + ':' + tree.tag,
                         'reason': 'unsupported-format-or-default-interpretation'})
    return parts, gaps


def _docx(z):
    parts = sorted(n for n in z.namelist() if re.fullmatch(
        r'word/(document|header\d+|footer\d+|footnotes|endnotes|comments)\.xml', n))
    if 'word/document.xml' not in parts:
        raise ValueError('missing Word document part')
    records = []
    semantic_gaps = []
    revisions = 0
    for part in parts:
        tree = _xml(z, part)
        stem = Path(part).stem
        expected = 'hdr' if stem.startswith('header') else 'ftr' if stem.startswith('footer') else stem
        if tree.tag != W + expected:
            raise ValueError('unrecognized Word part root or namespace; Strict OOXML is not supported')
        if stem == 'document' and tree.find(W + 'body') is None:
            raise ValueError('missing Word body')
        semantic_gaps.extend(_semantic_gaps(tree, part, WORD_SURFACE, {W + 't'}))
        parents = {child: parent for parent in tree.iter() for child in parent}
        revisions += sum(1 for e in tree.iter(W + 'del'))
        for index, paragraph in enumerate(tree.iter(W + 'p'), 1):
            pieces = []
            for item in paragraph.iter():
                if item.tag not in {W+'t', W+'tab', W+'br'}:
                    continue
                parent = parents.get(item)
                deleted = False
                while parent is not None and parent.tag != W+'p':
                    deleted |= parent.tag == W+'del'
                    parent = parents.get(parent)
                if parent is paragraph and not deleted:
                    pieces.append(item.text or '' if item.tag == W+'t' else ('\t' if item.tag == W+'tab' else '\n'))
            text = ''.join(pieces)
            if text:
                records.append({'locator': f'{part}:p[{index}]', 'text': text,
                                'part': part, 'state': status_value(text)})
    return records, {'parts_read': parts, 'semantic_gaps': semantic_gaps, 'tracked_deletion_groups': revisions,
                     'limitations': ['不含删除修订正文', '图片未OCR', '字段未更新', '未分析完整样式继承', '未完成视觉渲染核验']}


def _xlsx(z):
    wb = _xml(z, 'xl/workbook.xml')
    rels = _xml(z, 'xl/_rels/workbook.xml.rels')
    if wb.tag != X+'workbook' or rels.tag != P+'Relationships':
        raise ValueError('unrecognized workbook or relationships namespace; Strict OOXML is not supported')
    parts_read = ['xl/workbook.xml', 'xl/_rels/workbook.xml.rels']
    semantic_gaps = _semantic_gaps(wb, 'xl/workbook.xml', SHEET_SURFACE, {X + 't', X + 'v'})
    targets = {}
    for rel in rels:
        if rel.tag != P+'Relationship':raise ValueError('unrecognized relationship element')
        if rel.get('TargetMode') == 'External':
            continue
        raw = rel.get('Target', '')
        target = posixpath.normpath(raw.lstrip('/') if raw.startswith('/') else 'xl/' + raw)
        if not target.startswith('xl/') or '..' in target.split('/'):
            raise ValueError('workbook part escapes package scope')
        targets[rel.get('Id')] = target
    shared = []
    if 'xl/sharedStrings.xml' in z.namelist():
        strings = _xml(z, 'xl/sharedStrings.xml')
        if strings.tag != X+'sst':raise ValueError('unrecognized shared strings part')
        semantic_gaps.extend(_semantic_gaps(strings, 'xl/sharedStrings.xml', SHEET_SURFACE, {X + 't'}))
        shared = [''.join(t.text or '' for t in si.iter(X+'t')) for si in strings.iter(X+'si')]
        parts_read.append('xl/sharedStrings.xml')
    records, sheets = [], []
    seen_sheets, seen_targets, seen_sheet_ids = set(), set(), set()
    for sheet in wb.iter(X+'sheet'):
        target = targets.get(sheet.get(R+'id'))
        if not target:
            raise ValueError('worksheet relationship unavailable')
        if sheet.get('name') in seen_sheets or target in seen_targets or sheet.get('sheetId') in seen_sheet_ids:
            semantic_gaps.append({'part': 'xl/workbook.xml', 'locator': 'xl/workbook.xml:sheet',
                                  'reason': 'ambiguous-sheet-identity'})
        seen_sheets.add(sheet.get('name'))
        seen_targets.add(target)
        seen_sheet_ids.add(sheet.get('sheetId'))
        tree = _xml(z, target)
        if tree.tag != X+'worksheet':raise ValueError('unrecognized worksheet part or namespace')
        parts_read.append(target)
        semantic_gaps.extend(_semantic_gaps(tree, target, SHEET_SURFACE, {X + 't', X + 'v'}))
        info = {'name': sheet.get('name'), 'state': sheet.get('state', 'visible'), 'part': target,
                'merged_ranges': [e.get('ref') for e in tree.iter(X+'mergeCell')], 'formula_count': 0}
        seen_cells = set()
        for cell in tree.iter(X+'c'):
            if cell.get('r') in seen_cells:
                semantic_gaps.append({'part': target, 'locator': f"{target}:{cell.get('r')}",
                                      'reason': 'ambiguous-cell-reference'})
            seen_cells.add(cell.get('r'))
            t = cell.get('t');v = cell.find(X+'v');raw = v.text if v is not None else None
            formula = cell.find(X+'f')
            if t == 's':
                index = int(raw)
                if not 0 <= index < len(shared):raise ValueError('invalid shared string index')
                value = shared[index]
            elif t == 'inlineStr':value = ''.join(e.text or '' for e in cell.iter(X+'t'))
            else:value = raw
            if formula is not None:info['formula_count'] += 1
            if value is not None or formula is not None:
                record = {'locator': f"{sheet.get('name')}!{cell.get('r')}", 'part': target,
                          'text': value or '', 'stored_type': t or 'n',
                          'formula': formula.text or '' if formula is not None else None,
                          'formula_cache_present': formula is not None and raw is not None,
                          'state': status_value(value)}
                records.append(record)
        sheets.append(info)
    return records, {'parts_read': list(dict.fromkeys(parts_read)), 'semantic_gaps': semantic_gaps, 'sheets': sheets,
                     'limitations': ['公式只读未重算，缓存可能过期', '日期为原始存储值，需结合格式解释',
                                     '图片与图表未视觉核验', '未完成视觉渲染核验']}


# Properties contain source facts, not merely rendering settings. Inventory all
# XML text and attributes (including vectors and extension fields) with expanded
# names and sibling indexes, so coverage does not depend on a field-name list.
DOCUMENT_PROPERTY_ROOTS = {
    'docProps/core.xml': '{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}coreProperties',
    'docProps/app.xml': '{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}Properties',
}


CORE_PROPS = '{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}'
APP_PROPS = '{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}'
DC = '{http://purl.org/dc/elements/1.1/}'
DCT = '{http://purl.org/dc/terms/}'
VT = '{http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes}'
CORE_FIELDS = ({CORE_PROPS + name for name in
                'keywords lastModifiedBy revision lastPrinted category contentStatus version'.split()}
               | {DC + name for name in 'title subject creator description identifier language'.split()}
               | {DCT + name for name in 'created modified'.split()})
APP_FIELDS = {APP_PROPS + name for name in
              'Template Manager Company Pages Words Characters PresentationFormat Lines Paragraphs '
              'Slides Notes TotalTime HiddenSlides MMClips ScaleCrop LinksUpToDate CharactersWithSpaces '
              'SharedDoc HyperlinkBase HyperlinksChanged Application AppVersion DocSecurity'.split()}
PROPERTY_SURFACE = {name: (set(), {XML_SPACE: {'default', 'preserve'},
                                  '{http://www.w3.org/XML/1998/namespace}lang': None})
                    for name in CORE_FIELDS | APP_FIELDS}
PROPERTY_SURFACE[CORE_PROPS + 'coreProperties'] = (CORE_FIELDS, {})
PROPERTY_SURFACE[APP_PROPS + 'Properties'] = (APP_FIELDS | {APP_PROPS + 'TitlesOfParts', APP_PROPS + 'HeadingPairs'}, {})
for name in ('TitlesOfParts', 'HeadingPairs'):
    PROPERTY_SURFACE[APP_PROPS + name] = ({VT + 'vector'}, {})
PROPERTY_SCALARS = {VT + name for name in
                    'lpstr lpwstr bstr i1 i2 i4 i8 int ui1 ui2 ui4 ui8 uint r4 r8 bool date filetime'.split()}
for name in PROPERTY_SCALARS:
    PROPERTY_SURFACE[name] = (set(), {})
PROPERTY_SURFACE[VT + 'vector'] = (PROPERTY_SCALARS | {VT + 'variant'}, {'size': None, 'baseType': None})
PROPERTY_SURFACE[VT + 'variant'] = (PROPERTY_SCALARS, {})


def _document_properties(z):
    records, parts_read, gaps = [], [], []
    for part, expected_root in DOCUMENT_PROPERTY_ROOTS.items():
        if part not in z.namelist():
            continue
        tree = _xml(z, part)
        if tree.tag != expected_root:
            raise ValueError('unrecognized document properties root or namespace')

        def record(locator, value):
            if value and value.strip():
                records.append({'locator': f'{part}:{locator}', 'text': value,
                                'part': part, 'state': status_value(value)})

        def walk(node, locator):
            record(locator + '/text()', node.text)
            for name, value in sorted(node.attrib.items()):
                record(locator + '/@' + name, value)
            counts = {}
            for child in node:
                counts[child.tag] = counts.get(child.tag, 0) + 1
                child_locator = f'{locator}/{child.tag}[{counts[child.tag]}]'
                walk(child, child_locator)
                record(child_locator + '/tail()', child.tail)

        walk(tree, tree.tag + '[1]')
        parts_read.append(part)
        gaps.extend(_semantic_gaps(tree, part, PROPERTY_SURFACE, CORE_FIELDS | APP_FIELDS | PROPERTY_SCALARS))
    return records, parts_read, gaps


def inspect(path, stale=(), max_uncompressed_bytes=128*1024*1024):
    path = Path(path)
    if path.suffix.lower() not in {'.docx', '.xlsx'}:
        raise ValueError('only docx/xlsx supported; use the native format tool for other files')
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with zipfile.ZipFile(path) as z:
        entries = z.infolist()
        if len({i.filename for i in entries}) != len(entries):raise ValueError('duplicate archive members')
        if sum(i.file_size for i in entries) > max_uncompressed_bytes:
            raise ValueError('uncompressed size exceeds inspection limit')
        if z.testzip() is not None:raise ValueError('archive integrity failure')
        records, coverage = _docx(z) if path.suffix.lower() == '.docx' else _xlsx(z)
        property_records, property_parts, property_gaps = _document_properties(z)
        records.extend(property_records)
        coverage['parts_read'].extend(property_parts)
        format_parts, format_gaps = _format_coverage(z, path.suffix.lower())
        coverage['parts_read'].extend(format_parts)
        coverage['semantic_gaps'].extend(property_gaps + format_gaps)
        coverage['semantic_surface'] = SEMANTIC_SURFACE
        incomplete = {gap['part'] for gap in coverage['semantic_gaps']}
        coverage['parts_complete'] = [part for part in coverage['parts_read'] if part not in incomplete]
    after = hashlib.sha256(path.read_bytes()).hexdigest()
    if before != after:raise ValueError('source changed during inspection')
    hits = []
    numbers = []
    for record in records:
        for token in stale:
            if not token:continue
            for match in re.finditer(re.escape(token), record['text']):
                hits.append({'locator': record['locator'], 'token': token, 'offset': match.start(), 'severity': 'candidate'})
        for match in re.finditer(r'[-+]?\d+(?:[,.]\d+)*(?:%|％)?', record['text']):
            numbers.append({'locator': record['locator'], 'value': match.group(), 'offset': match.start()})
    return {'parse_status': 'PASS', 'overall_verdict': 'NOT_ASSESSED', 'read_only': True,
            'source_sha256': before, 'source_unchanged': True, 'coverage': coverage,
            'records': records, 'stale_candidates': hits, 'numeric_occurrences': numbers,
            'limitation': '结构和局部候选检查不代替事实、口径、全文覆盖或视觉验收'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path');parser.add_argument('--stale', action='append', default=[])
    args = parser.parse_args()
    try:
        result = inspect(args.path, args.stale)
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError, zipfile.BadZipFile, RuntimeError):
        print(json.dumps({'parse_status': 'BLOCKED', 'overall_verdict': 'NOT_ASSESSED',
                          'reason': '输入不可读、损坏、不支持或超限；未退回二进制猜读'}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2));return 0


if __name__ == '__main__':raise SystemExit(main())
