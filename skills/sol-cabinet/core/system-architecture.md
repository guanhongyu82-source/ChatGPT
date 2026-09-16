# Sol Cabinet System Architecture

代码与正式维护单一真源：`guanhongyu82-source/ChatGPT:skills/sol-cabinet/`。当前版本身份只读取根目录 [`VERSION`](../VERSION)，本文件不复制“当前版本号”。

本机 `/Users/macbook/ChatGPT/lineage/codex-root/配置库/04_skill索引/sol-cabinet/` 是 Codex／Work 的运行部署树，只执行已选定 GitHub commit 的部署版本，不作为第二维护真源。本机出现差异时视为 runtime drift，先比对 GitHub 基线，不得反向覆盖正式版本。部署、核验和回滚见 [Deployment Contract](../platform-adapter/deployment-contract.md)。

```text
sol-cabinet/
├── SKILL.md
├── core/
├── t0-executive-router/
├── task-classification/
├── domain-skills/
├── agent-orchestrator/
├── review-system/
├── memory-evolution/
├── templates/
├── examples/
├── platform-adapter/
├── source-index/
├── scripts/
└── tests/
```

| 用户架构名称 | 实际目录 | 唯一职责 |
|---|---|---|
| Core | `core/` | 长期不变量、权限、保密、资产保护 |
| T0 Executive Router | `t0-executive-router/` | 目标、风险、路径、等级和路由 |
| Task Classification | `task-classification/` | T1-T10 与核验需求；资源按独立工作和收益决策 |
| Domain Skills | `domain-skills/` | Office、写作、研究、数据、仓库与安全增量规则 |
| Agent Orchestrator | `agent-orchestrator/` | 角色、依赖图、并发、冲突裁决和持久运行 |
| Review System | `review-system/` | 独立取证、门禁、返工和 verdict |
| Memory / Evolution | `memory-evolution/` | 短期脱敏观察、三级提案、Direct Policy Change、中央卡点闭环和 Core 变更边界 |
| Templates | `templates/` | 结构化运行、审核、进化和交付模板 |
| Examples | `examples/` | 匿名路由示例 |
| Platform Adapter | `platform-adapter/` | Chat／Work／Codex 运行适配、Agent 配置、部署与安装 |
| Tests | `tests/` | 路由、结构、安全、源资产和前向行为验证 |

## Canonical Authority Map

同一规则域只允许一个规范 owner；入口摘要、平台适配、脚本和测试可以引用或机械执行，但不得成为第二套政策来源。

| 规则域 | Canonical owner | 边界 |
|---|---|---|
| 当前版本身份 | `VERSION` | 唯一当前版本号；README、SKILL、架构正文不得复制“当前版本=x.y.z” |
| 长期不变量、阶段授权、保密、资产保护 | `core/core.md` | 其他模块只能增加本域具体规则，不得弱化 Core |
| T0 目标理解与路由 | `t0-executive-router/router.md` | 负责路由，不定义 T 等级表、Office 交付细则或 Review verdict |
| T1-T10 分级与核验强度 | `task-classification/t1-t10.md` | 不定义固定 Agent 套餐或具体文件交付政策 |
| 文件、原稿、目录、预期成品与 Actual 对账政策 | `domain-skills/office-delivery.md` | `templates/task-card.json` 承载 Expected 数据；`scripts/delivery_gate.py` 只机械执行其可判定子集 |
| 独立审核、证据、返工与 PASS/FAIL/BLOCKED verdict | `review-system/review-system.md` | 可审 Office 规则是否满足，但不另写第二套 Office 政策 |
| Agent 编排、依赖与并发 | `agent-orchestrator/orchestration.md` | 不改变 T 分级、质量 Gate 或用户授权边界 |
| 进化、candidate→Stable 发布权限与 EVO/回滚 | `memory-evolution/evolution-policy.md` | `permission-cage.json` 是该域冻结机器边界；`scripts/evolve.py` 是执行门禁，不自行发明授权 |
| GitHub→Mac 正式部署 | `platform-adapter/deployment-contract.md` | 部署不等于发布；本机运行树不产生反向正式版本权威 |
| Chat/Work/Codex 宿主差异与 Hook 接法 | `platform-adapter/codex.md` | 只描述宿主适配；不得改写 Core、Office、Review、Evolution 或 Deployment 的通用政策 |
| Hot Path Weight 与控制面分层 | `core/system-architecture.md` | 只定义常驻／按需／治理三层边界和后续不扩张基线；不在各业务模块复制第二套分层政策 |

