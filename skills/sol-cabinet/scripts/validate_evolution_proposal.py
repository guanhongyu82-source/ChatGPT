#!/usr/bin/env python3
"""Validate a Level 2/3 Sol Cabinet evolution proposal without writing it."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import sys
import tarfile
from pathlib import PurePosixPath
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from verify_evidence import verify_evidence
DEFAULT_EVIDENCE_DIR = ROOT.parent / "evidence"
DEFAULT_OBSERVATIONS = ROOT / "memory-evolution" / "observations"
DEFAULT_SNAPSHOT_DIR = Path("/Users/macbook/ChatGPT/lineage/codex-root/配置库/90_归档备份/sol-cabinet")
DEFAULT_TEST_REGISTRY = ROOT / "tests" / "test-registry.json"
ALLOWED_KEYS = {
    "proposal_id", "change_mode", "level", "lesson_code", "observation_ids", "target_module",
    "change_code", "required_test_ids", "status", "user_authorized",
    "contains_sensitive_content", "sensitivity_checked", "authorization_basis",
    "authorization_ref", "authorization_fingerprint", "changed_paths",
    "rollback_id", "base_sha256", "candidate_sha256", "test_run_id",
    "test_candidate_sha256", "independent_review_ids", "post_verification",
}
PROPOSAL_ID = re.compile(r"^proposal-[0-9a-f]{32}$")
OBSERVATION_ID = re.compile(r"^obs-[0-9a-f]{32}$")
TEST_ID = re.compile(r"^[A-Z][A-Z0-9-]{0,15}[0-9]{1,3}$")
ROLLBACK_ID = re.compile(r"^snapshot-[0-9]{4}-[0-9]{2}-[0-9]{2}-v[0-9]+(?:\.[0-9]+)*$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
AUTHORIZATION_REF = re.compile(r"^turn-[0-9a-f]{16,64}$")
TEST_RUN_ID = re.compile(r"^testrun-[0-9a-f]{32}$")
REVIEW_ID = re.compile(r"^review-[0-9a-f]{32}$")
LESSON_CODES = {
    "single-source-of-truth", "route-too-low", "route-too-high",
    "agent-underuse", "agent-overuse", "skill-misroute",
    "review-caught-defect", "review-missed-defect", "source-protection",
    "platform-drift", "permission-boundary", "sensitive-skip",
    "template-gap", "tool-failure", "source-archive-omission",
    "agent-stall", "field-refresh-warning", "tool-permission-retry",
    "other-approved",
}
TARGET_MODULES = {
    "core", "t0-router", "task-classification", "domain-skills",
    "agent-orchestrator", "review-system", "memory-evolution",
    "templates", "platform-adapter", "tests",
}
CHANGE_CODES = {
    "add-or-tighten-gate", "adjust-routing", "adjust-agent-plan",
    "reduce-redundancy", "fix-platform-drift", "add-regression-test",
    "retire-obsolete-rule",
}


def _metadata_digest(metadata: dict[str, dict[str, Any]]) -> str:
    lines = [f"{metadata[path]['sha256']}  {path}\n" for path in sorted(metadata)]
    return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()


def snapshot_metadata(root: Path = ROOT) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if path.is_symlink():
            raise ValueError("active system contains an unsupported symlink")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative.startswith(("memory-evolution/observations/", "memory-evolution/proposals/")):
            continue
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        data = path.read_bytes()
        metadata[relative] = {
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
            "mode": stat.S_IMODE(path.stat().st_mode),
        }
    return metadata


def system_digest(root: Path = ROOT) -> str:
    metadata = snapshot_metadata(root)
    return _metadata_digest(metadata)


def validate_snapshot(snapshot: Path, rollback_id: str, base_sha256: str) -> None:
    if snapshot.is_symlink() or not snapshot.is_file():
        raise ValueError("rollback snapshot is missing or unsafe")
    sidecar = Path(f"{snapshot}.sha256")
    if sidecar.is_symlink() or not sidecar.is_file():
        raise ValueError("rollback snapshot sidecar is missing or unsafe")
    archive_sha256 = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    expected_sidecar = f"{archive_sha256}  {snapshot.name}\n"
    if sidecar.read_text(encoding="ascii") != expected_sidecar:
        raise ValueError("rollback snapshot sidecar does not match the archive")

    archived_files: dict[str, dict[str, Any]] = {}
    manifest = None
    total_size = 0
    with tarfile.open(snapshot, "r:gz") as archive:
        members = archive.getmembers()
        if len(members) > 10_000:
            raise ValueError("rollback snapshot has too many members")
        for member in members:
            name = PurePosixPath(member.name)
            if name.is_absolute() or ".." in name.parts:
                raise ValueError("rollback snapshot contains an unsafe path")
            if member.issym() or member.islnk() or member.isdev():
                raise ValueError("rollback snapshot contains an unsafe member type")
            total_size += member.size
            if total_size > 100 * 1024 * 1024:
                raise ValueError("rollback snapshot exceeds the size limit")
            if not member.isfile():
                raise ValueError("rollback snapshot may contain only regular files")
            handle = archive.extractfile(member)
            if handle is None:
                raise ValueError("rollback snapshot member could not be read")
            data = handle.read()
            if member.name == "snapshot-manifest.json":
                if manifest is not None:
                    raise ValueError("rollback snapshot contains duplicate manifests")
                manifest = json.loads(data.decode("utf-8"))
                continue
            if len(name.parts) < 2 or name.parts[0] != "sol-cabinet":
                raise ValueError("rollback snapshot member is outside sol-cabinet")
            relative = PurePosixPath(*name.parts[1:]).as_posix()
            if relative.startswith(("memory-evolution/observations/", "memory-evolution/proposals/")):
                raise ValueError("rollback snapshot contains excluded mutable content")
            if "__pycache__" in name.parts or relative.endswith(".pyc"):
                raise ValueError("rollback snapshot contains excluded cache content")
            if relative in archived_files:
                raise ValueError("rollback snapshot contains duplicate paths")
            archived_files[relative] = {
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data),
                "mode": member.mode & 0o777,
            }
    if not isinstance(manifest, dict):
        raise ValueError("rollback snapshot manifest is missing")
    if set(manifest) != {"format", "rollback_id", "base_sha256", "source", "files"}:
        raise ValueError("rollback snapshot manifest schema is invalid")
    if manifest["format"] != 2 or manifest["rollback_id"] != rollback_id:
        raise ValueError("rollback snapshot identity does not match the proposal")
    if manifest["base_sha256"] != base_sha256 or manifest["source"] != str(ROOT):
        raise ValueError("rollback snapshot base does not match the proposal")
    if manifest["files"] != archived_files:
        raise ValueError("rollback snapshot file set or metadata is inconsistent")
    if _metadata_digest(archived_files) != base_sha256:
        raise ValueError("rollback snapshot content does not match the base SHA-256")


def validate(
    proposal: dict[str, Any],
    observations_dir: Path = DEFAULT_OBSERVATIONS,
    snapshot_dir: Path = DEFAULT_SNAPSHOT_DIR,
    test_registry_path: Path = DEFAULT_TEST_REGISTRY,
    *, evidence_dir: Path = DEFAULT_EVIDENCE_DIR, candidate_root: Path = ROOT,
) -> dict[str, Any]:
    unknown = set(proposal) - ALLOWED_KEYS
    if unknown:
        raise ValueError("proposal contains unknown fields")
    if proposal.get("contains_sensitive_content") is not False:
        raise ValueError("contains_sensitive_content must be false")
    if proposal.get("sensitivity_checked") is not True:
        raise ValueError("sensitivity_checked must be true")
    if not isinstance(proposal.get("proposal_id"), str) or not PROPOSAL_ID.fullmatch(
        proposal["proposal_id"]
    ):
        raise ValueError("proposal_id must be an opaque 32-hex identifier")
    change_mode = proposal.get("change_mode", "repeated-evolution")
    if change_mode not in {"repeated-evolution", "direct-policy-change"}:
        raise ValueError("change_mode is invalid")
    level = proposal.get("level")
    if type(level) is not int or level not in (2, 3):
        raise ValueError("level must be 2 or 3")
    if proposal.get("lesson_code") not in LESSON_CODES:
        raise ValueError("lesson_code is not registered")
    observations = proposal.get("observation_ids")
    if not isinstance(observations, list) or not all(
        isinstance(item, str) and OBSERVATION_ID.fullmatch(item) for item in observations
    ):
        raise ValueError("observation_ids must contain opaque observation IDs")
    minimum_observations = 2 if level == 2 else 3
    if change_mode == "repeated-evolution" and len(set(observations)) < minimum_observations:
        raise ValueError("insufficient independent observations for the requested level")
    if change_mode == "direct-policy-change" and (level != 3 or observations):
        raise ValueError("direct policy changes must be Level 3 without task observations")
    task_instances = set()
    for observation_id in observations:
        path = observations_dir / f"{observation_id}.json"
        if path.parent.resolve() != observations_dir.resolve() or path.is_symlink() or not path.is_file():
            raise ValueError("referenced observation is missing or unsafe")
        observation = json.loads(path.read_text(encoding="utf-8"))
        if observation.get("observation_id") != observation_id:
            raise ValueError("observation identity mismatch")
        if observation.get("level") != 1 or observation.get("sensitive") is not False:
            raise ValueError("proposal may reference only non-sensitive Level 1 observations")
        if proposal["lesson_code"] not in observation.get("lesson_codes", []):
            raise ValueError("proposal lesson is not supported by every observation")
        task_instance = observation.get("task_instance_id")
        if not isinstance(task_instance, str):
            raise ValueError("observation lacks an opaque task identity")
        task_instances.add(task_instance)
    if change_mode == "repeated-evolution" and len(task_instances) < minimum_observations:
        raise ValueError("observations must come from independent task instances")
    if proposal.get("target_module") not in TARGET_MODULES:
        raise ValueError("target_module is not registered")
    if proposal.get("change_code") not in CHANGE_CODES:
        raise ValueError("change_code is not registered")
    tests = proposal.get("required_test_ids")
    if not isinstance(tests, list) or not tests or not all(
        isinstance(item, str) and TEST_ID.fullmatch(item) for item in tests
    ):
        raise ValueError("required_test_ids must contain registered-style test IDs")
    registry = json.loads(test_registry_path.read_text(encoding="utf-8"))
    if not isinstance(registry, dict):
        raise ValueError("test registry is invalid")
    if any(test_id not in registry or registry[test_id].get("status") != "PASS" for test_id in tests):
        raise ValueError("required tests are not registered and passing")
    status = proposal.get("status")
    if status not in {"draft", "approved", "rejected", "applied", "post_verified"}:
        raise ValueError("status is invalid")
    authorized = proposal.get("user_authorized")
    if not isinstance(authorized, bool):
        raise ValueError("user_authorized must be an explicit boolean")
    if status in {"approved", "applied", "post_verified"} and not authorized:
        raise ValueError("approved or applied proposals require user authorization")
    candidate_sha256 = proposal.get("candidate_sha256")
    if candidate_sha256 is not None and (
        not isinstance(candidate_sha256, str) or not SHA256.fullmatch(candidate_sha256)
    ):
        raise ValueError("candidate_sha256 is invalid")

    if change_mode == "direct-policy-change":
        if proposal.get("authorization_basis") != "explicit-user-long-term-directive":
            raise ValueError("direct policy change authorization basis is invalid")
        if not isinstance(proposal.get("authorization_ref"), str) or not AUTHORIZATION_REF.fullmatch(
            proposal["authorization_ref"]
        ):
            raise ValueError("direct policy change authorization_ref is invalid")
        fingerprint = proposal.get("authorization_fingerprint")
        if not isinstance(fingerprint, str) or not SHA256.fullmatch(fingerprint):
            raise ValueError("direct policy change authorization fingerprint is invalid")
        changed_paths = proposal.get("changed_paths")
        if not isinstance(changed_paths, list) or not changed_paths:
            raise ValueError("direct policy change must list changed paths")
        for raw_path in changed_paths:
            if not isinstance(raw_path, str):
                raise ValueError("changed_paths must contain relative strings")
            path = PurePosixPath(raw_path)
            if path.is_absolute() or ".." in path.parts or not path.parts:
                raise ValueError("changed_paths contains an unsafe path")
    else:
        for field in (
            "authorization_basis", "authorization_ref", "authorization_fingerprint",
        ):
            if proposal.get(field) is not None:
                raise ValueError("repeated evolution may not claim direct policy fields")
        if proposal.get("changed_paths") not in (None, []):
            raise ValueError("repeated evolution may not claim direct changed paths")
    if status in {"approved", "applied", "post_verified"}:
        if candidate_sha256 is None:
            raise ValueError("approved or applied change requires candidate_sha256")
        if not isinstance(proposal.get("test_run_id"), str) or not TEST_RUN_ID.fullmatch(
            proposal["test_run_id"]
        ):
            raise ValueError("approved or applied change requires a test_run_id")
        if proposal.get("test_candidate_sha256") != candidate_sha256:
            raise ValueError("test run is not bound to the candidate")
        if candidate_root.is_symlink() or not candidate_root.is_dir():
            raise ValueError("candidate directory is missing or unsafe")
        if system_digest(candidate_root) != candidate_sha256:
            raise ValueError("candidate content does not match the evidence hash")
        reviews = proposal.get("independent_review_ids")
        if not isinstance(reviews, list) or not all(isinstance(item, str) for item in reviews) or len(set(reviews)) < 2 or not all(
            isinstance(item, str) and REVIEW_ID.fullmatch(item) for item in reviews
        ):
            raise ValueError("approved or applied change requires two independent reviews")
        verify_evidence(evidence_dir, candidate_sha256, proposal["test_run_id"],
                        reviews, tests, require_post_apply=status == "post_verified")
    if status == "post_verified" and proposal.get("post_verification") != "PASS":
        raise ValueError("post_verified changes require PASS evidence")
    rollback_id = proposal.get("rollback_id")
    base_sha256 = proposal.get("base_sha256")
    if status in {"approved", "applied", "post_verified"}:
        if not isinstance(rollback_id, str) or not ROLLBACK_ID.fullmatch(rollback_id):
            raise ValueError("approved or applied proposals require a rollback snapshot ID")
        if not isinstance(base_sha256, str) or not SHA256.fullmatch(base_sha256):
            raise ValueError("approved or applied proposals require a base SHA-256")
        snapshot = snapshot_dir / f"{rollback_id}.tar.gz"
        if snapshot.parent.resolve() != snapshot_dir.resolve():
            raise ValueError("rollback snapshot is missing or unsafe")
        validate_snapshot(snapshot, rollback_id, base_sha256)
        active_sha256 = system_digest(ROOT)
        if status == "approved" and base_sha256 != active_sha256:
            raise ValueError("approved change base does not match the active system")
        if status in {"applied", "post_verified"}:
            if candidate_sha256 is None or candidate_sha256 != active_sha256:
                raise ValueError("applied change candidate does not match the active system")
    elif rollback_id is not None or base_sha256 is not None:
        raise ValueError("draft or rejected proposals must not claim an active rollback point")
    return proposal


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("proposal")
    parser.add_argument("--evidence-dir", type=Path, default=DEFAULT_EVIDENCE_DIR)
    parser.add_argument("--candidate-root", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        raw = json.loads(Path(args.proposal).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("proposal must be a JSON object")
        validate(raw, DEFAULT_OBSERVATIONS, DEFAULT_SNAPSHOT_DIR, DEFAULT_TEST_REGISTRY,
                 evidence_dir=args.evidence_dir, candidate_root=args.candidate_root)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {type(exc).__name__}: proposal validation or I/O failed", file=sys.stderr)
        return 2
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
