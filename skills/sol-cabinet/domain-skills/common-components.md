# Common Components

只加载解决本任务必要问题的组件，不重新实现目标平台已经具备的文件生成、浏览和图像工具。

| 能力 | 当前实现 | 边界 |
|---|---|---|
| 原稿归档 | scripts/archive_originals.py | 任务目录先存在；逐字节副本、清单及哈希；本轮不改实现 |
| DOCX／XLSX只读定位与候选检查 | scripts/inspect_office.py | 单文件结构定位、数字出现位置、旧值逐次命中、状态精确识别 |
| 多文件独立Office机械检查 | scripts/inspect_office_batch.py | 复用单文件检查语义并发执行；保持输入顺序、逐文件结果和 fail-closed；不替代事实、视觉或 Delivery Gate |
| 文档／表格／演示／PDF生成与编辑 | 当前原生Office／PDF技能及依赖 | 不迁移旧Grok生成器、版式套餐或禁用渲染链 |
| 候选测试与审核记录一致性 | scripts/verify_evidence.py | 实际文件、候选摘要、日志hash、结果、独立性声明；由维护提案校验器调用 |
| 调度、引用、错误与恢复 | 既有编排、研究接口、Review和阶段状态 | 不新建第二调度器或重复公共框架 |

`inspect_office.py <文件> [--stale 旧值]` 只输出JSON，不修改输入，不联网、不启动Office、宏或渲染程序。先按任务规则归档输入；输出保存于当前任务，不能写长期记忆。

多个 DOCX／XLSX 只有在同一阶段互不依赖、检查负载非轻量，并且预期净收益明确为正时，才使用 `inspect_office_batch.py <文件...>`；不能仅因为文件数大于一就启动并行。小文件、少量文件、收益未知或当前环境进程启动成本可能高于检查本身时，继续使用单文件路径或 `--max-workers 1`。批量器只负责并发调度，实际解析仍逐文件调用同一 `inspect()`；任一文件 BLOCKED 时整体为 BLOCKED，不用其他文件的 PASS 覆盖失败。若宿主的进程并行基础设施不可用，批量器必须退回相同检查语义的串行执行并标记 `execution_mode=serial_fallback`，不得跳过检查、假 PASS，或把回退耗时冒充并行收益。批量器输出的 wall-clock 仅作性能观测，不是质量门槛；没有 A/B 证据时不得声称更快。

它们都不是完整事实或视觉验收器。`parse_status=PASS` 仅表示安全解析完成，`overall_verdict=NOT_ASSESSED` 表示内容质量未裁决；解析失败为BLOCKED，不读取ZIP二进制假装正文。检查器不重算公式、不解释完整样式继承、不OCR图片、不认证文档可在所有Office应用打开。字段／公式缓存与未核项必须继续披露。当前只支持识别的Transitional OOXML部件；Strict或不识别的命名空间返回BLOCKED，由原生文件工具按实际支持处理，不能当空文档。

旧脚本的“未完成”子串误判、DOCX失败后猜读、只报告首次旧值、固定序号硬判，不迁移到本实现。状态映射只认明确完整值，未知状态不自行改成完成；候选问题由主代理结合上下文裁决。

证据校验读取与候选关联的真实记录和日志，不能把字段自洽当执行真实性。本地可编辑JSON无法证明不可伪造的身份或用户授权，须由可信工具结果采集与独立审核配合；见 [维护规范](../memory-evolution/evolution-policy.md)。

## v1.5.4 有限 Office 语义覆盖合同

`semantic_surface=sol-office-text-v1` 仅承诺下面的文本／存储值盘点，不承诺 Office GUI、排版或全部 OOXML 解释。代码中的 QName、父子结构及属性白名单是可执行边界；未知节点、属性、值、结构位置和解释依赖默认留下缺口，不靠不断补黑名单判断安全。

| 表面 | 可完整覆盖的内容 | 超出边界的处理 |
|---|---|---|
| DOCX | 普通 document/body/p/r 的 Unicode 文本，`w:t` 的空格、`w:tab`、普通 textWrapping `w:br`；简单 header/footer part 内同样的段落文本 | 表格结构、修订、字段、符号、其他换行、样式与字符属性、编号、文本框、绘图、扩展节点等仍可保留已提取文字，但必须标记 gap；不推断最终可见性 |
| XLSX | 唯一、明确引用的 sheet/row/cell；无样式解释依赖的普通数值、inline string、被引用的 shared string 与不带格式的文本片段 | 未引用非空 shared string、`_xHHHH_` 编码依赖、日期／时间序列、cell/row style、非空默认样式、number format、公式／缓存、富文本格式、hidden 行列或 sheet、header/footer、合并等未支持节点或属性均为 gap；raw storage value 不能消除缺口 |
| Document properties | 标准 core/app 的已列明字面字段，以及 TitlesOfParts/HeadingPairs 的普通向量和标量；保留非空文本、属性、展开 QName 与序号 locator | 扩展字段、未知向量 baseType、size／子类型不一致及未知属性／结构仍记录可读原值，同时留下 gap；不执行属性中的指令或自行解释编码数据 |
| 格式／控制部件 | 已解析、根 QName 正确且无属性／子节点／非空文本的空格式容器可证明没有未处理内容 | 非空 theme/styles/settings/font/numbering/calcChain 等统一 gap；图片、打印二进制、OLE、图表及其他未读取部件保持 unread，不因官方 relationship 或 Content-Type 豁免 |

覆盖对象明确分离三种状态：

- `coverage.parts_read`：只证明该 part 被安全解析。
- `coverage.semantic_gaps`：每个缺口有 `part + locator + reason`，记录 part 内尚未支持的语义。
- `coverage.parts_complete`：恰为已读 parts 扣除存在缺口的 parts；不能手填为“所有已读”。

`source_ingestion` 必须验证上述合同版本与一致性，将所有 semantic gaps 合入 evidence `unread`。未读取 part 与未知／自定义完整 relationship URI 另行 fail-closed；已读目标也必须与关系类型相符。只有内部缺口、包级 unread、字段与公式等未核项全部为空，来源才能为 EXTRACTED、ingestion 才能 PASS。语法损坏或合同缺失直接拒绝，不能回退旧的 parts_read 即完整覆盖逻辑。

高级 Office 语义进入后续版本 backlog；v1.5.4 通过标记 PARTIAL/UNREAD 收敛，不增加 renderer、number-format engine、Strict OOXML 或 GUI fidelity。
