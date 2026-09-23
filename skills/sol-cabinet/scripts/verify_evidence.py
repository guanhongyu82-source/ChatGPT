#!/usr/bin/env python3
"""Read candidate-bound local evidence. Hashes prove consistency, not identity.

Records and source logs must come from a trusted executor/review capture process.
Locally editable JSON cannot authenticate a model, reviewer, or user authorization.
This module never executes evidence or writes persistent records.
"""
from __future__ import annotations
import hashlib
import json
import re
import unicodedata
from pathlib import Path

ID = re.compile(r'^(?:testrun|review)-[0-9a-f]{32}$')
SHA = re.compile(r'^[0-9a-f]{64}$')


def _file(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or '..' in Path(relative).parts:
        raise ValueError('unsafe evidence path')
    path = root / relative
    if root.is_symlink() or any((root / Path(*Path(relative).parts[:i])).is_symlink() for i in range(1, len(Path(relative).parts) + 1)):
        raise ValueError('evidence symlinks are forbidden')
    if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('evidence file missing or outside evidence directory')
    return path


def _identity(value: object) -> bool:
    # Tool-provided opaque identities are data, never filesystem paths.
    return (isinstance(value, str) and 1 <= len(value) <= 256
            and bool(value.strip())
            and not any(unicodedata.category(char).startswith('C') for char in value))


def verify_evidence(evidence_dir: Path, candidate_sha256: str, test_run_id: str,
                    review_ids: list[str], required_test_ids: list[str], *,
                    minimum_reviewers: int = 2, require_post_apply: bool = False) -> dict:
    """Verify actual records/log bytes and independent recorded reviewer identities."""
    if not isinstance(candidate_sha256, str) or not SHA.fullmatch(candidate_sha256):
        raise ValueError('invalid candidate hash')
    if not isinstance(review_ids, list) or not all(isinstance(v, str) for v in review_ids):
        raise ValueError('review IDs must be strings')
    if len(review_ids) != len(set(review_ids)) or len(review_ids) < minimum_reviewers:
        raise ValueError('missing or duplicate reviews')
    records = []
    for record_id in [test_run_id, *review_ids]:
        if not isinstance(record_id, str) or not ID.fullmatch(record_id):
            raise ValueError('invalid evidence ID')
        record = json.loads(_file(evidence_dir, record_id + '.json').read_text(encoding='utf-8'))
        expected_kind = 'test' if record_id == test_run_id else 'review'
        if not record_id.startswith('testrun-' if expected_kind == 'test' else 'review-'):
            raise ValueError('evidence ID type mismatch')
        if not isinstance(record, dict) or record.get('record_id') != record_id or record.get('kind') != expected_kind:
            raise ValueError('evidence identity or type mismatch')
        if record.get('candidate_sha256') != candidate_sha256 or record.get('verdict') != 'PASS':
            raise ValueError('evidence failed or candidate is stale')
        if record.get('error_type') is not None:
            raise ValueError('passing evidence must not contain an error')
        if record.get('source') != 'executor-capture':
            raise ValueError('evidence requires executor capture provenance')
        log = _file(evidence_dir, record.get('artifact_path'))
        data = log.read_bytes()
        if not data or hashlib.sha256(data).hexdigest() != record.get('artifact_sha256'):
            raise ValueError('evidence artifact hash mismatch or empty artifact')
        records.append(record)
    test = records[0]
    if type(test.get('exit_code')) is not int or test['exit_code'] != 0:
        raise ValueError('test execution failed')
    results = test.get('test_results')
    if not isinstance(results, dict) or not required_test_ids or any(results.get(t) != 'PASS' for t in required_test_ids) or any(v != 'PASS' for v in results.values()):
        raise ValueError('required tests missing or test run contains failures')
    if require_post_apply and test.get('phase') != 'post-apply':
        raise ValueError('post verification requires a post-apply execution record')
    reviewers = [r.get('reviewer_id') for r in records[1:]]
    if any(not _identity(r) for r in reviewers):
        raise ValueError('reviewer identity missing or invalid')
    if len(set(reviewers)) != len(reviewers):
        raise ValueError('reviews must have distinct recorded reviewers')
    for record in records[1:]:
        if not isinstance(record.get("must_fix"), list) or record["must_fix"]:
            raise ValueError("review requires an explicit empty must_fix array")
        if record.get('independent') is not True or record.get('reviewer_id') == record.get('author_id') or not _identity(record.get('author_id')):
            raise ValueError('review must record an independent author and reviewer')
    return {'verdict': 'PASS', 'test_run_id': test_run_id, 'review_ids': review_ids}
