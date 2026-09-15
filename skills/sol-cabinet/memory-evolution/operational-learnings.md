# Operational Learnings

本模块是 Sol Cabinet 的中央运营卡点系统。机器真源是 [improvements.json](improvements.json)；本文件只定义字段、固定代码和闭环规则，不重复保存逐任务正文或每次反馈档案。

## 不可违反的边界

- 只记录抽象控制模式，不记录用户正文、原话、人名、单位、案件、密钥、附件文件名、完整路径、文件哈希或可识别任务信息。
- `sensitive=true`、`contains_sensitive_content!=false` 或 `sensitivity_checked!=true` 时，`scripts/manage_improvements.py` 必须拒绝写入。
- 相同 `blocker_code` 只能更新同一个 `improvement_id`；复发时增加次数并更新日期，不新建重复长期事项。
- 只有根因、解决方案、预防措施和验证全部有固定代码，且验证状态满足门禁时，事项才能进入 `VERIFIED` 或 `CLOSED`。
- observation 是短期 intake；中央事项验证后，只能通过明确 observation ID 清单安全退出，禁止通配删除或跟随符号链接。

## 闭环字段

| 字段 | 含义 |
|---|---|
| `improvement_id` | 稳定的 `OL-NNN` 事项编号 |
| `status` | `OPEN`、`INTEGRATING`、`VERIFIED`、`CLOSED` 或 `RECURRENT` |
| `scope_code` | 受影响的最窄系统模块 |
| `blocker_code` | 可复现卡点 |
| `root_cause_code` | 证据支持的根因 |
| `solution_code` | 已实施或待实施方案 |
| `prevention_code` | 进入真实模块、脚本或测试的预防门禁 |
| `verification_code` | 测试、哈希、Review Gate 或真实复验 |
| `first_seen_date` / `last_seen_date` / `last_verified_date` | 只记录日期，不记录任务标识 |
| `recurrence_count` | 相同问题的复发次数 |

## 固定代码

| 类型 | 已登记代码 |
|---|---|
| blocker | `source-archive-omission`、`agent-parallelism-underuse`、`page-field-update-warning`、`reviewer-stall`、`preview-permission-block`、`candidate-test-unbound`、`rollback-state-incomplete`、`external-source-material-drift` |
| root cause | `archive-gate-too-late`、`agent-plan-not-locked`、`global-field-refresh-overbroad`、`review-scope-overbroad`、`sandbox-service-boundary`、`static-pass-registry`、`approval-applied-state-conflated`、`concurrent-external-writer` |
| solution | `global-archive-gate-and-script`、`parallel-readonly-waves`、`remove-page-only-updatefields`、`bounded-review-replacement`、`single-controlled-escalation`、`candidate-bound-test-run`、`split-state-and-restore-drill`、`fail-closed-and-separate-reconciliation` |
| prevention | `archive-before-content`、`truthful-agent-trace`、`field-and-external-rel-audit`、`minimal-review-schema`、`preview-preflight`、`invalidate-test-on-candidate-change`、`verified-rollback-state-machine`、`pre-post-source-integrity-check` |
| verification | `archive-regression-and-live-idempotency`、`pending-ab-measurement`、`ooxml-structural-diff`、`pending-next-review-run`、`controlled-preview-pass`、`candidate-binding-tests-pass`、`pending-restore-drill`、`pending-source-owner-reconciliation` |

## 更新流程

1. 对当前任务卡点完成敏感检查；不能安全抽象时只在当前会话报告。
2. 使用固定代码形成或更新同一中央事项。
3. 运行 `scripts/manage_improvements.py` 的 schema 校验和原子 upsert；未知字段、自由文本或重复 blocker 必须失败。
4. 将预防措施落实到真实 Core、Router、Domain、Review、Orchestrator、Script 或 Test。
5. 通过候选后测试和独立审核，再更新为 `VERIFIED`／`CLOSED`。
6. 事项验证后，可按明确 ID 清单退出已归并的短期 observation；不得按目录、通配符或模糊条件清理。
