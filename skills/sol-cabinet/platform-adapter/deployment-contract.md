# Sol Cabinet Deployment Contract

本文件只定义 Sol Cabinet 的正式版本如何从 GitHub 部署到 Mac 运行树，不改变业务主结构、T1-T10、质量 Gate 或自我进化权限。

## 权威关系

- 正式维护真源：`guanhongyu82-source/ChatGPT:skills/sol-cabinet/`
- 正式历史：Git commit
- Mac 运行部署树：`/Users/macbook/ChatGPT/lineage/codex-root/配置库/04_skill索引/sol-cabinet/`
- Codex Skill 入口：解析到上述运行部署树

GitHub → Mac 是单向正式部署链。Mac 运行树不得因为本地临时修复、日志、缓存、候选文件或运行态差异自动反向成为正式版本。

## 何时允许部署

只有同时满足以下条件才执行：

1. 用户已在 Chat 明确定稿并授权更新；
2. GitHub 中存在对应已验证 commit；
3. 本次明确要更新 Mac 运行环境，或运行环境必须更新才能使用新版本；
4. 部署目标、源 commit 和回滚点已明确。

仅审阅、提方案、比较或查看状态不得触发部署。

## 标准部署闭环

1. **READ**：读取 `main` 当前目标 commit 和本机当前运行树状态。
2. **COMPARE**：只比较 `skills/sol-cabinet/` 与本机运行树；运行日志、锁、缓存、任务证据不作为反向差异来源。
3. **DRIFT CHECK**：若本机有未进入 GitHub 的人工改动，停止覆盖并报告差异；不得自动吸收。
4. **BACKUP**：为本机当前运行树建立可验证回滚点。
5. **DEPLOY**：只把选定 GitHub commit 的 Sol Cabinet 维护内容部署到运行树。仓库归档元数据仅在运行逻辑需要时部署；不得把 `.git`、任务输出、缓存或其他仓库内容带入运行树。
6. **RUNTIME SYNC**：按既有机制同步受管 Agent 运行副本；不改用户模型、effort、全局插件、权限或其他 AI 配置。
7. **VERIFY**：运行当前版本要求的安装检查及受影响测试；检查 Skill 入口、受管 Agent、关键哈希、运行边界和本次改动相关回归。
8. **REPORT**：报告 GitHub commit、本机部署结果、实际测试、未核项和回滚点。任何一步失败均不得声称部署完成。

## 本机漂移处理

本机差异分三类：

- **runtime-only**：日志、缓存、锁、临时证据、任务产物。保留或按本机规则清理，不进入 GitHub。
- **expected-managed-copy**：Agent 运行副本等由正式源派生的文件。以 GitHub 版本重新同步并核验。
- **unknown-source-change**：本机 Skill 正文、脚本、规则或模板存在 GitHub 未知改动。立即停止覆盖，形成差异报告，交用户裁决。

不得使用“本机更新较新”“文件时间较新”作为反向覆盖 GitHub 的理由。

## 回滚

回滚优先回到上一个已知稳定 Git commit，再把对应版本部署到本机运行树。若故障仅发生在部署动作而 GitHub 版本本身未发布失败，可恢复部署前本机快照并保持 GitHub 不变。

禁止 force push、删除历史、覆盖未知本地改动或把失败候选标成稳定版本。

## 执行角色

Chat 负责审阅、方案、定稿和 GitHub 正式维护。Mac 侧部署是机械执行环节，可由 Codex 或以后具备本机文件权限的受控执行器完成；执行器不得重新设计已定稿内容。
