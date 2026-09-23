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
import uuid
import copy
import contextlib
import fcntl
from datetime import datetime
from pathlib import Path
from maintenance_boundary import guarded, require_owned
from sync_agent_runtime import _atomic_regular_write

NAME = re.compile(r'^\d{4}-\d{2}-\d{2}_[^_\s]+_[^_\s]{3,10}_(?:v[1-9]\d*|终)\.[^.]+$')
FORMAT = re.compile(r'^\.[A-Za-z0-9]{1,10}$')
TASK_ROOT_NAME = re.compile(r'^(?P<date>\d{4}-\d{2}-\d{2})_(?P<subject>[^/\\\x00-\x1f]+)$')
FORMAL_NAME = re.compile(r'^(?P<date>\d{4}-\d{2}-\d{2})_.+_(?P<version>v[1-9]\d*)\.[^.]+$')
TEMPORARY_ROOT_NAMES = frozenset({'new-chat', 'temp', 'tmp', 'untitled', 'working', '未命名', '临时'})
FINALIZATION_GATES = (
    'content', 'deliverables', 'original_inputs', 'work_evidence',
    'task_root_archive', 'temporary_residue', 'version_continuity',
    'material_traceability', 'final_path', 'final_validation',
    'delivery_contract',
)


def _temporary_subject(subject):
    value = subject.strip().casefold()
    return (value in TEMPORARY_ROOT_NAMES
            or re.fullmatch(r'(?:new-chat|temp|tmp|untitled|working|final)[-_ ]?\d+', value) is not None
            or re.fullmatch(r'(?:未命名|临时)[-_ ]?\d+', value) is not None
            or value in {'最终版最新版', '最新版'})


