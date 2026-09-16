"""Regression guards for canonical rule ownership; no runtime policy is defined here."""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class AuthorityContract(unittest.TestCase):
    def read(self, relative):
        return (ROOT / relative).read_text(encoding='utf-8')

    def test_version_value_has_one_authority(self):
        version = self.read('VERSION').strip()
        self.assertRegex(version, r'^\d+\.\d+\.\d+$')
        for relative in ('README.md', 'SKILL.md', 'core/system-architecture.md'):
            text = self.read(relative)
            self.assertIsNone(
                re.search(r'(?:Current version|当前维护版本(?:为)?|当前版本(?:为)?)\s*[:：=]?\s*`?\d+\.\d+\.\d+', text),
                relative,
            )

    def test_router_does_not_own_future_timing_policy(self):
        router = self.read('t0-executive-router/router.md')
        self.assertNotIn('预计耗时', router)
        self.assertIn('不另定义开工字段或耗时规则', router)
        self.assertIn('../SKILL.md', router)

    def test_architecture_declares_required_canonical_owners(self):
        architecture = self.read('core/system-architecture.md')
        start = architecture.index('## Canonical Authority Map')
        end = architecture.index('## 单一版本与部署原则', start)
        section = architecture[start:end]
        required = {
            'VERSION': '当前版本身份',
            'core/core.md': '长期不变量',
            't0-executive-router/router.md': 'T0',
            'task-classification/t1-t10.md': 'T1-T10',
            'domain-skills/office-delivery.md': '文件',
            'review-system/review-system.md': '独立审核',
            'agent-orchestrator/orchestration.md': 'Agent',
            'memory-evolution/evolution-policy.md': '进化',
            'platform-adapter/deployment-contract.md': 'GitHub→Mac',
            'platform-adapter/codex.md': 'Chat/Work/Codex',
            'core/system-architecture.md': 'Hot Path Weight',
        }
        for owner, label in required.items():
            with self.subTest(owner=owner):
                self.assertIn(owner, section, label)

    def test_metadata_and_history_cannot_masquerade_as_current_authority(self):
        readme = self.read('README.md')
        architecture = self.read('core/system-architecture.md')
        self.assertIn('MANIFEST.md', readme)
        self.assertIn('archival evidence', readme)
        self.assertIn('MANIFEST.md', architecture)
        self.assertIn('不是当前文件哈希注册表', architecture)

    def test_entry_is_summary_not_second_owner(self):
        skill = self.read('SKILL.md')
        self.assertIn('本入口提供执行摘要', skill)
        self.assertIn('不另立同类规则的第二权威', skill)
        self.assertIn('core/system-architecture.md', skill)

    def test_hot_path_policy_has_one_owner_and_machine_guard(self):
        architecture = self.read('core/system-architecture.md')
        self.assertIn('## Hot Path Weight 与三层控制面', architecture)
        for marker in ('L0 — Hot Core', 'L1 — Task Modules', 'L2 — Governance Plane'):
            self.assertIn(marker, architecture)
        self.assertIn('v1.5.2 — Structure Governance / Non-expansion Baseline', architecture)
        self.assertIn('v1.5.3 — Quality Validation（框架）', architecture)
        self.assertIn('v1.5.4 — Control Plane Reduction（框架）', architecture)
        for relative in ('SKILL.md', 't0-executive-router/router.md'):
            self.assertNotIn('Hot Path Weight', self.read(relative), relative)

        cage = json.loads(self.read('memory-evolution/permission-cage.json'))
        self.assertIn('普通任务常驻控制面不随能力增长而扩大', cage['frozen'])
        denied = '\n'.join(cage['denied'])
        self.assertIn('无真实缺口证据和用户单独批准新增职责', denied)
        self.assertIn('为预防假设性问题向普通任务 Hot Path 添加常驻规则', denied)

    def test_legacy_operational_registry_cannot_regain_live_authority(self):
        ledger = self.read('memory-evolution/operational-learnings.md')
        policy = self.read('memory-evolution/evolution-policy.md')
        self.assertIn('Legacy Read-Only Registry', ledger)
        self.assertIn('不再作为新事故、待办、候选或晋升的活动真源', ledger)
        self.assertIn('旧 improvements 是历史', ledger)
        self.assertIn('INC/EV 是当前待办真源', ledger)
        self.assertIn('RES/EVO 是当前闭环真源', ledger)
        self.assertIn('INC/EV 为事故待办唯一真源', policy)
        self.assertIn('旧 improvements 仅保留历史', policy)


if __name__ == '__main__':
    unittest.main()
