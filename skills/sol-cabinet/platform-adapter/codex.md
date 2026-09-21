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

Hook 的唯一适配规则由本文件定义，`scripts/codex_delivery_hook.py` 只机械实现。Hook 只有在宿主实际加载并信任时才有阻断效力；脚本状态和合成测试不能证明宿主已经启用 Hook。

短期状态只保存在 `/Users/macbook/ChatGPT/system/codex-home/sol-cabinet-runtime/`，使用 schema v2；只记录不透明 session/turn ID、开工模型、生命周期、交付模式、契约路径与哈希、失败次数和时间戳，不记录用户 prompt、附件正文或业务内容。状态不是长期记忆、GitHub 状态、发布证据或 Runtime 部署凭证。

生命周期只有四个 phase：

1. `AWAITING_DECLARATION`：显式 Sol Cabinet 触发后建立；尚未声明 file 或 analysis。
2. `READY`：本轮已通过 `--register` 锁定文件契约，或通过 `--analysis-only` 声明无文件分析。
3. `RETRY_REQUIRED`：首次 Stop 检查失败；只允许一次定向返工，失败次数保持为 1。重新登记契约只能更新本轮契约锁，**不得重置返工预算**。
4. `TERMINAL_PARTIAL`：第二次失败或宿主已处于 stop-hook 重入时进入；停止自动重试，不得靠再次 Stop、重新登记或普通后续消息复活。

`mode=undecided|file|analysis` 与 phase 正交：`AWAITING_DECLARATION` 必须是 undecided，`READY` 必须已经声明 file/analysis。`--register` 和 `--analysis-only` 都必须绑定当前已经存在的显式激活，不能凭 session_id 独立创建任务状态。**同一 activation 内 mode 一经从 undecided 声明为 file 或 analysis 即锁定，禁止 file↔analysis 互换；需要改变交付模式必须再次显式触发 Sol Cabinet，建立新 activation。** 文件契约内容变化后旧 `contract_sha256` 失效，必须重新登记；analysis 模式若回复声称交付文件则 FAIL。

通过 Stop 检查后立即删除本任务短期状态。`TERMINAL_PARTIAL` 后出现普通、未触发 Sol Cabinet 的下一条用户消息时，只清除旧终态并保持 Hook 未激活，避免上一任务污染下一任务；如用户确需重新进入 Hook 治理，必须再次显式触发 Sol Cabinet，建立全新的 `AWAITING_DECLARATION` 和返工预算。无状态 Stop 永远不猜测任务归属、不补造状态。

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

## 历史范围

### v1.3

研究体系、外围专业Skill、公共检查与维护证据已收口，旧配置索引改为真源导航；保留用户全局模型、推理档位、权限、插件选择及Agent运行副本。历史快照和smoke记录不冒充新验证，本轮部署依据任务内变更与验收记录。该阶段未执行实战A/B与最终全体系验证。

### v1.4

1.4蒸馏阶段曾按用户要求延期测试；该阶段仅做文件身份、版本衔接与静态处置审阅。此为历史边界，不限制当前用户授权的1.5.x定向修复验证。

installation-manifest中的installed_at与smoke_tests仍是历史安装记录，不是当前版本的自动验证结果；更新版本身份不修改普通任务的验证门禁，也不授权后台补测。

## 当前能力映射

长期角色只定义职责；执行前按需读取 [模型映射](model-mapping.json)，默认继承当前会话，机械工作无需模型。模型/档位调整只改映射，核心策略变化须批准；不要把历史 runtime-snapshot 当当前事实。

Work 负责办公生产；Chat 负责正式维护决策与 GitHub 版本；Codex 收敛为 Mac 本机部署和运行核验。未验证 Work 本机写回通道时，脱敏问题在下次维护摄取，不声称自动同步。

## v1.5.x 执行约定

- 主体继承用户当前模型，子代理也继承；不因速度/额度自行覆写 model 或 effort。模型切换须从当前宿主真实设置核实；没有操作者证据时保持来源待核实。
- 非瞬时任务开工先给简短小结：T级、目标、预期交付物、目标文件夹／位置、关键约束和停止条件。**不要求也不编造未来耗时承诺。**
- 文件任务优先遵守用户指定工作目录；未指定时使用最小分区：`00_原稿/`、`work/`、`outputs/`。`outputs/` 或用户指定最终目录只放正式成品和明确附件；审核证据、日志、缓存、测试件、候选和临时转换件留在 `work/` 或受控过程目录。
- 文件任务在收尾前必须核预期成品清单与实际文件、枚举最终目录、确认原稿未覆盖并给完工小结。没有真实成品、目录不干净或缺完工小结时不得 PASS。
- 本机 hooks.json 只登记受任务范围约束的事件，调用正式部署版本的 `scripts/codex_delivery_hook.py`。钩子仅按上方 Hook 状态治理保存短期状态，不记录用户正文，不联网、不换型。只有经过宿主原生信任后才实际执行；未信任、宿主未加载或非本机环境，不称已自动强制。
- 文件任务在本轮显式激活后注册 delivery-contract；无文件分析在本轮显式激活后声明 analysis-only。首次失败只允许一次定向返工，重新登记不重置预算；再次失败进入 `TERMINAL_PARTIAL` 并停止自动重试，不以循环耗额度换“通过”。该检查验证真实文件和记录一致性，不认证模型说法或替代内容审查。
- Work读不到本机运行态时，按同一Skill主动完成收尾核验并保留脱敏待办；不得声称已经运行本机钩子。
- 正式 GitHub 版本或用户明确授权的 LAB 候选需要进入 Mac 运行环境时，按 [Deployment Contract](deployment-contract.md) 执行：锁定 channel/source ref/commit 与源摘要 → 比 Runtime 漂移 → 备份 → 单向部署 → Agent 同步 → 写带 channel/source ref 的外部部署状态凭证 → `check_installation.py --expected-commit --expected-channel` 核验到 SYNCED → 报告。任何一步失败不得声称本机已更新；LAB 不自动晋升 Stable。
