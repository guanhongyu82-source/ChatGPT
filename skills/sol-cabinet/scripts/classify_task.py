#!/usr/bin/env python3
"""Deterministic helper for Sol Cabinet T1-T10 classification.

The model still owns semantic judgment. This script makes borderline and
T4+ routing decisions reproducible from an anonymized task profile.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any


PROFILE_FIELDS = {
    "file_count", "input_size_kb", "deliverable_count", "steps", "complexity",
    "professional_roles", "multi_angle", "needs_research", "fact_risk",
    "current_fact", "multi_source", "formal_publish", "office_artifact",
    "multiple_deliverables", "sensitive", "secret_bearing", "high_risk",
    "regulated", "external_action", "destructive_action", "multi_stage",
    "long_running", "system_build", "explicit_t", "user_full_power",
    "user_fast", "user_compact", "needs_review", "data_task",
    "repository_task", "security_task", "materials_state",
    "memory_isolation_confirmed",
    "bounded_edit", "independent_work_units", "parallel_benefit",
    "available_subagent_slots", "additional_execution_agent_budget",
    "stage_complete", "next_stage_authorized", "formal_normative_additions",
}


def _as_int(profile: dict[str, Any], key: str, default: int = 0) -> int:
    value = profile.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be a JSON integer")
    if not 0 <= value <= 1_000_000:
        raise ValueError(f"{key} must be in 0..1000000")
    return value


def _as_float(profile: dict[str, Any], key: str, default: float = 0.0) -> float:
    value = profile.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a JSON number")
    number = float(value)
    if not math.isfinite(number) or not 0 <= number <= 1_000_000_000_000:
        raise ValueError(f"{key} must be finite and non-negative")
    return number


def _flag(profile: dict[str, Any], key: str) -> bool:
    value = profile.get(key, False)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a JSON boolean")
    return value


def _score_to_level(score: int) -> int:
    thresholds = ((1, 1), (3, 2), (5, 3), (7, 4), (9, 5),
                  (11, 6), (13, 7), (15, 8), (17, 9), (18, 10))
    for maximum, level in thresholds:
        if score <= maximum:
            return level
    return 10


def _scope_axis(profile: dict[str, Any]) -> int:
    files = _as_int(profile, "file_count")
    size_kb = _as_float(profile, "input_size_kb")
    deliverables = _as_int(profile, "deliverable_count", 1)
    steps = _as_int(profile, "steps", 1)
    if files >= 20 or size_kb >= 500 or deliverables >= 3 or steps >= 10:
        return 3
    if files >= 5 or size_kb >= 100 or deliverables >= 2 or steps >= 5:
        return 2
    if files >= 1 or size_kb >= 10 or steps >= 2:
        return 1
    return 0


def _reasoning_axis(profile: dict[str, Any]) -> int:
    complexity = _as_int(profile, "complexity")
    if complexity > 3:
        raise ValueError("complexity must be in 0..3")
    roles = _as_int(profile, "professional_roles", 1)
    if _flag(profile, "multi_angle") or roles >= 4:
        complexity = max(complexity, 2)
    if roles >= 8:
        complexity = 3
    return complexity


def _evidence_axis(profile: dict[str, Any]) -> int:
    signals = sum(
        _flag(profile, key)
        for key in ("needs_research", "fact_risk", "current_fact", "multi_source")
    )
    return min(3, signals)


def _delivery_axis(profile: dict[str, Any]) -> int:
    signals = sum(
        _flag(profile, key)
        for key in ("formal_publish", "office_artifact", "multiple_deliverables")
    )
    if _as_int(profile, "deliverable_count", 1) >= 3:
        signals += 1
    return min(3, signals)


def _risk_axis(profile: dict[str, Any]) -> int:
    score = 0
    if _flag(profile, "sensitive") or _flag(profile, "secret_bearing"):
        score += 2
    if _flag(profile, "high_risk") or _flag(profile, "regulated"):
        score += 2
    if _flag(profile, "external_action") or _flag(profile, "destructive_action"):
        score += 1
    return min(3, score)


def _duration_axis(profile: dict[str, Any]) -> int:
    score = 0
    if _flag(profile, "multi_stage"):
        score += 1
    if _flag(profile, "long_running"):
        score += 2
    if _flag(profile, "system_build"):
        score += 2
    return min(3, score)


def _bounded_edit(profile: dict[str, Any]) -> bool:
    """A narrow existing-file edit cannot downgrade evidence or safety risks."""
    if not _flag(profile, "bounded_edit"):
        return False
    return (
        _as_int(profile, "file_count") <= 1
        and _as_int(profile, "deliverable_count", 1) <= 1
        and _as_int(profile, "steps", 1) <= 3
        and _as_int(profile, "complexity") <= 1
        and not any(_flag(profile, key) for key in (
            "formal_publish", "formal_normative_additions", "multiple_deliverables", "multi_source",
            "multi_angle", "fact_risk", "current_fact", "needs_research",
            "sensitive", "secret_bearing", "high_risk", "regulated",
            "external_action", "destructive_action", "system_build",
            "long_running", "multi_stage",
        ))
    )


def _optional_count(profile: dict[str, Any], key: str) -> int | None:
    return None if profile.get(key) is None else _as_int(profile, key)


def _resource_plan(profile: dict[str, Any], reviewers: int) -> dict[str, Any]:
    """Plan only independently identified work; unknown benefit means no fan-out.

    Reviewer minimums are independence requirements, not execution-team bands.
    Counts are runtime inputs, never a mapping from T level or model generation.
    """
    units = _as_int(profile, "independent_work_units")
    benefit = profile.get("parallel_benefit", "unknown")
    if not isinstance(benefit, str) or benefit not in {"positive", "nonpositive", "unknown"}:
        raise ValueError("parallel_benefit must be positive, nonpositive, or unknown")
    budget = _optional_count(profile, "additional_execution_agent_budget")
    slots = _optional_count(profile, "available_subagent_slots")
    selected = units if benefit == "positive" else 0
    if budget is not None:
        selected = min(selected, budget)
    if slots == 0:
        selected = 0
    return {
        "minimum": 1 + reviewers,
        "maximum": None,
        "planned": 1 + reviewers + selected,
        "count_includes_final_lead": True,
        "physical_concurrency_is_separate": True,
        "independent_work_units": units,
        "additional_execution_agents": selected,
        "additional_execution_agent_budget": budget,
        "available_subagent_slots": slots,
        "parallel_benefit": benefit,
        "review_execution_blocked": reviewers > 0 and slots == 0,
        "unallocated_units_stay_with_lead": True,
        "planning_basis": "identified-independent-work-and-benefit; no-level-headcount-band",
    }


def classify(profile: dict[str, Any]) -> dict[str, Any]:
    unknown = set(profile) - PROFILE_FIELDS
    if unknown:
        raise ValueError("profile contains unknown fields")
    materials_state = profile.get("materials_state", "READY")
    if not isinstance(materials_state, str) or materials_state not in {"READY", "PARTIAL", "BLOCKED"}:
        raise ValueError("materials_state must be READY, PARTIAL, or BLOCKED")
    bounded_edit = _bounded_edit(profile)
    stage_complete = _flag(profile, "stage_complete")
    next_stage_authorized = _flag(profile, "next_stage_authorized")
    axes = {
        "scope": _scope_axis(profile),
        "reasoning": _reasoning_axis(profile),
        "evidence": _evidence_axis(profile),
        "delivery": _delivery_axis(profile),
        "risk": _risk_axis(profile),
        "duration": _duration_axis(profile),
    }
    score = sum(axes.values())
    level = _score_to_level(score)
    hard_gates: list[str] = []
    if bounded_edit:
        # The selected edit, not the whole container file, is the work unit.
        axes["scope"] = min(axes["scope"], 1)
        axes["reasoning"] = min(axes["reasoning"], 1)
        score = sum(axes.values())
        level = min(2, _score_to_level(score))
        hard_gates.append("bounded-edit-short-path")

    def floor(minimum: int, reason: str) -> None:
        nonlocal level
        if level < minimum:
            level = minimum
        hard_gates.append(reason)

    if _flag(profile, "formal_normative_additions") or _flag(profile, "formal_publish") or (_flag(profile, "office_artifact") and not bounded_edit):
        floor(4, "formal-or-office")
    if _flag(profile, "needs_review"):
        floor(3, "explicit-review")
    if (
        _flag(profile, "needs_research")
        and (_flag(profile, "current_fact") or _flag(profile, "fact_risk"))
    ):
        floor(5, "current-or-fact-sensitive-research")
    if _as_int(profile, "file_count") >= 3 and _flag(profile, "fact_risk"):
        floor(5, "multi-file-fact-synthesis")
    if _flag(profile, "high_risk") or _flag(profile, "regulated"):
        floor(6, "high-risk")
    if _flag(profile, "secret_bearing"):
        floor(6, "secret-bearing")
    if (
        (_flag(profile, "high_risk") or _flag(profile, "regulated"))
        and _flag(profile, "multi_source")
        and _flag(profile, "multi_angle")
        and _as_int(profile, "file_count") >= 20
    ):
        floor(7, "large-multi-source-high-risk-audit")
    if (
        (_flag(profile, "sensitive") or _flag(profile, "secret_bearing"))
        and (_flag(profile, "formal_publish") or _flag(profile, "fact_risk"))
    ):
        floor(7, "sensitive-formal-or-factual")
    if (
        _as_int(profile, "file_count") >= 20
        and _flag(profile, "formal_publish")
        and _flag(profile, "multi_source")
    ):
        floor(8, "large-multi-source-formal")
    if _flag(profile, "system_build"):
        floor(9, "system-build")
    if _flag(profile, "system_build") and _flag(profile, "long_running"):
        floor(10, "long-running-system")
    elif _flag(profile, "long_running"):
        floor(8, "long-running")

    explicit_t = profile.get("explicit_t")
    if explicit_t is not None:
        if isinstance(explicit_t, bool) or not isinstance(explicit_t, int):
            raise ValueError("explicit_t must be a JSON integer")
        if not 1 <= explicit_t <= 10:
            raise ValueError("explicit_t must be in 1..10")
        requested = explicit_t
        if requested > level:
            level = requested
            hard_gates.append("user-explicit-t")

    if _flag(profile, "user_full_power"):
        resource_mode = "full-power"
    elif _flag(profile, "user_fast"):
        resource_mode = "fast-with-gates"
    elif _flag(profile, "user_compact"):
        resource_mode = "compact-deliverable"
    else:
        resource_mode = "balanced"

    risk_tags = [
        key.replace("_", "-")
        for key in (
            "fact_risk",
            "current_fact",
            "sensitive",
            "secret_bearing",
            "high_risk",
            "regulated",
            "external_action",
            "destructive_action",
            "long_running",
        )
        if _flag(profile, key)
    ]

    if level <= 3 and not _flag(profile, "needs_review"):
        reviewers = 0
        rounds = 0
    elif level <= 6:
        reviewers = 1
        rounds = 1
    elif level <= 8:
        reviewers = 2
        rounds = 1
    else:
        reviewers = 2
        rounds = 2
    agents = _resource_plan(profile, reviewers)
    role_tasks = ["final_lead"]
    if reviewers:
        role_tasks.append("final_verifier")
    if reviewers > 1:
        role_tasks.append("independent_risk_or_fact_reviewer")
    if agents["additional_execution_agents"]:
        role_tasks.append("bounded_execution_units")
    sensitive_context = _flag(profile, "sensitive") or _flag(profile, "secret_bearing")

    skill_routes = []
    if _flag(profile, "office_artifact"):
        skill_routes.append("office-artifact-skill")
    if (_flag(profile, "needs_research") or _flag(profile, "current_fact")) and not sensitive_context:
        skill_routes.append("research")
    if _flag(profile, "data_task"):
        skill_routes.append("local-data-analysis" if sensitive_context else "data-analytics")
    if _flag(profile, "repository_task"):
        skill_routes.append("repo-health-check")
    if _flag(profile, "security_task"):
        skill_routes.append("security-audit")
    if _flag(profile, "system_build"):
        skill_routes.append("skill-creator")

    stop_conditions = ["missing-key-material", "new-external-authority", "hard-source-conflict",
                       "stage-complete-stop-and-reclassify"]
    if _flag(profile, "sensitive") or _flag(profile, "secret_bearing"):
        stop_conditions.append("sensitive-no-external-or-persistent-context")
    if _flag(profile, "secret_bearing") and not _flag(profile, "memory_isolation_confirmed"):
        materials_state = "BLOCKED"
        hard_gates.append("memory-isolation-unconfirmed")

    if sensitive_context:
        access_policy = {
            "external_access": "deny",
            "network": "deny",
            "connectors": "deny",
            "persistent_context": "deny",
            "tool_scope": "verified-local-only",
        }
    else:
        access_policy = {
            "external_access": "task-dependent",
            "network": "task-dependent",
            "connectors": "task-dependent",
            "persistent_context": "explicit-user-authorization-required",
            "tool_scope": "minimum-required",
        }

    return {
        "t_level": level,
        "score": score,
        "score_axes": axes,
        "hard_gates": hard_gates,
        "t_reason": f"score={score}; gates={','.join(hard_gates) or 'none'}",
        "resource_mode": resource_mode,
        "risk_tags": risk_tags,
        "skill_routes": skill_routes,
        "role_tasks": role_tasks,
        "stop_conditions": stop_conditions,
        "access_policy": access_policy,
        "materials_state": materials_state,
        "bounded_edit_short_path": bounded_edit,
        "agents": agents,
        "execution": {
            "current_stage_may_proceed": materials_state != "BLOCKED" and not stage_complete,
            "stage_complete": stage_complete,
            "next_stage_authorized": next_stage_authorized,
            "next_action": ("reclassify-authorized-next-stage" if next_stage_authorized else "stop-await-authorization")
                if stage_complete else ("resolve-material-blocker" if materials_state == "BLOCKED" else "execute-current-scope"),
            "classifier_does_not_verify_completion": True,
        },
        "review": {
            "required": level >= 4 or _flag(profile, "needs_review"),
            "minimum_independent_reviewers": reviewers,
            "minimum_rounds": rounds,
        },
    }


def _load_profile(path: str) -> dict[str, Any]:
    raw = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    if len(raw.encode("utf-8")) > 65_536:
        raise ValueError("profile exceeds 65536 bytes")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("profile must be a JSON object")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="-", help="JSON file or - for stdin")
    parser.add_argument("--compact", action="store_true", help="emit compact JSON")
    args = parser.parse_args()
    try:
        result = classify(_load_profile(args.profile))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {type(exc).__name__}: profile validation or I/O failed", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=None if args.compact else 2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
