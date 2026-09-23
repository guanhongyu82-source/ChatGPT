# Platform Adapter：Chat / Work / Codex

历史平台依据日期：2026-08-23。以下历史产品信息不是当前宿主功能保证；漂移时查当前工具或官方依据，不把版本快照写入 Core。

## 正式真源与运行部署

正式维护单一真源：

```text
guanhongyu82-source/ChatGPT:skills/sol-cabinet/
```

Mac 本机路径：

```text
/Users/macbook/ChatGPT/lineage/codex-root/配置库/04_skill索引/sol-cabinet
```

仅作为运行部署树，不再作为独立维护真源。GitHub→Mac 的单向部署、GitHub／Runtime 状态模型、漂移处理、验证和回滚见 [Deployment Contract](deployment-contract.md)。本机发现到未知正文改动时先停止覆盖并报告，不自动反推 GitHub。

个人 Skill 运行入口：

```text
/Users/macbook/.codex/skills/sol-cabinet -> 本机运行部署树
```

本机只保留 `.codex/skills/sol-cabinet` 一个发现入口；其他同名重复入口不作为当前正式加载路径。入口是符号链接，不另造维护副本。

自定义 Agent 真源随正式 Skill 版本维护，部署后同步到运行副本：

```text
skills/sol-cabinet/platform-adapter/codex-agents/sol-*.toml
  -- scripts/sync_agent_runtime.py -->
/Users/macbook/.codex/agents/sol-*.toml
```

当前 Codex 运行仍使用受管逐字节一致副本；只维护 GitHub 中的正式源，Mac 部署后再执行 `scripts/sync_agent_runtime.py --install`，验收执行 `--check`。同步器使用独占锁、单文件原子替换、目录 fsync、受控中断回滚和终态哈希检查。操作系统级 `SIGKILL` 仍可能留下可检测的混合代际；此时 `--check` 必须 FAIL，重新部署或同步恢复，不得继续使用旧 PASS。

角色说明见 [Agent Roster](codex-agents/roster.md)。

## Chat / Work / Codex 分工

- **Chat**：讨论、审阅、方案、定稿、GitHub 正式维护和版本决策；不因看见本机历史路径就把它当比 GitHub 更新的权威源。
- **Work**：中文办公生产、文件处理、多文件综合和实际成品交付；必须遵守原稿、目录、Review 与完工小结规则。
- **Codex**：本机部署、运行核验、受管 Agent 同步、确需本机文件权限的机械维护；不得重新设计已经在 Chat 定稿的内容。

宿主能力变化时按实际可用工具降级或转交，不伪称调用了不存在的 Work、Agent、Hook、连接器或本机权限。

