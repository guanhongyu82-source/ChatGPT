#!/usr/bin/env python3
"""Install managed agent copies with locking, atomic files, rollback, and verification."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any
from maintenance_boundary import guarded


ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = ROOT / "platform-adapter" / "codex-agents"
CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser().resolve()
TARGET_DIR = CODEX_HOME / "agents"
EXPECTED_TARGET_DIR = CODEX_HOME / "agents"
MARKER = "# Managed by Sol Cabinet single source; edit the source file only."
FILES = (
    "sol-researcher.toml",
    "sol-fact-checker.toml",
    "sol-structure-architect.toml",
    "sol-drafter.toml",
    "sol-critic.toml",
    "sol-compliance-reviewer.toml",
    "sol-language-editor.toml",
    "sol-final-verifier.toml",
)


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest(path: Path) -> str:
    return digest_bytes(path.read_bytes())


@guarded
def _atomic_regular_write(path: Path, data: bytes, mode: int = 0o600) -> None:
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, mode)
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@guarded
def _preflight() -> tuple[dict[str, bytes], dict[str, tuple[str, Any]]]:
    if not CODEX_HOME.is_dir() or CODEX_HOME.is_symlink():
        raise ValueError("resolved Codex home must be a regular directory")
    if TARGET_DIR.exists() and TARGET_DIR.is_symlink():
        raise ValueError("target agent directory must not be a symlink")
    TARGET_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    if TARGET_DIR.resolve() != EXPECTED_TARGET_DIR.resolve():
        raise ValueError("target agent directory escaped the Codex home")
    extras = sorted(path.name for path in TARGET_DIR.glob("sol-*.toml") if path.name not in FILES)
    if extras:
        raise ValueError(f"unexpected or retired Sol agent files require manual review: {extras}")

    sources: dict[str, bytes] = {}
    previous: dict[str, tuple[str, Any]] = {}
    if SOURCE_DIR.is_symlink() or SOURCE_DIR.resolve().parent != (ROOT / "platform-adapter").resolve():
        raise ValueError("source agent directory escaped the Sol truth source")
    for name in FILES:
        source = SOURCE_DIR / name
        if source.resolve().parent != SOURCE_DIR.resolve():
            raise ValueError(f"source escaped the managed directory: {source}")
        if not source.is_file() or source.is_symlink():
            raise ValueError(f"invalid source agent file: {source}")
        data = source.read_bytes()
        if not data.startswith(MARKER.encode("utf-8")):
            raise ValueError(f"missing managed marker: {source}")
        sources[name] = data

        target = TARGET_DIR / name
        if target.parent.resolve() != TARGET_DIR.resolve():
            raise ValueError(f"target escaped the managed directory: {target}")
        if target.is_symlink():
            if target.resolve() != source.resolve():
                raise ValueError(f"refusing foreign symlink: {target}")
            previous[name] = ("symlink", os.readlink(target))
        elif target.exists():
            if not target.is_file():
                raise ValueError(f"refusing non-file target: {target}")
            old_data = target.read_bytes()
            if not old_data.startswith(MARKER.encode("utf-8")):
                raise ValueError(f"refusing unmanaged target: {target}")
            previous[name] = ("regular", (old_data, stat.S_IMODE(target.stat().st_mode)))
        else:
            previous[name] = ("missing", None)
    return sources, previous


def check() -> dict[str, object]:
    issues = []
    if not TARGET_DIR.is_dir() or TARGET_DIR.is_symlink():
        return {"verdict": "FAIL", "issues": [{"issue": "invalid-agent-directory"}]}
    if stat.S_IMODE(TARGET_DIR.stat().st_mode) != 0o700:
        issues.append({"issue": "agent-directory-mode", "actual": oct(stat.S_IMODE(TARGET_DIR.stat().st_mode))})
    for path in sorted(TARGET_DIR.glob("sol-*.toml")):
        if path.name not in FILES:
            issues.append({"file": path.name, "issue": "unexpected-or-retired-sol-agent"})
    for name in FILES:
        source = SOURCE_DIR / name
        target = TARGET_DIR / name
        if not target.is_file() or target.is_symlink():
            issues.append({"file": name, "issue": "missing-regular-runtime-copy"})
            continue
        if not target.read_bytes().startswith(MARKER.encode("utf-8")):
            issues.append({"file": name, "issue": "managed-marker-missing"})
        if digest(source) != digest(target):
            issues.append({"file": name, "issue": "runtime-copy-drift"})
        if stat.S_IMODE(target.stat().st_mode) != 0o600:
            issues.append({"file": name, "issue": "runtime-file-mode", "actual": oct(stat.S_IMODE(target.stat().st_mode))})
    return {"verdict": "PASS" if not issues else "FAIL", "issues": issues}


@guarded
def _rollback(previous: dict[str, tuple[str, Any]]) -> None:
    for name, (kind, value) in previous.items():
        target = TARGET_DIR / name
        if target.exists() or target.is_symlink():
            target.unlink()
        if kind == "regular":
            data, mode = value
            _atomic_regular_write(target, data, mode)
        elif kind == "symlink":
            target.symlink_to(value)


@guarded
def install() -> dict[str, object]:
    sources, previous = _preflight()
    os.chmod(TARGET_DIR, 0o700)
    lock_path = TARGET_DIR / ".sol-cabinet-sync.lock"
    if lock_path.is_symlink():
        raise ValueError("sync lock must not be a symlink")
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    lock_fd = os.open(lock_path, flags, 0o600)
    lock_stat = os.fstat(lock_fd)
    if not stat.S_ISREG(lock_stat.st_mode) or lock_stat.st_uid != os.getuid():
        os.close(lock_fd)
        raise ValueError("sync lock must be an owned regular file")
    os.fchmod(lock_fd, 0o600)
    with os.fdopen(lock_fd, "r+") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        sources, previous = _preflight()
        try:
            for name in FILES:
                target = TARGET_DIR / name
                _atomic_regular_write(target, sources[name], 0o600)
            _fsync_directory(TARGET_DIR)
            result = check()
            if result["verdict"] != "PASS":
                raise RuntimeError(f"post-install verification failed: {result['issues']}")
        except BaseException:
            _rollback(previous)
            raise
        result["installed"] = list(FILES)
        result["source_sha256"] = {name: digest_bytes(data) for name, data in sources.items()}
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--install", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        result = install() if args.install else check()
    except (OSError, RuntimeError, UnicodeError, ValueError) as exc:
        print(json.dumps({"verdict": "FAIL", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
