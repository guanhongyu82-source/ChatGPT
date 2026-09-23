# Sol Cabinet Deployment Contract

本文件只定义 Sol Cabinet 的正式版本如何从 GitHub 部署到 Mac 运行树，以及 GitHub 状态与 Runtime 状态如何判定；不改变业务主结构、T1-T10、质量 Gate 或自我进化权限。

## 权威关系

- 正式维护真源：`guanhongyu82-source/ChatGPT:skills/sol-cabinet/`
- 当前版本身份：仓库中的 `VERSION`
- 正式历史：Git commit
- Mac 运行部署树：`/Users/macbook/ChatGPT/lineage/codex-root/配置库/04_skill索引/sol-cabinet/`
- Codex Skill 入口：解析到上述运行部署树
- Runtime 部署状态凭证：`/Users/macbook/ChatGPT/system/sol-cabinet-deployment/state.json`

GitHub → Mac 是单向正式部署链。Mac 运行树、部署状态凭证、`runtime-snapshot.json`、`installation-manifest.json`、文件时间或本机临时修复都不能反向成为正式维护真源。

Stable 与 LAB 是并行的 GitHub 来源通道；本机仍只有一个受管活动 Runtime。任一时刻只能有一个通道占用该 Runtime，当前活动通道必须写入部署状态凭证；LAB 的存在、安装或验证均不改变 `main` 的 Stable 身份。

## GitHub / Runtime 状态模型

GitHub 与 Runtime 是两个独立状态域，禁止用一个域的状态替代另一个域的结论。

### GitHub 状态

- **GITHUB_STABLE**：正式 `main` 上用户已定稿并发布的 commit；当前版本号只读 `VERSION`。
- **GITHUB_CANDIDATE**：候选分支或尚未发布的 commit。测试通过、审核通过、`CANDIDATE READY` 均不自动变成 Stable。

只有用户明确发布／定稿授权并完成正式发布链，Candidate 才能成为 Stable。Runtime 是否已经部署不参与这个判定。

### Runtime 状态

当前 Runtime 由 `scripts/deployment_state.py` 与 `scripts/check_installation.py` 读取真实文件及外部部署状态凭证判定：

- **UNTRACKED**：没有有效部署状态凭证，或凭证结构／身份无法验证。不得声称 Runtime 对应某个 Git commit。
- **SYNCED**：当前 Runtime `VERSION` 与系统摘要同时匹配部署凭证；如调用时指定目标 commit，还必须与该 commit 完全一致。
- **STALE**：Runtime 自身与其部署凭证一致，但不是本次明确要求核验的目标 commit。它可能仍可运行，但不能声称已更新到目标版本。
- **DRIFTED**：当前 Runtime 字节或 `VERSION` 已偏离部署时记录的状态，或实际 Runtime 无法完成验证。停止覆盖并报告差异。

`SYNCED` 只证明 Runtime 与已记录部署一致，不证明该 commit 已成为 GitHub Stable；`GITHUB_STABLE` 也不证明 Mac 已部署。

`SYNCED` 还必须与核验时指定的 `channel` 一致。`stable` 只能绑定 `main`，`lab` 只能绑定 `lab/v...` 候选引用；通道不一致时返回 `STALE`，不得把 Stable 与 LAB 的状态互相替代。

## 部署状态凭证

部署状态凭证是 Runtime 证据，不是仓库规则文件，不提交回 GitHub，不进入 Skill 系统摘要，也不拥有发布权。最少绑定：

- `schema_version=2` 时的 `channel`（`stable` 或 `lab`）与 `source_ref`；
- repository / repository_path；
- 完整 `source_commit`；
- `source_version`；
- 部署前从选定 GitHub 源计算的 `source_system_sha256`；
- Runtime 根路径及部署后的 `runtime_system_sha256`；
- deployed_at / verified_at。

`scripts/deployment_state.py --capture` 只有在当前 Runtime 系统摘要与选定源摘要完全一致时才允许写入凭证。该动作不修改 GitHub、`VERSION` 或发布状态。

旧 `schema_version=1` 凭证仅按 Stable 兼容读取，不具备 LAB 身份；新的 Stable 或 LAB 部署均写入 schema v2。LAB 捕获必须显式提供 `--channel lab --source-ref lab/v...`，Stable 捕获使用 `--channel stable --source-ref main`。

仓库内历史 `platform-adapter/runtime-snapshot.json` 与 `platform-adapter/installation-manifest.json` 只保留当时安装／能力证据，不作为当前 Runtime 状态输入；`scripts/check_installation.py` 不再以其中历史哈希决定当前 PASS。

