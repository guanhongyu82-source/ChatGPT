#!/usr/bin/env python3
"""Archive byte-identical user source files into a task-local 00_原稿 directory."""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import re
import secrets
import stat
import sys
import time
from pathlib import Path
from typing import Iterable
from maintenance_boundary import guarded


WORKSPACE_ROOT = Path("/Users/macbook/ChatGPT/workspace")
ARCHIVE_DIR_NAME = "00_原稿"
MANIFEST_NAME = "原稿清单.json"
ROLE_RE = re.compile(r"^[^/\\\x00-\x1f]{1,40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
RECORD_KEYS = {
    "source_role",
    "source_name",
    "archived_relative_path",
    "size_bytes",
    "source_sha256",
    "archived_sha256",
    "byte_identical",
    "source_unmodified",
    "status",
}
NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
DIRECTORY = getattr(os, "O_DIRECTORY", 0)


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("archive write made no progress")
        view = view[written:]


def _hash_fd(fd: int) -> str:
    os.lseek(fd, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
    return digest.hexdigest()


def _stable_stat(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _reject_symlink_components(path: Path) -> None:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        if not os.path.lexists(current):
            continue
        if current.is_symlink():
            raise ValueError("task_dir may not contain symlink components")


def _open_task_directory(task_dir: Path, *, allow_test_output: bool) -> tuple[int, Path]:
    if allow_test_output:
        _reject_symlink_components(task_dir)
        resolved = task_dir.resolve(strict=True)
        if not resolved.is_dir() or resolved.is_symlink():
            raise ValueError("task_dir must be a pre-existing real directory")
        fd = os.open(resolved, os.O_RDONLY | DIRECTORY | NOFOLLOW)
        return fd, resolved

    workspace = WORKSPACE_ROOT.resolve(strict=True)
    raw = task_dir.absolute()
    try:
        relative = raw.relative_to(workspace)
    except ValueError as exc:
        raise ValueError("task_dir must be under the approved workspace root") from exc
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("task_dir must be a concrete child of the workspace root")
    current_fd = os.open(workspace, os.O_RDONLY | DIRECTORY | NOFOLLOW)
    try:
        for part in relative.parts:
            info = os.stat(part, dir_fd=current_fd, follow_symlinks=False)
            if not stat.S_ISDIR(info.st_mode):
                raise ValueError("task_dir components must be real directories")
            next_fd = os.open(part, os.O_RDONLY | DIRECTORY | NOFOLLOW, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        return current_fd, workspace.joinpath(*relative.parts)
    except BaseException:
        os.close(current_fd)
        raise


def _open_archive_directory(task_fd: int, task_dir: Path) -> tuple[int, Path]:
    try:
        os.mkdir(ARCHIVE_DIR_NAME, mode=0o700, dir_fd=task_fd)
    except FileExistsError:
        pass
    info = os.stat(ARCHIVE_DIR_NAME, dir_fd=task_fd, follow_symlinks=False)
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError("00_原稿 must be a real directory")
    archive_fd = os.open(
        ARCHIVE_DIR_NAME,
        os.O_RDONLY | DIRECTORY | NOFOLLOW,
        dir_fd=task_fd,
    )
    os.fchmod(archive_fd, 0o700)
    archive_dir = task_dir / ARCHIVE_DIR_NAME
    if _stable_stat(os.fstat(archive_fd)) != _stable_stat(os.stat(archive_dir, follow_symlinks=False)):
        os.close(archive_fd)
        raise RuntimeError("00_原稿 changed during setup")
    return archive_fd, archive_dir


def _read_name(archive_fd: int, name: str) -> bytes:
    fd = os.open(name, os.O_RDONLY | NOFOLLOW, dir_fd=archive_fd)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("archive member must be a regular file")
        chunks = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _validate_record(record: object, archive_fd: int) -> dict[str, object]:
    if not isinstance(record, dict) or set(record) != RECORD_KEYS:
        raise ValueError("original manifest record schema is invalid")
    role = record["source_role"]
    source_name = record["source_name"]
    relative = record["archived_relative_path"]
    size_bytes = record["size_bytes"]
    source_sha256 = record["source_sha256"]
    archived_sha256 = record["archived_sha256"]
    if not isinstance(role, str) or not ROLE_RE.fullmatch(role) or role in {".", ".."}:
        raise ValueError("original manifest role is invalid")
    if not isinstance(source_name, str) or Path(source_name).name != source_name:
        raise ValueError("original manifest source_name is invalid")
    _validate_basename(source_name)
    if not isinstance(relative, str):
        raise ValueError("original manifest path is invalid")
    parts = Path(relative).parts
    if len(parts) != 2 or parts[0] != ARCHIVE_DIR_NAME or Path(parts[1]).name != parts[1]:
        raise ValueError("original manifest path escapes 00_原稿")
    if type(size_bytes) is not int or size_bytes < 0:
        raise ValueError("original manifest size is invalid")
    if not isinstance(source_sha256, str) or not SHA256_RE.fullmatch(source_sha256):
        raise ValueError("original manifest source hash is invalid")
    if not isinstance(archived_sha256, str) or not SHA256_RE.fullmatch(archived_sha256):
        raise ValueError("original manifest archive hash is invalid")
    if source_sha256 != archived_sha256:
        raise ValueError("original manifest hashes disagree")
    if record["byte_identical"] is not True or record["source_unmodified"] is not True:
        raise ValueError("original manifest preservation flags are invalid")
    if record["status"] != "UNMODIFIED_BYTE_COPY":
        raise ValueError("original manifest status is invalid")
    member_name = parts[1]
    _validate_basename(member_name)
    fd = os.open(member_name, os.O_RDONLY | NOFOLLOW, dir_fd=archive_fd)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size != size_bytes:
            raise ValueError("archived original size or type is invalid")
        if _hash_fd(fd) != archived_sha256:
            raise ValueError("archived original hash no longer matches the manifest")
    finally:
        os.close(fd)
    return record


def _parse_manifest(archive_fd: int) -> dict[str, object]:
    try:
        data = _read_name(archive_fd, MANIFEST_NAME)
    except FileNotFoundError:
        return {"schema_version": 1, "archive_state": "PASS", "files": []}
    payload = json.loads(data.decode("utf-8"))
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "archive_state", "files"}:
        raise ValueError("original manifest schema is invalid")
    if payload["schema_version"] != 1 or payload["archive_state"] != "PASS":
        raise ValueError("original manifest state is invalid")
    if not isinstance(payload["files"], list):
        raise ValueError("original manifest files must be a list")
    identities: set[tuple[object, object, object]] = set()
    paths: set[object] = set()
    records = []
    for raw_record in payload["files"]:
        record = _validate_record(raw_record, archive_fd)
        identity = (record["source_role"], record["source_name"], record["source_sha256"])
        relative = record["archived_relative_path"]
        if identity in identities or relative in paths:
            raise ValueError("original manifest contains duplicate records")
        identities.add(identity)
        paths.add(relative)
        records.append(record)
    return {"schema_version": 1, "archive_state": "PASS", "files": records}


def _open_source(source: Path) -> tuple[int, os.stat_result, str]:
    if source.is_symlink() or not source.is_file():
        raise ValueError("each source must be a regular non-symlink file")
    fd = os.open(source, os.O_RDONLY | NOFOLLOW)
    info_before = os.fstat(fd)
    if not stat.S_ISREG(info_before.st_mode):
        os.close(fd)
        raise ValueError("each source must be a regular file")
    digest = _hash_fd(fd)
    info_after = os.fstat(fd)
    if _stable_stat(info_before) != _stable_stat(info_after):
        os.close(fd)
        raise RuntimeError("source changed while it was being inspected")
    return fd, info_after, digest


def _copy_source_fd(
    source_fd: int,
    source_before: os.stat_result,
    pre_sha256: str,
    archive_fd: int,
    destination_name: str,
) -> tuple[int, str]:
    destination_fd = os.open(
        destination_name,
        os.O_RDWR | os.O_CREAT | os.O_EXCL | NOFOLLOW,
        0o600,
        dir_fd=archive_fd,
    )
    try:
        os.lseek(source_fd, 0, os.SEEK_SET)
        digest = hashlib.sha256()
        copied = 0
        while True:
            chunk = os.read(source_fd, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            copied += len(chunk)
            _write_all(destination_fd, chunk)
        os.fsync(destination_fd)
        source_after_copy = os.fstat(source_fd)
        post_sha256 = _hash_fd(source_fd)
        source_final = os.fstat(source_fd)
        copied_sha256 = digest.hexdigest()
        if not (
            _stable_stat(source_before)
            == _stable_stat(source_after_copy)
            == _stable_stat(source_final)
        ):
            raise RuntimeError("source changed while it was being archived")
        if not (pre_sha256 == copied_sha256 == post_sha256):
            raise RuntimeError("source content changed while it was being archived")
        destination_info = os.fstat(destination_fd)
        if not stat.S_ISREG(destination_info.st_mode) or destination_info.st_size != copied:
            raise RuntimeError("archived copy size or type is invalid")
        if _hash_fd(destination_fd) != copied_sha256:
            raise RuntimeError("archived copy does not match the source")
        return copied, copied_sha256
    except BaseException:
        try:
            os.unlink(destination_name, dir_fd=archive_fd)
        except FileNotFoundError:
            pass
        raise
    finally:
        os.close(destination_fd)


def _validate_basename(name: str) -> None:
    if not name or Path(name).name != name or any(ord(char) < 32 for char in name):
        raise ValueError("source filename is invalid")
    if len(name.encode("utf-8")) > 180:
        raise ValueError("source filename is too long for a safe archive name")


@guarded
def archive_originals(
    task_dir: Path,
    sources: Iterable[tuple[str, Path]],
    *,
    allow_test_output: bool = False,
) -> dict[str, object]:
    items = [(role, Path(path)) for role, path in sources]
    if not items:
        return {"state": "NOT_APPLICABLE", "archived_count": 0}
    task_fd, task_dir = _open_task_directory(
        Path(task_dir), allow_test_output=allow_test_output
    )
    archive_fd = None
    created: list[str] = []
    manifest_committed = False
    lock_created = False
    try:
        archive_fd, archive_dir = _open_archive_directory(task_fd, task_dir)
        lock_fd = os.open(
            ".archive-originals.lock",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW,
            0o600,
            dir_fd=archive_fd,
        )
        lock_created = True
        try:
            lock_payload = json.dumps(
                {"pid": os.getpid(), "created_ns": time.time_ns()},
                sort_keys=True,
            ).encode("ascii")
            _write_all(lock_fd, lock_payload)
            os.fsync(lock_fd)
        finally:
            os.close(lock_fd)

        manifest = _parse_manifest(archive_fd)
        records = list(manifest["files"])
        existing = {
            (record["source_role"], record["source_name"], record["source_sha256"])
            for record in records
        }
        occupied = {record["archived_relative_path"] for record in records}

        for role, source in items:
            if not isinstance(role, str) or not ROLE_RE.fullmatch(role) or role in {".", ".."}:
                raise ValueError("source role is invalid")
            _validate_basename(source.name)
            source_fd, source_info, source_sha256 = _open_source(source)
            try:
                identity = (role, source.name, source_sha256)
                if identity in existing:
                    continue
                archived_name = f"原稿_{role}_{source.name}"
                _validate_basename(archived_name)
                relative = f"{ARCHIVE_DIR_NAME}/{archived_name}"
                if relative in occupied:
                    raise FileExistsError("an original archive destination already exists")
                try:
                    os.stat(archived_name, dir_fd=archive_fd, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    raise FileExistsError("an original archive destination already exists")
                size_bytes, copied_sha256 = _copy_source_fd(
                    source_fd,
                    source_info,
                    source_sha256,
                    archive_fd,
                    archived_name,
                )
                created.append(archived_name)
                records.append(
                    {
                        "source_role": role,
                        "source_name": source.name,
                        "archived_relative_path": relative,
                        "size_bytes": size_bytes,
                        "source_sha256": copied_sha256,
                        "archived_sha256": copied_sha256,
                        "byte_identical": True,
                        "source_unmodified": True,
                        "status": "UNMODIFIED_BYTE_COPY",
                    }
                )
                existing.add(identity)
                occupied.add(relative)
            finally:
                os.close(source_fd)

        payload = json.dumps(
            {"schema_version": 1, "archive_state": "PASS", "files": records},
            ensure_ascii=False,
            indent=2,
        ).encode("utf-8") + b"\n"
        temp_name = f".original-manifest-{secrets.token_hex(12)}"
        temp_fd = os.open(
            temp_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW,
            0o600,
            dir_fd=archive_fd,
        )
        try:
            _write_all(temp_fd, payload)
            os.fsync(temp_fd)
        finally:
            os.close(temp_fd)
        try:
            os.replace(temp_name, MANIFEST_NAME, src_dir_fd=archive_fd, dst_dir_fd=archive_fd)
            manifest_committed = True
        except BaseException:
            try:
                os.unlink(temp_name, dir_fd=archive_fd)
            except FileNotFoundError:
                pass
            raise
        os.fsync(archive_fd)
        if _stable_stat(os.fstat(archive_fd)) != _stable_stat(os.stat(archive_dir, follow_symlinks=False)):
            raise RuntimeError("00_原稿 changed during archive commit")
        return {
            "state": "PASS",
            "archived_count": len(records),
            "manifest": str(archive_dir / MANIFEST_NAME),
        }
    except BaseException:
        if archive_fd is not None and not manifest_committed:
            for name in reversed(created):
                try:
                    os.unlink(name, dir_fd=archive_fd)
                except FileNotFoundError:
                    pass
        raise
    finally:
        if archive_fd is not None:
            if lock_created:
                try:
                    os.unlink(".archive-originals.lock", dir_fd=archive_fd)
                except FileNotFoundError:
                    pass
            os.close(archive_fd)
        os.close(task_fd)


def _source_arg(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("source must use ROLE=PATH")
    role, path = value.split("=", 1)
    if not role or not path:
        raise argparse.ArgumentTypeError("source must use ROLE=PATH")
    return role, Path(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_dir", type=Path)
    parser.add_argument("--source", action="append", default=[], type=_source_arg)
    args = parser.parse_args()
    try:
        result = archive_originals(args.task_dir, args.source)
    except (OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"state": "BLOCKED", "error_type": type(exc).__name__}), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
