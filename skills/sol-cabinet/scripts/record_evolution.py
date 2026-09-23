#!/usr/bin/env python3
"""Atomically record a transient sanitized Sol Cabinet evolution observation."""

from __future__ import annotations

import argparse
import hashlib
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
DEFAULT_OUTPUT = ROOT / "memory-evolution" / "observations"
ALLOWED_KEYS = {
    "task_instance_id",
    "date",
    "task_type",
    "planned_t",
    "actual_t",
    "planned_agents",
    "used_agents",
    "skill_routes",
    "outcome",
    "feedback_codes",
    "lesson_codes",
    "level",
    "sensitive",
    "sensitivity_checked",
    "lifecycle_state",
    "review_after_date",
    "consolidated_improvement_id",
}
TASK_TYPES = {
    "office-edit", "formal-writing", "spreadsheet", "presentation", "pdf",
    "research", "data-analysis", "repository-review", "security-audit",
    "skill-build", "system-build", "long-running-system", "office-system-build",
    "template-check", "other-non-sensitive",
}
SKILL_ROUTES = {
    "sol-cabinet", "documents:documents", "spreadsheets:Spreadsheets",
    "presentations:Presentations", "pdf:pdf", "research-agent",
    "repo-health-check", "security-audit", "skill-creator", "openai-docs",
    "data-analytics", "imagegen", "browser", "chrome", "computer-use",
}
FEEDBACK_CODES = {
    "no-user-correction", "user-specified-router", "user-corrected-fact",
    "user-corrected-tone", "user-corrected-scope", "user-corrected-format",
    "user-authorized-system-rule",
}
LESSON_CODES = {
    "single-source-of-truth", "route-too-low", "route-too-high",
    "agent-underuse", "agent-overuse", "skill-misroute",
    "review-caught-defect", "review-missed-defect", "source-protection",
    "platform-drift", "permission-boundary", "sensitive-skip",
    "template-gap", "tool-failure", "source-archive-omission",
    "agent-stall", "field-refresh-warning", "tool-permission-retry",
    "other-approved",
}
TASK_INSTANCE_ID = re.compile(r"^task-[0-9a-f]{32}$")


def _validate_codes(value: Any, field: str, allowed: set[str]) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be a list of strings")
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"{field} contains unregistered codes")
    return value


def validate(entry: dict[str, Any]) -> dict[str, Any]:
    unknown = set(entry) - ALLOWED_KEYS
    if unknown:
        raise ValueError("entry contains unknown fields")
    if entry.get("sensitivity_checked") is not True:
        raise ValueError("sensitivity_checked must be true before persistence")
    if not isinstance(entry.get("sensitive"), bool):
        raise ValueError("sensitive must be an explicit boolean")
    if entry["sensitive"] is True:
        return {"status": "SKIPPED_SENSITIVE"}

    task_type = entry.get("task_type")
    task_instance_id = entry.get("task_instance_id")
    if not isinstance(task_instance_id, str) or not TASK_INSTANCE_ID.fullmatch(task_instance_id):
        raise ValueError("task_instance_id must be an opaque 32-hex identifier")
    if task_type not in TASK_TYPES:
        raise ValueError("task_type must be a registered non-sensitive category")

    entry_date = entry.get("date", date.today().isoformat())
    if not isinstance(entry_date, str):
        raise ValueError("date must be an ISO date string")
    try:
        date.fromisoformat(entry_date)
    except ValueError as exc:
        raise ValueError("date must be a valid ISO date") from exc
    entry["date"] = entry_date
    if entry.get("lifecycle_state") != "intake":
        raise ValueError("new observations must start in the intake lifecycle state")
    review_after = entry.get("review_after_date")
    if not isinstance(review_after, str):
        raise ValueError("review_after_date must be an ISO date string")
    try:
        review_date = date.fromisoformat(review_after)
    except ValueError as exc:
        raise ValueError("review_after_date must be a valid ISO date") from exc
    if review_date < date.fromisoformat(entry_date):
        raise ValueError("review_after_date may not precede the observation date")
    if entry.get("consolidated_improvement_id") is not None:
        raise ValueError("new intake observations may not claim consolidation")

    for field in ("planned_t", "actual_t", "level"):
        if type(entry.get(field)) is not int:
            raise ValueError(f"{field} must be an integer")
    if not 1 <= entry["planned_t"] <= 10 or not 1 <= entry["actual_t"] <= 10:
        raise ValueError("T values must be in 1..10")
    if entry["level"] != 1:
        raise ValueError("observations must be Level 1; use a validated proposal for Level 2 or 3")

    for field in ("planned_agents", "used_agents"):
        if type(entry.get(field)) is not int or entry[field] < 1:
            raise ValueError(f"{field} must be a positive integer")

    outcome = entry.get("outcome")
    if outcome not in {"pass", "partial", "blocked", "fail"}:
        raise ValueError("outcome must be pass, partial, blocked, or fail")

    entry["skill_routes"] = _validate_codes(
        entry.get("skill_routes", []), "skill_routes", SKILL_ROUTES
    )
    entry["feedback_codes"] = _validate_codes(
        entry.get("feedback_codes", []), "feedback_codes", FEEDBACK_CODES
    )
    entry["lesson_codes"] = _validate_codes(
        entry.get("lesson_codes", []), "lesson_codes", LESSON_CODES
    )
    entry["sensitive"] = False
    return entry


@guarded
def write_observation(
    entry: dict[str, Any], output_dir: Path, *, allow_test_output: bool = False, user_authorized: bool = False
) -> Path | None:
    clean = validate(dict(entry))
    if clean.get("status") == "SKIPPED_SENSITIVE":
        return None
    if user_authorized is not True:
        raise ValueError("persistent observations require explicit user authorization")
    canonical_output = output_dir.resolve(strict=False)
    canonical_default = DEFAULT_OUTPUT.resolve(strict=False)
    if canonical_output != canonical_default and not allow_test_output:
        raise ValueError("output_dir must be the canonical observations directory")
    if output_dir.exists() and output_dir.is_symlink():
        raise ValueError("output_dir must not be a symlink")
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(output_dir, 0o700)
    observation_id = "obs-" + hashlib.sha256(clean["task_instance_id"].encode("ascii")).hexdigest()[:32]
    clean["observation_id"] = observation_id
    destination = output_dir / f"{observation_id}.json"
    payload = json.dumps(clean, ensure_ascii=False, indent=2) + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=".sol-evolution-", dir=output_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, 0o600)
        os.link(temp_name, destination)
        os.unlink(temp_name)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("entry", help="path to a sanitized JSON entry")
    parser.add_argument("--user-authorized", action="store_true", help="assert explicit user authorization for this persistent record")
    args = parser.parse_args()
    try:
        raw = json.loads(Path(args.entry).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("entry must be a JSON object")
        path = write_observation(raw, DEFAULT_OUTPUT, user_authorized=args.user_authorized)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {type(exc).__name__}: validation or I/O failed", file=sys.stderr)
        return 2
    if path is None:
        print("SKIPPED_SENSITIVE")
    else:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
