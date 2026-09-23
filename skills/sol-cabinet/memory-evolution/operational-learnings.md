# Operational Learnings — Legacy Read-Only Registry

本模块是 Sol Cabinet 早期中央运营卡点系统的历史记录说明。自当前 1.5.x 维护线起，`improvements.json`、`manage_improvements.py`、`record_evolution.py` 及旧 Evolution Entry／Proposal 仅保留历史兼容与审计用途，**不再作为新事故、待办、候选或晋升的活动真源**。

当前活动闭环唯一依据见 [Evolution Policy](evolution-policy.md)：真实问题以 `INC/EV` 进入待办，修复或正式晋升以有证据的 `RES/EVO` 闭合。生产任务不得同时向新旧两套账本重复登记。

## 历史边界

- `improvements.json` 冻结为历史状态快照，不因新任务继续增加、复发计数或变更状态。
- 旧 `OPEN`、`INTEGRATING`、`RECURRENT`、`VERIFIED`、`CLOSED` 状态只描述当时系统记录，不代表当前仍有活动维护授权或当前运行状态。
- 如旧事项在当前版本再次真实发生，应按 `evolution-policy.md` 新建脱敏 `INC/EV`，并把旧编号仅作为历史参考；不得直接继续写旧 registry。
- 不删除、重写或美化既有历史记录；需要清理旧体系时必须另有用户明确授权。
- 历史脚本、模板与测试不能被用来绕过当前 permission cage、候选绑定、真实回归、双独立审核或回滚要求。

## 历史术语兼容

旧记录和兼容测试中的“卡点”“根因”“解决方案”“预防门禁”“验证”，分别只用于解释历史 `blocker_code`、`root_cause_code`、`solution_code`、`prevention_code`、`verification_code` 字段，不重新建立活动维护流程。旧流程曾要求“相同 `blocker_code` 只能更新同一个”历史事项；该去重规则现已退役，当前 `INC/EV` 不继承该写入机制。历史兼容读取继续遵守“不记录用户正文”的隐私要求。

## 历史隐私约束

这些约束继续适用于读取旧记录：

- 不记录或恢复用户正文、原话、人名、单位、案件、密钥、附件文件名、完整业务路径或可识别任务信息。
- 旧 `sensitive=true`、`contains_sensitive_content!=false` 或 `sensitivity_checked!=true` 的事项不得被复制进新的活动账本。
- observation／旧 improvements 的存在不能自动生成新 EVO，也不能证明问题仍存在。

## 历史字段

| 字段 | 历史含义 |
|---|---|
| `improvement_id` | 稳定的 `OL-NNN` 历史事项编号 |
| `status` | `OPEN`、`INTEGRATING`、`VERIFIED`、`CLOSED` 或 `RECURRENT` 的历史快照 |
| `scope_code` | 当时受影响的最窄系统模块 |
| `blocker_code` | 当时登记的可复现卡点 |
| `root_cause_code` | 当时证据支持的根因 |
| `solution_code` | 当时已实施或计划方案 |
| `prevention_code` | 当时进入模块、脚本或测试的预防门禁 |
| `verification_code` | 当时测试、哈希、Review Gate 或复验状态 |
| `first_seen_date` / `last_seen_date` / `last_verified_date` | 历史日期 |
| `recurrence_count` | 旧 registry 中记录的复发次数 |

## 历史固定代码

以下代码仅用于解释旧数据，不是新事故的活动 taxonomy：

| 类型 | 已登记代码 |
|---|---|
| blocker | `source-archive-omission`、`agent-parallelism-underuse`、`page-field-update-warning`、`reviewer-stall`、`preview-permission-block`、`candidate-test-unbound`、`rollback-state-incomplete`、`external-source-material-drift` |
| root cause | `archive-gate-too-late`、`agent-plan-not-locked`、`global-field-refresh-overbroad`、`review-scope-overbroad`、`sandbox-service-boundary`、`static-pass-registry`、`approval-applied-state-conflated`、`concurrent-external-writer` |
| solution | `global-archive-gate-and-script`、`parallel-readonly-waves`、`remove-page-only-updatefields`、`bounded-review-replacement`、`single-controlled-escalation`、`candidate-bound-test-run`、`split-state-and-restore-drill`、`fail-closed-and-separate-reconciliation` |
| prevention | `archive-before-content`、`truthful-agent-trace`、`field-and-external-rel-audit`、`minimal-review-schema`、`preview-preflight`、`invalidate-test-on-candidate-change`、`verified-rollback-state-machine`、`pre-post-source-integrity-check` |
| verification | `archive-regression-and-live-idempotency`、`pending-ab-measurement`、`ooxml-structural-diff`、`pending-next-review-run`、`controlled-preview-pass`、`candidate-binding-tests-pass`、`pending-restore-drill`、`pending-source-owner-reconciliation` |

## 当前维护入口

新问题不得调用旧 registry 更新流程。当前统一使用：

1. 生产任务先完成当前交付；
2. 有真实实质失败才按 `evolution-policy.md` 记录脱敏 `INC/EV`；
3. `status` 读取活动待办；
4. 维护层形成候选并运行相关回归；
5. 通过真实证据、权限判断和独立审核后，以 `RES` 或正式 `EVO` 闭合；
6. 需要回滚时走当前 EVO 回滚机制。

因此：**旧 improvements 是历史，INC/EV 是当前待办真源，RES/EVO 是当前闭环真源。**
