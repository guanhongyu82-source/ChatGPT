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
TASK_ROOT_NAME = re.compile(r'^(?P<date>\d{4}-\d{2}-\d{2})_(?P<subject>[^/\\\x00-\x1f]+)$')
FORMAL_NAME = re.compile(r'^(?P<date>\d{4}-\d{2}-\d{2})_.+_(?P<version>v[1-9]\d*)\.[^.]+$')
TEMPORARY_ROOT_NAMES = frozenset({'new-chat', 'temp', 'tmp', 'untitled', 'working', '未命名', '临时'})
FINALIZATION_GATES = (
    'content', 'deliverables', 'original_inputs', 'work_evidence',
    'task_root_archive', 'temporary_residue', 'version_continuity',
    'material_traceability', 'final_path', 'final_validation',
    'delivery_contract',
)


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
    if name.casefold() in TEMPORARY_ROOT_NAMES or subject.strip().casefold() in TEMPORARY_ROOT_NAMES:
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
    require(match.group('subject').strip().casefold() not in TEMPORARY_ROOT_NAMES,
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

    manifest_raw = lifecycle.get('material_manifest')
    manifest_path = Path(manifest_raw) if isinstance(manifest_raw, str) else None
    batch_ids = set()
    archived_members = set()
    if manifest_path is None:
        require(lifecycle.get('original_inputs_state') == 'NOT_APPLICABLE',
                'material manifest required when original inputs are applicable')
    else:
        valid_manifest = (
            manifest_path.is_absolute()
            and manifest_path.is_file()
            and manifest_path.resolve().is_relative_to(task_root / '00_原稿')
        )
        require(valid_manifest, 'material manifest must be inside task_root/00_原稿')
        if valid_manifest:
            try:
                manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            except (OSError, UnicodeError, ValueError):
                manifest = None
            require(isinstance(manifest, dict), 'material manifest must be valid JSON')
            if isinstance(manifest, dict):
                require(manifest.get('schema_version') == 2, 'material manifest must use lifecycle schema 2')
                require(manifest.get('archive_state') == 'PASS', 'material manifest must be PASS')
                files = manifest.get('files')
                batches = manifest.get('batches')
                require(isinstance(files, list), 'material manifest files must be an array')
                require(isinstance(batches, list), 'material manifest batches must be an array')
                file_paths = set()
                if isinstance(files, list):
                    for item in files:
                        if not isinstance(item, dict) or not isinstance(item.get('archived_relative_path'), str):
                            require(False, 'material manifest contains invalid file record')
                            continue
                        relative = item['archived_relative_path']
                        relative_path = Path(relative)
                        valid_relative = (len(relative_path.parts) == 2
                                          and relative_path.parts[0] == '00_原稿'
                                          and relative_path.name == relative_path.parts[1])
                        require(valid_relative, 'archived original path is invalid: ' + relative)
                        member = task_root / relative if valid_relative else task_root / '00_原稿' / '__invalid__'
                        valid_member = member.is_file() and not member.is_symlink()
                        require(valid_member, 'archived original is missing: ' + relative)
                        if valid_member:
                            digest = item.get('archived_sha256')
                            require(isinstance(digest, str) and re.fullmatch(r'[0-9a-f]{64}', digest) is not None,
                                    'archived original hash is invalid: ' + relative)
                            if isinstance(digest, str) and re.fullmatch(r'[0-9a-f]{64}', digest) is not None:
                                require(hashlib.sha256(member.read_bytes()).hexdigest() == digest,
                                        'archived original hash mismatch: ' + relative)
                            require(item.get('source_sha256') == item.get('archived_sha256')
                                    and item.get('byte_identical') is True
                                    and item.get('source_unmodified') is True
                                    and item.get('status') == 'UNMODIFIED_BYTE_COPY',
                                    'archived original preservation flags are invalid: ' + relative)
                        file_paths.add(relative)
                        archived_members.add(member.name)
                if isinstance(batches, list):
                    mapped = set()
                    for batch in batches:
                        if not isinstance(batch, dict):
                            require(False, 'material manifest contains invalid batch')
                            continue
                        batch_id = batch.get('batch_id')
                        record_paths = batch.get('record_paths')
                        require(isinstance(batch_id, str) and re.fullmatch(r'B\d{2,}', batch_id) is not None,
                                'material batch id is invalid')
                        require(isinstance(record_paths, list) and bool(record_paths),
                                'material batch record_paths are required')
                        if isinstance(batch_id, str):
                            batch_ids.add(batch_id)
                        if isinstance(record_paths, list):
                            for relative in record_paths:
                                require(relative in file_paths, 'material batch points to unknown archive file')
                                mapped.add(relative)
                    require(file_paths <= mapped, 'archived original is not mapped to a material batch')
                archive_dir = task_root / '00_原稿'
                if archive_dir.is_dir():
                    allowed_archive = {'原稿清单.json'} | archived_members
                    for child in archive_dir.iterdir():
                        require(child.name in allowed_archive,
                                'unknown item in 00_原稿: ' + str(child))

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
