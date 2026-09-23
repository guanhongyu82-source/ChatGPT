#!/usr/bin/env python3
"""Create a validated, non-overwriting Sol Cabinet rollback snapshot."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import os
import re
import stat
import tarfile
import tempfile
from pathlib import Path
from maintenance_boundary import guarded


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = Path("/Users/macbook/ChatGPT/lineage/codex-root/配置库/90_归档备份/sol-cabinet")
ROLLBACK_ID = re.compile(r"^snapshot-[0-9]{4}-[0-9]{2}-[0-9]{2}-v[0-9]+(?:\.[0-9]+)*$")


def _validator_module():
    path = ROOT / "scripts" / "validate_evolution_proposal.py"
    spec = importlib.util.spec_from_file_location("sol_snapshot_validator", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("snapshot validator unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _included_files(root: Path):
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if path.is_symlink():
            raise ValueError(f"snapshot source contains a symlink: {path.relative_to(root)}")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative.startswith(("memory-evolution/observations/", "memory-evolution/proposals/")):
            continue
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        yield path, relative


@guarded
def create_snapshot(
    rollback_id: str,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    allow_test_output: bool = False,
) -> tuple[Path, str]:
    if not ROLLBACK_ID.fullmatch(rollback_id):
        raise ValueError("rollback_id is invalid")
    if output_dir.resolve(strict=False) != DEFAULT_OUTPUT_DIR.resolve(strict=False) and not allow_test_output:
        raise ValueError("output directory is outside the approved backup root")
    if output_dir.exists() and output_dir.is_symlink():
        raise ValueError("output directory must not be a symlink")
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(output_dir, 0o700)
    destination = output_dir / f"{rollback_id}.tar.gz"
    sidecar = output_dir / f"{rollback_id}.tar.gz.sha256"
    if destination.exists() or sidecar.exists():
        raise FileExistsError("rollback snapshot already exists")

    validator = _validator_module()
    base_sha256 = validator.system_digest(ROOT)
    file_metadata = validator.snapshot_metadata(ROOT)
    manifest = {
        "format": 2,
        "rollback_id": rollback_id,
        "base_sha256": base_sha256,
        "source": str(ROOT),
        "files": file_metadata,
    }

    fd, temp_name = tempfile.mkstemp(prefix=f".{rollback_id}.", suffix=".tar.gz", dir=output_dir)
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        with tarfile.open(temp_path, "w:gz") as archive:
            manifest_bytes = (json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
            info = tarfile.TarInfo("snapshot-manifest.json")
            info.size = len(manifest_bytes)
            info.mode = 0o600
            info.mtime = 0
            archive.addfile(info, io.BytesIO(manifest_bytes))
            for path, relative in _included_files(ROOT):
                data = path.read_bytes()
                info = tarfile.TarInfo(f"sol-cabinet/{relative}")
                info.size = len(data)
                info.mode = stat.S_IMODE(path.stat().st_mode)
                info.mtime = 0
                archive.addfile(info, io.BytesIO(data))
        os.chmod(temp_path, 0o600)
        with temp_path.open("rb") as handle:
            os.fsync(handle.fileno())
        archive_sha256 = hashlib.sha256(temp_path.read_bytes()).hexdigest()
        os.link(temp_path, destination)
        temp_path.unlink()
        side_fd = os.open(sidecar, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(side_fd, "w", encoding="ascii") as handle:
            handle.write(f"{archive_sha256}  {destination.name}\n")
            handle.flush()
            os.fsync(handle.fileno())
        validator.validate_snapshot(destination, rollback_id, base_sha256)
        directory_fd = os.open(output_dir, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return destination, base_sha256
    except BaseException:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass
        if sidecar.exists():
            sidecar.unlink()
        if destination.exists():
            destination.unlink()
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rollback_id")
    args = parser.parse_args()
    try:
        path, base_sha256 = create_snapshot(args.rollback_id)
    except (OSError, RuntimeError, ValueError) as exc:
        print(json.dumps({"verdict": "FAIL", "error_type": type(exc).__name__}))
        return 2
    print(json.dumps({"verdict": "PASS", "path": str(path), "base_sha256": base_sha256}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
