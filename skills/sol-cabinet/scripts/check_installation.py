#!/usr/bin/env python3
"""Verify live Sol Cabinet installation structure and, when requested, deployment identity."""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
from pathlib import Path

import deployment_state


ROOT = Path(__file__).resolve().parent.parent
SKILL_LINK = Path.home() / ".codex" / "skills" / "sol-cabinet"
GLOBAL_OVERRIDE = Path.home() / ".codex" / "AGENTS.override.md"
PROJECT_AGENTS = Path("/Users/macbook/ChatGPT/AGENTS.md")
LINEAGE_AGENTS = Path("/Users/macbook/ChatGPT/lineage/codex-root/AGENTS.md")
BLOCK_SOURCE = ROOT / "platform-adapter" / "AGENTS.managed-block.md"
BEGIN = "<!-- SOL CABINET MANAGED BLOCK BEGIN -->"
END = "<!-- SOL CABINET MANAGED BLOCK END -->"
AGENT_SOURCE_DIR = ROOT / "platform-adapter" / "codex-agents"
AGENT_TARGET_DIR = Path.home() / ".codex" / "agents"
AGENT_MARKER = "# Managed by Sol Cabinet single source; edit the source file only."
AGENT_FILES = {
    "sol-researcher.toml", "sol-fact-checker.toml", "sol-structure-architect.toml",
    "sol-drafter.toml", "sol-critic.toml", "sol-compliance-reviewer.toml",
    "sol-language-editor.toml", "sol-final-verifier.toml",
}


def _extract_block(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if text.count(BEGIN) != 1 or text.count(END) != 1:
        raise ValueError(f"managed block markers invalid: {path}")
    start = text.index(BEGIN)
    finish = text.index(END, start) + len(END)
    return text[start:finish].strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _check_agent_runtime() -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    if not AGENT_TARGET_DIR.is_dir() or AGENT_TARGET_DIR.is_symlink():
        return [{"issue": "invalid-agent-directory"}]
    if stat.S_IMODE(AGENT_TARGET_DIR.stat().st_mode) != 0o700:
        issues.append({"issue": "agent-directory-mode"})
    actual = {path.name for path in AGENT_TARGET_DIR.glob("sol-*.toml")}
    if actual != AGENT_FILES:
        issues.append({"issue": "agent-file-set-mismatch"})
    for name in AGENT_FILES:
        source = AGENT_SOURCE_DIR / name
        target = AGENT_TARGET_DIR / name
        if not source.is_file() or source.is_symlink():
            issues.append({"issue": "invalid-agent-source", "file": name})
            continue
        if not target.is_file() or target.is_symlink():
            issues.append({"issue": "invalid-agent-runtime-copy", "file": name})
            continue
        if not source.read_text(encoding="utf-8").startswith(AGENT_MARKER):
            issues.append({"issue": "agent-source-marker-missing", "file": name})
        if _sha256(source) != _sha256(target):
            issues.append({"issue": "agent-runtime-drift", "file": name})
        if stat.S_IMODE(target.stat().st_mode) != 0o600:
            issues.append({"issue": "agent-runtime-mode", "file": name})
    return issues


def check(*, expected_commit: str | None = None,
          state_path: Path = deployment_state.DEFAULT_STATE) -> dict[str, object]:
    issues: list[dict[str, object]] = []
    warnings: list[str] = []
    deployment_scope = expected_commit is not None

    if not SKILL_LINK.is_symlink() or SKILL_LINK.resolve() != ROOT.resolve():
        issues.append({"issue": "skill-link-invalid", "path": str(SKILL_LINK)})

    duplicate = Path.home() / ".agents" / "skills" / "sol-cabinet"
    if duplicate.exists() or duplicate.is_symlink():
        issues.append({"issue": "duplicate-skill-entry", "path": str(duplicate)})

    try:
        expected = BLOCK_SOURCE.read_text(encoding="utf-8").strip()
        for path in (PROJECT_AGENTS, LINEAGE_AGENTS):
            if _extract_block(path) != expected:
                issues.append({"issue": "managed-block-drift", "path": str(path)})
    except (OSError, UnicodeError, ValueError) as exc:
        issues.append({"issue": "managed-block-check-failed", "detail": str(exc)})

    if GLOBAL_OVERRIDE.is_file() and GLOBAL_OVERRIDE.stat().st_size > 0:
        issues.append({"issue": "global-agents-override-shadows-base", "path": str(GLOBAL_OVERRIDE)})

    try:
        issues.extend(_check_agent_runtime())
    except (OSError, UnicodeError, ValueError) as exc:
        issues.append({"issue": "agent-runtime-check-failed", "detail": str(exc)})

    runtime = deployment_state.classify(
        deployment_state.read_state(state_path), ROOT, expected_commit=expected_commit
    )
    if deployment_scope and runtime["state"] != "SYNCED":
        issues.append({"issue": "runtime-deployment-state-" + runtime["state"].lower(),
                       "detail": runtime.get("issues", [])})
    elif not deployment_scope and runtime["state"] != "SYNCED":
        warnings.append(
            "runtime deployment state is " + runtime["state"]
            + "; content-only check does not certify deployment identity"
        )

    hooks = Path.home() / ".codex" / "hooks.json"
    if hooks.is_file() and "Otty" in hooks.read_text(encoding="utf-8", errors="replace"):
        hook_script = Path(
            "/Applications/Otty.app/Contents/Resources/agent-integration/codex/otty-hook.sh"
        )
        if not hook_script.exists():
            warnings.append("pre-existing Otty hooks are registered but their executable is missing")

    return {
        "verdict": "PASS" if not issues else "FAIL",
        "scope": "deployment" if deployment_scope else "content-only",
        "runtime_state": runtime,
        "issues": issues,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-commit")
    parser.add_argument("--state", type=Path, default=deployment_state.DEFAULT_STATE)
    args = parser.parse_args()
    result = check(expected_commit=args.expected_commit, state_path=args.state)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
