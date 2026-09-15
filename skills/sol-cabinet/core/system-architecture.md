# Sol Cabinet v1.5 System Architecture

代码与正式维护单一真源：`guanhongyu82-source/ChatGPT:skills/sol-cabinet/`。

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

1.5.x 不改变主结构和 T1-T10。该维护线只收口三类问题：GitHub→本机的单向部署可追溯性、旧进化入口的只读退役、当前 Chat／Work／Codex 宿主的交付与能力适配。任何后续优化仍以“任务不变、边界不扩”为前提。
