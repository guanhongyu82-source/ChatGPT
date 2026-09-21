#!/usr/bin/env python3
"""Capture and verify Sol Cabinet runtime deployment identity.

The state file is runtime evidence only. It never promotes a GitHub candidate,
changes VERSION, or becomes a source of maintained Skill content. Stable and
LAB share one active Runtime path, but the state record always identifies which
channel is active so a candidate cannot masquerade as Stable.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from maintenance_boundary import guarded

DEFAULT_STATE = Path('/Users/macbook/ChatGPT/system/sol-cabinet-deployment/state.json')
REPOSITORY = 'guanhongyu82-source/ChatGPT'
REPOSITORY_PATH = 'skills/sol-cabinet'
COMMIT = re.compile(r'^[0-9a-f]{40}$')
SHA256 = re.compile(r'^[0-9a-f]{64}$')
VERSION = re.compile(r'^\d+\.\d+\.\d+(?:-lab\.\d+)?$')
CHANNELS = {'stable', 'lab'}
SOURCE_REF = re.compile(r'^(?:main|lab/v\d+\.\d+\.\d+-lab\.\d+)$')
STATE_KEYS_V1 = {
    'schema_version', 'record_kind', 'repository', 'repository_path',
    'source_commit', 'source_version', 'source_system_sha256',
    'runtime_root', 'runtime_system_sha256', 'deployed_at', 'verified_at',
}
STATE_KEYS_V2 = STATE_KEYS_V1 | {'channel', 'source_ref'}


def _digest(root: Path) -> str:
    path = root / 'scripts' / 'validate_evolution_proposal.py'
    spec = importlib.util.spec_from_file_location('sol_runtime_digest', path)
    if spec is None or spec.loader is None:
        raise RuntimeError('system digest implementation unavailable')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.system_digest(root)


def _version(root: Path) -> str:
    value = (root / 'VERSION').read_text(encoding='utf-8').strip()
    if VERSION.fullmatch(value) is None:
        raise ValueError('runtime VERSION is invalid')
    return value


def channel_for_version(version: str) -> str:
    if VERSION.fullmatch(version or '') is None:
        raise ValueError('version is invalid')
    return 'lab' if '-lab.' in version else 'stable'


def _validate_channel_ref(channel: object, source_ref: object) -> None:
    if channel not in CHANNELS:
        raise ValueError('channel is invalid')
    if not isinstance(source_ref, str) or SOURCE_REF.fullmatch(source_ref) is None:
        raise ValueError('source_ref is invalid')
    if channel == 'stable' and source_ref != 'main':
        raise ValueError('stable deployments must use source_ref main')
    if channel == 'lab' and not source_ref.startswith('lab/'):
        raise ValueError('lab deployments must use a lab source_ref')


def build_state(source_commit: str, source_system_sha256: str, root: Path = ROOT,
                *, now: datetime | None = None, channel: str | None = None,
                source_ref: str | None = None) -> dict[str, object]:
    if COMMIT.fullmatch(source_commit or '') is None:
        raise ValueError('source_commit must be a full Git commit SHA')
    if SHA256.fullmatch(source_system_sha256 or '') is None:
        raise ValueError('source_system_sha256 is invalid')
    source_version = _version(root)
    inferred_channel = channel_for_version(source_version)
    if channel is None:
        channel = inferred_channel
    if channel != inferred_channel:
        raise ValueError('channel does not match runtime VERSION')
    if source_ref is None:
        if channel == 'stable':
            source_ref = 'main'
        else:
            raise ValueError('source_ref is required for LAB capture')
    _validate_channel_ref(channel, source_ref)
    runtime_digest = _digest(root)
    if runtime_digest != source_system_sha256:
        raise ValueError('runtime bytes do not match selected source digest')
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    return {
        'schema_version': 2,
        'record_kind': 'runtime-deployment-state',
        'channel': channel,
        'source_ref': source_ref,
        'repository': REPOSITORY,
        'repository_path': REPOSITORY_PATH,
        'source_commit': source_commit,
        'source_version': source_version,
        'source_system_sha256': source_system_sha256,
        'runtime_root': str(root.resolve()),
        'runtime_system_sha256': runtime_digest,
        'deployed_at': stamp,
        'verified_at': stamp,
    }


def _parse_time(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def classify(record: object, root: Path = ROOT, *, expected_commit: str | None = None,
             expected_channel: str | None = None) -> dict[str, object]:
    issues: list[str] = []
    if not isinstance(record, dict):
        return {'state': 'UNTRACKED', 'issues': ['deployment state missing or invalid']}
    schema_version = record.get('schema_version')
    if schema_version == 1:
        if set(record) != STATE_KEYS_V1:
            issues.append('deployment state schema mismatch')
        record_channel = 'stable'
        record_ref = None
    elif schema_version == 2:
        if set(record) != STATE_KEYS_V2:
            issues.append('deployment state schema mismatch')
        record_channel = record.get('channel')
        record_ref = record.get('source_ref')
        try:
            _validate_channel_ref(record_channel, record_ref)
        except ValueError as exc:
            issues.append(str(exc))
    else:
        issues.append('deployment state schema mismatch')
        record_channel = None
        record_ref = None
    if record.get('record_kind') != 'runtime-deployment-state':
        issues.append('deployment state identity mismatch')
    if record.get('repository') != REPOSITORY or record.get('repository_path') != REPOSITORY_PATH:
        issues.append('deployment state repository mismatch')
    if COMMIT.fullmatch(str(record.get('source_commit', ''))) is None:
        issues.append('invalid source_commit')
    source_version = str(record.get('source_version', ''))
    if VERSION.fullmatch(source_version) is None:
        issues.append('invalid source_version')
    else:
        try:
            if channel_for_version(source_version) != record_channel:
                issues.append('state channel does not match source_version')
        except ValueError:
            issues.append('invalid source_version')
    if schema_version == 1 and record_channel != 'stable':
        issues.append('legacy deployment state cannot identify LAB')
    if SHA256.fullmatch(str(record.get('source_system_sha256', ''))) is None:
        issues.append('invalid source_system_sha256')
    if SHA256.fullmatch(str(record.get('runtime_system_sha256', ''))) is None:
        issues.append('invalid runtime_system_sha256')
    if record.get('runtime_root') != str(root.resolve()):
        issues.append('runtime_root mismatch')
    if not _parse_time(record.get('deployed_at')) or not _parse_time(record.get('verified_at')):
        issues.append('invalid deployment timestamps')
    if issues:
        return {'state': 'UNTRACKED', 'issues': issues}

    try:
        current_digest = _digest(root)
        current_version = _version(root)
    except (OSError, RuntimeError, ValueError) as exc:
        return {'state': 'DRIFTED', 'issues': ['runtime cannot be verified: ' + type(exc).__name__]}
    if (current_digest != record['runtime_system_sha256']
            or current_digest != record['source_system_sha256']
            or current_version != record['source_version']
            or channel_for_version(current_version) != record_channel):
        return {'state': 'DRIFTED', 'issues': ['runtime bytes or VERSION differ from deployment state']}
    if expected_commit is not None:
        if COMMIT.fullmatch(expected_commit) is None:
            return {'state': 'UNTRACKED', 'issues': ['expected_commit is invalid']}
        if record['source_commit'] != expected_commit:
            return {'state': 'STALE', 'issues': ['runtime is internally consistent but not the requested Git commit']}
    if expected_channel is not None:
        if expected_channel not in CHANNELS:
            return {'state': 'UNTRACKED', 'issues': ['expected_channel is invalid']}
        if record_channel != expected_channel:
            return {'state': 'STALE', 'issues': ['runtime is internally consistent but not the requested channel']}
    result = {'state': 'SYNCED', 'issues': [], 'source_commit': record['source_commit'],
              'source_version': record['source_version'], 'channel': record_channel,
              'system_sha256': current_digest}
    if record_ref is not None:
        result['source_ref'] = record_ref
    return result


@guarded
def write_state(record: dict[str, object], destination: Path = DEFAULT_STATE) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(destination.parent, 0o700)
    fd, temp_name = tempfile.mkstemp(prefix='.deployment-state.', suffix='.tmp', dir=destination.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            os.chmod(temp, 0o600)
            json.dump(record, handle, ensure_ascii=False, sort_keys=True)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, destination)
    finally:
        if temp.exists():
            temp.unlink()


def read_state(path: Path = DEFAULT_STATE) -> object:
    if not path.is_file() or path.is_symlink():
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, ValueError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', action='store_true')
    parser.add_argument('--source-commit')
    parser.add_argument('--source-system-sha256')
    parser.add_argument('--state', type=Path, default=DEFAULT_STATE)
    parser.add_argument('--expected-commit')
    parser.add_argument('--channel', choices=sorted(CHANNELS))
    parser.add_argument('--source-ref')
    parser.add_argument('--expected-channel', choices=sorted(CHANNELS))
    args = parser.parse_args()
    try:
        if args.capture:
            record = build_state(
                args.source_commit or '', args.source_system_sha256 or '',
                channel=args.channel, source_ref=args.source_ref,
            )
            write_state(record, args.state)
            result = classify(
                record, expected_commit=args.source_commit,
                expected_channel=args.expected_channel or args.channel,
            )
        else:
            result = classify(
                read_state(args.state), expected_commit=args.expected_commit,
                expected_channel=args.expected_channel,
            )
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
        result = {'state': 'UNTRACKED', 'issues': ['deployment state operation failed: ' + type(exc).__name__]}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result['state'] == 'SYNCED' else 2


if __name__ == '__main__':
    raise SystemExit(main())
