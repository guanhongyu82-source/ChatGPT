from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class HotPathPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        cls.router = (ROOT / "t0-executive-router" / "router.md").read_text(encoding="utf-8")
        cls.orchestrator = (ROOT / "agent-orchestrator" / "orchestration.md").read_text(encoding="utf-8")
        cls.review = (ROOT / "review-system" / "review-system.md").read_text(encoding="utf-8")
        cls.formal_writing = (ROOT / "domain-skills" / "formal-writing.md").read_text(encoding="utf-8")
        cls.task_card = json.loads((ROOT / "templates" / "task-card.json").read_text(encoding="utf-8"))
        cls.performance = json.loads(
            (ROOT / "tests" / "performance-validation-v1.5.4.json").read_text(encoding="utf-8")
        )

    def test_routine_nonlight_path_does_not_unconditionally_load_core(self):
        self.assertIn("普通办公执行不固定加载", self.skill)
        self.assertIn("先读 [Router]", self.skill)
        self.assertIn("L0 热核最小", self.skill)
        self.assertEqual(
            self.performance["control_plane_targets"]["routine_nonlight_fixed_load"],
            ["router"],
        )

    def test_task_card_has_reusable_evidence_and_resource_plan_surfaces(self):
        self.assertIn("resource_plan", self.task_card)
        self.assertIn("independent_units", self.task_card["resource_plan"])
        self.assertIn("evidence_pack", self.task_card)
        for key in ("sources", "coverage", "facts", "conflicts", "unread"):
            self.assertIn(key, self.task_card["evidence_pack"])

    def test_router_requires_single_extraction_and_reasoned_reread(self):
        self.assertIn("一次提取，多处复用", self.router)
        self.assertIn("已有可信提取时不重新全文读取", self.router)
        self.assertIn("来源指纹", self.router)
        self.assertIn("重复全文读取", self.router)

    def test_final_lead_cannot_default_to_full_source_reread(self):
        self.assertIn("不默认让 Final Lead 重新全文读取", self.orchestrator)
        self.assertIn("duplicate_read", self.orchestrator)
        self.assertIn("来源 fingerprint", self.orchestrator)

    def test_independent_final_artifacts_are_not_forced_through_one_global_writer(self):
        self.assertIn("one writer per artifact/path", self.orchestrator)
        self.assertIn("不同且输出路径隔离的最终成品", self.orchestrator)
        self.assertIn("可以各有一个授权写者同波生成", self.orchestrator)
        qv06 = next(item for item in self.performance["scenarios"] if item["id"] == "QV-06")
        self.assertIn("one writer per final artifact", qv06["single_writer_scope"])

    def test_formal_writing_reuses_shared_evidence_pack_instead_of_second_material_pack(self):
        self.assertIn("Task Card `evidence_pack`", self.formal_writing)
        self.assertIn("不再另建第二份来源画像", self.formal_writing)
        self.assertIn("INTERPRET_PACK", self.formal_writing)
        self.assertIn("不重新读取来源", self.formal_writing)
        self.assertIn("evidence-pack slice", self.formal_writing)

    def test_review_reuses_extraction_but_resourses_critical_claims(self):
        self.assertIn("不要求把未变化的大材料机械地全文重新解析一遍", self.review)
        self.assertIn("高风险／争议事实", self.review)
        self.assertIn("必须直接读取对应原始片段", self.review)
        self.assertIn("reuse extraction, re-decide independently", self.review)

    def test_multi_artifact_review_can_parallelize_without_weakening_cross_artifact_join(self):
        self.assertIn("按 artifact/object 切成多个独立只读实例同波执行", self.review)
        self.assertIn("跨成品一致性 join", self.review)
        self.assertIn("不降低最低独立审核强度", self.review)
        qv06 = next(item for item in self.performance["scenarios"] if item["id"] == "QV-06")
        review_wave = qv06["after_waves"][3]
        self.assertIn("docx_artifact_review", review_wave)
        self.assertIn("xlsx_artifact_review", review_wave)
        self.assertIn("cross_artifact_consistency_join", qv06["after_waves"][4])

    def test_performance_guard_rejects_unreasoned_duplicate_full_reads(self):
        targets = self.performance["control_plane_targets"]
        self.assertEqual(targets["duplicate_full_source_reads_without_invalidation"], 0)
        self.assertFalse(targets["final_lead_default_full_reread_after_trusted_extraction"])
        self.assertFalse(targets["review_default_full_source_reparse"])


if __name__ == "__main__":
    unittest.main()
