#!/usr/bin/env python3
"""Validate Sol Cabinet structure, links, JSON, and runtime isolation."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
REQUIRED = [
    "domain-skills/common-components.md",
    "scripts/inspect_office.py",
    "scripts/verify_evidence.py",
    "tests/test_office_inspection.py",
    "tests/test_evidence.py",
    "source-index/migration-v1.3.json",
    "SKILL.md",
    "agents/openai.yaml",
    "core/core.md",
    "t0-executive-router/router.md",
    "task-classification/t1-t10.md",
    "domain-skills/routing-map.md",
    "agent-orchestrator/orchestration.md",
    "agent-orchestrator/durable-operations.md",
    "review-system/review-system.md",
    "memory-evolution/evolution-policy.md",
    "memory-evolution/operational-learnings.md",
    "memory-evolution/improvements.json",
    "templates/template-index.md",
    "templates/source-archive-manifest.json",
    "templates/improvement-item.json",
    "examples/routing-examples.md",
    "platform-adapter/codex.md",
    "source-index/source-assets.json",
    "source-index/source-distillation.md",
    "tests/test_sol_cabinet.py",
    "tests/migration_integrity_check.py",
    "tests/smoke-test-results.json",
    "tests/test-registry.json",
    "scripts/sync_agent_runtime.py",
    "scripts/check_installation.py",
    "scripts/delivery_gate.py",
    "scripts/codex_delivery_hook.py",
    "tests/test_delivery_rules.py",
    "tests/test_delivery_hook.py",
    "tests/test_last_lab_matrix.py",
    "platform-adapter/lab-hooks.json",
    "tests/test_evolution_intake.py",
    "scripts/validate_evolution_proposal.py",
    "scripts/create_release_snapshot.py",
    "scripts/archive_originals.py",
    "scripts/manage_improvements.py",
    "platform-adapter/AGENTS.managed-block.md",
    "platform-adapter/installation-manifest.json",
    "platform-adapter/codex-agents/sol-researcher.toml",
    "platform-adapter/codex-agents/sol-fact-checker.toml",
    "platform-adapter/codex-agents/sol-structure-architect.toml",
    "platform-adapter/codex-agents/sol-drafter.toml",
    "platform-adapter/codex-agents/sol-critic.toml",
    "platform-adapter/codex-agents/sol-compliance-reviewer.toml",
    "platform-adapter/codex-agents/sol-language-editor.toml",
    "platform-adapter/codex-agents/sol-final-verifier.toml",
]
RUNTIME_DIRS = [
    ROOT / "core",
    ROOT / "t0-executive-router",
    ROOT / "task-classification",
    ROOT / "domain-skills",
    ROOT / "agent-orchestrator",
    ROOT / "review-system",
    ROOT / "memory-evolution",
]
BANNED_RUNTIME = ("/grok-cowork", "grok-4.6", "spawn_subagent", "capability_mode", "auto-sync.sh")
LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def main() -> int:
    issues: list[str] = []
    for relative in REQUIRED:
        if not (ROOT / relative).is_file():
            issues.append(f"missing: {relative}")

    for path in ROOT.rglob("*"):
        if path.is_symlink():
            issues.append(f"internal-symlink-not-allowed: {path.relative_to(ROOT)}")

    for path in ROOT.rglob("*.json"):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            issues.append(f"invalid-json: {path.relative_to(ROOT)}: {exc}")

    for path in ROOT.rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        if "[TODO" in text or "TODO:" in text:
            issues.append(f"placeholder: {path.relative_to(ROOT)}")
        for target in LINK_RE.findall(text):
            if target.startswith(("http://", "https://", "#")):
                continue
            target_path = (path.parent / target.split("#", 1)[0]).resolve()
            try:
                target_path.relative_to(ROOT.resolve())
            except ValueError:
                issues.append(f"escaping-link: {path.relative_to(ROOT)} -> {target}")
                continue
            if not target_path.exists():
                issues.append(f"broken-link: {path.relative_to(ROOT)} -> {target}")

    runtime_files = [ROOT / "SKILL.md"]
    for directory in RUNTIME_DIRS:
        runtime_files.extend(directory.rglob("*.md"))
    for path in runtime_files:
        text = path.read_text(encoding="utf-8")
        for term in BANNED_RUNTIME:
            if term in text:
                issues.append(f"active-grok-contract: {path.relative_to(ROOT)}: {term}")

    for path in (ROOT / "platform-adapter/codex-agents").glob("sol-*.toml"):
        text = path.read_text(encoding="utf-8")
        for field in ("name =", "description =", "developer_instructions =", "sandbox_mode ="):
            if field not in text:
                issues.append(f"agent-field-missing: {path.relative_to(ROOT)}: {field}")
        for term in BANNED_RUNTIME:
            if term in text:
                issues.append(f"agent-grok-contract: {path.relative_to(ROOT)}: {term}")

    managed = (ROOT / "platform-adapter/AGENTS.managed-block.md").read_text(encoding="utf-8")
    if managed.count("SOL CABINET MANAGED BLOCK BEGIN") != 1 or managed.count(
        "SOL CABINET MANAGED BLOCK END"
    ) != 1:
        issues.append("managed-block-markers-invalid")

    if issues:
        print(json.dumps({"verdict": "FAIL", "issues": issues}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"verdict": "PASS", "required_files": len(REQUIRED)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
