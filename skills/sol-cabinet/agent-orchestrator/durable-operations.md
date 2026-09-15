# Durable Operations：T9-T10

长期运行只有在用户明确要求持续执行、定时、监控或持久状态时启用。T9/T10 标签本身不授权创建计划任务、后台服务、提交、推送或外发。

## 最小有用图

每个持久节点必须写清：

```text
(prompt, model-policy, activation, read-set, write-set, authority, stop-condition)
```

没有独立信息流、权限或写集的节点应折叠，不为展示增加 Agent。

推荐最小图：

- **Executor**：唯一写当前 run ledger；完成最小可独立验证增量。
- **Supervisor**：使用干净上下文重新验证真实产物，只写 directives，不能改 ledger。
- **Scout**：只有研究结果需要跨轮持久、可审计时才创建；只写 findings。
- **Final Lead**：处理用户决策、里程碑放行和终态。

## 单写者状态边

| 状态边 | 唯一写者 | 读取者 |
|---|---|---|
| `ledger` | Executor | Supervisor、Lead |
| `directives` | Supervisor | Executor、Lead |
| `findings` | Scout | Executor、Supervisor、Lead |
| `owner-decisions` | Lead | 全部节点 |

禁止多个 Agent 同写一个状态文件。一次 run 使用一个新目录；后继 run 不修改旧 ledger，只蒸馏仍有效的状态和 Standing Rules。

## 轮次与里程碑

- 一轮最小单位是“实现、验证、记账”闭合的最小可独立验证增量。
- 大批量工作先做最小真实样本试点，再扩全量。
- `pending-audit` 冻结待审范围；审核完成前不得继续修改该里程碑或抢跑下一里程碑。
- Supervisor 必须重跑真实门禁，不能把 Executor 的自报计数当证明。
- 终态、权限阻塞、重复失败或用户停止时必须结束，禁止无停止条件空转。

## 有界热状态

- ledger 只保留当前状态和最近必要轮次；旧轮次进入冷档案。
- directives 只保留未消费纠偏和仍有效规则。
- 正常节点不读取冷档案；通过 Context Index 精确定位源、符号、证据和窄门禁。
- 规则、代码或文档连续只增不减时安排收敛轮；收敛轮不得新增功能。

## 用户决策卡

需要新增权限或高影响选择时，先完成调查，再给最多三个互斥选项，说明推荐项、结果和延误影响。未回复时保持安全的无变化状态。
