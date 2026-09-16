# Agent Orchestrator

主 Agent 是唯一编排者与 Final Lead。角色库见 [Roster](../platform-adapter/codex-agents/roster.md)，不在各领域组件重复组队。

## 父代理与子代理

父代理锁定范围、识别依赖、分配最小上下文、裁决冲突、发起定向返工并验收交付。不能为展示能力扩大研究、章节或团队。

子代理任务必须窄、目标清：给出职责、读集、输出、写权限、验收与停止条件。默认只读返回，禁止再分叉或自行生成正式文件。确需生成器写入时实行 **one writer per artifact/path**：同一最终文件或同一路径只能有一个明确授权写者；不同且输出路径隔离的最终成品，在共同事实基线稳定、彼此无写依赖且平台可承载时，可以各有一个授权写者同波生成。每个写者使用独立 scratch／临时文件，不共享可变中间件；最终由 Final Lead join、核哈希和对账。所有代理共享文件系统，不能假定彼此隔离。

## 动态编排

1. 先把当前范围画成最小 dependency DAG。每个候选子任务标明 `depends_on`、是否 `join_required`、是否 `single_writer`、是否 `review_required`；没有依赖且输入已经可用的任务进入当前 ready-set。既有源文件必须先通过原稿归档门禁；门禁一通过就建立一次 source manifest，为每个来源分配稳定 `source_id`、类型、fingerprint/hash、locator 体系与预期 coverage，不等“先串行读完一份再决定怎么拆”。
2. 每个候选子任务必须有不可折叠的差异：独立读集、输出、证据来源或判断权；能合并的工序不拆成多人。来源解析优先单次读取并结构化，结果写入当前任务 `evidence_pack` 或等价证据包，至少保留来源指纹／hash、coverage、事实 locator、conflicts 与 unverified。其他角色复用该证据包；关键疑点和独立审核可按 locator 定向回源，不把整份大材料反复塞给所有 Agent，也不把全文复制进交接结果。
3. 同一 ready-set 中有两个及以上独立工作单元，且并行收益明确为正时，在当前平台可承载范围内同波启动；不得因为实现方便把本可同时进行的 `A + B + C` 无依据改成 `A → B → C`。物理并发不足时只分成必要的最少波次，不改变逻辑依赖。结果回流按依赖事件处理：某单元一完成就立即校验其 fingerprint、coverage、状态与未核项，并释放只依赖它的后继；不得为了“等齐一波”阻塞与慢单元无依赖关系的后继。只有确实依赖整组结果的节点才等待完整 join。
4. 有依赖先满足依赖。材料提取可并行，依赖事实与结构的起草不得抢跑；不同对象可分开处理，禁止换名套稿。多个独立来源先并行读取／提取／核验，再进入统一冲突裁决；多个交付物只有在共同事实基线稳定后才可并行生产。并行写入只允许互不重叠的 artifact/path；同一 artifact 的生成、修订和最终落盘保持串行单写者。
5. Join 是提交前硬边界：并行单元完成后先汇总来源指纹、版本、coverage、hash、冲突和未核项，再进入真正依赖它们的起草、审核或 Delivery Gate。Join 只合并结果与冲突，不默认让 Final Lead 重新全文读取所有已经被可信结果覆盖且字节未变化的来源；只有冲突、关键高风险事实、覆盖缺口或 source fingerprint 变化才定向回源。Reviewer 必须针对当前 immutable candidate；最终提交仍由单一 Final Lead 收口。
6. 每波只启动当前平台可承载的就绪任务。Agent 总数按实际工作与收益决定；没有按 T 级、模型代际固定的执行人数或最低满槽要求。准备大规模调用前判断新增证据或时间收益是否抵得过协调、上下文和调用成本；额度未知不查询或编造。
7. 优先缩减重复读取与非必要代理。已有可信 evidence 时直接复用；同一来源 fingerprint、hash、Office inspection 或机械检查没有输入变化时不重复运行。若同一未变化来源发生第二次全文读取，执行者必须能指向遗漏、冲突、独立复核或 source change 等具体原因；否则记为 `duplicate_read` 并在下一波消除。不能用“减少工具调用”为由跳过用户要求的事实核验、必要审核或实体文件检查。
8. 主代理与子代理都描述能力需求，不固定模型或 effort；可调范围与继承限制由 [平台适配](../platform-adapter/codex.md) 核实。不具备动态切换能力时明确限制，不偷偷更改全局配置。
9. 独立审核保留必要判断路径，角色可复用，但同一最终写者不能为自己提供独立通过。风险强度决定审核要求，不要求每个检查维度单独创建一个新实例。多个互不依赖的审核维度针对同一 immutable candidate 时可并行，最终由主代理统一裁决。

