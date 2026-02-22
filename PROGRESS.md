# Task: 中文化 + 日志系统

## Plan
- [ ] Step 1: 新建 `core/log.py` — logging 模块
- [ ] Step 2: orchestrator.py 全面改造（日志 + 中文 + stream tee）
- [ ] Step 3: 其余 7 个脚本中文化
- [ ] Step 4: 更新 CLAUDE.md + README.md ← CURRENT

## Current State
Starting fresh.

## Key Decisions
- 日志文件: `.cc-dev-framework/orchestrator.log`, mode="w" 每次清空
- prompts.py / briefing.py / store.py 不改（prompt 模板保持英文，store 无 print）
- [FAIL]/[PASS] 标签保留英文（国际通用标记）
- system_note 追加 `请用中文回复。`

## Blockers / Open Questions
- None
