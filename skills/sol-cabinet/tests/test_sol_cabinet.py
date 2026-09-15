#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import hashlib
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def load_module(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {relative}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


classifier = load_module("sol_classifier", "scripts/classify_task.py")
evolution = load_module("sol_evolution", "scripts/record_evolution.py")
agent_sync = load_module("sol_agent_sync", "scripts/sync_agent_runtime.py")
proposal_validator = load_module("sol_proposal_validator", "scripts/validate_evolution_proposal.py")
snapshot_creator = load_module("sol_snapshot_creator", "scripts/create_release_snapshot.py")
original_archiver = load_module("sol_original_archiver", "scripts/archive_originals.py")
improvement_manager = load_module("sol_improvement_manager", "scripts/manage_improvements.py")


def make_evidence(directory, proposal):
    directory.mkdir(exist_ok=True)
    for index, record_id in enumerate([proposal["test_run_id"], *proposal["independent_review_ids"]]):
        artifact = record_id + ".log"
        data = b"captured executor output\n"
        (directory / artifact).write_bytes(data)
        record = {"record_id": record_id, "kind": "test" if index == 0 else "review",
                  "candidate_sha256": proposal["candidate_sha256"], "verdict": "PASS",
                  "error_type": None, "source": "executor-capture", "artifact_path": artifact,
                  "artifact_sha256": hashlib.sha256(data).hexdigest()}
        if index == 0:
            record.update(exit_code=0, test_results={t: "PASS" for t in proposal["required_test_ids"]}, phase="post-apply")
        else:
            record.update(reviewer_id="agent-" + str(index) * 16, author_id="agent-" + "0" * 16, independent=True, must_fix=[])
        (directory / (record_id + ".json")).write_text(json.dumps(record))


class RouterTests(unittest.TestCase):
    def test_all_router_cases(self):
        cases = json.loads((ROOT / "tests/router-cases.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(cases), 20)
        for case in cases:
            with self.subTest(case=case["id"]):
                result = classifier.classify(case["profile"])
                expected = case["expected"]
                self.assertGreaterEqual(result["t_level"], expected["t_min"])
                self.assertLessEqual(result["t_level"], expected["t_max"])
                self.assertEqual(result["review"]["required"], expected["review"])
                self.assertEqual(result["agents"]["additional_execution_agents"], 0)
                self.assertEqual(result["agents"]["planned"],
                                 1 + result["review"]["minimum_independent_reviewers"])

    def test_speed_and_full_power_do_not_change_complexity(self):
        base = {
            "file_count": 8,
            "complexity": 2,
            "multi_source": True,
            "fact_risk": True,
            "formal_publish": True,
        }
        normal = classifier.classify(base)
        fast = classifier.classify({**base, "user_fast": True})
        full = classifier.classify({**base, "user_full_power": True})
        self.assertEqual(normal["t_level"], fast["t_level"])
        self.assertEqual(normal["t_level"], full["t_level"])
        self.assertEqual(fast["resource_mode"], "fast-with-gates")
        self.assertEqual(full["resource_mode"], "full-power")

    def test_string_false_is_rejected(self):
        with self.assertRaises(ValueError):
            classifier.classify({"formal_publish": "false"})

    def test_non_finite_and_negative_numbers_are_rejected(self):
        with self.assertRaises(ValueError):
            classifier.classify({"input_size_kb": float("nan")})
        with self.assertRaises(ValueError):
            classifier.classify({"file_count": -1})

    def test_materials_state_is_an_enum(self):
        with self.assertRaises(ValueError):
            classifier.classify({"materials_state": "UNKNOWN"})

    def test_high_level_does_not_create_an_execution_team(self):
        result = classifier.classify({"system_build": True, "long_running": True})
        self.assertEqual(result["t_level"], 10)
        self.assertEqual(result["agents"]["additional_execution_agents"], 0)
        self.assertEqual(result["agents"]["planned"],
                         1 + result["review"]["minimum_independent_reviewers"])
        self.assertIsNone(result["agents"]["maximum"])
        self.assertTrue(result["agents"]["count_includes_final_lead"])

    def test_secret_bearing_micro_task_gets_independent_review(self):
        result = classifier.classify(
            {"steps": 1, "complexity": 0, "sensitive": True, "secret_bearing": True}
        )
        self.assertGreaterEqual(result["t_level"], 6)
        self.assertGreaterEqual(result["review"]["minimum_independent_reviewers"], 1)
        self.assertIn("sensitive-no-external-or-persistent-context", result["stop_conditions"])
        self.assertEqual(result["materials_state"], "BLOCKED")

    def test_secret_bearing_can_proceed_only_after_memory_isolation_confirmation(self):
        result = classifier.classify(
            {"secret_bearing": True, "memory_isolation_confirmed": True}
        )
        self.assertEqual(result["materials_state"], "READY")

    def test_sensitive_t7_keeps_lead_and_has_no_external_research(self):
        result = classifier.classify(
            {
                "file_count": 8,
                "complexity": 3,
                "formal_publish": True,
                "fact_risk": True,
                "multi_source": True,
                "needs_research": True,
                "sensitive": True,
                "secret_bearing": True,
                "professional_roles": 8,
            }
        )
        self.assertEqual(result["t_level"], 7)
        self.assertIn("final_lead", result["role_tasks"])
        self.assertIn("final_verifier", result["role_tasks"])
        self.assertNotIn("researcher", result["role_tasks"])
        self.assertNotIn("research", result["skill_routes"])
        self.assertEqual(result["access_policy"]["network"], "deny")
        self.assertEqual(result["access_policy"]["connectors"], "deny")
        self.assertEqual(result["access_policy"]["persistent_context"], "deny")

    def test_sensitive_data_uses_local_route(self):
        result = classifier.classify({"sensitive": True, "data_task": True})
        self.assertIn("local-data-analysis", result["skill_routes"])
        self.assertNotIn("data-analytics", result["skill_routes"])

    def test_explicit_review_has_reviewer_and_round(self):
        result = classifier.classify({"steps": 1, "complexity": 0, "needs_review": True})
        self.assertTrue(result["review"]["required"])
        self.assertGreaterEqual(result["review"]["minimum_independent_reviewers"], 1)
        self.assertGreaterEqual(result["review"]["minimum_rounds"], 1)
        self.assertGreaterEqual(result["agents"]["planned"], 2)

    def test_known_office_micro_edit_keeps_tool_route_without_team(self):
        result = classifier.classify({"file_count": 1, "input_size_kb": 9000,
            "steps": 3, "complexity": 1, "office_artifact": True, "bounded_edit": True})
        self.assertLessEqual(result["t_level"], 2)
        self.assertTrue(result["bounded_edit_short_path"])
        self.assertIn("office-artifact-skill", result["skill_routes"])
        self.assertFalse(result["review"]["required"])
        self.assertEqual(result["agents"]["planned"], 1)

    def test_bounded_edit_never_bypasses_substantive_risk(self):
        base = {"file_count": 1, "office_artifact": True, "bounded_edit": True}
        for flag in ("formal_publish", "fact_risk", "high_risk", "secret_bearing",
                     "sensitive", "external_action", "destructive_action"):
            with self.subTest(flag=flag):
                result = classifier.classify({**base, flag: True})
                self.assertFalse(result["bounded_edit_short_path"])
                self.assertTrue(result["review"]["required"])
                self.assertGreaterEqual(result["t_level"], 4)

    def test_explicit_review_survives_micro_edit_short_path(self):
        result = classifier.classify({"office_artifact": True, "bounded_edit": True,
                                      "needs_review": True})
        self.assertTrue(result["review"]["required"])
        self.assertGreaterEqual(result["review"]["minimum_independent_reviewers"], 1)

    def test_only_positive_independent_work_gets_execution_agents(self):
        base = {"system_build": True, "independent_work_units": 3}
        uncertain = classifier.classify(base)
        positive = classifier.classify({**base, "parallel_benefit": "positive"})
        negative = classifier.classify({**base, "parallel_benefit": "nonpositive"})
        self.assertEqual(uncertain["agents"]["additional_execution_agents"], 0)
        self.assertEqual(negative["agents"]["additional_execution_agents"], 0)
        self.assertEqual(positive["agents"]["additional_execution_agents"], 3)
        self.assertEqual(positive["t_level"], uncertain["t_level"])

    def test_execution_budget_does_not_claim_to_cover_review_budget(self):
        base = {"system_build": True, "independent_work_units": 4,
                "parallel_benefit": "positive", "available_subagent_slots": 1}
        for budget in (0, 1):
            result = classifier.classify({**base, "additional_execution_agent_budget": budget})
            self.assertEqual(result["agents"]["additional_execution_agents"], budget)
            self.assertEqual(result["agents"]["planned"],
                             1 + budget + result["review"]["minimum_independent_reviewers"])
            self.assertFalse(result["agents"]["review_execution_blocked"])
        blocked = classifier.classify({**base, "available_subagent_slots": 0})
        self.assertEqual(blocked["agents"]["additional_execution_agents"], 0)
        self.assertTrue(blocked["agents"]["review_execution_blocked"])
        self.assertTrue(blocked["review"]["required"])

    def test_professional_roles_is_not_an_agent_count(self):
        result = classifier.classify({"system_build": True, "professional_roles": 100})
        self.assertEqual(result["agents"]["additional_execution_agents"], 0)

    def test_stopped_stage_cannot_auto_execute_the_next_stage(self):
        for authorized in (False, True):
            result = classifier.classify({"stage_complete": True,
                                          "next_stage_authorized": authorized})
            self.assertFalse(result["execution"]["current_stage_may_proceed"])
            self.assertTrue(result["execution"]["classifier_does_not_verify_completion"])
            self.assertEqual(result["execution"]["next_action"],
                             "reclassify-authorized-next-stage" if authorized else "stop-await-authorization")
        missing = classifier.classify({"materials_state": "BLOCKED"})
        self.assertFalse(missing["execution"]["current_stage_may_proceed"])
        self.assertEqual(missing["execution"]["next_action"], "resolve-material-blocker")

    def test_dynamic_profile_fields_are_strict(self):
        cases = [{"bounded_edit": "false"}, {"stage_complete": "true"},
                 {"next_stage_authorized": 1}, {"independent_work_units": -1},
                 {"independent_work_units": True}, {"parallel_benefit": {}},
                 {"parallel_benefit": "maybe"}, {"available_subagent_slots": -1},
                 {"additional_execution_agent_budget": 1.5}, {"materials_state": []}]
        for profile in cases:
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                classifier.classify(profile)

    def test_profile_template_can_be_classified(self):
        profile = json.loads((ROOT / "templates/task-profile.json").read_text())
        result = classifier.classify(profile)
        self.assertEqual(result["t_level"], 1)
        self.assertTrue(result["execution"]["current_stage_may_proceed"])

    def test_default_context_policy_requires_explicit_persistence_authorization(self):
        result = classifier.classify({})
        self.assertEqual(result["access_policy"]["persistent_context"],
                         "explicit-user-authorization-required")


class SourceArchiveTests(unittest.TestCase):
    def test_empty_input_is_not_applicable_and_creates_no_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            task_dir = Path(temp_dir) / "task"
            result = original_archiver.archive_originals(
                task_dir, [], allow_test_output=True
            )
            self.assertEqual(result, {"state": "NOT_APPLICABLE", "archived_count": 0})
            self.assertFalse(task_dir.exists())

    def test_binary_original_is_byte_identical_and_manifested(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir).resolve()
            task_dir = base / "task"
            task_dir.mkdir()
            source = base / "样本.docx"
            payload = b"PK\x03\x04\x00\xff\noriginal-binary"
            source.write_bytes(payload)
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            result = original_archiver.archive_originals(
                task_dir, [("附件1", source)], allow_test_output=True
            )
            self.assertEqual(result["state"], "PASS")
            archived = task_dir / "00_原稿" / "原稿_附件1_样本.docx"
            self.assertEqual(archived.read_bytes(), payload)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
            manifest = json.loads((task_dir / "00_原稿" / "原稿清单.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["archive_state"], "PASS")
            self.assertEqual(len(manifest["files"]), 1)
            record = manifest["files"][0]
            self.assertEqual(record["source_sha256"], before)
            self.assertEqual(record["archived_sha256"], before)
            self.assertTrue(record["byte_identical"])
            self.assertTrue(record["source_unmodified"])
            self.assertEqual(record["status"], "UNMODIFIED_BYTE_COPY")

    def test_idempotent_repeat_and_safe_append(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir).resolve()
            task_dir = base / "task"
            task_dir.mkdir()
            first = base / "first.txt"
            second = base / "第二份.txt"
            first.write_text("one", encoding="utf-8")
            second.write_text("two", encoding="utf-8")
            original_archiver.archive_originals(
                task_dir, [("主件", first)], allow_test_output=True
            )
            repeated = original_archiver.archive_originals(
                task_dir, [("主件", first)], allow_test_output=True
            )
            self.assertEqual(repeated["archived_count"], 1)
            appended = original_archiver.archive_originals(
                task_dir, [("附件", second)], allow_test_output=True
            )
            self.assertEqual(appended["archived_count"], 2)
            manifest = json.loads((task_dir / "00_原稿" / "原稿清单.json").read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["files"]), 2)

    def test_symlink_source_and_collision_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir).resolve()
            real = base / "real.txt"
            real.write_text("keep", encoding="utf-8")
            link = base / "link.txt"
            link.symlink_to(real)
            (base / "symlink-task").mkdir()
            with self.assertRaises(ValueError):
                original_archiver.archive_originals(
                    base / "symlink-task", [("主件", link)], allow_test_output=True
                )

            left = base / "left"
            right = base / "right"
            left.mkdir()
            right.mkdir()
            (left / "same.txt").write_text("left", encoding="utf-8")
            (right / "same.txt").write_text("right", encoding="utf-8")
            task_dir = base / "collision-task"
            task_dir.mkdir()
            original_archiver.archive_originals(
                task_dir, [("附件", left / "same.txt")], allow_test_output=True
            )
            with self.assertRaises(FileExistsError):
                original_archiver.archive_originals(
                    task_dir, [("附件", right / "same.txt")], allow_test_output=True
                )
            archived = task_dir / "00_原稿" / "原稿_附件_same.txt"
            self.assertEqual(archived.read_text(encoding="utf-8"), "left")

    def test_existing_archive_is_reverified_after_tamper_or_delete(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir).resolve()
            source = base / "source.bin"
            source.write_bytes(b"original")

            tamper_task = base / "tamper-task"
            tamper_task.mkdir()
            original_archiver.archive_originals(
                tamper_task, [("主件", source)], allow_test_output=True
            )
            archived = tamper_task / "00_原稿" / "原稿_主件_source.bin"
            archived.write_bytes(b"tampered")
            with self.assertRaises(ValueError):
                original_archiver.archive_originals(
                    tamper_task, [("主件", source)], allow_test_output=True
                )

            delete_task = base / "delete-task"
            delete_task.mkdir()
            original_archiver.archive_originals(
                delete_task, [("主件", source)], allow_test_output=True
            )
            (delete_task / "00_原稿" / "原稿_主件_source.bin").unlink()
            with self.assertRaises(FileNotFoundError):
                original_archiver.archive_originals(
                    delete_task, [("主件", source)], allow_test_output=True
                )

    def test_manifest_escape_forged_hash_and_archived_symlink_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir).resolve()
            source = base / "source.txt"
            source.write_text("original", encoding="utf-8")

            escape_task = base / "escape-task"
            escape_task.mkdir()
            original_archiver.archive_originals(
                escape_task, [("主件", source)], allow_test_output=True
            )
            manifest_path = escape_task / "00_原稿" / "原稿清单.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["files"][0]["archived_relative_path"] = "../escape.txt"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(ValueError):
                original_archiver.archive_originals(
                    escape_task, [("主件", source)], allow_test_output=True
                )

            forged_task = base / "forged-task"
            forged_task.mkdir()
            original_archiver.archive_originals(
                forged_task, [("主件", source)], allow_test_output=True
            )
            manifest_path = forged_task / "00_原稿" / "原稿清单.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["files"][0]["archived_sha256"] = "0" * 64
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(ValueError):
                original_archiver.archive_originals(
                    forged_task, [("主件", source)], allow_test_output=True
                )

            symlink_task = base / "archived-symlink-task"
            symlink_task.mkdir()
            original_archiver.archive_originals(
                symlink_task, [("主件", source)], allow_test_output=True
            )
            archived = symlink_task / "00_原稿" / "原稿_主件_source.txt"
            archived.unlink()
            archived.symlink_to(source)
            with self.assertRaises(OSError):
                original_archiver.archive_originals(
                    symlink_task, [("主件", source)], allow_test_output=True
                )

    def test_workspace_root_and_symlinked_task_components_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source.txt"
            source.write_text("original", encoding="utf-8")
            with self.assertRaises(ValueError):
                original_archiver.archive_originals(
                    original_archiver.WORKSPACE_ROOT,
                    [("主件", source)],
                    allow_test_output=False,
                )
            real_parent = Path(temp_dir) / "real-parent"
            real_parent.mkdir()
            linked_parent = Path(temp_dir) / "linked-parent"
            linked_parent.symlink_to(real_parent)
            with self.assertRaises(ValueError):
                original_archiver.archive_originals(
                    linked_parent / "task",
                    [("主件", source)],
                    allow_test_output=True,
                )

    def test_post_copy_verification_failure_leaves_no_orphan_or_lock(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir).resolve()
            task_dir = base / "task"
            task_dir.mkdir()
            source = base / "source.bin"
            source.write_bytes(b"original")
            original_hash_fd = original_archiver._hash_fd
            calls = {"count": 0}

            def mismatching_third_hash(fd):
                calls["count"] += 1
                value = original_hash_fd(fd)
                return "0" * 64 if calls["count"] == 3 else value

            original_archiver._hash_fd = mismatching_third_hash
            try:
                with self.assertRaises(RuntimeError):
                    original_archiver.archive_originals(
                        task_dir, [("主件", source)], allow_test_output=True
                    )
            finally:
                original_archiver._hash_fd = original_hash_fd
            archive_dir = task_dir / "00_原稿"
            self.assertFalse((archive_dir / "原稿_主件_source.bin").exists())
            self.assertFalse((archive_dir / "原稿清单.json").exists())
            self.assertFalse((archive_dir / ".archive-originals.lock").exists())

    def test_stale_lock_fails_closed_without_changing_existing_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir).resolve()
            task_dir = base / "task"
            archive_dir = task_dir / "00_原稿"
            archive_dir.mkdir(parents=True)
            lock = archive_dir / ".archive-originals.lock"
            lock.write_text('{"pid": 1}', encoding="ascii")
            source = base / "source.txt"
            source.write_text("original", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                original_archiver.archive_originals(
                    task_dir, [("主件", source)], allow_test_output=True
                )
            self.assertEqual(lock.read_text(encoding="ascii"), '{"pid": 1}')
            self.assertFalse((archive_dir / "原稿_主件_source.txt").exists())

    def test_archive_gate_is_global_and_t_level_independent(self):
        managed = (ROOT / "platform-adapter/AGENTS.managed-block.md").read_text(encoding="utf-8")
        core = (ROOT / "core/core.md").read_text(encoding="utf-8")
        router = (ROOT / "t0-executive-router/router.md").read_text(encoding="utf-8")
        office = (ROOT / "domain-skills/office-delivery.md").read_text(encoding="utf-8")
        review = (ROOT / "review-system/review-system.md").read_text(encoding="utf-8")
        for text in (managed, core, router, office, review):
            self.assertIn("00_原稿", text)
        self.assertIn("T1-T10", managed)
        self.assertIn("state!=PASS", router)
        self.assertIn("source_archive_gate.required=true", review)

    def test_operational_learning_contract_is_closed_loop(self):
        policy = (ROOT / "memory-evolution/evolution-policy.md").read_text(encoding="utf-8")
        ledger = (ROOT / "memory-evolution/operational-learnings.md").read_text(encoding="utf-8")
        for term in ("Direct Policy Change", "blocker", "root_cause", "solution", "prevention", "verification"):
            self.assertIn(term, policy)
        for term in ("卡点", "根因", "解决方案", "预防门禁", "验证"):
            self.assertIn(term, ledger)
        self.assertIn("不记录用户正文", ledger)
        self.assertIn("相同 `blocker_code` 只能更新同一个", ledger)
        registry = json.loads((ROOT / "memory-evolution/improvements.json").read_text(encoding="utf-8"))
        self.assertEqual(len(improvement_manager.validate_registry(registry)["items"]), 8)

    def test_page_only_field_warning_prevention_is_documented(self):
        office = (ROOT / "domain-skills/office-delivery.md").read_text(encoding="utf-8")
        self.assertIn("PAGE", office)
        self.assertIn("w:updateFields=true", office)
        self.assertIn("外部关系", office)


class EvolutionTests(unittest.TestCase):
    def base_entry(self):
        return {
            "task_instance_id": "task-0123456789abcdef0123456789abcdef",
            "date": "2026-08-23",
            "task_type": "office-system-build",
            "planned_t": 10,
            "actual_t": 10,
            "planned_agents": 12,
            "used_agents": 12,
            "skill_routes": ["skill-creator"],
            "outcome": "pass",
            "feedback_codes": ["user-specified-router"],
            "lesson_codes": ["single-source-of-truth"],
            "level": 1,
            "sensitive": False,
            "sensitivity_checked": True,
            "lifecycle_state": "intake",
            "review_after_date": "2026-09-23",
            "consolidated_improvement_id": None,
        }

    def test_sensitive_entry_is_not_written(self):
        entry = self.base_entry()
        entry["sensitive"] = True
        with tempfile.TemporaryDirectory() as temp_dir:
            path = evolution.write_observation(entry, Path(temp_dir), allow_test_output=True, user_authorized=True)
            self.assertIsNone(path)
            self.assertEqual(list(Path(temp_dir).iterdir()), [])

    def test_normal_entry_is_atomic_and_immutable(self):
        entry = self.base_entry()
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir)
            path = evolution.write_observation(entry, output, allow_test_output=True, user_authorized=True)
            self.assertIsNotNone(path)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["task_type"], "office-system-build")
            with self.assertRaises(FileExistsError):
                evolution.write_observation(entry, output, allow_test_output=True, user_authorized=True)

    def test_free_text_fields_are_rejected(self):
        entry = self.base_entry()
        entry["note"] = "not allowed"
        with self.assertRaises(ValueError):
            evolution.validate(entry)

    def test_template_matches_evolution_schema(self):
        template = json.loads((ROOT / "templates/evolution-entry.json").read_text(encoding="utf-8"))
        template.update(
            {
                "date": "2026-08-23",
                "task_instance_id": "task-0123456789abcdef0123456789abcdef",
                "task_type": "template-check",
                "sensitivity_checked": True,
                "review_after_date": "2026-09-23",
            }
        )
        clean = evolution.validate(template)
        self.assertEqual(clean["task_type"], "template-check")

    def test_colon_skill_route_is_valid(self):
        entry = self.base_entry()
        entry["skill_routes"] = ["documents:documents", "spreadsheets:Spreadsheets"]
        clean = evolution.validate(entry)
        self.assertEqual(clean["skill_routes"], entry["skill_routes"])

    def test_missing_sensitivity_assessment_is_rejected(self):
        entry = self.base_entry()
        del entry["sensitivity_checked"]
        with self.assertRaises(ValueError):
            evolution.validate(entry)

    def test_null_date_is_rejected(self):
        entry = self.base_entry()
        entry["date"] = None
        with self.assertRaises(ValueError):
            evolution.validate(entry)

    def test_invalid_date_error_does_not_echo_input(self):
        entry = self.base_entry()
        marker = "SECRET-DATE-MARKER"
        entry["date"] = marker
        with self.assertRaises(ValueError) as caught:
            evolution.validate(entry)
        self.assertNotIn(marker, str(caught.exception))

    def test_observation_cannot_claim_level_three(self):
        entry = self.base_entry()
        entry["level"] = 3
        with self.assertRaises(ValueError):
            evolution.validate(entry)

    def test_evolution_proposal_requires_independent_observations_and_authorization(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            observations = Path(temp_dir)
            entries = []
            for suffix in ("0", "1"):
                entry = self.base_entry()
                entry["task_instance_id"] = "task-" + suffix * 32
                entry["lesson_codes"] = ["template-gap"]
                entries.append(evolution.write_observation(entry, observations, allow_test_output=True, user_authorized=True))
            proposal = {
                "proposal_id": "proposal-0123456789abcdef0123456789abcdef",
                "change_mode": "repeated-evolution",
                "level": 2,
                "lesson_code": "template-gap",
                "observation_ids": [path.stem for path in entries],
                "target_module": "templates",
                "change_code": "add-regression-test",
                "required_test_ids": ["E02", "S11"],
                "status": "draft",
                "user_authorized": False,
                "contains_sensitive_content": False,
                "sensitivity_checked": True,
                "rollback_id": None,
                "base_sha256": None,
            }
            self.assertEqual(proposal_validator.validate(proposal, observations)["level"], 2)
            proposal["status"] = "approved"
            with self.assertRaises(ValueError):
                proposal_validator.validate(proposal, observations)
            proposal["user_authorized"] = True
            proposal["rollback_id"] = "snapshot-2026-08-23-v1.0"
            with self.assertRaises(ValueError):
                proposal_validator.validate(proposal, observations, observations / "missing")
            snapshots = observations / "snapshots"
            _, proposal["base_sha256"] = snapshot_creator.create_snapshot(
                "snapshot-2026-08-23-v1.0", snapshots, allow_test_output=True
            )
            # A static PASS registry and valid snapshot alone cannot approve evolution.
            with self.assertRaises(ValueError):
                proposal_validator.validate(proposal, observations, snapshots)
            proposal.update(candidate_sha256=proposal_validator.system_digest(ROOT),
                            test_run_id="testrun-" + "a" * 32,
                            independent_review_ids=["review-" + "b" * 32, "review-" + "c" * 32])
            proposal["test_candidate_sha256"] = proposal["candidate_sha256"]
            evidence = observations / "evidence"
            make_evidence(evidence, proposal)
            for status in ("approved", "applied", "post_verified"):
                proposal["status"] = status
                proposal["post_verification"] = "PASS" if status == "post_verified" else None
                self.assertEqual(
                    proposal_validator.validate(proposal, observations, snapshots, evidence_dir=evidence)["status"],
                    status,
                )
                for field in ("candidate_sha256", "test_run_id", "test_candidate_sha256", "independent_review_ids"):
                    with self.subTest(status=status, field=field), self.assertRaises(ValueError):
                        proposal_validator.validate({**proposal, field: None}, observations, snapshots, evidence_dir=evidence)
            (evidence / (proposal["test_run_id"] + ".log")).write_text("tampered")
            with self.assertRaises(ValueError):
                proposal_validator.validate(proposal, observations, snapshots, evidence_dir=evidence)

    def test_direct_policy_change_has_real_candidate_test_and_review_gates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            observations = base / "observations"
            observations.mkdir()
            snapshots = base / "snapshots"
            rollback_id = "snapshot-2026-08-24-v8.8"
            _, base_sha256 = snapshot_creator.create_snapshot(
                rollback_id, snapshots, allow_test_output=True
            )
            candidate_sha256 = proposal_validator.system_digest(ROOT)
            proposal = {
                "proposal_id": "proposal-abcdefabcdefabcdefabcdefabcdefab",
                "change_mode": "direct-policy-change",
                "level": 3,
                "lesson_code": "source-protection",
                "observation_ids": [],
                "target_module": "core",
                "change_code": "add-or-tighten-gate",
                "required_test_ids": ["A01", "S11"],
                "status": "approved",
                "user_authorized": True,
                "contains_sensitive_content": False,
                "sensitivity_checked": True,
                "authorization_basis": "explicit-user-long-term-directive",
                "authorization_ref": "turn-0123456789abcdef",
                "authorization_fingerprint": "b" * 64,
                "changed_paths": ["core/core.md", "review-system/review-system.md"],
                "rollback_id": rollback_id,
                "base_sha256": base_sha256,
                "candidate_sha256": candidate_sha256,
                "test_run_id": "testrun-0123456789abcdef0123456789abcdef",
                "test_candidate_sha256": candidate_sha256,
                "independent_review_ids": [
                    "review-0123456789abcdef0123456789abcdef",
                    "review-fedcba9876543210fedcba9876543210",
                ],
                "post_verification": None,
            }
            make_evidence(base / "evidence", proposal)
            self.assertEqual(
                proposal_validator.validate(proposal, observations, snapshots, evidence_dir=base / "evidence")["change_mode"],
                "direct-policy-change",
            )
            stale_candidate = base / "changed-candidate"
            stale_candidate.mkdir()
            (stale_candidate / "changed.txt").write_text("candidate changed after tests")
            with self.assertRaises(ValueError):
                proposal_validator.validate(proposal, observations, snapshots,
                                            evidence_dir=base / "evidence", candidate_root=stale_candidate)
            for field, bad_value in (
                ("sensitivity_checked", False),
                ("contains_sensitive_content", True),
                ("authorization_basis", "current-task-only"),
                ("test_candidate_sha256", "c" * 64),
                ("independent_review_ids", proposal["independent_review_ids"][:1]),
            ):
                broken = {**proposal, field: bad_value}
                with self.subTest(field=field), self.assertRaises(ValueError):
                    proposal_validator.validate(broken, observations, snapshots)
            broken = {**proposal, "observation_ids": ["obs-" + "0" * 32]}
            with self.assertRaises(ValueError):
                proposal_validator.validate(broken, observations, snapshots)

    def test_applied_direct_change_requires_active_candidate_and_post_verification(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            observations = base / "observations"
            observations.mkdir()
            snapshots = base / "snapshots"
            rollback_id = "snapshot-2026-08-24-v8.9"
            _, base_sha256 = snapshot_creator.create_snapshot(
                rollback_id, snapshots, allow_test_output=True
            )
            candidate_sha256 = proposal_validator.system_digest(ROOT)
            proposal = {
                "proposal_id": "proposal-1234567890abcdef1234567890abcdef",
                "change_mode": "direct-policy-change",
                "level": 3,
                "lesson_code": "source-protection",
                "observation_ids": [],
                "target_module": "core",
                "change_code": "add-or-tighten-gate",
                "required_test_ids": ["A01", "S11"],
                "status": "applied",
                "user_authorized": True,
                "contains_sensitive_content": False,
                "sensitivity_checked": True,
                "authorization_basis": "explicit-user-long-term-directive",
                "authorization_ref": "turn-fedcba9876543210",
                "authorization_fingerprint": "d" * 64,
                "changed_paths": ["core/core.md"],
                "rollback_id": rollback_id,
                "base_sha256": base_sha256,
                "candidate_sha256": candidate_sha256,
                "test_run_id": "testrun-fedcba9876543210fedcba9876543210",
                "test_candidate_sha256": candidate_sha256,
                "independent_review_ids": [
                    "review-11111111111111111111111111111111",
                    "review-22222222222222222222222222222222",
                ],
                "post_verification": None,
            }
            make_evidence(base / "evidence", proposal)
            original_digest = proposal_validator.system_digest
            try:
                proposal_validator.system_digest = lambda root=proposal_validator.ROOT: candidate_sha256
                self.assertEqual(
                    proposal_validator.validate(proposal, observations, snapshots, evidence_dir=base / "evidence")["status"],
                    "applied",
                )
                post = {**proposal, "status": "post_verified", "post_verification": "PASS"}
                self.assertEqual(
                    proposal_validator.validate(post, observations, snapshots, evidence_dir=base / "evidence")["status"],
                    "post_verified",
                )
                with self.assertRaises(ValueError):
                    proposal_validator.validate(
                        {**post, "post_verification": None}, observations, snapshots
                    )
            finally:
                proposal_validator.system_digest = original_digest


class ImprovementRegistryTests(unittest.TestCase):
    def test_active_registry_is_valid_and_has_unique_blockers(self):
        registry = json.loads(
            (ROOT / "memory-evolution/improvements.json").read_text(encoding="utf-8")
        )
        clean = improvement_manager.validate_registry(registry)
        self.assertEqual(len(clean["items"]), 8)

    def test_sensitive_unknown_and_duplicate_blockers_are_rejected(self):
        registry = json.loads(
            (ROOT / "memory-evolution/improvements.json").read_text(encoding="utf-8")
        )
        item = dict(registry["items"][0])
        for field, value in (
            ("sensitive", True),
            ("contains_sensitive_content", True),
            ("sensitivity_checked", False),
        ):
            with self.subTest(field=field), self.assertRaises(ValueError):
                improvement_manager.validate_item({**item, field: value})
        with self.assertRaises(ValueError):
            improvement_manager.validate_item({**item, "note": "free text"})

    def test_upsert_updates_one_item_and_refuses_duplicate_blocker(self):
        active = json.loads(
            (ROOT / "memory-evolution/improvements.json").read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "improvements.json"
            first = dict(active["items"][0])
            first["status"] = "OPEN"
            path.write_text(json.dumps({"schema_version": 1, "items": [first]}), encoding="utf-8")
            updated = {**first, "status": "RECURRENT", "recurrence_count": 2}
            improvement_manager.upsert_item(updated, path, allow_test_output=True, user_authorized=True)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(saved["items"]), 1)
            self.assertEqual(saved["items"][0]["recurrence_count"], 2)
            duplicate = {**updated, "improvement_id": "OL-099"}
            with self.assertRaises(ValueError):
                improvement_manager.upsert_item(duplicate, path, allow_test_output=True, user_authorized=True)

    def test_retirement_requires_verified_central_item_and_exact_ids(self):
        active = json.loads(
            (ROOT / "memory-evolution/improvements.json").read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            registry_path = base / "improvements.json"
            item = dict(active["items"][0])
            item["status"] = "VERIFIED"
            item["last_verified_date"] = "2026-08-24"
            registry_path.write_text(
                json.dumps({"schema_version": 1, "items": [item]}), encoding="utf-8"
            )
            observations = base / "observations"
            observations.mkdir()
            observation_id = "obs-" + "0" * 32
            observation_path = observations / f"{observation_id}.json"
            observation_path.write_text(
                json.dumps({"observation_id": observation_id, "sensitive": False}),
                encoding="utf-8",
            )
            self.assertEqual(
                improvement_manager.retire_observations(
                    [observation_id],
                    item["improvement_id"],
                    registry_path=registry_path,
                    observations_dir=observations,
                    allow_test_output=True, user_authorized=True,
                ),
                1,
            )
            self.assertFalse(observation_path.exists())


class IntegrityTests(unittest.TestCase):
    def test_release_snapshot_is_content_verified(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive, base = snapshot_creator.create_snapshot(
                "snapshot-2026-08-23-v9.9", Path(temp_dir), allow_test_output=True
            )
            proposal_validator.validate_snapshot(archive, "snapshot-2026-08-23-v9.9", base)
            evil = Path(temp_dir) / "evil.tar.gz"
            with tarfile.open(archive, "r:gz") as source, tarfile.open(evil, "w:gz") as target:
                for member in source.getmembers():
                    handle = source.extractfile(member) if member.isfile() else None
                    target.addfile(member, handle)
                data = b"must-not-be-ignored"
                info = tarfile.TarInfo(
                    "sol-cabinet/memory-evolution/observations/extra.txt"
                )
                info.size = len(data)
                info.mode = 0o600
                target.addfile(info, io.BytesIO(data))
            evil.replace(archive)
            archive_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
            Path(f"{archive}.sha256").write_text(
                f"{archive_hash}  {archive.name}\n", encoding="ascii"
            )
            with self.assertRaises(ValueError):
                proposal_validator.validate_snapshot(
                    archive, "snapshot-2026-08-23-v9.9", base
                )

    def test_custom_agents_have_required_fields(self):
        files = sorted((ROOT / "platform-adapter/codex-agents").glob("sol-*.toml"))
        self.assertEqual(len(files), 8)
        for path in files:
            text = path.read_text(encoding="utf-8")
            self.assertIn("name =", text)
            self.assertIn("description =", text)
            self.assertIn("developer_instructions =", text)
            self.assertIn("sandbox_mode =", text)
            self.assertIn("do not use web, MCP, connectors, apps, external services", text)

    def test_all_custom_agents_are_read_only(self):
        agent_dir = ROOT / "platform-adapter/codex-agents"
        for path in agent_dir.glob("sol-*.toml"):
            text = path.read_text(encoding="utf-8")
            self.assertIn('sandbox_mode = "read-only"', text)

    def test_force_invocation_phrases(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        for phrase in ("Sol Cabinet", "使用 Sol Cabinet", "交给 Sol Cabinet", "SC处理"):
            self.assertIn(phrase, text)

    def test_agent_runtime_sync_in_isolated_target(self):
        original_target = agent_sync.TARGET_DIR
        original_expected = agent_sync.EXPECTED_TARGET_DIR
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                agent_sync.TARGET_DIR = Path(temp_dir) / "agents"
                agent_sync.EXPECTED_TARGET_DIR = agent_sync.TARGET_DIR
                installed = agent_sync.install()
                self.assertEqual(installed["verdict"], "PASS")
                self.assertEqual(agent_sync.check()["verdict"], "PASS")
                first = agent_sync.TARGET_DIR / agent_sync.FILES[0]
                first.write_text("drift\n", encoding="utf-8")
                self.assertEqual(agent_sync.check()["verdict"], "FAIL")
        finally:
            agent_sync.TARGET_DIR = original_target
            agent_sync.EXPECTED_TARGET_DIR = original_expected

    def test_agent_sync_rolls_back_on_keyboard_interrupt(self):
        original_target = agent_sync.TARGET_DIR
        original_expected = agent_sync.EXPECTED_TARGET_DIR
        original_write = agent_sync._atomic_regular_write
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                agent_sync.TARGET_DIR = Path(temp_dir) / "agents"
                agent_sync.EXPECTED_TARGET_DIR = agent_sync.TARGET_DIR
                agent_sync.install()
                before = {
                    name: (agent_sync.TARGET_DIR / name).read_bytes()
                    for name in agent_sync.FILES
                }
                calls = {"count": 0}

                def interrupted(path, data, mode=0o600):
                    calls["count"] += 1
                    if calls["count"] == 3:
                        raise KeyboardInterrupt()
                    return original_write(path, data, mode)

                agent_sync._atomic_regular_write = interrupted
                with self.assertRaises(KeyboardInterrupt):
                    agent_sync.install()
                agent_sync._atomic_regular_write = original_write
                self.assertEqual(agent_sync.check()["verdict"], "PASS")
                for name, data in before.items():
                    self.assertEqual((agent_sync.TARGET_DIR / name).read_bytes(), data)
        finally:
            agent_sync._atomic_regular_write = original_write
            agent_sync.TARGET_DIR = original_target
            agent_sync.EXPECTED_TARGET_DIR = original_expected

    def test_agent_sync_rejects_symlink_lock(self):
        original_target = agent_sync.TARGET_DIR
        original_expected = agent_sync.EXPECTED_TARGET_DIR
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                base = Path(temp_dir)
                agent_sync.TARGET_DIR = base / "agents"
                agent_sync.EXPECTED_TARGET_DIR = agent_sync.TARGET_DIR
                agent_sync.TARGET_DIR.mkdir(mode=0o700)
                victim = base / "victim"
                victim.write_text("keep", encoding="utf-8")
                (agent_sync.TARGET_DIR / ".sol-cabinet-sync.lock").symlink_to(victim)
                with self.assertRaises(ValueError):
                    agent_sync.install()
                self.assertEqual(victim.read_text(encoding="utf-8"), "keep")
        finally:
            agent_sync.TARGET_DIR = original_target
            agent_sync.EXPECTED_TARGET_DIR = original_expected


if __name__ == "__main__":
    unittest.main()