并行治理浓缩为：**Parallelize independent work. Serialize dependencies. Join before commitment.** 目标不是更多 Agent，而是更短的可靠 Critical Path。

## 材料提取 Critical Path

材料提取是事实底座，优化目标是缩短 **archive PASS → first extraction dispatch → evidence coverage ready**，不以少读、猜读或牺牲定位精度换速度。

仓库运行时对已归档的本地 `.txt/.md/.docx/.xlsx` 提供一个可执行的机械基线：`scripts/source_ingestion.py`。它读取 `00_原稿/原稿清单.json`，复核 archived hash 与原稿保护标记，将独立来源同波提交到 extraction ready-set，DOCX/XLSX 复用 `inspect_office.py`，最后由同一生产函数 join 为带 source fingerprint、locator、coverage、conflicts 与 unread 的 `evidence_pack`。T10 与回归测试必须调用这个生产入口，不得在测试文件里复制一套平行 extractor/joiner。脚本不支持的格式保持 `unread`，再由当前平台真正支持的原生读取路径补齐；不得猜读或把 archive-only 当内容 coverage。

1. **先建 manifest，再派工**：归档门禁通过后立即建立 source manifest；每个 source 必须有 `source_id + fingerprint/hash + source_type + locator_scheme + expected_coverage`。派工前就确定 coverage 边界，避免多个 Agent 重复读同一块、又遗漏另一块。
2. **默认按来源并发，不盲拆单文件**：多文件任务优先“一来源一 extraction unit”或按真实独立对象分配。单个超大文件只有在一次低成本结构索引后能够按稳定 locator 做随机／分段读取时，才继续拆页段、工作表、表块或章节；如果每个子任务仍会把整份文件重新解码一遍，就保持单次解析，禁止用重复全文读取伪造并行收益。
3. **格式感知但共用证据合同**：纯文本／Word 记录段落、表格、页眉页脚、文本框等实际 coverage；Excel 先识别 workbook/sheet 结构，再按独立 sheet/range 分工，公式、合并区、状态与未核项不能在 join 时丢失；PDF 先确认页数／页索引与可读类型，平台支持稳定分页读取时才按 page range 并行，扫描／图像页只能走当前平台支持的视觉读取并明确 coverage，无法可靠读取的页必须进入 `unverified/unread`，不得根据邻页猜正文。
4. **结果一到即回流**：每个 extraction unit 完成后立刻返回 Agent Result；父代理先核 source fingerprint 与 coverage，再把可信 facts/locators/conflicts 合入 evidence_pack。只依赖已完成来源的下游可以被释放；需要全量材料的综合判断必须等 coverage join 完整。
5. **Coverage join 优先于全文复读**：join 检查期望 coverage 是否有缺口、重复、交叉矛盾和 locator 冲突。相同 `source_id + fingerprint + locator` 的重复结果只保留一份并比对冲突，不因多个 Agent 得到同一句话就增加事实权重。
6. **观测尾延迟**：有可靠计时时记录 `source_dispatch_delay`、`source_extraction_tail`、`evidence_join_delay`、`duplicate_reads` 与 `maximum_parallel_width`。重点看最慢 extraction unit 和 join 等待，而不是平均单文件耗时。

## 审阅 Critical Path

