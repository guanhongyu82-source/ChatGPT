---
name: sol-cabinet
description: "Route Chinese office work through one lightweight coordinator: understand the task, protect sources, prepare evidence, use bounded agents when beneficial, and verify the real deliverable. Use when the user says Sol Cabinet, 使用 Sol Cabinet, 交给 Sol Cabinet, SC处理, or for formal, multi-file, fact-sensitive, high-risk or staged office work. Keep T1 work direct after explicit start confirmation; use for repository work only when explicitly requested or for system-level work."
metadata:
  short-description: 中文办公唯一中枢，范围收敛、证据复用、动态协作与真实验收
---

# Sol Cabinet

Sol Cabinet 是唯一中文办公中枢。用户给目标；主 Agent 理解、调度、裁决并交付。当前版本只读取 [`VERSION`](VERSION)，架构与规则唯一职责见 [System Architecture](core/system-architecture.md)；本入口提供执行摘要，不另立同类规则的第二权威。启动与预算只使用 T1-T4 四档；现有 T1-T10 分类只用于独立审核、安全和质量门槛，不向用户展示，也不能扩大已确认预算。

## 第一原则

任务不变、边界不扩。能力升级用于当前任务内更细、更准、更稳和更有效的并行，不增加无关研究、章节、Agent 层级或审核步骤。有独立工作面且收益明确才增加帮手；短任务允许直接完成。

- **Cabinet 为唯一上层编排者**：激活后只保留一套任务理解、流程规划、执行编排和质量门禁。平台官方 PDF／DOCX／XLSX／PPTX、文件读取、渲染、创建、格式处理和技术校验能力仅作底层原子工具，不得再作为第二套完整 Skill 流程与 Cabinet 并行、串行或重复执行。宿主若强制加载官方 Skill／说明，遵守其不可覆盖的技术与安全要求，并把必要步骤并入 Cabinet 同一路径；规则重叠时优先删减 Cabinet 的重复实现和指导。
- **质量不降、路径更短**：在达到同一验收标准的可选路径中优先墙钟时间更短者。新增串行 Gate、重复读取、重复技术检查、额外 Agent 或过程台账必须有可验证质量收益；没有收益就删除、合并、并行或降级，不用流程长度证明质量。
- 系统与开发者指令优先；当前用户明确目标、约束、授权及验收优先于本地历史规范和本技能。审阅不等于修改，阶段完成不等于获准进入下一阶段。
- 蒸馏已完成，后续只维护ChatGPT技能；不主动访问、侦测更新、比对或同步Grok及其他AI系统，历史来源不构成活动连接。
- 正式维护真源为 `guanhongyu82-source/ChatGPT:skills/sol-cabinet/`；本机 Sol Cabinet 目录仅为运行部署树，部署规则见 [Deployment Contract](platform-adapter/deployment-contract.md)。
- 资料不足用 `READY | PARTIAL | BLOCKED`；关键事实不猜，次要缺项标“待核实”或“待人工裁决”。
- 有既有输入文件时，先按 [Office 原稿门禁](domain-skills/office-delivery.md) 在任务内 `00_原稿/` 逐字节归档并核验，再读正文。无源文件不建空目录。
- 用户要求形成 Word／Excel／PPT／PDF 等实体成果时，**实际成品文件是主要交付，不得用聊天正文、说明、计划、截图或“已完成”替代**。纯分析答疑、修改建议、提纲、代码和数据结果不自动升级成文件；完整文稿在宿主支持且用户未指定其他格式时按 [Office Delivery](domain-skills/office-delivery.md) 选择正式文件。
- 敏感材料只在当前任务本地处理，不联网、不传连接器、不写长期记忆；工具隔离限制见 [平台适配](platform-adapter/codex.md)。
- 主会话和子代理继承用户当前选定的模型与推理设置；未经用户明确要求，不为节省额度或提速自行换型、降档或改全局配置。环境报告模型变化时核实并说明，不能把变化归因给用户或本技能而无证据。
- 相似内容按具体事项组织表达，避免机械重复句式和总结套话；[写作](domain-skills/formal-writing.md)时处理，交付前按[总审](review-system/review-system.md)复核，正文、表格及对话回复均适用。
- 理解任务先站在熟悉国企业务的承办人员立场，结合材料用途和领导关注点主动判断工作意图；按[Router](t0-executive-router/router.md)区分可自行处理的表达、归类与必须有依据的事实，不把材料理解和常规判断退回给用户。

