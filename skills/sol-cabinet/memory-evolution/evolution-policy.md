# 守边界进化：生产观察，维护晋升

本机制复用原 observation、improvements、candidate evidence、snapshot 和独立审核，不新增办公入口或团队。2026-09-12 用户施工令授权后续按本权限笼记录脱敏事故及低风险维护；不授权用户长期记忆写入、敏感正文持久化、外部发布或冻结层变更。

## 冻结与权限

[权限笼](permission-cage.json) 是冻结层。最高遵循：任务不变、边界不扩；能力升级、帮手增加；并行增强、速度提升；范围收敛、颗粒度加深；减少发散、提高精度与质量。质量不得为速度下降。速度来自有效并行、调度、路由、减少空转和能力提升。

- A 冻结层与 D 否决层：进化无权改写、弱化、绕过或换名重引。涉及这些内容停止晋升，另形成用户裁决方案；当前自动权限永远不能用于改自己的权限笼。
- B 自动层：仅白名单低风险路径且双独立审核确认冻结项零影响。白名单不是整文件任意修改授权；语义触及核心即升级或拒绝。非核心表达、兼容、路由、上下文挂载、无职责变化的并行、消除重复与修执行链可自动完成观察、分析、候选、回归和审核准备，但最高只到 `CANDIDATE READY`。`auto_paths` 只表示候选风险分层，不产生 Stable 写入权。
- C 用户裁决层：任何 `candidate → stable` 都必须有当前用户明确的发布/定稿授权。授权必须绑定当前 candidate hash、base hash、changes hash 和用途，并记录 `release_intent=finalize-stable`；“看看 / 优化一下 / 建议一下 / 先改改看 / 先出一版”等模糊表达不得生成发布授权。候选任一字节变化后，旧授权失效，必须重新确认。
- 自保护文件只允许独立的用户直接维护施工，不进入自我进化自动通道。
- 本地脚本是机械门禁，不是操作系统权限隔离；同一用户可改文件，哈希不能认证人或模型身份。维护执行者必须核对真实用户消息和真实独立工具输出，禁止自填通过。

## 生产收尾：无事故零写入

生产 Agent 仅执行办公、解决当前返工、发现并提供证据，不改 Skill。使用现有交付/总审时顺带观察：用户纠正、漏文件/对象/步骤、假完成、质量失败、误路由、多文件遗漏、角色未执行、不必要串行、重复读取检查、规则未生效、兼容与质量退化。普通审美、措辞偏好、正常润色不当事故。

无真实问题：停止，不写账本，不读维护全文，不跑回归，不生成 EVO。生产事故按现有独立 task/evidence 去重口径分级触发：普通首次问题只记录，不启动 Skill 优化；同类问题达到两个独立任务时，触发维护分析并建立最小维护计划；高影响问题首次出现即可触发维护分析并建立计划。达到触发条件只表示开始研究和准备最小候选，不授权修改 Stable。用户直接提出的持久规则、流程或行为修改不受事故次数阈值约束，按 Direct Policy Change 立即进入维护计划记录。重复 hits 不能把一次任务拆成多个事件凑数。

能安全抽象时使用 `scripts/evolve.py record <incident.json> <evidence-dir>`；数据写入现有 observations 目录的 incident 文件（INC/EV 为事故待办唯一真源；旧 improvements 仅保留历史，不声称新事故自动归并），文件 0600、目录 0700。敏感原文、姓名、单位、业务正文、附件名与业务路径禁止输入。字段仅 incident_id、time、failure_type、cause、impact、evidence、capabilities、repeated、hits、permission；全部分类代码/不透明证据 ID，不接收自由正文。证据 ID 指向本任务脱敏机械证据，原文仍留本任务，不复制长期账本。

Work 无法写本机时，只在当前任务保留脱敏待处理项，下一次实际维护时摄取；不得声称已跨平台同步或后台运行。不创建固定周期压测、轮询或外部搜索。

## 归因、案例与候选

根因只有 `execution_failure | rule_gap | rule_conflict | runtime_issue | noise`。已有规则未执行就修执行链，不堆规则；noise 只记录不改。先查现有机制，再复用 ＞ 修执行链 ＞ 调整表达 ＞ 小补缺 ＞ 最后增结构。

[Regression Cases](../tests/regression-cases.json) 保存代表性真实失败的抽象触发、正确行为、禁止退化与 PASS 条件，并关联执行测试。现有历史测试保留；新增验收合成场景明确标 test fixture，不冒充真实事故。候选在任务 work/ 中，证据在候选外，旧 observation/improvements 历史不改写。

