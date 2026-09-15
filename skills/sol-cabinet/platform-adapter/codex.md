# Platform Adapter：Codex CLI / Desktop

历史平台依据日期：2026-08-23。v1.2阶段仅核实本机入口与核心契约；以下历史产品信息不是当前宿主功能保证。漂移时查当前工具或官方依据，不把版本快照写入 Core。

## 单一真源

```text
/Users/macbook/ChatGPT/lineage/codex-root/配置库/04_skill索引/sol-cabinet
```

个人 Skill 入口：

```text
/Users/macbook/.codex/skills/sol-cabinet -> 单一真源（物理位于 ChatGPT/lineage）
```

Codex 官方当前把个人 Skills 放在 `$HOME/.agents/skills`，并支持 Skill 文件夹符号链接。本机只保留 `.codex/skills/sol-cabinet` 一个发现入口；`.agents/skills` 同名重复入口移除。入口是符号链接，不另造维护副本。

自定义 Agent 真源与运行副本：

```text
真源/platform-adapter/codex-agents/sol-*.toml
  -- scripts/sync_agent_runtime.py -->
/Users/macbook/.codex/agents/sol-*.toml（兼容入口；物理位于 ChatGPT/system/codex-home）
```

官方明确个人 Agent 目录为 `~/.codex/agents/`。本机 Codex CLI 0.149.0 的实际发现测试未识别 TOML 符号链接，因此使用受管、逐字节一致的运行副本；只编辑真源，安装或升级后执行 `scripts/sync_agent_runtime.py --install`，验收执行 `--check`。这不是第二套维护版本。

同步器使用独占锁、单文件原子替换、目录 fsync、受控中断回滚和终态哈希检查。操作系统级 `SIGKILL` 仍可能留下可检测的混合代际；此时 `--check` 必须 FAIL，重新运行 `--install` 恢复，不得继续使用旧 PASS。

角色说明见 [Agent Roster](codex-agents/roster.md)。

## AGENTS.md 层级

Codex 先读 `~/.codex/AGENTS.md`，再按项目根到当前目录叠加更具体规则。`/Users/macbook/AGENTS.md` 属于 Grok workspace，因此 Codex 日常会话的 CWD 固定为 `/Users/macbook/ChatGPT`，由更深层 `ChatGPT/AGENTS.md` 明确覆盖产品边界；任务文件使用绝对路径写入 `ChatGPT/workspace`。不要修改或删除 Grok 规则。

最小托管段见 [AGENTS managed block](AGENTS.managed-block.md)。它负责轻量 T0、覆盖 T1-T10 的源文件归档硬门禁和加载 `$sol-cabinet`；完整规则仍在 Skill 真源。之所以把 Archive Gate 放在托管段，是因为 T1-T2 可以不加载完整 Skill，但不能跳过原稿保护。

## 多 Agent

- 主 Agent 负责 spawn、等待、冲突合并和 Final Lead；子 Agent 默认不再 spawn。
- 物理并发受当前会话槽位限制；逻辑角色按波执行。
- 子 Agent 与主 Agent 共享文件系统，写入必须隔离。
- 审核角色配置 `sandbox_mode = "read-only"`，但会话实时权限仍可能覆盖配置；提示词必须再次明确只读。

## 敏感会话与 Memory

T0 命中真实人名加具体案件或 `secret-bearing` 时，除禁止联网和 Evolution Log 外，还要关闭或确认当前聊天不贡献未来 Memory。若当前界面/工具无法程序化确认，先给保密提示，明确仅在当前任务范围处理，并停止任何持久化步骤。全局关闭 `generate_memories` 属于用户配置变更，必须另行授权，不得静默修改。

`sandbox_mode=read-only` 只约束文件写入，不是网络、MCP 或连接器的技术隔离。敏感 `TASK_CARD` 必须显式写 `external_access/network/connectors/persistent_context=deny`，并在每个 Agent 任务中重复。若宿主不能保证该工具边界，secret-bearing 任务进入 `BLOCKED` 或先去标识，不能仅凭提示词宣称隔离。