def task_root_name(last_substantive_date, subject):
    """Return the one-work task-root name without creating or renaming anything."""
    if not isinstance(last_substantive_date, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', last_substantive_date):
        raise ValueError('last_substantive_date must be an ISO date')
    try:
        datetime.fromisoformat(last_substantive_date)
    except ValueError as exc:
        raise ValueError('last_substantive_date must be a valid ISO date') from exc
    if not isinstance(subject, str) or not subject.strip() or '/' in subject or '\\' in subject:
        raise ValueError('task subject must be a non-empty directory-safe string')
    name = f'{last_substantive_date}_{subject.strip()}'
    if _temporary_subject(subject):
        raise ValueError('temporary task-root names are not allowed')
    return name


def formal_version_number(path):
    """Return the numeric formal version encoded in a filename, or None."""
    match = FORMAL_NAME.fullmatch(Path(path).name)
    return int(match.group('version')[1:]) if match else None


def highest_formal_version(output_root):
    """Read the highest existing formal version from one outputs directory."""
    root = Path(output_root)
    if not root.is_dir() or root.is_symlink():
        raise ValueError('output_root must be a real directory')
    versions = [formal_version_number(path) for path in root.iterdir() if path.is_file()]
    versions = [value for value in versions if value is not None]
    return max(versions, default=0)


def next_formal_version(output_root):
    """Return the next formal version without reserving or creating a file."""
    return f'v{highest_formal_version(output_root) + 1}'


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


def _expected_artifacts(c, root, require, card=None):
    card = card if card is not None else _load_locked_task_card(c, require)
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


def _check_lifecycle(c, root, archive, card, contract_path, require):
    """Check the explicit one-work lifecycle when a task claims final archive."""
    lifecycle = c.get('lifecycle')
    require(isinstance(lifecycle, dict), 'final archive requires lifecycle declaration')
    if not isinstance(lifecycle, dict):
        return set()

    task_root_raw = lifecycle.get('task_root')
    task_root = Path(task_root_raw) if isinstance(task_root_raw, str) else Path('.')
    valid_task_root = (
        isinstance(task_root_raw, str)
        and task_root.is_absolute()
        and task_root.is_dir()
        and not task_root.is_symlink()
    )
    require(valid_task_root, 'task_root must be an existing absolute real directory')
    if not valid_task_root:
        return set()
    task_root = task_root.resolve()
    match = TASK_ROOT_NAME.fullmatch(task_root.name)
    require(match is not None, 'task_root name must be YYYY-MM-DD_<subject>')
    if match is None:
        return set()
    root_date = match.group('date')
    require(not _temporary_subject(match.group('subject')),
            'temporary task-root name is not allowed')
    require(lifecycle.get('task_id') == c.get('task_id'), 'lifecycle task_id does not match contract task_id')
    require(lifecycle.get('last_substantive_date') == root_date,
            'task_root date must equal last substantive work date')
    require(lifecycle.get('state') == 'DELIVERED', 'final archive requires lifecycle state DELIVERED')
    require(root.is_absolute() and root.resolve().is_relative_to(task_root),
            'output_root must be inside task_root')
    require(root.name == 'outputs', 'final archive output_root must be task_root/outputs')
    require(task_root.is_relative_to(archive.resolve()), 'archive root must contain task_root')
    retention = c.get('retention') if isinstance(c.get('retention'), dict) else {}
    process_root = Path(retention.get('process_root') or '.')
    require(process_root.is_absolute() and process_root.is_dir()
            and process_root.resolve() == (task_root / 'work').resolve(),
            'final archive process_root must be task_root/work')

    allowed_children = {'00_原稿', 'work', 'outputs'}
    children = list(task_root.iterdir())
    require((task_root / 'work').is_dir() and not (task_root / 'work').is_symlink(),
            'task_root work directory is required')
    for child in children:
        require(child.name in allowed_children, 'unknown task-root item: ' + str(child))
        require(not child.is_symlink(), 'task-root child may not be a symlink: ' + str(child))

    if card is not None:
        card_lifecycle = card.get('lifecycle')
        require(isinstance(card_lifecycle, dict), 'task card lifecycle declaration required')
        if isinstance(card_lifecycle, dict):
            require(card_lifecycle.get('task_root') == str(task_root),
                    'task card task_root does not match contract lifecycle')
            require(card_lifecycle.get('last_substantive_date') == root_date,
                    'task card last_substantive_date does not match task_root')
        card_path = Path(c.get('task_card', {}).get('path') or '.')
        require(card_path.is_absolute() and card_path.is_file()
                and card_path.resolve().is_relative_to(task_root),
                'task card must be retained inside task_root')

    from archive_originals import _parse_manifest
    manifest_raw = lifecycle.get('material_manifest')
    manifest_path = Path(manifest_raw) if isinstance(manifest_raw, str) else None
    batch_ids = set()
    archive_dir = task_root / '00_原稿'
    if manifest_path is None:
        require(lifecycle.get('original_inputs_state') == 'NOT_APPLICABLE',
                'material manifest required when inputs are applicable')
        require(not archive_dir.exists() or not any(archive_dir.iterdir()),
                'unregistered originals cannot be NOT_APPLICABLE')
    else:
        require(manifest_path == archive_dir / '原稿清单.json', 'material manifest path must be canonical')
        try:
            _regular(manifest_path, archive_dir)
            fd = os.open(archive_dir, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
            try:
                manifest = _parse_manifest(fd)
            finally:
                os.close(fd)
            require(manifest['archive_state'] == 'PASS', 'material archive must pass')
            batch_ids = {b['batch_id'] for b in manifest['batches']}
            allowed = {'原稿清单.json'} | {Path(r['archived_relative_path']).name for r in manifest['files']}
            require({p.name for p in archive_dir.iterdir()} == allowed, 'unknown original archive item')
        except (OSError, ValueError, TypeError, KeyError) as exc:
            require(False, 'original archive invalid: ' + str(exc))
    versions = lifecycle.get('formal_versions')
    require(isinstance(versions, list) and bool(versions), 'formal version history is required')
    version_numbers = []
    lifecycle_paths = set()
    if isinstance(versions, list):
        for entry in versions:
            if not isinstance(entry, dict):
                require(False, 'invalid formal version entry')
                continue
            version = entry.get('version')
            formed_date = entry.get('formed_date')
            material_batches = entry.get('material_batches')
            formal_artifacts = entry.get('artifacts')
            number = int(version[1:]) if isinstance(version, str) and re.fullmatch(r'v[1-9]\d*', version) else None
            require(number is not None, 'formal version id is invalid')
            require(isinstance(formed_date, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', formed_date) is not None,
                    'formal version formed_date is invalid')
            require(isinstance(material_batches, list) and bool(material_batches),
                    'formal version material_batches are required')
            if isinstance(material_batches, list):
                for batch_id in material_batches:
                    if manifest_path is not None:
                        require(batch_id in batch_ids, 'formal version references unknown material batch')
                    else:
                        require(batch_id == 'NOT_APPLICABLE',
                                'no-input formal version must use NOT_APPLICABLE batch')
            require(isinstance(formal_artifacts, list) and bool(formal_artifacts),
                    'formal version artifacts are required')
            if number is not None:
                version_numbers.append(number)
            if isinstance(formal_artifacts, list):
                for artifact in formal_artifacts:
                    if not isinstance(artifact, dict):
                        require(False, 'invalid formal version artifact')
                        continue
                    path_value = artifact.get('path')
                    path = Path(path_value) if isinstance(path_value, str) else Path('.')
                    valid_path = (isinstance(path_value, str) and path.is_absolute()
                                  and path.is_file() and path.resolve().is_relative_to(root.resolve()))
                    require(valid_path, 'formal version artifact is missing or outside outputs')
                    digest = artifact.get('sha256')
                    require(isinstance(digest, str) and re.fullmatch(r'[0-9a-f]{64}', digest) is not None,
                            'formal version artifact hash is invalid')
                    if valid_path:
                        require(hashlib.sha256(path.read_bytes()).hexdigest() == digest,
                                'formal version artifact hash mismatch: ' + str(path))
                        path_number = formal_version_number(path)
                        require(path_number == number, 'formal version filename does not match history')
                        require(isinstance(formed_date, str) and path.name.startswith(formed_date + '_'),
                                'formal version filename date does not match history')
                        lifecycle_paths.add(str(path))
    require(sorted(version_numbers) == list(range(1, max(version_numbers, default=0) + 1)),
            'formal versions must be continuous from v1')
    current_version = lifecycle.get('current_version')
    if version_numbers:
        require(current_version == f'v{max(version_numbers)}', 'current_version must be highest formal version')
        require(highest_formal_version(root) == max(version_numbers),
                'outputs contains a missing or unregistered formal version')

    finalization = lifecycle.get('finalization_gates')
    require(isinstance(finalization, dict) and set(finalization) == set(FINALIZATION_GATES),
            'all FINAL PASS gates must be declared exactly once')
    if isinstance(finalization, dict):
        for gate_name in FINALIZATION_GATES:
            require(finalization.get(gate_name) == 'PASS', 'finalization gate is not PASS: ' + gate_name)
    require(lifecycle.get('final_validation') == 'PASS', 'final_validation must be PASS')
    if contract_path is None:
        require(False, 'final delivery contract path is required')
    else:
        contract = Path(contract_path).resolve()
        require(contract.is_file() and contract.is_relative_to(task_root),
                'delivery contract must be retained inside task_root')
    return lifecycle_paths


def check_components(c, contract_path=None):
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

    card = _load_locked_task_card(c, require)
    expected = _expected_artifacts(c, root, require, card=card)
    require(bool(expected), 'file delivery requires at least one expected artifact; use analysis-only for no-file tasks')
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

    lifecycle_paths = set()
    if storage.get('archive_status') == 'done':
        archive = Path(storage.get('archive_root') or '.')
        if archive.is_absolute() and archive.is_dir() and root.is_absolute() and root.is_dir():
            lifecycle_paths = _check_lifecycle(c, root, archive, card, contract_path, require)

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
            listed = str(path) in hashes or str(path) in lifecycle_paths
            if path.is_dir():
                listed = any(Path(name).is_relative_to(path) for name in hashes)
            require(listed or (storage.get('archive_status') != 'done' and bool(reasons.get(str(path)))),
                    'unlisted output item: ' + str(path))
    return {'state': 'FAIL' if issues else 'PASS', 'issues': issues}


def _json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _save(path, value):
    _atomic_regular_write(Path(path), (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode(), 0o600)


def _save_new(path, value):
    data = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _owned_save(path, value, tracker, *, new=False):
    path = Path(path)
    key = str(path)
    if new:
        _save_new(path, value)
        tracker['delete'].add(key)
    else:
        if not path.is_file() or _sha(path) not in tracker['hashes'].get(key, set()):
            raise RuntimeError('concurrent write detected; refusing overwrite')
        _save(path, value)
    tracker['hashes'].setdefault(key, set()).add(_sha(path))


def _regular(path, root):
    path = Path(path)
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise ValueError('expected a real absolute file')
    if not path.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError('file escapes task root')
    if any(p.is_symlink() for p in path.parents):
        raise ValueError('symlink parent is not allowed')
    return path


def _root(path):
    root = Path(path).absolute()
    require_owned(root)
    if not root.is_dir() or any(p.is_symlink() for p in [root, *root.parents]):
        raise ValueError('task root must be an existing real directory')
    if root.name in ('workspace', 'ChatGPT', 'work', 'outputs', '.scratch'):
        raise ValueError('a concrete task root is required')
    return root


@contextlib.contextmanager
def _task_lock(root):
    # flock on the directory inode survives an in-place root rename; no lock artifact.
    fd = os.open(root, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def _history(card, root):
    lc = card['lifecycle']
    info = root.stat()
    if lc['root_identity'] != [info.st_dev, info.st_ino]:
        raise ValueError('task root identity changed: copied task is not a reopen')
    versions = lc['formal_versions']
    manifest_path = root / '00_原稿/原稿清单.json'
    if manifest_path.exists():
        from archive_originals import _parse_manifest
        fd = os.open(manifest_path.parent, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        try:
            manifest = _parse_manifest(fd)
        finally:
            os.close(fd)
    else:
        manifest = {'batches': [], 'files': []}
    if [v['version'] for v in versions] != [f'v{i + 1}' for i in range(len(versions))]:
        raise ValueError('formal history is not continuous')
    for entry in versions:
        report = _regular(root / 'work' / ('finalization-' + entry['version'] + '.json'), root)
        receipt = _json(report)
        contract_path = _regular(root / 'work' / ('delivery-' + entry['version'] + '.json'), root)
        historical_contract = _json(contract_path)
        if (receipt.get('task_id') != card['task_instance_id']
                or receipt.get('version_record') != entry or receipt.get('state') != 'PASS'):
            raise ValueError('formal version history differs from retained delivery receipt')
        if (_sha(contract_path) != receipt.get('contract_sha256')
                or historical_contract.get('task_id') != card['task_instance_id']
                or historical_contract.get('lifecycle', {}).get('current_version') != entry['version']):
            raise ValueError('historical delivery contract differs from retained receipt')
        for artifact in entry['artifacts']:
            path = _regular(root / artifact['relative_path'], root / 'outputs')
            if _sha(path) != artifact['sha256']:
                raise ValueError('historical delivered artifact changed')
        snapshot = entry.get('material_snapshot')
        if not isinstance(snapshot, dict):
            raise ValueError('historical material snapshot is missing')
        selected = set(entry['material_batches'])
        actual_batches = [b for b in manifest['batches'] if b['batch_id'] in selected]
        paths = {p for b in actual_batches for p in b['record_paths']}
        actual_files = [f for f in manifest['files'] if f['archived_relative_path'] in paths]
        if snapshot != {'batches': actual_batches, 'files': actual_files}:
            raise ValueError('historical original records or material batches changed')
    return versions


@guarded
def prepare_task(task_root, subject, work_date, inputs=(), *, revision=False):
    """Reopen one task, classify declared inputs and archive bytes; never create a second root.

    The assistant supplies semantic roles from the user's message. Uncertain roles
    remain unresolved in the existing Task Card, including files outside the root.
    """
    from archive_originals import archive_originals, _parse_manifest, UNKNOWN_ROLES
    root = _root(task_root)
    desired_name = task_root_name(work_date, subject)
    with _task_lock(root):
        for name in ('work', 'outputs', '00_原稿'):
            child = root / name
            if child.is_symlink() or (child.exists() and not child.is_dir()):
                raise ValueError('task partition is not a real directory')
        (root / 'work').mkdir(exist_ok=True)
        card_path = root / 'work/task-card.json'
        if card_path.exists():
            card = _json(_regular(card_path, root))
            _history(card, root)
        else:
            if (root / 'outputs').exists() and any((root / 'outputs').iterdir()):
                raise ValueError('existing formal files need explicit history adoption; do not invent delivery facts')
            card = {'schema_version': 2, 'task_instance_id': 'task-' + uuid.uuid4().hex,
                    'deliverables': [], 'lifecycle': {
                        'task_root': str(root), 'root_identity': [root.stat().st_dev, root.stat().st_ino],
                        'last_substantive_date': work_date, 'state': 'ACTIVE',
                        'reopen_count': 0, 'formal_versions': [], 'current_version': None,
                        'unresolved_inputs': [], 'material_batches': []}}
        lc = card['lifecycle']
        if work_date < lc['last_substantive_date']:
            raise ValueError('substantive date cannot go backwards')
        inputs = [dict(item) for item in inputs]
        supplied = {str(Path(item['path']).absolute()) for item in inputs}
        for child in root.iterdir():
            if child.name not in ('work', 'outputs', '00_原稿') and str(child) not in supplied:
                inputs.append({'path': str(child), 'role': 'unknown'})
        pending = {item['path']: item for item in lc.get('unresolved_inputs', [])}
        known = []
        for item in inputs:
            path = Path(item['path']).absolute()
            role = item.get('role', 'unknown')
            if (not isinstance(role, str) or role.strip().casefold() in UNKNOWN_ROLES
                    or not path.is_file() or path.is_symlink()):
                pending[str(path)] = {'path': str(path), 'reason': 'classification-required'}
            else:
                pending.pop(str(path), None)
                known.append((role, path, item.get('supersedes')))
        lc['unresolved_inputs'] = list(pending.values())
        if pending:
            _save(card_path, card)
            return {'state': 'BLOCKED', 'task_id': card['task_instance_id'],
                    'task_root': str(root), 'unresolved_inputs': lc['unresolved_inputs']}
        prior_hashes = set()
        manifest_path = root / '00_原稿/原稿清单.json'
        if manifest_path.exists():
            fd = os.open(manifest_path.parent, os.O_RDONLY)
            try:
                prior_hashes = {x['source_sha256'] for x in _parse_manifest(fd)['files']}
            finally:
                os.close(fd)
        changed = revision or any(_sha(p) not in prior_hashes for _, p, _ in known)
        effective_date = work_date if changed else lc['last_substantive_date']
        # A wording-only title request does not move a delivered root or invalidate receipts.
        desired = (root.with_name(task_root_name(effective_date, subject))
                   if changed or not lc['formal_versions'] else root)
        if desired != root:
            if desired.exists():
                raise FileExistsError('task root destination already exists; preserve both')
            old_root = root
            # All valid source locations are established before rename.
            root.rename(desired)
            root = desired
            known = [(role, root / p.relative_to(old_root) if p.is_relative_to(old_root) else p, supersedes)
                     for role, p, supersedes in known]
        card_path = root / 'work/task-card.json'
        lc.update(task_root=str(root), last_substantive_date=effective_date)
        if changed and lc['state'] == 'DELIVERED':
            lc.update(state='REOPENED', reopen_count=lc['reopen_count'] + 1)
        # Persist the new root binding before potentially failing intake.
        _save(card_path, card)
        (root / 'outputs').mkdir(exist_ok=True)
        if known:
            relations = {str(p): supersedes for _, p, supersedes in known if supersedes}
            result = archive_originals(root, [(role, p) for role, p, _ in known],
                                       allow_test_output=True, batch_date=work_date,
                                       supersedes=relations)
            # Root-level uploads with a known role are preserved under work after byte archive.
            for _, p, _ in known:
                if p.parent == root:
                    received = root / 'work/received'
                    received.mkdir(exist_ok=True)
                    target = received / (uuid.uuid4().hex[:8] + '_' + p.name)
                    p.rename(target)
        else:
            result = {'new_count': 0, 'duplicate_count': 0, 'batch_id': None}
        manifest_path = root / '00_原稿/原稿清单.json'
        lc['material_manifest'] = str(manifest_path) if manifest_path.exists() else None
        lc['material_batches'] = [b['batch_id'] for b in _json(manifest_path)['batches']] if manifest_path.exists() else []
        _save(card_path, card)
        return {'state': 'READY', 'task_id': card['task_instance_id'], 'task_root': str(root),
                'task_card': str(card_path), 'next_version': f"v{len(lc['formal_versions']) + 1}",
                **result}


def _check_final_evidence(c, root, require):
    expected = {item['path']: item['sha256'] for item in c['artifacts']}
    for kind in ('content', 'final_validation'):
        ref = c.get('validation_evidence', {}).get(kind, {})
        try:
            path = _regular(ref['path'], root / 'work')
            data = path.read_bytes()
            record = json.loads(data)
            valid = (hashlib.sha256(data).hexdigest() == ref['sha256']
                     and record.get('verdict') == 'PASS' and record.get('must_fix') == []
                     and record.get('candidate_sha256') == expected
                     and bool(record.get('source_ref')) and bool(record.get('checks')))
        except (OSError, ValueError, KeyError, TypeError):
            valid = False
        require(valid, kind + ' final-path evidence missing or inconsistent')


def check(c, contract_path=None):
    """Final delivery gate: legacy component PASS alone never certifies finalization."""
    try:
        result = check_components(c, contract_path)
        issues = result['issues']
        def require(ok, message):
            if not ok:
                issues.append(message)
        require(c.get('storage', {}).get('archive_status') == 'done',
                'finalization requires completed Task Root Archive')
        lc = c.get('lifecycle', {})
        require(bool(lc), 'finalization lifecycle required')
        if lc:
            root = _root(lc['task_root'])
            path = _regular(contract_path, root / 'work')
            require(_json(path) == c, 'contract bytes differ from checked value')
            card = _json(_regular(c['task_card']['path'], root / 'work'))
            require(not card['lifecycle'].get('unresolved_inputs'), 'unresolved inputs block Archive')
            history = _history(card, root)
            expanded = copy.deepcopy(history)
            for entry in expanded:
                for artifact in entry['artifacts']:
                    artifact['path'] = str(root / artifact.pop('relative_path'))
            require(expanded == lc['formal_versions'], 'contract history differs from retained Task Card')
            require(card['lifecycle']['current_version'] == lc['current_version'], 'current version differs')
            require(card['lifecycle']['state'] == 'DELIVERED', 'task has not finalized')
            require(root / 'outputs' == Path(c['storage']['output_root']), 'outputs must be direct task partition')
            current = expanded[-1]
            require({a['path'] for a in current['artifacts']} == {a['path'] for a in c['artifacts']},
                    'current version must exactly match Actual deliverables')
            require(set(current['material_batches']) == set(card['lifecycle']['material_batches'] or ['NOT_APPLICABLE']),
                    'current version omits an effective material batch')
            # Historical files and known inputs are verified before report acceptance.
            for item in c['artifacts']:
                _regular(item['path'], root / 'outputs')
            _check_final_evidence(c, root, require)
            report = _json(_regular(root / 'work' / ('finalization-' + lc['current_version'] + '.json'), root))
            require(report.get('contract_sha256') == _sha(path), 'finalization report is not bound to final contract')
            require(report.get('task_root') == str(root), 'finalization report records an old path')
            require(report.get('gates') == lc['finalization_gates'], 'finalization report gates differ')
            # No reason string, nested directory or contract exclusion may whitelist process output.
            allowed = {str(p) for p in root.joinpath('outputs').iterdir()
                       if p.is_file() and not p.is_symlink()}
            recorded = {a['path'] for v in expanded for a in v['artifacts']}
            require(allowed == recorded and len(list((root / 'outputs').iterdir())) == len(recorded),
                    'outputs contains undeclared files, links or directories')
        return {'state': 'FAIL' if issues else 'PASS', 'issues': issues}
    except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError) as exc:
        return {'state': 'FAIL', 'issues': ['finalization check failed: ' + str(exc)]}


def _publish_version(task_card, candidates, evidence, *, formed_date, t_level=3, reviews=(), tracker=None):
    """Publish new bytes once, using caller-supplied final-path content/technical evidence.

    Candidates are files in work with artifact_id and filename. Evidence is captured
    after final paths are fixed; the provided candidate hashes must match those paths.
    Failed publication remains visibly pending for repair, never delivered.
    """
    card_path = Path(task_card)
    root = _root(card_path.parent.parent)
    with contextlib.nullcontext():
        card = _json(_regular(card_path, root / 'work'))
        lc = card['lifecycle']
        history = _history(card, root)
        if lc.get('unresolved_inputs') or lc['state'] not in ('ACTIVE', 'REOPENED'):
            raise ValueError('task must be ready/reopened with no unresolved inputs')
        if formed_date != lc['last_substantive_date'] or root.name[:10] != formed_date:
            raise ValueError('prepare task at substantive formation date before publish')
        version = f'v{len(history) + 1}'
        if highest_formal_version(root / 'outputs') != len(history):
            raise ValueError('outputs history differs from Task Card')
        artifacts, expected, plans = [], [], []
        for item in candidates:
            source = _regular(item['path'], root / 'work')
            name = item['filename']
            if Path(name).name != name or formal_version_number(name) != len(history) + 1 or not name.startswith(formed_date + '_'):
                raise ValueError('candidate filename is not the next formal version')
            target = root / 'outputs' / name
            if target.exists() or target.is_symlink():
                raise FileExistsError('formal artifact destination exists')
            artifact = {'artifact_id': item['artifact_id'], 'role': 'final',
                        'path': str(target), 'sha256': _sha(source)}
            artifacts.append(artifact)
            expected.append({'artifact_id': item['artifact_id'], 'required': True,
                             'format': target.suffix, 'target_role': 'final',
                             'target_directory': str(target.parent), 'filename_override': name})
            plans.append((source, target))
        if not artifacts or len({a['path'] for a in artifacts}) != len(artifacts):
            raise ValueError('unique publish artifacts required')
        if not callable(evidence):
            raise ValueError('final-path validator callback required')
        for source, target in plans:
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(source.read_bytes())
                stream.flush()
                os.fsync(stream.fileno())
            tracker['delete'].add(str(target))
            tracker['hashes'].setdefault(str(target), set()).add(_sha(target))
            if _sha(target) != _sha(source):
                raise ValueError('published copy changed')
        effective_batches = list(lc['material_batches'] or ['NOT_APPLICABLE'])
        if lc['material_manifest']:
            manifest = _json(lc['material_manifest'])
            selected = set(effective_batches)
            snap_batches = [b for b in manifest['batches'] if b['batch_id'] in selected]
            snap_paths = {p for b in snap_batches for p in b['record_paths']}
            snap_files = [f for f in manifest['files'] if f['archived_relative_path'] in snap_paths]
        else:
            snap_batches, snap_files = [], []
        record = {'version': version, 'formed_date': formed_date,
                  'material_batches': effective_batches,
                  'material_snapshot': {'batches': snap_batches, 'files': snap_files},
                  'artifacts': [{'relative_path': str(Path(a['path']).relative_to(root)),
                                 'sha256': a['sha256']} for a in artifacts]}
        lc['formal_versions'].append(record)
        lc.update(current_version=version, state='DELIVERED')
        card['deliverables'] = expected
        _owned_save(card_path, card, tracker)
        expanded = copy.deepcopy(lc['formal_versions'])
        for v in expanded:
            for artifact in v['artifacts']:
                artifact['path'] = str(root / artifact.pop('relative_path'))
        contract_path = root / 'work' / ('delivery-' + version + '.json')
        report_path = root / 'work' / ('finalization-' + version + '.json')
        retained = {card_path, report_path, *(source for source, _target in plans)}
        for old_contract_path in (root / 'work').glob('delivery-v*.json'):
            retained.add(old_contract_path)
            old_contract = _json(old_contract_path)
            old_root = Path(old_contract.get('lifecycle', {}).get('task_root') or root)
            for name in old_contract.get('retention', {}).get('retained_reason', {}):
                old = Path(name)
                try:
                    remapped = root / old.relative_to(old_root)
                except ValueError:
                    remapped = old
                if remapped.exists() and remapped.resolve().is_relative_to((root / 'work').resolve()):
                    retained.add(remapped)
        retained.update((root / 'work').glob('finalization-v*.json'))
        received = root / 'work/received'
        if received.is_dir():
            retained.update(p for p in received.rglob('*') if p.is_file() and not p.is_symlink())
        reasons = {str(p): 'version-bound task evidence/history' for p in retained}
        contract = {
            'task_id': card['task_instance_id'], 't_level': t_level,
            'formal_normative_additions': False, 'opening_notice': True,
            'summary_present': True, 'incident_present': False,
            'timing': {'unavailable_reason': 'executor must report observed wall time separately'},
            'storage': {'output_root': str(root / 'outputs'), 'archive_status': 'done', 'archive_root': str(root)},
            'task_card': {'path': str(card_path), 'sha256': _sha(card_path)},
            'artifacts': artifacts, 'reviews': list(reviews), 'validation_evidence': {},
            'retention': {'process_root': str(root / 'work'), 'temporary_files': [], 'retained_reason': reasons},
            'lifecycle': {
                'task_id': card['task_instance_id'], 'task_root': str(root), 'state': 'DELIVERED',
                'last_substantive_date': formed_date, 'current_version': version,
                'original_inputs_state': 'PASS' if lc['material_manifest'] else 'NOT_APPLICABLE',
                'material_manifest': lc['material_manifest'], 'formal_versions': expanded,
                'finalization_gates': {key: 'PENDING' for key in FINALIZATION_GATES},
                'final_validation': 'PENDING'}}
        # The contract exists at its final path before final-path content/technical validation.
        _owned_save(contract_path, contract, tracker, new=True)
        evidence = evidence(artifacts)
        ev_issues = []
        _check_final_evidence({'artifacts': artifacts, 'validation_evidence': evidence}, root,
                             lambda ok, message: ev_issues.append(message) if not ok else None)
        if ev_issues:
            raise ValueError('; '.join(ev_issues))
        for ref in evidence.values():
            evidence_path = Path(ref['path'])
            if evidence_path.resolve().is_relative_to((root / 'work').resolve()):
                retained.add(evidence_path)
        for review in reviews:
            evidence_path = Path(review.get('evidence_path') or '.')
            if evidence_path.is_file() and evidence_path.resolve().is_relative_to((root / 'work').resolve()):
                retained.add(evidence_path)
        contract['validation_evidence'] = evidence
        contract['retention']['retained_reason'] = {
            str(p): 'version-bound task evidence/history' for p in retained
        }
        contract['lifecycle']['finalization_gates'] = {key: 'PASS' for key in FINALIZATION_GATES}
        contract['lifecycle']['final_validation'] = 'PASS'
        _owned_save(contract_path, contract, tracker)
        # Re-read the actual final-path bytes through the component gate before report.
        preliminary = check_components(contract, contract_path)
        if preliminary['state'] != 'PASS':
            lc['state'] = 'FINALIZATION_FAILED'
            _owned_save(card_path, card, tracker)
            raise ValueError('; '.join(preliminary['issues']))
        report = {'task_id': card['task_instance_id'], 'task_root': str(root),
                  'version_record': record, 'contract_sha256': _sha(contract_path),
                  'gates': contract['lifecycle']['finalization_gates'], 'state': 'PASS'}
        if report_path.exists():
            raise FileExistsError('formal delivery receipt already exists')
        _owned_save(report_path, report, tracker, new=True)
        final = check(contract, contract_path)
        if final['state'] != 'PASS':
            lc['state'] = 'FINALIZATION_FAILED'
            _owned_save(card_path, card, tracker)
            report['state'] = 'FAIL'
            _owned_save(report_path, report, tracker)
            raise ValueError('; '.join(final['issues']))
        return {'state': 'PASS', 'task_id': card['task_instance_id'], 'version': version,
                'contract': str(contract_path), 'report': str(report_path), 'artifacts': artifacts}


@guarded
def publish_version(task_card, candidates, evidence, *, formed_date, t_level=3, reviews=()):
    """Commit one delivery or restore only this attempt's known files; old versions stay intact."""
    card_path = Path(task_card)
    root = _root(card_path.parent.parent)
    before = _regular(card_path, root).read_bytes()
    card = json.loads(before)
    version = f"v{len(card['lifecycle']['formal_versions']) + 1}"
    targets = [root / 'outputs' / x['filename'] for x in candidates]
    for target in targets:
        if target.parent != root / 'outputs' or target.exists() or target.is_symlink():
            raise ValueError('publish requires unoccupied output basenames')
    generated = [root / 'work' / ('delivery-' + version + '.json'),
                 root / 'work' / ('finalization-' + version + '.json')]
    if any(p.exists() or p.is_symlink() for p in generated):
        raise ValueError('version receipts already exist; preserve existing state')
    # The outer lock spans rollback as well as publication.
    with _task_lock(root):
        if card_path.read_bytes() != before or any(p.exists() for p in targets + generated):
            raise ValueError('concurrent task change; retry from current state')
        tracker = {'hashes': {str(card_path): {hashlib.sha256(before).hexdigest()}}, 'delete': set()}
        try:
            return _publish_version(task_card, candidates, evidence, formed_date=formed_date,
                                    t_level=t_level, reviews=reviews, tracker=tracker)
        except BaseException as exc:
            unsafe = []
            for name in tracker['delete']:
                path = Path(name)
                if path.is_file() and not path.is_symlink() and _sha(path) in tracker['hashes'].get(name, set()):
                    path.unlink()
                elif path.exists():
                    unsafe.append(name)
            if card_path.is_file() and _sha(card_path) in tracker['hashes'][str(card_path)]:
                _atomic_regular_write(card_path, before, 0o600)
            elif card_path.read_bytes() != before:
                unsafe.append(str(card_path))
            if unsafe:
                raise RuntimeError('rollback preserved concurrently changed paths: ' + ', '.join(unsafe)) from exc
            raise


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
