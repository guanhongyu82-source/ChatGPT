#!/usr/bin/env python3
"""Verify Sol Cabinet skill, agents, and managed rule installation."""

from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SKILL_LINK = Path.home() / ".codex" / "skills" / "sol-cabinet"
GLOBAL_AGENTS = Path.home() / ".codex" / "AGENTS.md"
GLOBAL_OVERRIDE = Path.home() / ".codex" / "AGENTS.override.md"
PROJECT_AGENTS = Path("/Users/macbook/ChatGPT/AGENTS.md")
LINEAGE_AGENTS = Path("/Users/macbook/ChatGPT/lineage/codex-root/AGENTS.md")
BLOCK_SOURCE = ROOT / "platform-adapter" / "AGENTS.managed-block.md"
INSTALL_MANIFEST = ROOT / "platform-adapter" / "installation-manifest.json"
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
MANIFEST_KEYS = {
    "system", "version", "installed_at", "source_of_truth", "skill_entry",
    "agent_runtime", "managed_rules", "required_cwd", "smoke_tests",
    "known_preexisting_warning", "verification",
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


def check() -> dict[str, object]:
    issues = []
    warnings = []
    if not SKILL_LINK.is_symlink() or SKILL_LINK.resolve() != ROOT.resolve():
        issues.append({"issue": "skill-link-invalid", "path": str(SKILL_LINK)})

    duplicate = Path.home() / ".agents" / "skills" / "sol-cabinet"
    if duplicate.exists() or duplicate.is_symlink():
        issues.append({"issue": "duplicate-skill-entry", "path": str(duplicate)})

    try:
        expected = BLOCK_SOURCE.read_text(encoding="utf-8").strip()
        rules = json.loads(INSTALL_MANIFEST.read_text(encoding="utf-8"))["managed_rules"]
        for raw in rules["installed_in"]:
            path = Path(raw)
            if _extract_block(path) != expected:
                issues.append({"issue": "managed-block-drift", "path": str(path)})
        for raw, expected_hash in rules.get("user_owned", {}).items():
            if _sha256(Path(raw)) != expected_hash:
                issues.append({"issue": "user-owned-rule-changed-review-required", "path": raw})
    except (OSError, UnicodeError, ValueError, KeyError) as exc:
        issues.append({"issue": "managed-block-check-failed", "detail": str(exc)})

    if GLOBAL_OVERRIDE.is_file() and GLOBAL_OVERRIDE.stat().st_size > 0:
        issues.append({"issue": "global-agents-override-shadows-base", "path": str(GLOBAL_OVERRIDE)})

    try:
        issues.extend(_check_agent_runtime())
    except (OSError, UnicodeError, ValueError) as exc:
        issues.append({"issue": "agent-runtime-check-failed", "detail": str(exc)})

    try:
        manifest = json.loads(INSTALL_MANIFEST.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("manifest must be a JSON object")
        if set(manifest) != MANIFEST_KEYS:
            raise ValueError("manifest top-level schema mismatch")
        if manifest["system"] != "Sol Cabinet" or manifest["version"] != "1.5":
            raise ValueError("manifest identity mismatch")
        if manifest["source_of_truth"] != str(ROOT):
            raise ValueError("manifest source mismatch")
        if manifest["skill_entry"] != {
            "path": str(SKILL_LINK),
            "mode": "symlink",
            "resolved_path": str(ROOT),
            "skill_md_sha256": manifest["skill_entry"].get("skill_md_sha256"),
        }:
            raise ValueError("manifest skill entry mismatch")
        runtime_manifest = manifest["agent_runtime"]
        if set(runtime_manifest) != {"path", "mode", "sync_script", "sync_script_sha256", "files"}:
            raise ValueError("manifest agent runtime schema mismatch")
        if set(runtime_manifest["files"]) != AGENT_FILES:
            raise ValueError("manifest agent file set mismatch")
        if runtime_manifest["path"] != str(AGENT_TARGET_DIR) or runtime_manifest["mode"] != "managed-regular-copies":
            raise ValueError("manifest agent runtime mismatch")
        if runtime_manifest["sync_script"] != "scripts/sync_agent_runtime.py":
            raise ValueError("manifest sync script mismatch")
        if _sha256(ROOT / runtime_manifest["sync_script"]) != runtime_manifest["sync_script_sha256"]:
            issues.append({"issue": "installation-manifest-sync-script-hash-drift"})
        if _sha256(ROOT / "SKILL.md") != manifest["skill_entry"]["skill_md_sha256"]:
            issues.append({"issue": "installation-manifest-skill-hash-drift"})
        if _sha256(BLOCK_SOURCE) != manifest["managed_rules"]["source_sha256"]:
            issues.append({"issue": "installation-manifest-rule-hash-drift"})
        if manifest["managed_rules"]["source"] != "platform-adapter/AGENTS.managed-block.md":
            raise ValueError("manifest managed rule source mismatch")
        if set(manifest["managed_rules"]) != {"source", "source_sha256", "installed_in", "user_owned"}:
            raise ValueError("manifest managed rule schema mismatch")
        if set(manifest["managed_rules"]["installed_in"]) | set(manifest["managed_rules"]["user_owned"]) != {
            str(GLOBAL_AGENTS), str(PROJECT_AGENTS), str(LINEAGE_AGENTS)
        }:
            raise ValueError("manifest managed rule targets mismatch")
        if set(manifest["managed_rules"]["installed_in"]) & set(manifest["managed_rules"]["user_owned"]):
            raise ValueError("rule target cannot be both managed and user-owned")
        if manifest["required_cwd"] != "/Users/macbook/ChatGPT":
            raise ValueError("manifest cwd mismatch")
        smoke = manifest["smoke_tests"]
        if set(smoke) != {
            "skill_discovery", "custom_agent_discovery", "custom_agent_name",
            "custom_agent_sandbox_mode",
        }:
            raise ValueError("manifest smoke schema mismatch")
        if smoke.get("skill_discovery") != "PASS" or smoke.get("custom_agent_discovery") != "PASS":
            raise ValueError("manifest smoke status mismatch")
        if smoke.get("custom_agent_name") != "sol_final_verifier" or smoke.get("custom_agent_sandbox_mode") != "read-only":
            raise ValueError("manifest custom agent smoke mismatch")
        verification = manifest["verification"]
        if verification.get("check_script") != "scripts/check_installation.py":
            raise ValueError("manifest verification script mismatch")
        if set(verification) != {"check_script", "check_script_sha256"}:
            raise ValueError("manifest verification schema mismatch")
        if _sha256(ROOT / verification["check_script"]) != verification["check_script_sha256"]:
            issues.append({"issue": "installation-manifest-check-script-hash-drift"})
        for name, expected_hash in manifest["agent_runtime"]["files"].items():
            if _sha256(ROOT / "platform-adapter/codex-agents" / name) != expected_hash:
                issues.append({"issue": "installation-manifest-agent-hash-drift", "file": name})
    except (OSError, AttributeError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        issues.append({"issue": "installation-manifest-invalid", "detail": str(exc)})

    hooks = Path.home() / ".codex" / "hooks.json"
    if hooks.is_file() and "Otty" in hooks.read_text(encoding="utf-8", errors="replace"):
        hook_script = Path(
            "/Applications/Otty.app/Contents/Resources/agent-integration/codex/otty-hook.sh"
        )
        if not hook_script.exists():
            warnings.append("pre-existing Otty hooks are registered but their executable is missing")

    return {"verdict": "PASS" if not issues else "FAIL", "issues": issues, "warnings": warnings}


def main() -> int:
    result = check()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
