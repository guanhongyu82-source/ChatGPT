# Sol Cabinet

- Canonical name: Sol Cabinet
- Canonical repository: `guanhongyu82-source/ChatGPT`
- Canonical path: `skills/sol-cabinet/`
- Legacy command/name: `/sol cabinet`
- Entry point: `SKILL.md`
- Current version authority: [`VERSION`](VERSION)（本文件不复制版本号）
- Repository role: authoritative source for maintained Skill content and version history
- Local runtime role: deployed execution copy only; never overrides the repository baseline

## Source-of-truth rule

From the 2026-09-15 Cabinet baseline onward, `guanhongyu82-source/ChatGPT:skills/sol-cabinet/` is the only maintained source of truth for Sol Cabinet.

The historical local tree at `/Users/macbook/ChatGPT/lineage/codex-root/配置库/04_skill索引/sol-cabinet/` remains a runtime deployment target for Codex/Work compatibility. It is not an independent maintenance source. A local difference is runtime drift to be reconciled against an explicitly selected GitHub commit; it must not silently become a new canonical version.

Formal changes follow: Chat review/finalization → GitHub minimum diff → verification → commit → local deployment of the selected commit when the Mac runtime must be updated → local installation check. The deployment contract is documented in `platform-adapter/deployment-contract.md`.

`MANIFEST.md` records the original import/source baseline and historical hashes; it is archival evidence, not a current-file hash registry, version authority, runtime authority, or policy owner. Current identity is determined by Git history plus `VERSION`, and current rules by the canonical owners listed in `core/system-architecture.md`.

The original 2026-09-15 import was a lossless archival migration. Python bytecode, runtime lock files, and generated log files were intentionally excluded. Repository metadata (`README.md`, `MANIFEST.md`, `.gitignore`) is not part of the runtime behavior contract unless explicitly referenced by a maintenance task.
