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


def _docx(z):
    parts = sorted(n for n in z.namelist() if re.fullmatch(
        r'word/(document|header\d+|footer\d+|footnotes|endnotes|comments)\.xml', n))
    if 'word/document.xml' not in parts:
        raise ValueError('missing Word document part')
    records = []
    revisions = 0
    for part in parts:
        tree = _xml(z, part)
        stem = Path(part).stem
        expected = 'hdr' if stem.startswith('header') else 'ftr' if stem.startswith('footer') else stem
        if tree.tag != W + expected:
            raise ValueError('unrecognized Word part root or namespace; Strict OOXML is not supported')
        if stem == 'document' and tree.find(W + 'body') is None:
            raise ValueError('missing Word body')
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
    return records, {'parts_read': parts, 'tracked_deletion_groups': revisions,
                     'limitations': ['不含删除修订正文', '图片未OCR', '字段未更新', '未分析完整样式继承', '未完成视觉渲染核验']}


def _xlsx(z):
    wb = _xml(z, 'xl/workbook.xml')
    rels = _xml(z, 'xl/_rels/workbook.xml.rels')
    if wb.tag != X+'workbook' or rels.tag != P+'Relationships':
        raise ValueError('unrecognized workbook or relationships namespace; Strict OOXML is not supported')
    parts_read = ['xl/workbook.xml', 'xl/_rels/workbook.xml.rels']
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
        shared = [''.join(t.text or '' for t in si.iter(X+'t')) for si in strings.iter(X+'si')]
        parts_read.append('xl/sharedStrings.xml')
    records, sheets = [], []
    for sheet in wb.iter(X+'sheet'):
        target = targets.get(sheet.get(R+'id'))
        if not target:
            raise ValueError('worksheet relationship unavailable')
        tree = _xml(z, target)
        if tree.tag != X+'worksheet':raise ValueError('unrecognized worksheet part or namespace')
        parts_read.append(target)
        info = {'name': sheet.get('name'), 'state': sheet.get('state', 'visible'), 'part': target,
                'merged_ranges': [e.get('ref') for e in tree.iter(X+'mergeCell')], 'formula_count': 0}
        for cell in tree.iter(X+'c'):
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
    return records, {'parts_read': list(dict.fromkeys(parts_read)), 'sheets': sheets,
                     'limitations': ['公式只读未重算，缓存可能过期', '日期为原始存储值，需结合格式解释',
                                     '图片与图表未视觉核验', '未完成视觉渲染核验']}


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