已激活的新 Cabinet 任务统一使用同一开工卡与确认状态；当前 Lab 的 Hook 接线见 [Hook 状态治理](#hook-状态治理)。

## AGENTS.md 层级

Codex 先读 `~/.codex/AGENTS.md`，再按项目根到当前目录叠加更具体规则。`/Users/macbook/AGENTS.md` 属于其他 workspace，Codex 日常会话的 CWD 固定为 `/Users/macbook/ChatGPT`，由更深层 `ChatGPT/AGENTS.md` 明确覆盖产品边界；任务文件使用实际授权路径。不要修改或删除其他产品规则。

最小托管段见 [AGENTS managed block](AGENTS.managed-block.md)。它负责轻量 T0、覆盖 T1-T10 的源文件归档硬门禁和加载 `$sol-cabinet`；完整规则仍在 Skill 正式源。Archive Gate 保留在托管段，是因为 T1-T2 可以不加载完整 Skill，但不能跳过原稿保护。

## 多 Agent

- 主 Agent 负责 spawn、等待、冲突合并和 Final Lead；子 Agent 默认不再 spawn。
- 物理并发受当前会话槽位限制；逻辑角色按波执行。
- 子 Agent 与主 Agent 共享文件系统，写入必须隔离。
- 审核角色配置 `sandbox_mode = "read-only"`，但会话实时权限仍可能覆盖配置；提示词必须再次明确只读。

## 敏感会话与 Memory

T0 命中真实人名加具体案件或 `secret-bearing` 时，除禁止联网和 Evolution Log 外，还要关闭或确认当前聊天不贡献未来 Memory。若当前界面/工具无法程序化确认，先给保密提示，明确仅在当前任务范围处理，并停止任何持久化步骤。全局关闭 Memory 属于用户配置变更，必须另行授权，不得静默修改。

`sandbox_mode=read-only` 只约束文件写入，不是网络、插件或连接器的技术隔离。敏感 `TASK_CARD` 必须显式写 `external_access/network/connectors/persistent_context=deny`，并在每个 Agent 任务中重复。若宿主不能保证该工具边界，secret-bearing 任务进入 `BLOCKED` 或先去标识，不能仅凭提示词宣称隔离。

## Hook 状态治理

Hook 规则由本文件定义，`scripts/codex_delivery_hook.py` 机械执行。`platform-adapter/lab-hooks.json` 是 LAB 候选配置，只有随明确授权的 Lab 部署复制到活动 hooks.json 并经宿主信任后才生效。LAB 候选需同步启用 `UserPromptSubmit`、`PreToolUse` 和 `Stop`；不恢复全局 Intake 或预算熔断。宿主未加载／信任时，不能声称写入已被机械阻断。

短期状态保存在 `/Users/macbook/ChatGPT/system/codex-home/sol-cabinet-runtime/`，schema v3 仅记录不透明 session/turn ID、模型标识、T级／路由、阶段、确认来源、交付契约路径与哈希、编码的 Evolution 状态和时间戳；不记录用户 prompt、卡片正文、附件正文或自由文本。

唯一生命周期为：`RECEIVED → CLASSIFIED → START_CARD_READY → EXECUTING → DELIVERY_PASSED → EVOLUTION_REVIEW → FINISHED`。`RETRY_REQUIRED` 只允许一次定向修复；再次失败为 `TERMINAL_PARTIAL`；未开始的取消为 `CANCELLED`。

- `RECEIVED`／`CLASSIFIED`：按 T1-T10 得到 `workflow.lane`，展示开工卡。
- `START_CARD_READY`：用户确认前停住；`PreToolUse` 对识别到的文件／shell／发布等写入调用返回 deny。直接执行授权也必须先把卡片交给用户，再以 `user-preauthorized` 来源推进。
- `EXECUTING`：只由自然语言确认或当前请求中的明确预授权推进；`started_at` 在此转换记录。`--register` 与 `--analysis-only` 只能在此后使用。
- `DELIVERY_PASSED`：`--verify-delivery` 对文件任务运行既有 `delivery_gate.check()` 一次；分析任务登记为无文件。复用该 PASS，不在 Stop 重跑完整门。此后、Evolution 完成前写入工具被拒；如获授权需修文件，`--reopen` 使 PASS 失效并回到 EXECUTING，不重置 `started_at`，修复后重新验收。EVOLUTION_REVIEW 后封闭写入，改动须另开任务。
- `EVOLUTION_REVIEW`：外部偶发或无 Cabinet 异常为 CLEAN，不读历史；真实异常须先调用 `evolve.py history <failure_type> <cause>`，再记录或判 PENDING，避免给旧问题再添相似规则。每次只允许一次。
- `FINISHED`：Stop 核开工卡闭环、真实交付路径、进化状态行和 Hook 时间，随后才写入 `finished_at`。Hook 状态不是办公成果或长期记忆。

Codex Hook 只拦截宿主交给它的本地工具事件；官方文档明确说明某些专用调用路径可能不进入该 Hook 通道。因此它提供任务写入门，不冒充操作系统权限隔离。实际门禁必须实测目标 Codex 版本、工具名、Hook trust 和错误时行为。候选 Hook 新增或改变时，必须先由用户信任后才生效。

已激活 session 的状态损坏、无法读取或不兼容时，PreToolUse fail-closed 返回 deny；无 activation 状态的普通任务保持未激活。旧 schema 只会迁移为未启动 `RECEIVED`，必须重新开卡、确认，不恢复旧计时或契约。

## 历史能力与安装记录

[runtime-snapshot.json](runtime-snapshot.json) 与 [installation-manifest.json](installation-manifest.json) 仅记录 2026-08-23/24 当时的能力、路径、安装身份和 smoke 结果。其内部历史 `source_of_truth`、模型、并发、哈希、installed_at 与 smoke_tests 字段只解释当时发生过什么，不是当前 Runtime 状态，也不得覆盖 GitHub 正式维护真源。

当前 Runtime 是否与某 Git commit 一致，只由外部部署状态凭证和实时文件检查判断：部署时由 `scripts/deployment_state.py` 绑定 commit、`VERSION` 与系统摘要，安装核验由 `scripts/check_installation.py` 读取真实入口、受管 Agent、托管规则和部署凭证。历史 snapshot/manifest 不参与当前 PASS/FAIL。

初装或更新不修改模型、并发或权限设置；只有真实验证证明必要且用户授权时再提议。

## 官方依据

- [Build skills](https://learn.chatgpt.com/docs/build-skills)
- [Custom instructions with AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
- [Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)
- [Skills and plugins](https://learn.chatgpt.com/docs/skills-and-plugins)

上述链接为历史记录中的依据入口；涉及当前产品能力时应重新核当前官方信息，不把历史页面状态当永久事实。

## 能力需求与运行时适配

- 父与子仅声明任务类型、风险、材料规模、不确定性、推理与核验需求、时限和质量目标；业务规则、Agent卡和路由不固定模型产品、reasoning枚举或effort档位。
- 调用前根据当前会话工具合同核实可选能力、上下文继承、并发与写权限；仅在当前工具确实支持、当前授权允许且预期有收益时调整。无法调整父模型或推理时沿用会话选择，明确限制，不改全局配置或假报自动降档。
- 独立任务才并行；当前槽位是运行时观测，不写成永久人数配置。完整历史继承、最小上下文等限制以当前可用工具为准。
- 新模型能力是否足以降低推理、代理或检查成本，以同类真实任务的验收证据判断；没有实测只作设计预期，不因换代扩范围或常驻更强档位。
- 模型升级不改变 T1-T10、完成定义、质量 Gate、原稿保护或主架构。

## 当前能力映射

长期角色只定义职责；执行前按需读取 [模型映射](model-mapping.json)，默认继承当前会话，机械工作无需模型。模型/档位调整只改映射，核心策略变化须批准；不要把历史 runtime-snapshot 当当前事实。

Work 负责办公生产；Chat 负责正式维护决策与 GitHub 版本；Codex 收敛为 Mac 本机部署和运行核验。未验证 Work 本机写回通道时，脱敏问题在下次维护摄取，不声称自动同步。

## v1.5.x 执行约定

- 主体继承用户当前模型，子代理也继承；不因速度/额度自行覆写 model 或 effort。模型切换须从当前宿主真实设置核实；没有操作者证据时保持来源待核实。
- 每个已激活的新 Cabinet 任务都先出开工卡，含 T 级、目标、范围／排除项、交付、验收、停止条件、待确认的 `started_at` 和确认方式；T1-T2 不豁免。直接执行授权仍先出卡再开始。
- 文件任务优先遵守用户指定工作目录；未指定时使用最小分区：`00_原稿/`、`work/`、`outputs/`。`outputs/` 或用户指定最终目录只放正式成品和明确附件；审核证据、日志、缓存、测试件、候选和临时转换件留在 `work/` 或受控过程目录。
- 文件任务跨日、补充材料或 Delivered 后继续办理时沿用 Task Card 的稳定 `task_instance_id` 和同一 Task Root；原稿清单登记材料批次，正式版本只递增不覆盖，最终归档先核任务根再核内部目录。具体门禁由 Office Delivery 与 `scripts/delivery_gate.py` 执行。
- 文件任务在收尾前必须核预期成品清单与实际文件、枚举最终目录、确认原稿未覆盖并给完工小结。没有真实成品、目录不干净或缺完工小结时不得 PASS。
- LAB 候选如进入本机运行环境，必须将 `UserPromptSubmit`、`PreToolUse`、`Stop` 一起绑定到同一版本 `scripts/codex_delivery_hook.py`；需完成宿主 trust 与写入阻断实测。当前 Stable 运行配置保持原状，未部署 LAB 时不得说 Hook 正在生效。
- 所有写入须在开工确认后；交付门通过后做一次 Evolution Checkpoint，再形成完工小结。`started_at` 来自确认 Hook，`finished_at` 来自最终门和 Evolution 状态均通过后的 Stop Hook；模型不得自估。首次最终门失败只允许一次定向返工，第二次进入 `TERMINAL_PARTIAL`。
- Work读不到本机运行态时，按同一Skill主动完成收尾核验并保留脱敏待办；不得声称已经运行本机钩子。
- 正式 GitHub 版本或用户明确授权的 LAB 候选需要进入 Mac 运行环境时，按 [Deployment Contract](deployment-contract.md) 执行：锁定 channel/source ref/commit 与源摘要 → 比 Runtime 漂移 → 备份 → 单向部署 → Agent 同步 → 写带 channel/source ref 的外部部署状态凭证 → `check_installation.py --expected-commit --expected-channel` 核验到 SYNCED → 报告。任何一步失败不得声称本机已更新；LAB 不自动晋升 Stable。
