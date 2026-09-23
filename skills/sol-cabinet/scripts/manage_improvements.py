#!/usr/bin/env python3
"""Validate and atomically update the single Sol Cabinet improvement registry."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any
from maintenance_boundary import guarded


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REGISTRY = ROOT / "memory-evolution" / "improvements.json"
DEFAULT_OBSERVATIONS = ROOT / "memory-evolution" / "observations"
IMPROVEMENT_ID = re.compile(r"^OL-[0-9]{3}$")
OBSERVATION_ID = re.compile(r"^obs-[0-9a-f]{32}$")
ITEM_KEYS = {
    "improvement_id", "status", "scope_code", "blocker_code",
    "root_cause_code", "solution_code", "prevention_code", "verification_code",
    "first_seen_date", "last_seen_date", "last_verified_date", "recurrence_count",
    "sensitive", "contains_sensitive_content", "sensitivity_checked",
}
STATUSES = {"OPEN", "INTEGRATING", "VERIFIED", "CLOSED", "RECURRENT"}
SCOPES = {
    "file-governance", "routing", "agent-orchestration", "office", "review",
    "evolution", "platform",
}
BLOCKERS = {
    "source-archive-omission", "agent-parallelism-underuse",
    "page-field-update-warning", "reviewer-stall", "preview-permission-block",
    "candidate-test-unbound", "rollback-state-incomplete", "external-source-material-drift",
}
ROOT_CAUSES = {
    "archive-gate-too-late", "agent-plan-not-locked",
    "global-field-refresh-overbroad", "review-scope-overbroad",
    "sandbox-service-boundary", "static-pass-registry",
    "approval-applied-state-conflated", "concurrent-external-writer",
}
SOLUTIONS = {
    "global-archive-gate-and-script", "parallel-readonly-waves",
    "remove-page-only-updatefields", "bounded-review-replacement",
    "single-controlled-escalation", "candidate-bound-test-run",
    "split-state-and-restore-drill", "fail-closed-and-separate-reconciliation",
}
PREVENTIONS = {
    "archive-before-content", "truthful-agent-trace",
    "field-and-external-rel-audit", "minimal-review-schema", "preview-preflight",
    "invalidate-test-on-candidate-change", "verified-rollback-state-machine",
    "pre-post-source-integrity-check",
}
VERIFICATIONS = {
    "archive-regression-and-live-idempotency", "pending-ab-measurement",
    "ooxml-structural-diff", "pending-next-review-run", "controlled-preview-pass",
    "candidate-binding-tests-pass", "pending-restore-drill",
    "pending-source-owner-reconciliation",
}


def _iso_date(value: object, field: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO date")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO date") from exc
    return value


def validate_item(raw: object) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) != ITEM_KEYS:
        raise ValueError("improvement item schema is invalid")
    item = dict(raw)
    if not isinstance(item["improvement_id"], str) or not IMPROVEMENT_ID.fullmatch(
        item["improvement_id"]
    ):
        raise ValueError("improvement_id is invalid")
    if item["status"] not in STATUSES or item["scope_code"] not in SCOPES:
        raise ValueError("improvement status or scope is invalid")
    if item["blocker_code"] not in BLOCKERS:
        raise ValueError("blocker_code is invalid")
    if item["root_cause_code"] not in ROOT_CAUSES:
        raise ValueError("root_cause_code is invalid")
    if item["solution_code"] not in SOLUTIONS or item["prevention_code"] not in PREVENTIONS:
        raise ValueError("solution or prevention code is invalid")
    if item["verification_code"] not in VERIFICATIONS:
        raise ValueError("verification_code is invalid")
    if item["status"] in {"VERIFIED", "CLOSED"} and item["verification_code"].startswith("pending-"):
        raise ValueError("pending verification cannot be verified or closed")
    if item["sensitive"] is not False or item["contains_sensitive_content"] is not False:
        raise ValueError("sensitive improvements are forbidden")
    if item["sensitivity_checked"] is not True:
        raise ValueError("sensitivity_checked must be true")
    first = _iso_date(item["first_seen_date"], "first_seen_date")
    last = _iso_date(item["last_seen_date"], "last_seen_date")
    verified = _iso_date(item["last_verified_date"], "last_verified_date", nullable=True)
    if first > last:
        raise ValueError("improvement dates are inconsistent")
    if item["status"] in {"VERIFIED", "CLOSED"} and verified is None:
        raise ValueError("verified or closed improvements require a verification date")
    if type(item["recurrence_count"]) is not int or item["recurrence_count"] < 1:
        raise ValueError("recurrence_count must be a positive integer")
    return item


def validate_registry(raw: object) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) != {"schema_version", "items"}:
        raise ValueError("improvement registry schema is invalid")
    if raw["schema_version"] != 1 or not isinstance(raw["items"], list):
        raise ValueError("improvement registry version or items are invalid")
    items = [validate_item(item) for item in raw["items"]]
    ids = [item["improvement_id"] for item in items]
    blockers = [item["blocker_code"] for item in items]
    if len(ids) != len(set(ids)) or len(blockers) != len(set(blockers)):
        raise ValueError("improvement registry contains duplicate identities")
    return {"schema_version": 1, "items": items}


def _load_registry(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("improvement registry is missing or unsafe")
    return validate_registry(json.loads(path.read_text(encoding="utf-8")))


@guarded
def upsert_item(
    item: dict[str, Any],
    registry_path: Path = DEFAULT_REGISTRY,
    *,
    allow_test_output: bool = False,
    user_authorized: bool = False,
) -> Path:
    if user_authorized is not True:
        raise ValueError("persistent improvement updates require explicit user authorization")
    clean = validate_item(item)
    if registry_path.resolve(strict=False) != DEFAULT_REGISTRY.resolve(strict=False) and not allow_test_output:
        raise ValueError("registry_path must be the canonical improvement registry")
    if registry_path.exists():
        registry = _load_registry(registry_path)
    else:
        registry = {"schema_version": 1, "items": []}
    existing_by_id = {value["improvement_id"]: value for value in registry["items"]}
    for value in registry["items"]:
        if value["blocker_code"] == clean["blocker_code"] and value["improvement_id"] != clean["improvement_id"]:
            raise ValueError("the blocker must update its existing improvement item")
    prior = existing_by_id.get(clean["improvement_id"])
    if prior is not None:
        if clean["recurrence_count"] < prior["recurrence_count"]:
            raise ValueError("recurrence_count may not decrease")
        if clean["last_seen_date"] < prior["last_seen_date"]:
            raise ValueError("last_seen_date may not move backward")
        registry["items"] = [
            clean if value["improvement_id"] == clean["improvement_id"] else value
            for value in registry["items"]
        ]
    else:
        registry["items"].append(clean)
    validate_registry(registry)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    lock = registry_path.parent / ".improvements.lock"
    lock_fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(lock_fd)
    try:
        fd, temp_name = tempfile.mkstemp(prefix=".improvements-", dir=registry_path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(registry, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp_name, 0o600)
            os.replace(temp_name, registry_path)
        except BaseException:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise
    finally:
        lock.unlink()
    return registry_path


@guarded
def retire_observations(
    observation_ids: list[str],
    improvement_id: str,
    *,
    registry_path: Path = DEFAULT_REGISTRY,
    observations_dir: Path = DEFAULT_OBSERVATIONS,
    allow_test_output: bool = False,
    user_authorized: bool = False,
) -> int:
    if user_authorized is not True:
        raise ValueError("observation retirement requires explicit user authorization")
    registry = _load_registry(registry_path)
    matching = [item for item in registry["items"] if item["improvement_id"] == improvement_id]
    if len(matching) != 1 or matching[0]["status"] not in {"VERIFIED", "CLOSED"}:
        raise ValueError("observations may retire only into a verified central improvement")
    if observations_dir.resolve(strict=False) != DEFAULT_OBSERVATIONS.resolve(strict=False) and not allow_test_output:
        raise ValueError("observations_dir must be canonical")
    paths = []
    for observation_id in observation_ids:
        if not isinstance(observation_id, str) or not OBSERVATION_ID.fullmatch(observation_id):
            raise ValueError("observation ID is invalid")
        path = observations_dir / f"{observation_id}.json"
        if path.is_symlink() or not path.is_file() or path.parent.resolve() != observations_dir.resolve():
            raise ValueError("observation is missing or unsafe")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("observation_id") != observation_id or payload.get("sensitive") is not False:
            raise ValueError("observation identity or sensitivity is invalid")
        paths.append(path)
    for path in paths:
        path.unlink()
    return len(paths)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        registry = _load_registry(DEFAULT_REGISTRY)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"verdict": "FAIL", "error_type": type(exc).__name__}))
        return 2
    print(json.dumps({"verdict": "PASS", "items": len(registry["items"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