`scripts/check_installation.py` 有两个明确 scope：不带 `--expected-commit` 和 `--expected-channel` 时只做 **content-only** 的当前安装结构核验，并附带报告 Runtime 状态；即使该检查 PASS，也**不能**据此声称 Runtime 已部署到某个 Git commit 或通道。正式调用 `--expected-commit <commit>` 和／或 `--expected-channel <channel>` 时才进入 **deployment** scope，并把 Runtime 非 `SYNCED` 作为 FAIL。自我进化 post-apply 等尚未进入正式 GitHub→Mac 部署链的内部检查只能使用 content-only 结论，不能冒充部署完成。

## 何时允许部署

只有同时满足以下条件才执行：

1. 用户已在 Chat 明确定稿并授权更新；
2. 选定来源已在 GitHub 中存在并完成身份核验：Stable 必须是 **GITHUB_STABLE** 的 `main` commit；LAB 必须是用户明确指定的 **GITHUB_CANDIDATE** commit；
3. 本次明确要更新 Mac 运行环境，或运行环境必须更新才能使用新版本；
4. 部署目标、通道、源 ref、源 commit、源系统摘要和回滚点已明确。

仅审阅、提方案、比较、候选测试通过或查看状态不得触发部署。Candidate 默认禁止部署为正式 Runtime；用户明确要求临时候选试装时必须单独标识，不得覆盖 Stable 部署身份或冒充正式更新。

## 标准部署闭环

1. **READ**：读取选定来源的 `channel/source_ref/commit/VERSION` 与本机当前 Runtime 状态；同时确认 Stable 回退目标仍为 `main`。
2. **SOURCE DIGEST**：对选定 GitHub commit 的 `skills/sol-cabinet/` 计算系统摘要，记录 channel + source ref + commit + version + digest；不得从 Runtime 反推源身份。
3. **COMPARE**：只比较正式源与本机运行树；运行日志、锁、缓存、任务证据及部署凭证不作为反向差异来源。
4. **DRIFT CHECK**：若 Runtime 为 DRIFTED 或存在未知正文改动，停止覆盖并报告差异；不得自动吸收。
5. **BACKUP**：为本机当前运行树建立可验证回滚点。
6. **DEPLOY**：只把选定 GitHub 来源 commit 的 Sol Cabinet 维护内容部署到运行树。部署 LAB 时不得把它标成 Stable，不得修改 `main`，不得把 `.git`、任务输出、缓存或其他仓库内容带入运行树。
7. **RUNTIME SYNC**：按既有机制同步受管 Agent 运行副本；不改用户模型、effort、全局插件、权限或其他 AI 配置。
8. **CAPTURE STATE**：确认 Runtime 系统摘要等于第2步源摘要后，用 `scripts/deployment_state.py --capture --channel <channel> --source-ref <source-ref>` 写 schema v2 外部部署状态凭证。
9. **VERIFY**：运行 `scripts/check_installation.py --expected-commit <commit> --expected-channel <channel>` 及本次改动相关回归；只有返回 `scope=deployment`、`runtime_state.state=SYNCED`、通道与 source ref 正确且安装检查 PASS 才视为 Runtime 部署验证通过。
10. **REPORT**：分别报告 GitHub Stable 基线、当前 Runtime 活动通道、实际 commit/version、实际测试、未核项和回滚点。任何一步失败均不得声称部署完成。

## 本机漂移处理

本机差异分三类：

- **runtime-only**：日志、缓存、锁、临时证据、任务产物和外部部署状态凭证。保留或按本机规则处理，不进入 GitHub。
- **expected-managed-copy**：Agent 运行副本等由正式源派生的文件。以已选定 GitHub 版本重新同步并核验。
- **unknown-source-change**：本机 Skill 正文、脚本、规则或模板存在部署凭证之外的未知改动。Runtime 记为 DRIFTED，立即停止覆盖，形成差异报告，交用户裁决。

不得使用“本机更新时间较新”“文件时间较新”“快照记录较新”作为反向覆盖 GitHub 的理由。

## 回滚

回滚优先回到上一个已知稳定 Git commit，再把对应版本部署到本机运行树，并重新生成与该 commit 绑定的 Runtime 部署状态凭证。若故障仅发生在部署动作而 GitHub 版本本身未发布失败，可恢复部署前本机快照并重新验证 Runtime 状态，保持 GitHub 不变。

从 LAB 回滚时，目标固定为用户此前确认的 Stable `main` commit；回滚完成后必须以 `channel=stable`、`source_ref=main` 重新捕获并核验状态。LAB 与 Stable 的“并行”表示来源和证据可同时存在，不表示失败时保留一个未核验的双重活动 Runtime。

禁止 force push、删除历史、覆盖未知本地改动或把失败候选标成稳定版本。

## 执行角色

Chat 负责审阅、方案、定稿和 GitHub 正式维护。Mac 侧部署是机械执行环节，可由 Codex 或以后具备本机文件权限的受控执行器完成；执行器不得重新设计已定稿内容，也不得根据 Runtime 状态自行改变 GitHub 发布状态。
