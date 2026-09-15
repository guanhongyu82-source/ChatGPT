#!/usr/bin/env python3
"""Read-only delivery contract check. Declarations do not authenticate behavior.

CLI: --contract PATH; JSON state/issues; exit 0 PASS, 2 FAIL.
The host must invoke this checker to enforce a delivery boundary.
Expected artifacts come only from the locked Task Card; contract.artifacts are Actual.
"""
import argparse
import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path

NAME = re.compile(r'^\d{4}-\d{2}-\d{2}_[^_\s]+_[^_\s]{3,10}_(?:v[1-9]\d*|终)\.[^.]+$')
FORMAT = re.compile(r'^\.[A-Za-z0-9]{1,10}$')


def _load_locked_task_card(c, require):
    ref = c.get('task_card')
    require(isinstance(ref, dict), 'task_card reference required')
    if not isinstance(ref, dict):
        return None
    raw_path = ref.get('path')
    path = Path(raw_path) if isinstance(raw_path, str) else Path('.')
    valid_path = isinstance(raw_path, str) and path.is_absolute() and path.is_file()
    require(valid_path, 'task_card path must be an existing absolute file')
    if not valid_path:
        return None
    try:
        data = path.read_bytes()
        require(hashlib.sha256(data).hexdigest() == ref.get('sha256'), 'task_card changed after contract lock')
        card = json.loads(data)
        require(isinstance(card, dict), 'task_card must be an object')
        return card if isinstance(card, dict) else None
    except (OSError, ValueError, UnicodeError):
        require(False, 'task_card cannot be read or parsed')
        return None


def _expected_artifacts(c, root, require):
    card = _load_locked_task_card(c, require)
    if card is None:
        return {}
    require(card.get('task_instance_id') == c.get('task_id'), 'task_card task_instance_id does not match task_id')
    deliverables = card.get('deliverables')
    require(isinstance(deliverables, list), 'task_card deliverables must be an array')
    expected = {}
    for item in deliverables if isinstance(deliverables, list) else []:
        if not isinstance(item, dict):
            require(False, 'invalid expected deliverable')
            continue
        artifact_id = item.get('artifact_id')
        required = item.get('required')
        fmt = item.get('format')
        role = item.get('target_role')
        directory = item.get('target_directory')
        override = item.get('filename_override')
        valid_id = isinstance(artifact_id, str) and bool(artifact_id.strip()) and artifact_id not in expected
        require(valid_id, 'expected artifact_id missing or duplicated')
        require(type(required) is bool, 'expected required must be boolean: ' + str(artifact_id))
        require(isinstance(fmt, str) and FORMAT.fullmatch(fmt) is not None, 'invalid expected format: ' + str(artifact_id))
        require(isinstance(role, str) and bool(role.strip()), 'expected target_role required: ' + str(artifact_id))
        target = Path(directory) if isinstance(directory, str) else Path('.')
        valid_target = isinstance(directory, str) and target.is_absolute() and target.is_dir()
        require(valid_target, 'expected target_directory must be an existing absolute directory: ' + str(artifact_id))
        if valid_target and root.is_absolute() and root.is_dir():
            require(target.resolve().is_relative_to(root.resolve()), 'expected target_directory outside output root: ' + str(artifact_id))
        valid_override = override is None or (isinstance(override, str) and bool(override.strip())
                                             and Path(override).name == override and '/' not in override and '\\' not in override)
        require(valid_override, 'invalid filename_override: ' + str(artifact_id))
        if isinstance(override, str) and isinstance(fmt, str):
            require(Path(override).suffix.lower() == fmt.lower(), 'filename_override format mismatch: ' + str(artifact_id))
        if valid_id:
            expected[artifact_id] = item
    return expected


