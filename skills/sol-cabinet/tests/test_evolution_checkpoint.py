from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class EvolutionCheckpointTests(unittest.TestCase):
    def test_checkpoint_is_mandatory_and_visible(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        policy = (ROOT / "memory-evolution" / "evolution-policy.md").read_text(encoding="utf-8")
        summary = (ROOT / "templates" / "delivery-summary.md").read_text(encoding="utf-8")

        self.assertIn("Evolution Checkpoint", skill)
        self.assertIn("无信号记 `CLEAN`", skill)
        self.assertIn("不重新读文件", skill)
        self.assertIn("每次收尾必经", policy)
        self.assertIn("零账本读取、零 incident、零回归、零 EVO", policy)
        self.assertIn("若 `record` 返回拒绝或写入失败，本次状态只能是 `PENDING`", policy)
        self.assertIn("进化：CLEAN", summary)
        self.assertIn("进化：RECORDED｜N项", summary)
        self.assertIn("进化：PENDING｜N项", summary)
        self.assertIn("不得包含业务正文、姓名、单位、附件名、业务路径", summary)


if __name__ == "__main__":
    unittest.main()
