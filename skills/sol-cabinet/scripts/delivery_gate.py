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


def _expected_artifacts(c, root, require, card):
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


def review_evidence_baseline(card):
    """Fingerprint the locked source/evidence baseline used by independent reviews.

    The digest is SHA-256 over canonical JSON containing the Task Card's
    source_archive and evidence_pack objects. When either object exists, every
    review scope is bound to this baseline. Delivery separately revalidates the
    manifest and archived bytes against these locked declarations.
    """
    if not isinstance(card, dict):
        return None
    baseline = {}
    for key in ('source_archive', 'evidence_pack'):
        if key in card:
            baseline[key] = card[key]
    if not baseline:
        return None
    raw = json.dumps(
        baseline,
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


# Compatibility for callers/tests created with the first v1.5.4 remediation.
_review_evidence_baseline = review_evidence_baseline


def _validate_live_evidence(card, contract, require):
    """Re-prove locked source declarations against canonical on-disk bytes.

    Archive paths are relative to the locked Task Card directory. A review of
    declarations is current only while the manifest bytes and every source still
    match them. Reuse ingestion validation for canonical archive invariants.
    """
    if not isinstance(card, dict):
        return
    archive = card.get('source_archive')
    pack = card.get('evidence_pack')
    if archive is None and pack is None:
        return
    empty_pack = (isinstance(pack, dict)
                  and set(pack) == {'sources', 'coverage', 'facts', 'conflicts', 'unread'}
                  and all(value == [] for value in pack.values()))
    if (isinstance(archive, dict) and archive.get('source_files_present') is False
            and archive.get('state') == 'NOT_APPLICABLE'
            and not archive.get('required') and not archive.get('source_asset_count')
            and (pack is None or empty_pack)):
        return
    try:
        from source_ingestion import _load_units, ARCHIVE_DIR_NAME, MANIFEST_NAME
        if not isinstance(archive, dict) or not isinstance(pack, dict):
            raise ValueError('source_archive and evidence_pack required together')
        relative = str(Path(ARCHIVE_DIR_NAME) / MANIFEST_NAME)
        if archive.get('manifest_relative_path') != relative:
            raise ValueError('canonical manifest_relative_path required')
        if archive.get('source_files_present') is not True or archive.get('state') != 'PASS':
            raise ValueError('source archive must declare preserved sources')
        task_root = Path(contract['task_card']['path']).parent
        manifest = task_root / relative
        before = manifest.read_bytes()
        units = _load_units(task_root, manifest)
        after = manifest.read_bytes()
        if before != after or hashlib.sha256(after).hexdigest() != archive.get('manifest_sha256'):
            raise ValueError('manifest bytes changed after evidence lock')
        for field in ('source_asset_count', 'verified_count'):
            if field in archive and (type(archive[field]) is not int or archive[field] != len(units)):
                raise ValueError('source archive count mismatch')
        sources = pack.get('sources')
        fields = ('source_id', 'source_sha256', 'source_type', 'archived_relative_path')
        if (not isinstance(sources, list) or len(sources) != len(units)
                or any(not isinstance(item, dict) for item in sources)):
            raise ValueError('evidence sources do not cover the live archive')
        if [{key: item.get(key) for key in fields} for item in sources] != [
                {key: unit[key] for key in fields} for unit in units]:
            raise ValueError('evidence sources differ from the live archive')
        if pack.get('unread') != []:
            raise ValueError('evidence has unread source semantics')
        coverage = pack.get('coverage')
        if (not isinstance(coverage, list) or len(coverage) != len(units)
                or any(not isinstance(item, dict) for item in coverage)):
            raise ValueError('evidence coverage must cover every live source')
        for unit, item in zip(units, coverage):
            if item.get('source_id') != unit['source_id'] or item.get('state') != 'EXTRACTED':
                raise ValueError('source semantic coverage is incomplete')
            if unit['source_type'] in ('.docx', '.xlsx'):
                from inspect_office import SEMANTIC_SURFACE
                inspection = item.get('inspection_coverage')
                if not isinstance(inspection, dict):
                    raise ValueError('Office semantic coverage contract required')
                parts = inspection.get('parts_read')
                complete = inspection.get('parts_complete')
                if (inspection.get('semantic_surface') != SEMANTIC_SURFACE
                        or inspection.get('semantic_gaps') != []
                        or not isinstance(parts, list) or not parts
                        or not all(isinstance(part, str) and part for part in parts)
                        or len(parts) != len(set(parts))
                        or not isinstance(complete, list) or complete != parts):
                    raise ValueError('Office semantic coverage is incomplete or unsupported')

    except (OSError, ValueError, TypeError, KeyError, UnicodeError) as exc:
        require(False, 'live evidence validation failed: ' + str(exc))


def _normalize_review_scope(review, actual_by_id, hashes):
    """Return (scope, artifact_ids, expected_hashes) or None for an invalid scope.

    Backward-compatible review evidence without scope fields remains a full-candidate
    review. Artifact scope binds declared artifact hashes; full and cross-artifact
    scopes bind the complete current candidate hash map. Evidence-baseline binding
    is enforced separately and uniformly for every scope when a baseline exists.
    """
    if not isinstance(review, dict):
        return None
    all_ids = set(actual_by_id)
    scope = review.get('review_scope', 'full')
    declared_ids = review.get('artifact_ids')

    if scope == 'full':
        if declared_ids is None:
            ids = sorted(all_ids)
        elif (isinstance(declared_ids, list) and declared_ids
              and all(isinstance(item, str) and item in all_ids for item in declared_ids)
              and len(declared_ids) == len(set(declared_ids))
              and set(declared_ids) == all_ids):
            ids = list(declared_ids)
        else:
            return None
        return scope, ids, dict(hashes)

    if not (isinstance(declared_ids, list) and declared_ids
            and all(isinstance(item, str) and item in all_ids for item in declared_ids)
            and len(declared_ids) == len(set(declared_ids))):
        return None

    if scope == 'artifact':
        ids = list(declared_ids)
        expected_hashes = {
            actual_by_id[artifact_id]['path']: actual_by_id[artifact_id]['sha256']
            for artifact_id in ids
        }
        return scope, ids, expected_hashes

    if scope == 'cross_artifact':
        if len(all_ids) < 2 or set(declared_ids) != all_ids:
            return None
        return scope, list(declared_ids), dict(hashes)

    return None


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
    if storage.get('archive_status') == 'done':
        archive = Path(storage.get('archive_root') or '.')
        require(archive.is_absolute() and archive.is_dir() and root.resolve().is_relative_to(archive.resolve()), 'archive root does not contain output root')

    card = _load_locked_task_card(c, require)
    expected = _expected_artifacts(c, root, require, card)
    _validate_live_evidence(card, c, require)
    evidence_baseline_sha256 = review_evidence_baseline(card)
    require(bool(expected), 'file delivery requires at least one expected artifact; use analysis-only for no-file tasks')
    artifacts = c.get('artifacts')
    require(isinstance(artifacts, list), 'artifact manifest must be an array')
    hashes = {}
    actual_ids = set()
    actual_by_id = {}
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
            if valid_actual_id:
                actual_by_id[artifact_id] = {'path': str(p), 'sha256': digest}
    required_ids = {
        artifact_id for artifact_id, spec in expected.items()
        if isinstance(spec, dict) and spec.get('required') is True
    }
    for artifact_id in required_ids:
        require(artifact_id in actual_ids, 'required expected artifact missing: ' + artifact_id)

    required = 2 if type(level) is int and level >= 7 else (1 if type(level) is int and level >= 4 else 0)
    reviewers = set()
    artifact_reviewers = {artifact_id: set() for artifact_id in required_ids}
    cross_artifact_reviewed = len(actual_by_id) <= 1
    reviews = c.get('reviews', [])
    require(isinstance(reviews, list), 'reviews must be array')
    for review in reviews if isinstance(reviews, list) else []:
        if not isinstance(review, dict):
            issues.append('invalid review')
            continue
        reviewer, author = review.get('reviewer_id'), review.get('author_id')
        evidence = Path(review.get('evidence_path') or '.')
        scope_info = _normalize_review_scope(review, actual_by_id, hashes)
        baseline_bound = scope_info is not None and evidence_baseline_sha256 is not None
        valid = (scope_info is not None
                 and isinstance(reviewer, str) and bool(reviewer.strip()) and isinstance(author, str)
                 and bool(author.strip()) and reviewer != author and evidence.is_absolute()
                 and evidence.is_file() and evidence.stat().st_size > 0
                 and review.get('candidate_sha256') == scope_info[2] and bool(scope_info[2])
                 and (not baseline_bound
                      or review.get('evidence_baseline_sha256') == evidence_baseline_sha256)
                 and review.get('verdict') == 'PASS' and review.get('must_fix') == [])
        if valid:
            try:
                data = evidence.read_bytes()
                recorded = json.loads(data)
                recorded_scope = _normalize_review_scope(recorded, actual_by_id, hashes)
                fields = ('reviewer_id', 'author_id', 'verdict', 'must_fix', 'candidate_sha256', 'source_ref')
                if baseline_bound:
                    fields += ('evidence_baseline_sha256',)
                valid = (hashlib.sha256(data).hexdigest() == review.get('evidence_sha256')
                         and isinstance(recorded, dict)
                         and all(recorded.get(key) == review.get(key) for key in fields)
                         and recorded_scope is not None
                         and recorded_scope[0] == scope_info[0]
                         and set(recorded_scope[1]) == set(scope_info[1])
                         and isinstance(recorded.get('source_ref'), str)
                         and bool(recorded['source_ref'].strip()))
            except (OSError, ValueError, UnicodeError):
                valid = False
        require(valid, 'missing, changed, or inconsistent independent review JSON evidence')
        if valid:
            reviewers.add(reviewer)
            scope, scope_ids, _ = scope_info
            if scope in ('full', 'artifact'):
                for artifact_id in scope_ids:
                    if artifact_id in artifact_reviewers:
                        artifact_reviewers[artifact_id].add(reviewer)
            if scope in ('full', 'cross_artifact') and set(scope_ids) == set(actual_by_id):
                cross_artifact_reviewed = True
    require(len(reviewers) >= required, 'insufficient independent reviews')
    if required:
        for artifact_id in sorted(required_ids):
            require(len(artifact_reviewers.get(artifact_id, set())) >= required,
                    'insufficient independent review coverage: ' + artifact_id)
        if len(actual_by_id) > 1:
            require(cross_artifact_reviewed, 'missing full or cross-artifact consistency review')

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