def check(c, contract_path=None):
    issues = []
    def require(ok, message):
        if not ok:
            issues.append(message)
    require(isinstance(c, dict), 'contract must be an object')
    if issues:
        return {'state': 'FAIL', 'issues': issues}
    require(bool(c.get('task_id')), 'task_id required')
    level = c.get('t_level')
    require(type(level) is int and 1 <= level <= 10, 'invalid t_level')
    additions = c.get('formal_normative_additions')
    require(type(additions) is bool, 'formal_normative_additions must be boolean')
    require(not additions or (type(level) is int and level >= 4), 'formal normative additions require T4+')
    for field in ('opening_notice', 'summary_present'):
        require(c.get(field) is True, field + ' required')
    require(type(c.get('incident_present')) is bool, 'incident_present must be boolean')
    require(not c.get('incident_present') or bool(str(c.get('incident_disposition', '')).strip()), 'incident disposition required')
    if c.get('incident_present') is True:
        records = c.get('incident_records')
        require(isinstance(records, list) and bool(records), 'incident record paths required')
        for name in records if isinstance(records, list) else []:
            valid = False
            if isinstance(name, str) and Path(name).is_absolute() and Path(name).is_file():
                try:
                    record = json.loads(Path(name).read_bytes())
                    valid = (isinstance(record, dict)
                             and isinstance(record.get('incident_id'), str)
                             and re.fullmatch(r'INC-[0-9a-f]{32}', record['incident_id']) is not None
                             and record.get('permission') == 'record'
                             and isinstance(record.get('failure_type'), str)
                             and bool(record['failure_type'].strip())
                             and isinstance(record.get('evidence'), list)
                             and bool(record['evidence']))
                except (OSError, ValueError, UnicodeError):
                    valid = False
            require(valid, 'missing or invalid existing incident record')
    timing = c.get('timing', {})
    if not isinstance(timing, dict):
        timing = {}
    start, end = timing.get('started_at'), timing.get('ended_at')
    if start and end:
        try:
            a, b = (datetime.fromisoformat(v.replace('Z', '+00:00')) for v in (start, end))
            require(a.tzinfo is not None and b.tzinfo is not None and b >= a, 'invalid timing interval')
            require(bool(timing.get('basis')), 'timing basis required')
        except (TypeError, ValueError, AttributeError):
            issues.append('invalid timing timestamps')
    else:
        require(bool(timing.get('unavailable_reason')), 'timing unavailable reason required')
    storage = c.get('storage', {})
    if not isinstance(storage, dict):
        storage = {}
    root = Path(storage.get('output_root') or '.')
    require(root.is_absolute() and root.is_dir(), 'output_root must be an existing absolute directory')
    require(storage.get('archive_status') in ('done', 'not_applicable', 'deferred'), 'archive status required')
    require(storage.get('archive_status') != 'deferred' or bool(storage.get('archive_reason')), 'deferred archive reason required')
    # done is checked against a declared archive root, not inferred from a label.
    if storage.get('archive_status') == 'done':
        archive = Path(storage.get('archive_root') or '.')
        require(archive.is_absolute() and archive.is_dir() and root.resolve().is_relative_to(archive.resolve()), 'archive root does not contain output root')

    expected = _expected_artifacts(c, root, require)
    artifacts = c.get('artifacts')
    require(isinstance(artifacts, list), 'artifact manifest must be an array')
    hashes = {}
    actual_ids = set()
    for item in artifacts if isinstance(artifacts, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get('path'), str):
            issues.append('invalid artifact entry')
            continue
        artifact_id = item.get('artifact_id')
        valid_actual_id = isinstance(artifact_id, str) and bool(artifact_id.strip()) and artifact_id not in actual_ids
        require(valid_actual_id, 'actual artifact_id missing or duplicated')
        if valid_actual_id:
            actual_ids.add(artifact_id)
        spec = expected.get(artifact_id) if isinstance(artifact_id, str) else None
        require(spec is not None, 'unauthorized actual artifact: ' + str(artifact_id))
        p = Path(item['path'])
        require(p.is_absolute() and p.is_file(), 'artifact missing or relative: ' + str(p))
        require(p.resolve().is_relative_to(root.resolve()), 'artifact outside output root: ' + str(p))
        if spec is not None:
            target = Path(spec.get('target_directory') or '.')
            require(p.parent.resolve() == target.resolve(), 'artifact in wrong target directory: ' + str(artifact_id))
            require(p.suffix.lower() == str(spec.get('format', '')).lower(), 'artifact format mismatch: ' + str(artifact_id))
            require(item.get('role') == spec.get('target_role'), 'artifact role mismatch: ' + str(artifact_id))
            override = spec.get('filename_override')
            if override is not None:
                require(p.name == override, 'artifact filename does not match locked override: ' + str(artifact_id))
            else:
                require(bool(NAME.fullmatch(p.name)), 'artifact filename not normalized: ' + p.name)
        if p.is_file():
            digest = hashlib.sha256(p.read_bytes()).hexdigest()
            require(digest == item.get('sha256'), 'artifact hash mismatch: ' + str(p))
            hashes[str(p)] = digest
    for artifact_id, spec in expected.items():
        if spec.get('required') is True:
            require(artifact_id in actual_ids, 'required expected artifact missing: ' + artifact_id)

    required = 2 if type(level) is int and level >= 7 else (1 if type(level) is int and level >= 4 else 0)
    reviewers = set()
    reviews = c.get('reviews', [])
    require(isinstance(reviews, list), 'reviews must be array')
    for review in reviews if isinstance(reviews, list) else []:
        if not isinstance(review, dict):
            issues.append('invalid review')
            continue
        reviewer, author = review.get('reviewer_id'), review.get('author_id')
        evidence = Path(review.get('evidence_path') or '.')
        valid = (isinstance(reviewer, str) and bool(reviewer.strip()) and isinstance(author, str)
                 and bool(author.strip()) and reviewer != author and evidence.is_absolute()
                 and evidence.is_file() and evidence.stat().st_size > 0
                 and review.get('candidate_sha256') == hashes and bool(hashes)
                 and review.get('verdict') == 'PASS' and review.get('must_fix') == [])
        # Read exactly the bytes whose digest is checked; mutable external
        # verdict declarations cannot override the recorded review decision.
        if valid:
            try:
                data = evidence.read_bytes()
                recorded = json.loads(data)
                fields = ('reviewer_id', 'author_id', 'verdict', 'must_fix', 'candidate_sha256', 'source_ref')
                valid = (hashlib.sha256(data).hexdigest() == review.get('evidence_sha256')
                         and isinstance(recorded, dict)
                         and all(recorded.get(key) == review.get(key) for key in fields)
                         and isinstance(recorded.get('source_ref'), str)
                         and bool(recorded['source_ref'].strip()))
            except (OSError, ValueError, UnicodeError):
                valid = False
        require(valid, 'missing, changed, or inconsistent independent review JSON evidence')
        if valid:
            reviewers.add(reviewer)
    require(len(reviewers) >= required, 'insufficient independent reviews')
    retention = c.get('retention', {})
    if not isinstance(retention, dict):
        retention = {}
    temporary = retention.get('temporary_files')
    reasons = retention.get('retained_reason', {})
    require(isinstance(temporary, list) and isinstance(reasons, dict), 'temporary inventory required')
    for name in temporary if isinstance(temporary, list) else []:
        if not isinstance(name, str) or not Path(name).is_absolute():
            issues.append('invalid temporary path')
        elif Path(name).exists():
            require(isinstance(reasons, dict) and bool(reasons.get(name)), 'unjustified temporary file: ' + name)
    # Inspect only the declared task process root and immediate output children.
    # Do not follow directory symlinks into other tasks or roots.
    excluded = Path(contract_path).resolve() if contract_path else None
    reasons = reasons if isinstance(reasons, dict) else {}
    registered = set(name for name in (temporary if isinstance(temporary, list) else []) if isinstance(name, str))
    registered.update(name for name, reason in reasons.items() if isinstance(name, str) and isinstance(reason, str) and reason.strip())
    require('process_root' in retention, 'process_root declaration required')
    process = retention.get('process_root')
    if process is not None:
        valid_root = isinstance(process, str) and Path(process).is_absolute() and Path(process).is_dir() and not Path(process).is_symlink()
        require(valid_root, 'invalid task process root')
        if valid_root:
            process_path = Path(process)
            # A task-specific directory must not be the entire output/root tree.
            safe_root = (process_path.resolve() != root.resolve()
                         and process_path.resolve() not in root.resolve().parents
                         and process_path.name not in ('workspace', 'maintenance'))
            require(safe_root, 'process_root must be task-specific')
            if safe_root:
                for base, dirs, files in os.walk(process_path, followlinks=False):
                    links = [d for d in dirs if (Path(base) / d).is_symlink()]
                    for name in files + links:
                        path = Path(base) / name
                        if excluded is None or path.resolve() != excluded:
                            require(str(path) in registered, 'unlisted process file: ' + str(path))
    if root.is_absolute() and root.is_dir():
        for path in root.iterdir():
            if excluded is not None and path.resolve() == excluded:
                continue
            listed = str(path) in hashes
            if path.is_dir():
                listed = any(Path(name).is_relative_to(path) for name in hashes)
            require(listed or bool(reasons.get(str(path))), 'unlisted output item: ' + str(path))
    return {'state': 'FAIL' if issues else 'PASS', 'issues': issues}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--contract', required=True, type=Path)
    args = parser.parse_args()
    try:
        result = check(json.loads(args.contract.read_text(encoding='utf-8')), contract_path=args.contract)
    except (OSError, ValueError, TypeError) as exc:
        result = {'state': 'FAIL', 'issues': ['contract read/check failed: ' + type(exc).__name__]}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['state'] == 'PASS' else 2


if __name__ == '__main__':
    raise SystemExit(main())
