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
from datetime import date
from pathlib import Path
from typing import Iterable
from maintenance_boundary import guarded


WORKSPACE_ROOT = Path("/Users/macbook/ChatGPT/workspace")
ARCHIVE_DIR_NAME = "00_原稿"
MANIFEST_NAME = "原稿清单.json"
ROLE_RE = re.compile(r"^[^/\\\x00-\x1f]{1,40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
BATCH_ID_RE = re.compile(r"^B\d{2,}$")
UNKNOWN_ROLES = frozenset({'unknown', 'unclassified', '未分类', '待确认', '未知'})
BASE_RECORD_KEYS = {
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
OPTIONAL_RECORD_KEYS = {"material_batch_id", "supersedes"}
BATCH_KEYS = {"batch_id", "batch_date", "kind", "record_paths"}
DUPLICATE_KEYS = {
    "source_role", "source_name", "source_sha256",
    "existing_archived_relative_path", "status",
}
NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
DIRECTORY = getattr(os, "O_DIRECTORY", 0)


def _valid_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


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
    if (not isinstance(record, dict)
            or not BASE_RECORD_KEYS.issubset(record)
            or set(record) - (BASE_RECORD_KEYS | OPTIONAL_RECORD_KEYS)):
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
    if "material_batch_id" in record:
        batch_id = record["material_batch_id"]
        if not isinstance(batch_id, str) or not BATCH_ID_RE.fullmatch(batch_id):
            raise ValueError("original manifest material batch is invalid")
    if "supersedes" in record:
        supersedes = record["supersedes"]
        if not isinstance(supersedes, str) or not supersedes:
            raise ValueError("original manifest supersedes relation is invalid")
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
        return {"schema_version": 2, "archive_state": "PASS", "files": [], "batches": [], "duplicates": []}
    payload = json.loads(data.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("original manifest schema is invalid")
    schema_version = payload.get("schema_version")
    if schema_version not in {1, 2} or payload.get("archive_state") != "PASS":
        raise ValueError("original manifest state is invalid")
    if schema_version == 1 and set(payload) != {"schema_version", "archive_state", "files"}:
        raise ValueError("original manifest schema is invalid")
    if schema_version == 2 and set(payload) != {"schema_version", "archive_state", "files", "batches", "duplicates"}:
        raise ValueError("original manifest schema is invalid")
    if not isinstance(payload["files"], list):
        raise ValueError("original manifest files must be a list")
    identities: set[tuple[object, object, object]] = set()
    paths: set[object] = set()
    hashes: set[str] = set()
    records = []
    for raw_record in payload["files"]:
        record = _validate_record(raw_record, archive_fd)
        identity = (record["source_role"], record["source_name"], record["source_sha256"])
        relative = record["archived_relative_path"]
        if identity in identities or relative in paths:
            raise ValueError("original manifest contains duplicate records")
        identities.add(identity)
        paths.add(relative)
        hashes.add(record["source_sha256"])
        records.append(record)

    if schema_version == 1:
        records = [dict(record, material_batch_id="B00") for record in records]
        batches = []
        if records:
            batches.append({
                "batch_id": "B00",
                "batch_date": "unknown",
                "kind": "legacy-existing",
                "record_paths": [record["archived_relative_path"] for record in records],
            })
        return {"schema_version": 2, "archive_state": "PASS", "files": records,
                "batches": batches, "duplicates": []}

    batches = payload["batches"]
    duplicates = payload["duplicates"]
    if not isinstance(batches, list) or not isinstance(duplicates, list):
        raise ValueError("original manifest batches and duplicates must be lists")
    batch_ids: set[str] = set()
    mapped: set[str] = set()
    batch_for_path = {}
    legacy_paths = set()
    for batch in batches:
        if not isinstance(batch, dict) or set(batch) != BATCH_KEYS:
            raise ValueError("original manifest batch schema is invalid")
        batch_id = batch["batch_id"]
        batch_date = batch["batch_date"]
        record_paths = batch["record_paths"]
        if (not isinstance(batch_id, str) or not BATCH_ID_RE.fullmatch(batch_id)
                or batch_id in batch_ids):
            raise ValueError("original manifest batch id is invalid")
        if (not isinstance(batch_date, str)
                or (batch_date != "unknown" and (not DATE_RE.fullmatch(batch_date)
                                                  or _valid_date(batch_date) is False))):
            raise ValueError("original manifest batch date is invalid")
        if not isinstance(batch["kind"], str) or not batch["kind"]:
            raise ValueError("original manifest batch kind is invalid")
        if not isinstance(record_paths, list) or not record_paths:
            raise ValueError("original manifest batch records are invalid")
        for relative in record_paths:
            if not isinstance(relative, str) or relative not in paths or relative in mapped:
                raise ValueError("original manifest batch record mapping is invalid")
            mapped.add(relative)
            batch_for_path[relative] = batch_id
            if batch_id == "B00" and batch["kind"] == "legacy-existing":
                legacy_paths.add(relative)
        batch_ids.add(batch_id)
    if mapped != paths:
        raise ValueError("original manifest contains unmapped records")
    records_by_path = {r["archived_relative_path"]: r for r in records}
    paths_by_hash = {}
    earlier_paths = set()
    for record in records:
        relative = record["archived_relative_path"]
        if "material_batch_id" in record and record["material_batch_id"] != batch_for_path[relative]:
            raise ValueError("original manifest material batch mapping disagrees")
        paths_by_hash.setdefault(record["source_sha256"], []).append(relative)
        supersedes = record.get("supersedes")
        if supersedes is not None:
            if supersedes not in earlier_paths:
                raise ValueError("supersedes target must precede revision")
            if records_by_path[supersedes]["source_sha256"] == record["source_sha256"]:
                raise ValueError("revision must have different content")
        earlier_paths.add(relative)
    for same_hash_paths in paths_by_hash.values():
        if len(same_hash_paths) > 1 and not set(same_hash_paths).issubset(legacy_paths):
            raise ValueError("duplicate hashes outside legacy batch")
    for duplicate in duplicates:
        if not isinstance(duplicate, dict) or set(duplicate) != DUPLICATE_KEYS:
            raise ValueError("original manifest duplicate schema is invalid")
        if (not isinstance(duplicate["source_role"], str)
                or not ROLE_RE.fullmatch(duplicate["source_role"])
                or not isinstance(duplicate["source_name"], str)
                or not isinstance(duplicate["source_sha256"], str)
                or not SHA256_RE.fullmatch(duplicate["source_sha256"])
                or not isinstance(duplicate["existing_archived_relative_path"], str)
                or duplicate["existing_archived_relative_path"] not in paths
                or duplicate["status"] != "DUPLICATE_HASH"):
            raise ValueError("original manifest duplicate record is invalid")
        if duplicate["source_sha256"] != records_by_path[duplicate["existing_archived_relative_path"]]["source_sha256"]:
            raise ValueError("duplicate hash disagrees with target")
    return {"schema_version": 2, "archive_state": "PASS", "files": records,
            "batches": batches, "duplicates": duplicates}


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


def _next_batch_id(batches: list[dict[str, object]]) -> str:
    numbers = []
    for batch in batches:
        value = batch.get("batch_id") if isinstance(batch, dict) else None
        if isinstance(value, str) and BATCH_ID_RE.fullmatch(value):
            numbers.append(int(value[1:]))
    return f"B{max(numbers, default=0) + 1:02d}"


def _unique_archive_name(role: str, source_name: str, source_sha256: str,
                         occupied: set[str], archive_fd: int) -> str:
    base = f"原稿_{role}_{source_name}"
    candidates = [base]
    if base in occupied:
        source_path = Path(source_name)
        candidates.append(
            f"原稿_{role}_{source_path.stem}__{source_sha256[:12]}{source_path.suffix}"
        )
    index = 2
    while candidates:
        candidate = candidates.pop(0)
        try:
            _validate_basename(candidate)
        except ValueError:
            continue
        if candidate in occupied:
            if candidate == base:
                candidates.append(
                    f"原稿_{role}_{Path(source_name).stem}__{source_sha256[:12]}{Path(source_name).suffix}"
                )
            continue
        try:
            os.stat(candidate, dir_fd=archive_fd, follow_symlinks=False)
        except FileNotFoundError:
            return candidate
        if candidate == base:
            candidates.append(f"{Path(candidate).stem}__{source_sha256[:12]}{Path(candidate).suffix}")
        else:
            candidates.append(
                f"{Path(candidate).stem}-{index}{Path(candidate).suffix}"
            )
            index += 1
    raise FileExistsError("unable to allocate a unique original archive destination")


@guarded
def archive_originals(
    task_dir: Path,
    sources: Iterable[tuple[str, Path]],
    *,
    allow_test_output: bool = False,
    batch_id: str | None = None,
    batch_date: str | None = None,
    batch_kind: str | None = None,
    supersedes: dict[str, str] | None = None,
) -> dict[str, object]:
    items = [(role, Path(path)) for role, path in sources]
    supersedes = {} if supersedes is None else supersedes
    if not isinstance(supersedes, dict) or not all(
            isinstance(k, str) and isinstance(v, str) and v
            and k in {str(p) for _, p in items} for k, v in supersedes.items()):
        raise ValueError("supersedes must map supplied source paths to prior archive paths")
    if not items:
        return {"state": "NOT_APPLICABLE", "archived_count": 0}
    for role, _source in items:
        if (not isinstance(role, str) or not ROLE_RE.fullmatch(role)
                or not role.strip() or role in {".", ".."} or role.strip().casefold() in UNKNOWN_ROLES):
            raise ValueError("source role is unknown or invalid; archive is blocked")
    if batch_id is not None and (not isinstance(batch_id, str) or not BATCH_ID_RE.fullmatch(batch_id)):
        raise ValueError("batch_id must use B## format")
    if batch_date is not None and (batch_date != "unknown"
                                   and (not isinstance(batch_date, str)
                                        or not DATE_RE.fullmatch(batch_date)
                                        or not _valid_date(batch_date))):
        raise ValueError("batch_date must be an ISO date")
    if batch_kind is not None and (not isinstance(batch_kind, str) or not batch_kind.strip()):
        raise ValueError("batch_kind must be a non-empty string")
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
        batches = [dict(batch) for batch in manifest["batches"]]
        duplicates = list(manifest["duplicates"])
        existing_hashes = {record["source_sha256"] for record in records}
        archive_by_hash = {
            record["source_sha256"]: record["archived_relative_path"] for record in records
        }
        occupied = {record["archived_relative_path"] for record in records}
        frozen_batch_ids = {batch["batch_id"] for batch in batches}
        if any(value not in occupied for value in supersedes.values()):
            raise ValueError("supersedes must reference existing archived originals")
        new_record_paths: list[str] = []
        duplicate_count = 0
        active_batch_id = batch_id
        active_batch_date = batch_date
        active_batch_kind = batch_kind

        for role, source in items:
            _validate_basename(source.name)
            source_fd, source_info, source_sha256 = _open_source(source)
            try:
                if source_sha256 in existing_hashes:
                    if str(source) in supersedes:
                        raise ValueError("explicit revision content is already archived")
                    duplicates.append({
                        "source_role": role,
                        "source_name": source.name,
                        "source_sha256": source_sha256,
                        "existing_archived_relative_path": archive_by_hash[source_sha256],
                        "status": "DUPLICATE_HASH",
                    })
                    duplicate_count += 1
                    continue
                if active_batch_id is None:
                    active_batch_id = _next_batch_id(batches)
                if active_batch_id in frozen_batch_ids or active_batch_id == "B00":
                    raise ValueError("existing material batches are immutable")
                if active_batch_date is None:
                    active_batch_date = date.today().isoformat()
                if active_batch_kind is None:
                    active_batch_kind = "initial" if not records else "supplement"
                archived_name = _unique_archive_name(
                    role, source.name, source_sha256, occupied, archive_fd
                )
                relative = f"{ARCHIVE_DIR_NAME}/{archived_name}"
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
                        "material_batch_id": active_batch_id,
                    }
                )
                if str(source) in supersedes:
                    records[-1]["supersedes"] = supersedes[str(source)]
                existing_hashes.add(copied_sha256)
                archive_by_hash[copied_sha256] = relative
                occupied.add(relative)
                new_record_paths.append(relative)
            finally:
                os.close(source_fd)

        if new_record_paths:
            batches.append({
                "batch_id": active_batch_id, "batch_date": active_batch_date,
                "kind": active_batch_kind, "record_paths": list(new_record_paths),
            })

        payload = json.dumps(
            {"schema_version": 2, "archive_state": "PASS", "files": records,
             "batches": batches, "duplicates": duplicates},
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
            "new_count": len(new_record_paths),
            "duplicate_count": duplicate_count,
            "batch_id": active_batch_id,
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
    parser.add_argument("--batch-id")
    parser.add_argument("--batch-date")
    parser.add_argument("--batch-kind")
    parser.add_argument("--supersedes", help="existing archive path for a single explicit revision")
    args = parser.parse_args()
    if args.supersedes and len(args.source) != 1:
        parser.error("--supersedes requires exactly one --source")
    try:
        result = archive_originals(
            args.task_dir,
            args.source,
            batch_id=args.batch_id,
            batch_date=args.batch_date,
            batch_kind=args.batch_kind,
            supersedes={str(args.source[0][1]): args.supersedes} if args.supersedes else None,
        )
    except (OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"state": "BLOCKED", "error_type": type(exc).__name__}), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
