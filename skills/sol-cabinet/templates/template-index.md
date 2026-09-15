# Templates

| 模板 | 用途 | 何时使用 |
|---|---|---|
| [TASK_CARD](task-card.json) | T0 目标、授权、风险、路由 | 每个任务内部；T1-T2 可不落盘 |
| [Task Profile](task-profile.json) | 确定性 T 级脚本的匿名输入 | 临界或 T4+ 复核 |
| [Agent Result](agent-result.json) | 子 Agent 统一返回 | 启用多 Agent 时 |
| [Review Gate](review-gate.json) | 独立验收和返工 | T4+ |
| [Evolution Entry](evolution-entry.json) | 短期脱敏 intake，不是每次反馈的永久档案 | 用户明确授权长期记忆后 |
| [Evolution Proposal](evolution-proposal.json) | Level 2/3 匿名规则提案 | 用户明确授权规则维护且提案条件满足后 |
| [Source Archive Manifest](source-archive-manifest.json) | 任务内逐字节原稿归档清单 | 任意 T 级存在用户源文件时 |
| [Improvement Item](improvement-item.json) | 中央卡点的根因、方案、预防和验证闭环 | 更新 `operational-learnings.md` 时 |
| [Delivery Summary](delivery-summary.md) | 对话收尾或独立交付说明 | 有实体成果时 |

模板是 schema 起点，不要求逐项落盘；分级、计划和审核优先会话内复用。只有必要交接或已接线交付门禁才留最小文件，统一放受控过程目录。
