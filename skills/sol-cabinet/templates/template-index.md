# Templates

| 模板 | 用途 | 何时使用 |
|---|---|---|
| [TASK_CARD](task-card.json) | 确认后的目标、授权、风险与交付路由 | 仅在需要结构化交接或持久化门禁时落盘；启动卡不落文件 |
| [Task Profile](task-profile.json) | 确定性 T 级脚本的匿名输入 | 临界或 T4+ 复核 |
| [Opening Summary](opening-summary.md) | 确认后的目标、预期交付、位置、约束和停止条件 | 非轻量任务；启动卡优先，确认后按需呈现 |
| [Agent Result](agent-result.json) | 子 Agent 统一返回 | 启用多 Agent 时 |
| [Review Gate](review-gate.json) | 独立验收和返工 | T4+ |
| [Evolution Entry](evolution-entry.json) | **LEGACY / READ ONLY**：早期短期 intake schema | 仅解释或核查历史记录；新事故不得使用 |
| [Evolution Proposal](evolution-proposal.json) | **LEGACY / READ ONLY**：早期 Level 2/3 提案 schema | 仅解释或核查历史记录；新晋升不得使用 |
| [Source Archive Manifest](source-archive-manifest.json) | 任务内逐字节原稿归档清单 | 任意 T 级存在用户源文件时 |
| [Improvement Item](improvement-item.json) | **LEGACY / READ ONLY**：旧 `improvements.json` schema | 仅解释旧 registry；不得新建或更新活动事项 |
| [Completion Summary](delivery-summary.md) | 真实成品、路径、目录状态、核验、限制与耗时的完工小结 | 文件型任务成功前必需；其他非瞬时任务用于收口 |

模板是 schema 起点，不要求逐项落盘；分级、计划和审核优先会话内复用。只有必要交接或已接线交付门禁才留最小文件，统一放受控过程目录。

当前自我进化活动入口统一以 `memory-evolution/evolution-policy.md` 为准：`INC/EV` 记录待办，`RES/EVO` 闭合。旧 evolution／improvement 模板不与当前闭环并行写入。
