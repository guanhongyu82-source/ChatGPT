# Domain Skills 路由

先按目标选择能力，再调用当前环境中可用的最小 Skill 集。不要因为文件类型出现就加载所有 Office Skill。

| 目标 | 首选能力/当前 Skill | 同时读取 |
|---|---|---|
| Word 创建、修订、批注、红线 | `documents:documents` | [Office](office-delivery.md)、[正式写作](formal-writing.md) |
| Excel、CSV、台账、公式 | `spreadsheets:Spreadsheets` | [台账与数据](ledger-data.md) |
| PowerPoint/Google Slides | `presentations:Presentations` | [Office](office-delivery.md) |
| PDF 阅读、填写、生成、版面核验 | `pdf:pdf` | [Office](office-delivery.md) |
| 单点公开事实、版本核实 | `research-agent`；OpenAI产品用当前官方文档能力 | [研究与事实](research-facts.md) |
| 多来源专题、政策／行业研究、复杂证据综合 | `sol-research` | [研究与事实](research-facts.md) |
| KPI、数据质量、诊断、报告 | 相应 `data-analytics:*` 专项 Skill | [台账与数据](ledger-data.md) |
| 陌生仓库只读体检 | `repo-health-check` | [仓库与安全](repository-security.md) |
| 鉴权、密钥、注入、供应链 | `security-audit` | [仓库与安全](repository-security.md) |
| Codex/OpenAI 设置、Skill、模型、API | `openai-docs`；失败诊断按专项 Skill | [Codex Adapter](../platform-adapter/codex.md) |
| 产图或改图 | 仅用户明确要求时使用 `imagegen` | 当前图像要求 |
| 浏览已登录网页或本地 Web UI | 仅任务需要交互状态时用 Browser/Chrome 控制 | 保密和授权边界 |

## 路由规则

- 当前环境没有列出的 Skill 时，不得伪称已调用；使用等价本地能力或报告降级。
- 专门 Skill 的格式和验证流程用于完成当前授权目标；不能覆盖用户的工具禁令、保密要求、微改边界或阶段停止条件。
- 涉密材料禁止发送给网页、连接器或外部研究工具；公开政策可用去敏关键词单独查询。
- 审阅请求默认只读。只有用户明确要求修改，或原请求本身已经授权修改，才进入写入链。
- 一个任务可以命中多个领域，但只加载会改变决策或交付方式的模块。

## 公共组件

文件结构、保真线索和旧值候选按需使用 [公共能力](common-components.md)，不建立Office或Writer第二中枢。公共读取不得绕过原稿门禁；原生文档、表格、演示和PDF工具继续负责生成与各自必要核验。
