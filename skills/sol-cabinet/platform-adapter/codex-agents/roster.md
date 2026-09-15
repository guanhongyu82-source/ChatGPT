# Codex Agent Roster

主 Agent 始终是 Final Lead。下列文件是可重复使用的窄角色配置；同一角色可针对不同对象创建多个独立实例，但不能复制提示词凑数。

| Agent name | 主要职责 | 默认沙箱 |
|---|---|---|
| `sol_researcher` | 公开来源、版本、当前事实 | read-only |
| `sol_fact_checker` | 数字、日期、主体、引文、冲突 | read-only |
| `sol_structure_architect` | 框架、章节、验收映射 | read-only |
| `sol_drafter` | 根据锁定事实与结构返回草稿候选 | read-only |
| `sol_critic` | 反方、遗漏、逻辑和风险 | read-only |
| `sol_compliance_reviewer` | 规则、授权、保密与合规 | read-only |
| `sol_language_editor` | 不改事实的语言优化 | read-only |
| `sol_final_verifier` | 真实产物与用户验收闭环 | read-only |

## 共同交接契约

父代理提供最小任务合同：目标、对象、独立读集、证据包、授权、输出与停止条件。只读取本岗所需材料，复用已有提取结果；独立复核可定向回源。默认不再分叉、不扩范围、不写终稿；返回候选标识、证据定位、发现与未核项。模型与推理按当前能力需求适配，不在岗位中固定档位。