`scripts/evolve.py regress <candidate> <evidence-dir>` 执行候选 unittest 与结构检查并记录真实退出码、日志及候选哈希。原事故需有可执行 case 测试；非退化复用既有套件。边界、质量与速度五项必须由独立审核核对实际差异；不能用静态 PASS 登记代替测试。未经实际 A/B，速度仅写预计不降或待实测，不伪造提升。

维护层准备 proposal JSON：incident_id、case_ids、base_sha256、candidate_sha256、test_run_id、review_ids、permission、approval_ref、summary、quality、speed。`permission=auto|approve` 仅表示候选风险分层，不表示发布权。审核沿用 `verify_evidence.py` 格式及双独立审核，并补 permission、frozen_impact=false、dimensions（fix/non_regression/boundary/quality/speed 均 PASS）。受影响检查不足、未知项或任一失败均不进入发布 Gate。

候选通过全部回归和双审核后只能进入 `CANDIDATE READY`。没有用户明确 FINAL，不生成发布授权记录，不执行 promote，不写 Stable，不产生正式 EVO。

## 晋升、EVO 与回滚

`scripts/evolve.py promote <candidate> <proposal.json> <evidence-dir>` 是 Stable 发布动作，不再属于自动进化权限。无论 proposal 的候选风险分层是 `auto` 还是 `approve`，promote 都必须验证用户发布授权：`actor=user`、`approved=true`、`release_intent=finalize-stable`，并同时绑定当前 candidate_sha256、base_sha256、changes_sha256、purpose 和真实消息证据。任一不匹配即拒绝；候选变化后旧授权自动失效。

发布顺序：锁定 → 当前基线/候选/案例 → 回归证据 → 候选权限分层 → 用户发布授权 → 已验证快照 → 最小文件变更 → 实体哈希复验 → EVO。失败保留候选、拒绝原因和证据，不产生 EVO。部署异常恢复修改文件；中断留下 pending 标记阻止后续晋升，须维护恢复，不假完成。

EVO 仅为真实成功版本，格式 EVO-YYYYMMDD-HHMMSS（UTC），记录事故、根因、Case、前后哈希、文件差异、摘要、质量/速度、回归、候选风险分层、用户批准依据和回滚点。运行记录放 `memory-evolution/proposals/`，不参与候选代码摘要；不用 record、hits、分析、回归失败或 `CANDIDATE READY` 凑 EVO。

`scripts/evolve.py rollback <EVO>` 仅在当前版本仍等于该 EVO 时恢复其确切变更集，保留原 EVO，新增 rollback_of 记录；不盲目覆盖后续维护。回滚仍须维护层真实核验，不得将回滚记录当新成功 EVO。

仅有正式 EVO 时，在现有交付小结附一行“进化：EVO-YYYYMMDD-HHMMSS｜改进内容｜质量↑ / 速度↑｜回归通过”。只填实际有证据的提升维度；没有 EVO 不显示，不新增日志块。

需要交给 Codex 的待办，仅按[现有交付小结的维护提醒条件](../templates/delivery-summary.md)显示一行；复用已知状态，不改变事故、候选、权限或晋升逻辑。

外部 Skill 仅在真实缺口重复、内部机制不能解决且缺口已精确定义时研究，只吸收缺失机制。既有旧 proposal 校验器继续用于历史 Level 2/3 记录；本闭环复用其 snapshot/hash 与 evidence 底座，新的晋升统一走 evolve，不混用旧状态字段绕过权限。

## Direct Policy Change 与历史事项

用户直接指定的持久规则施工走 Direct Policy Change，仅免重复观察等待，不免候选测试、独立审核、用户定稿授权或回滚；本次闭环初装属于该路径。凡用户直接提出需要长期保留的规则新增、修改、删除、修复或优化意见，无论当轮是否立即施工，都必须先形成维护计划记录，不得只停留在聊天中。计划复用现有 `memory-evolution/proposals/`，不新建第二套台账；至少记录 `plan_id`、`source=user_direct|incident_threshold`、真实 `request_ref` 或关联 incident、`intent`、`canonical_owner`、`scope`、`non_goals`、当前 `base_ref/base_sha256`、预期 `validation` 与 `status`。尚未形成候选时 `candidate_sha256` 可为空；形成候选后补绑定当前 candidate。计划记录不得复制用户业务正文、姓名、单位、业务文件名或路径。