### 冲突与重复裁决

1. 系统／开发者指令和当前用户明确授权始终高于仓库规则；仓库内部再按上表 owner 裁决。
2. `SKILL.md` 是运行入口和最短路径摘要，不是各规则域的第二 owner。摘要与 canonical owner 不一致时，摘要视为缺陷并回指 owner，不把两份文字折中合并。
3. Template 只定义数据形状；Script 只执行可机械判断的门禁；Test 只证明既定行为没有退化；Example 只示例。四者都不能单独创造新政策。
4. `README.md`、`MANIFEST.md`、`source-index/` 和历史 smoke/runtime snapshot 属于导航、迁移或历史证据，不覆盖当前政策、版本或运行状态。`MANIFEST.md` 中哈希只表示原始导入基线，不是当前文件哈希注册表。
5. 允许“摘要性重复”：非 owner 可用一句话说明并链接 owner；禁止“规范性重复”：不得在非 owner 重新列完整条件、阈值、权限或状态机，使其可独立解释同一规则域。
6. 发现 owner 之间边界重叠时，先按职责切分后再修改；不得新增第二清单、第二状态机或兼容性镜像来回避裁决。

## Hot Path Weight 与三层控制面

Cabinet 的长期性能约束不是“总行数越少越好”，而是**普通任务真正激活的控制面不得随能力增长而线性增长**。`Hot Path Weight` 指一个具体任务实际加载或执行的规则、模块、判断节点、串行 Gate 与控制性工具调用总负担；后续性能判断优先看激活量，而不是仓库总代码量。

- **L0 — Hot Core**：所有任务都必须经过的最小常驻层，只保留任务目标／边界、第一准则、绝对禁止项和最小路由。只有“所有任务都必须知道”的规则才允许进入 L0。
- **L1 — Task Modules**：Office、写作、审阅、数据等场景规则按任务需要加载；未命中的模块不读、不判断、不执行。模块内部也优先按需，而不是因为文件存在就整段常驻。
- **L2 — Governance Plane**：版本、GitHub、Runtime 部署、自我进化、回归、EVO、回滚、Hook 治理和系统维护。普通业务任务原则上不进入 L2；只有真实事故或用户明确维护 Cabinet 时才加载相应治理机制。

从本维护基线起，新增能力默认不得扩大 L0 或普通任务 Hot Path。新增职责、Domain、Agent、常驻控制节点或治理链条，必须有真实缺口证据并由用户单独批准；能通过复用、下沉、合并、延后、并行或删除解决时，不以新增常驻规则替代。模型能力升级优先转化为更少空转、更高并行、更深颗粒度、更高精度与质量，不转化为更宽职责或更重常驻控制面。

后续性能验证可观察 `Activated Rules`、`Loaded Modules`、`Decision Nodes`、`Serial Gates`、控制性工具调用和 `Control / Work Ratio`；本阶段只确立指标方向，不设阈值、不重构目录、不提前实施减重工程。

## 单一版本与部署原则

