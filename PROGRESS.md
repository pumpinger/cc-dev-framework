# Task: 构建 aifw — AI Agent 长任务开发框架

## Plan
- [x] Step 1: 项目脚手架 (pyproject.toml, 目录结构, .gitignore)
- [x] Step 2: Config 模块 (加载 config.yaml, 环境变量, 数据模型)
- [x] Step 3: State 模块 (features.json CRUD, schema 校验, 原子写入)
- [x] Step 4: Tool Registry + 基础工具 (file_ops, bash, git)
- [x] Step 5: BaseAgent (Claude API 对话循环, streaming, thinking, 工具执行)
- [x] Step 6: Callbacks 系统 (终端 UI 输出, 可观测性)
- [x] Step 7: InitializerAgent (分析项目, 生成 features.json)
- [x] Step 8: CoderAgent (实现单个 feature)
- [x] Step 9: VerifierAgent (验证 feature)
- [x] Step 10: Orchestrator (调度器, session 恢复, feature 循环)
- [x] Step 11: CLI 入口 (click, init/run/status/next 命令)
- [ ] Step 12: 集成测试 (用 test-project 端到端测试) ← CURRENT

## Current State
核心框架已全部实现。剩余端到端集成测试。

## Key Decisions
- 语言: Python 3.12
- AI 后端: Anthropic Claude API (anthropic SDK)
- CLI: click
- 状态持久化: JSON 文件 (features.json)
- 用 streaming + extended thinking 提供实时可观测性

## Blockers / Open Questions
- 集成测试需要有效的 ANTHROPIC_API_KEY