## 当前能力快照

见 [runtime-snapshot.json](runtime-snapshot.json) 与 [installation-manifest.json](installation-manifest.json)。初装不修改 `config.toml` 的模型、并发或权限设置；只有真实验证证明必要且用户授权时再提议。

## 官方依据

- [Build skills](https://learn.chatgpt.com/docs/build-skills)
- [Custom instructions with AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
- [Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)
- [Skills and plugins](https://learn.chatgpt.com/docs/skills-and-plugins)

## 能力需求与运行时适配

- 父与子仅声明任务类型、风险、材料规模、不确定性、推理与核验需求、时限和质量目标；业务规则、Agent卡和路由不固定模型产品、reasoning枚举或effort档位。
- 调用前根据当前会话工具合同核实可选能力、上下文继承、并发与写权限；仅在当前工具确实支持、当前授权允许且预期有收益时调整。无法调整父模型或推理时沿用会话选择，明确限制，不改全局配置或假报自动降档。
- 独立任务才并行；当前槽位是运行时观测，不写成永久人数配置。完整历史继承、最小上下文等限制以当前可用工具为准。
- 新模型能力是否足以降低推理、代理或检查成本，以同类真实任务的验收证据判断；没有实测只作设计预期，不因换代扩范围或常驻更强档位。
- v1.2阶段未修改全局model/effort、Agent TOML与其运行副本、Sol Research或跨Chat／Work接口；v1.3的当前范围见下节。

## v1.3历史范围

研究体系、外围专业Skill、公共检查与维护证据已收口，旧配置索引改为真源导航；保留用户全局模型、推理档位、权限、插件选择及Agent运行副本。历史快照和smoke记录不冒充新验证，本轮部署依据任务内变更与验收记录。该阶段未执行实战A/B与最终全体系验证。

## v1.4历史状态

1.4蒸馏阶段曾按用户要求延期测试；该阶段仅做文件身份、版本衔接与静态处置审阅。此为历史边界，不限制当前用户授权的1.5定向修复验证。

installation-manifest中的installed_at与smoke_tests仍是历史安装记录，不是1.4测试结果；当前完成／延期边界以[最终处置状态](../source-index/distillation-status.json)为准。更新版本身份不修改普通任务的验证门禁，也不授权后台补测。

## 当前能力映射

长期角色只定义职责；执行前按需读取 [模型映射](model-mapping.json)，默认继承当前会话，机械工作无需模型。模型/档位调整只改映射，核心策略变化须批准；不要把历史 runtime-snapshot 当当前事实。Work 负责办公生产，Codex 负责维护。未验证 Work 本机写回通道时，脱敏问题在下次维护摄取，不声称自动同步。

## v1.5 本机执行约定

- 主体继承用户当前模型，子代理也继承；不因速度/额度自行覆写model或effort。模型切换须从会话turn_context/settings记录核实，记录没有操作者就保持来源待核实。
- 普通办公在workspace，后台维护在system/maintenance；各用日期主题任务夹。若宿主明确固定当前cwd和outputs，优先遵从上级路径，仍执行规范文件名及最小留存；不为了同时满足两套路径而复制整套文件或制造多组链接。已完成归档才声称已归档，受宿主限制写明延后。
- 本机 hooks.json 只登记 UserPromptSubmit/Stop 两个受任务范围约束的事件，调用本真源 scripts/codex_delivery_hook.py。钩子只保留不透明会话ID、模型及本任务契约指针等短期运行态，不记录用户正文，不联网、不换型。只有经过Codex原生信任后才实际执行。未信任、宿主未加载或非本机Work环境，不称已自动强制。
- 文件任务注册delivery-contract；无文件分析显式analysis-only。失败只要求一次定向返工，仍失败则PARTIAL并停止自动重试；不以循环耗额度换“通过”。该检查验证真实文件和记录一致性，不认证模型说法或替代内容审查。
- Work读不到本机运行态时，按同一Skill主动完成收尾核验并保留脱敏待办；不得声称已经运行本机钩子。