维护计划只是“已进入优化准备”的可追溯记录：不计入 incident hits，不冒充 INC/EV，不等于用户批准施工，不产生 Stable 写入权，也不替代最终发布授权。用户直接修改意见没有次数阈值；只要意图明确且属于持久规则，就应当场建立计划。事故型优化仍遵循“普通首次只记录、同类两个独立任务或高影响首次触发计划”的阈值。中央 improvements 仅作历史参考，新事故的记录、处理和关闭统一以 INC/EV、RES 和 EVO 为依据；`pending-*` 不得进入 VERIFIED 或 CLOSED，未经实战 A/B 不标为已验证收益。

复用事项字段 blocker、root_cause、solution、prevention、verification 与 status，不复制用户正文。

新 Case 可单调追加，配套新增测试可随低风险修复进入同一候选；已有 Case 和已有测试不能被自我进化覆盖或删减。发布批准记录必须关联当前候选、当前基线、当前差异哈希、用途、`release_intent=finalize-stable` 和真实消息采集记录。事故 capture 按独立 task ID 去重。审核还须确认 sanitized_metadata=true；summary/quality/speed 采用脚本固定代码。

中断恢复：维护层先运行 `scripts/evolve.py recover`；脚本只在全部当前字节属于登记前/后版本、无旁路修改时恢复晋升前状态，已提交版本先验安装再解除 pending。回滚期间中断保留 pending，须对照其 rollback_path、已验证 snapshot-manifest 和 changes 逐项核对，禁止直接删 pending 或通配解包覆盖；无法确认时停止并报告人工恢复项。

## 收尾与下次维护的实际入口

本机收尾发现真实失败时，先完成当前返工，再使用上述 `record` 保存安全分类及本任务真实机械证据；成功返回 RECORDED 只表示入队，不表示已修复。随后 `scripts/evolve.py status` 只读列出全部 pending 事故及候选，不因影响普通、只有一次或尚无候选而隐藏。无真实事故不调用 record，不新建记录；不创建后台进程。Work 无本机写入工具时，只在当前任务留脱敏待办并说明未同步。

下一次实际维护先读 status，再处理已知未结项。重复按相同 failure_type 的独立 task ID 去重，不能以多个事件或重复读取凑次数。`execution_failure`、`rule_conflict` 是根因；`task_underclassification`、`file_delivery_uncontrolled`、`incident_not_recorded` 是可用故障分类。分类记录不接收业务正文、姓名、单位、业务文件名或路径，也不写用户长期记忆。

正式 EVO 只关闭其中实际包含的 EV；回滚后重新待处理。用户直接授权维护可在真实修改和相关测试、两条独立审核完成后调用 `scripts/evolve.py resolve <INC> <resolution.json> <evidence-dir>`。resolution 仅含 candidate_sha256、test_run_id、review_ids、required_test_ids；必须绑定当前实体摘要并通过既有 verify_evidence。必需测试由系统 regression-cases 按 failure_type 与 cause 同时匹配决定，调用者只能增加不能省略相关 Case；无匹配 Case 或只有不相关测试时拒绝关闭。局部修复只要求相关局部测试，不为记录强制全套回归。该命令保留证据并生成 RES 处置记录，不生成 EVO、不授权新的规则修改。新增 EV 未被既有 RES/EVO 覆盖时重新 pending；无证据不得关闭。原始审核与测试工具定位由维护者在当前维护任务保留，本地摘要和哈希不能代替真实来源。

## 从当前基线起的自动维护隔离

保留当前全部历史成果、技能和各自进化机制，不回滚、不清理、不恢复已经不存在的公共入口。Sol 自动写入、删除、移动、重命名、归档、去重、整理、修复、升级、软链接操作及同步只能在 `/Users/macbook/ChatGPT/`（含解析到该目录的 `/Users/macbook/.codex/`）内进行；`/Users/macbook/Grok/`、`/Users/macbook/.grok/`、`/Users/macbook/Cursor/`、`/Users/macbook/.cursor/` 是受保护运行域。必须同时判断原路径、真实目标与操作两端，不能沿软链接或共享真源跨域写入。发现公共入口仅用于兼容发现时保留，不推定获得维护权限。

内置维护写入口自动启用 `scripts/maintenance_boundary.py` 的进程写入沙箱，子进程继承；其他临时自动维护命令也必须通过 `python3 -B scripts/maintenance_boundary.py -- 命令 参数…` 执行，不能直接用未受保护的 shell／文件工具绕过。保护不可用即停止该自动写操作，不自动降级。该保护不改变其他客户端的配置、权限或自进化。

用户未来明确指定的单次 Grok／Cursor 任务不属于 Sol 自动维护，可在该次授权范围内另行执行；不得把授权转换为长期豁免、持续共享或同步。知识迁移仅在明确授权后只读提取，并在 ChatGPT 内形成独立文件，完成即断开。历史出处不是活动连接，Sol 中已形成的独立成果继续保留。