审阅优化目标是缩短 **candidate immutable → reviewer dispatch → last required review result → review join**，审核强度和独立性不降级。

1. **候选冻结前准备 reviewer ready-set**：在最终成品接近稳定时，主代理可以提前确定审核对象、review scope、必要 evidence-pack slice、独立性要求、验收字段和返工定位，但不得提前给未冻结候选 verdict，也不为“预热”无收益地占用并发槽。
2. **冻结即同波派工**：一旦当前候选 hash/manifest 可用，在同一次调度决策里启动所有已就绪且可独立执行的 reviewer；不得采用“创建 reviewer A → 等 A 完成 → 再创建 reviewer B”的无依赖串行链。单成品或强耦合审核仍按原路径。
3. **审核按 scope 绑定版本**：full review 绑定整套当前 candidate hash map；artifact-scoped review 只绑定自己声明的 `artifact_ids` 与对应当前 hash；多成品 scoped 模式还必须有一次 full／cross-artifact consistency review 绑定整套当前 candidate。三种 scope 在 Task Card 存在 `source_archive`／`evidence_pack` 时还统一绑定 `evidence_baseline_sha256`，共享事实 baseline 变化即失效。Delivery Gate 按每个必交 artifact 分别核最低 reviewer 覆盖强度，不能因为切 scope 少审对象。
4. **完工反馈事件化**：Reviewer 一完成就立即返回结构化 PASS／FAIL／BLOCKED、`issue_id × object_id`、证据 locator、must-fix 和未核项；Final Lead 不等待无关 reviewer 才读取已完成结果。只有最终裁决或确有跨对象依赖时才等待 required review join。
5. **定向失效，不全套重审**：某个 artifact 发生实质变更时，只使覆盖该 artifact 的 scoped review 与 full／cross-artifact consistency review 失效；其他 artifact 字节、hash 与依赖事实均未变化时，其已通过 scoped review 可以保留。共享事实基线改变时，依赖该事实的全部 scope 仍须失效重审，不能以文件 hash 未变掩盖事实依赖变化。当前 gate 采用共享 baseline 的保守失效策略，后续只有在显式、可验证的 dependency slice 合同存在时才允许更细粒度复用。
6. **观测审核尾延迟**：有可靠计时时记录 `review_dispatch_delay`、`review_tail`、`review_join_delay`、`reused_unaffected_reviews` 和 `invalidated_review_scopes`。最慢 required reviewer 是重点；不把“创建更多 reviewer”本身当性能改善。

## 交接与返工

子结果按 [Agent Result](../templates/agent-result.json) 给出对象、覆盖范围、证据定位、发现及未核项。对文件候选附其哈希；不能用“读取成功”“ID齐全”代替内容判断。交接优先传结构化 findings、locators、coverage、conflicts 与 unverified，不传已经存在于原始材料中的整段全文；需要复核时由接收方按 locator 读取最小必要片段。

Agent Result 中的 `dispatch` 只在宿主存在可靠时间源时填写 `ready_at / started_at / completed_at / timing_basis`；无可靠时间就保持 null，不编造时间。子代理完成后应直接回传结果，不再增加“已完成、请再查询”之类二次确认链。父代理接到结果即更新 dependency state，并在依赖满足时释放后继。

事实冲突按来源权威性、时点、原始性与可核验性裁决，不按人数投票。只重做受影响的 `issue_id × object_id`；事实或结构变更后，仅使依赖它的语言候选和审核失效。

记录实际创建的 Agent ID、职责、输出与验收，不把逻辑任务数当实际人数。持续无新证据的任务先缩小读集与目标，再有界重试；无进展停止并说明，不无限等待。

## 写入与停止

每个并行写者的受控 scratch 放在当前任务夹内独立子路径，只由该写者负责；清理仅限本次登记文件。最终结果按清单与哈希收集，不能通配覆盖、移动或删除输入。

阶段验收通过后交付并停止，子代理也须结束。不因空闲槽位、已加载上下文或已知下一步继续执行。长期运行必须另有明确授权，见 [Durable Operations](durable-operations.md)。
