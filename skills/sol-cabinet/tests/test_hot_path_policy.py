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
        cls.task_card = json.loads((ROOT / "templates" / "task-card.json").read_text(encoding="utf-8"))
        cls.performance = json.loads(
            (ROOT / "tests" / "performance-validation-v1.5.4.json").read_text(encoding="utf-8")
        )

    def test_routine_nonlight_path_does_not_unconditionally_load_core(self):
        self.assertIn("普通办公执行不固定加载", self.skill)
        self.assertIn("Router 作为热核", self.skill.replace("[Router]", "Router"))
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
        self.assertIn("source fingerprint", self.router)
        self.assertIn("duplicate", self.router)

    def test_final_lead_cannot_default_to_full_source_reread(self):
        self.assertIn("不默认让 Final Lead 重新全文读取", self.orchestrator)
        self.assertIn("duplicate_read", self.orchestrator)
        self.assertIn("来源 fingerprint", self.orchestrator)

    def test_review_reuses_extraction_but_resourses_critical_claims(self):
        self.assertIn("不要求把未变化的大材料机械地全文重新解析一遍", self.review)
        self.assertIn("高风险／争议事实", self.review)
        self.assertIn("必须直接读取对应原始片段", self.review)
        self.assertIn("reuse extraction, re-decide independently", self.review)

    def test_performance_guard_rejects_unreasoned_duplicate_full_reads(self):
        targets = self.performance["control_plane_targets"]
        self.assertEqual(targets["duplicate_full_source_reads_without_invalidation"], 0)
        self.assertFalse(targets["final_lead_default_full_reread_after_trusted_extraction"])
        self.assertFalse(targets["review_default_full_source_reparse"])


if __name__ == "__main__":
    unittest.main()