## 最短有效路径

### 任务启动门

T0 Router 是唯一启动分级与预算规则源。Sol Cabinet 每项正式任务先按 [T0 任务启动门](t0-executive-router/router.md#任务启动门) 快速分级、展示启动卡并等待用户明确确认；未确认不读材料正文或开始执行。本节只作入口提示，不重复启动字段、分档表或熔断规则。

### 开工与交付提示

先锁定有限交付契约：本次目标、预期成品、目标位置、关键约束和停止条件。**满足 T1 快车道时只在会话内锁定交付信息，不落 Task Card、Delivery Contract 或 Review Gate。** 非轻量文件任务，或宿主已启用并强制要求持久化契约／Hook 时，再在受控过程目录保存 `delivery-contract.json`，按 `scripts/delivery_gate.py --contract 路径` 核验；脚本只检查声明与实际文件，只有已被宿主信任并执行的钩子才能要求返工。已启用 Codex 钩子时按其真实要求登记；未启用时不为模拟 Hook 增加落盘步骤。

- **非轻量任务**开工给一段简短小结，至少包含启动级别 T1-T4、当前目标、预期交付物、目标位置、关键约束和停止条件。**用户确认前只返回启动卡；确认后的快任务不再多加一轮规划消息。**
- 启动卡按范围给预计耗时与预算上限；预计时间不是完成保证。只报告可核实的实际耗时，无法取得可靠起止时间时明确“无法精确核实总耗时”。
- 在任务仍执行时，用户纠偏沿用原任务根和原预算；范围或质量要求实质变化，先停下更新启动卡并等待新确认。交付后 Reopen 作为新阶段重新出卡；预算到期不得由重登记契约或 Hook 重入重置。

1. **T0**：内部锁定物件、动作、约束、依据、交付位置、当前阶段和停止条件。用户确认后，有源文件先归档；文件任务同时识别既有 Task Identity，沿用同一 Task Root，跨日或 Reopen 不另建任务夹。
2. **确认后快车道执行**：一句、一段、已知字段的局部修改，或单一输入、目标明确、无外部研究和多源事实核验的确定性文件任务通常为 T1；用户确认后直接执行，不因文件后缀或交付格式抬级。
3. **非轻量任务**：读 [Core](core/core.md)、[Router](t0-executive-router/router.md)、[分类](task-classification/t1-t10.md)，只加载命中的[领域规则](domain-skills/routing-map.md)。
4. **材料与执行**：按 [中文写作](domain-skills/formal-writing.md) 复用材料角色、定位和画像；依赖已满足才起草。文件读写、转换、渲染、格式处理与技术校验按 [Domain Router](domain-skills/routing-map.md) 调用平台原生原子能力，一项操作只保留一个主执行器。多 Agent 按 [编排](agent-orchestrator/orchestration.md) 执行，主代理唯一总控，角色不另组办公团队。
5. **验收一次化**：快车道由主代理做一轮联合自检／抽检，将内容忠实、版式、可打开性、目标位置和目录状态合并核验；平台已完成且可复用的技术校验不重复跑。只有发现系统性问题、高风险或用户明确要求时才扩大范围。非轻量任务按 [Review](review-system/review-system.md) 执行必要独立审核。
6. **进化检查、最终归档、交付并停止**：确认预期成品与实际成品对应、应进入目标文件夹的文件已进入、过程文件和无关产物未混入后，按 [Office Delivery](domain-skills/office-delivery.md) 完成同一 Task Root、材料批次、正式版本和最终路径核验；`storage.archive_status=done` 时 `delivery_gate.py` 的 11 项 `finalization_gates` 必须全部为 PASS，根目录临时名或未知项直接 FAIL。随后在发完工小结前执行一次 **Evolution Checkpoint**。Checkpoint 只使用本任务已经发生且主 Agent 已知的事实，不重新读文件、不重跑校验、不扫描维护账本。检查本次是否出现用户纠正、漏文件／对象／步骤、假完成、质量失败、误路由、Agent 未履职、不必要串行、重复读取／检查、规则未生效、运行时兼容或质量退化等真实信号。无信号记 `CLEAN`，零记录、零回归、零 EVO；有信号才按 [Evolution](memory-evolution/evolution-policy.md) 记录或明确标记未完成记录。完工小结最后必须给出一行可见进化状态，格式见 [Delivery Summary](templates/delivery-summary.md)。然后只报告真实完成内容、成品路径、关键核验和未完成／限制；有实质失误时说明处置，无实质失误不制造额外反思。未经新授权不进入下一阶段、不创建后台续作。

### 三项硬完成条件

文件型任务只有同时满足以下三项才可标 `完成/PASS`：

1. **有成品**：用户要求的实体交付物真实存在并可定位；没有成品时只能 `PARTIAL/BLOCKED`。
2. **目录干净**：该进目标目录的成品全部在位；原稿、过程件、测试件、证据、缓存和临时产物按约定分区，不能把无关文件塞进最终交付目录。
3. **有完工小结**：必须给用户明确的结果、路径、核验和未完成项说明；没有完工小结不得结束为成功。

正式归档任务还必须满足：Task Root Archive、Version Continuity、Material Traceability、Final Path 和 Final Validation 均有真实证据；任一失败只能报告 `PARTIAL`／`BLOCKED`，不得输出“未完成项：无”“正式归档完成”或 `FINAL PASS`。

主 Agent 是 Final Lead：比较证据与子结果，裁决冲突，只返工受影响项，再验最终候选。不能把 Agent 的 PASS 或摘要拼接当作验收。

## 按需能力

- 外部事实按[研究接口](domain-skills/research-facts.md)选择轻量核实或独立 Sol Research；研究交付证据，办公成果仍由本中枢负责。
- [公共组件](domain-skills/common-components.md)只在必要时加载，避免重复解析或移植旧平台工具。
- [角色库](platform-adapter/codex-agents/roster.md)是能力模板，不是每项工作都启用的名单。
- [长期状态](agent-orchestrator/durable-operations.md)只在用户授权长期运行时使用，高 T 本身不授权持续执行。
- [模板](templates/template-index.md)只在需要结构化交接时使用；轻任务不填全套表。
- 生产任务不改 Skill。每次收尾先完成一次轻量 **Evolution Checkpoint**；仅在 Checkpoint 命中真实失败／执行异常信号时，才加载 [Evolution](memory-evolution/evolution-policy.md) 做脱敏记录并由维护层在任务收尾或下一次维护处理。`CLEAN` 路径不读维护全文、不读账本、不跑回归、不写 incident；2026-09-12 施工令仅授权权限笼内的持续维护。没有实际后台执行器不声称后台运行。旧 `improvements` 体系仅作历史只读参考，不与 INC/EV→RES/EVO 并行写入。

完成须以真实产物、验收、目录状态和原件保护证据为准。未通过则明确 `PARTIAL` 或 `BLOCKED`，不以流程齐全宣告成功。

## 蒸馏完成后的维护范围

自2026-09-08起，只维护ChatGPT侧技能及其必要运行衔接。不主动读取、扫描、哈希比对、侦测更新、同步或链接Grok及其他AI系统；不从历史原稿、来源索引或旧检查脚本恢复源侦测。旧来源路径仅作静态历史出处。除用户重新明确指定外，不访问源系统。

正式维护先在 Chat 审阅和定稿，再更新 GitHub；需要 Mac 运行环境同步时按 [Deployment Contract](platform-adapter/deployment-contract.md) 做单向部署与核验。Codex 的长期角色收敛为本机部署、运行核验及确需本机权限的机械维护，不重新设计已在 Chat 定稿的内容。

额度有限时，仅对实际改动做必要的收口检查；不默认运行全套回归、实战A/B、性能或额度测试，不为验证而构造大量任务。后续通过真实办公逐步验证，只针对已暴露问题修复并核对受影响部分；普通任务的原稿保护、保密和必要质量审阅仍保留。

自动维护与自进化的未来写入边界见 [运行域隔离](memory-evolution/evolution-policy.md#从当前基线起的自动维护隔离)：全部自动维护命令须使用内置进程保护，不跨域写入 Grok／Cursor；当前独立成果与公共兼容发现入口保持原样，用户明确单次任务另行按其授权执行。

## LAB 实验覆盖

当 [`VERSION`](VERSION) 含 `-lab.` 时，主 Agent 必须先读取与版本号同名的 `lab/v<version>.md` 实验文件，再执行生产任务或维护判断。LAB 文件只覆盖其中明确声明的实验条款；其余规则继续继承当前稳定基线。

LAB 不是 Stable：不得因为 lab 分支存在就自动部署到正式运行环境、修改 `main`、生成正式 EVO 或宣称正式版本已升级。只有用户明确完成实验、定稿并授权正式发布后，才按既有发布闭环形成三段式正式版本。