- GitHub `skills/sol-cabinet/` 保存正式维护版本和 Git 历史；Chat 中的定稿只有在正式写入 GitHub 后才成为持久版本。
- CLI 与 Desktop 使用同一已部署 Skill 入口和同一 `~/.codex` Agent 配置；本机运行树必须能追溯到一个明确 GitHub commit。
- 本机部署不得把运行态日志、锁文件、缓存、临时证据或任务文件反推回仓库；只有用户定稿并授权的最小变更才进入 GitHub。
- Domain 模块不是 11 个自动触发 Skill；入口只加载当前任务需要的模块。
- 用户长期记忆、当前业务正文和脱敏技术事故分开处理。依2026-09-12/13授权，真实事故在收尾记录为INC/EV并进入待办；无事故零写入。生产不改规则，维护按证据和权限修复。旧 improvements 为历史，不作为新事故待办真源。
- Grok 资产只在 `source-index/` 留存历史路径、哈希和迁移决策，不成为运行依赖。

## v1.2 核心蒸馏

能力升级不扩界；当前阶段授权独立；局部Office编辑不因格式误升档；分类与执行人数分离；材料角色与证据复用进入既有领域模块；总审同时验遗漏、越界和真实文件。Sol Research、外围Skill、公共脚本、全局模型配置及最终实战A/B不属于v1.2升级。

## v1.3 外围收口

研究由Sol Research独立承接，research-agent为轻量兼容入口；外围审阅与写作机制收敛进既有领域模块，原生文件工具复用；新增只读Office定位及维护证据公共组件。目标历史配置索引改为当前真源导航，用户全局模型、档位、权限和插件选择不改。当时将真实办公A/B、性能／额度评估与全体系验证留待后续；当前安排见下方1.4状态。

## v1.4 蒸馏完整版

2026-09-08按用户要求完成蒸馏收口，测试延期。74个技能入口沿用已完成处置；规则、Agent、Workflow、知识框架、公共工具、研究、配置、维护和命令等非Skill资产在[最终处置状态](../source-index/distillation-status.json)统一归并。没有为版本号重写已完成的执行实现。

“完整版”指约定范围内的能力融合与资产处置完成，不表示全部功能或办公场景已经测试。1.3的测试与验收保留历史身份，本次不运行测试、功能试跑或A/B；普通办公任务原有的质量、原稿、保密和独立审核规则没有关闭。测试何时恢复由用户另行通知。

## v1.5 执行闭环修复

唯一运行入口为 Codex Home 的 `skills/sol-cabinet`，指向本机部署树；重复发现入口移除，备份只在维护归档中保留压缩原稿，不作为技能加载。开工、定级、文件命名、必要审核、临时留存、结束小结和事故记录在交付契约统一核验。Codex钩子按任务触发并需宿主信任，无后台守护进程；第二次失败停止自动续跑并明确PARTIAL。新事故状态只以INC/EV及有证据的RES/EVO闭合判断，不以道歉或自报PASS替代。

## v1.5.x 维护方向

**v1.5.2 — Structure Governance / Non-expansion Baseline**：完成发布权、Expected↔Actual、Authority、GitHub／Runtime、Hook 状态治理，并把 Hot Path Weight、L0/L1/L2 与“不扩张”确立为后续维护基线。自此以后默认只做验证、修复、收敛、下沉、合并、减重和提速；没有真实缺口证据和用户单独批准，不新增职责、Domain、Agent、常驻控制节点或治理链条。

**v1.5.3 — Quality Validation（框架）**：用真实办公任务验证当前结构是否影响质量，优先区分执行失败与规则缺口；没有真实 failure 不增加 Cabinet 重量。本阶段只预留方向，不在 v1.5.2 提前设计任务集、阈值或施工细则。

**v1.5.4 — Control Plane Reduction（框架）**：基于 v1.5.3 的真实证据做减重、并行和提速，重点降低 Hot Path Weight，而不是追求总代码行数下降。本阶段只预留方向和观察指标，不在 v1.5.2 提前删规则、改路由、设性能阈值或实施重构。

1.5.x 不改变主结构和 T1-T10。任何后续优化继续遵守“任务不变、边界不扩；能力升级不增加普通任务常驻控制面”的原则。