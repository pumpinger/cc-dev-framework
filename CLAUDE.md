# CLAUDE.md — cc-dev-framework 开发上下文

> 本文件供 Claude Code 在开发此框架时阅读。
> 框架本身被拷贝到目标项目后，AI 的行为由 `orchestrator.py` + `roles/prompts.py` 控制，不依赖本文件。

## 这是什么

cc-dev-framework 是一个 Python 编排框架，用于驱动 Claude Code (`claude -p`) 自动完成软件开发：
- **Python 控制流** — orchestrator.py 控制规划→执行→验证→修复→完成的全流程
- **Claude 做 AI 工作** — Planner 规划 feature、Executor 写代码、Fixer 修 bug
- **脚本做机械验证** — verify.py 跑 4 项门禁检查，validate_plan.py 检查规划质量

## 仓库结构

```
cc-dev-framework/               ← 仓库根目录
├── CLAUDE.md                   ← 本文件（框架开发上下文）
├── README.md                   ← 用户使用说明
├── .gitignore
└── .cc-dev-framework/          ← 被拷贝到目标项目的框架目录
    ├── orchestrator.py         ← 主入口
    ├── status.py               ← 进度查看
    ├── init.sh                 ← 项目初始化模板
    ├── features.json           ← 功能规划数据
    ├── progress.json           ← 会话进度记录
    ├── roles/                  ← AI 角色 + 验证
    │   ├── prompts.py          ← Planner/Executor/Fixer prompt 模板
    │   ├── briefing.py         ← 上下文压缩，注入项目信息给 Claude
    │   ├── verify.py           ← 4 项门禁（steps_done, evidence, commands, branch）
    │   └── validate_plan.py    ← 规划质量检查（8 项）
    └── core/                   ← 基础设施
        ├── store.py            ← 数据模型 + features.json 原子读写
        ├── start.py            ← 建 feature 分支 + 设 in_progress
        ├── step.py             ← Executor 调用：标记步骤完成 + 写证据
        ├── complete.py         ← commit → merge → 标记 completed
        └── archive.py          ← 归档已完成 feature 到 vN.json
```

## 工作流（orchestrator.py 的 5 个阶段）

```
INIT → RESUME → PLAN → EXECUTE (循环: verify→fix) → ARCHIVE
```

| 阶段 | 做什么 |
|------|--------|
| INIT | git init + 运行 init.sh 安装依赖 |
| RESUME | 检测 in_progress feature，断点恢复 |
| PLAN | Claude (Planner) 分析项目 → 输出 features.json → validate_plan 检查 → 用户审批 |
| EXECUTE | 按 priority 逐个 feature：start.py 建分支 → Claude (Executor) 写代码 → verify.py 门禁 → 失败则 Claude (Fixer) 修复 → 通过后 complete.py 提交合并 |
| ARCHIVE | 所有 feature 完成后归档到 archive/vN.json |

## call_claude() 的两种模式

- `stream=False`（Planner 用）：`stdout=PIPE` 捕获 JSON 输出解析，stderr 流到终端
- `stream=True`（Executor/Fixer 用）：stdout+stderr 都继承，用户实时看到 Claude 工作

## 关键设计约定

- 所有路径用 `Path(__file__).parent` 计算，拷贝到任何项目后自动适配
- `core/store.py` 定义 `FRAMEWORK_DIR` 和 `PROJECT_DIR`，其他脚本 import 它
- `roles/` 下脚本需要 store 时：`sys.path.insert(0, str(Path(__file__).parent.parent / "core"))`
- Windows 兼容：`reconfigure(encoding="utf-8")` 或 `TextIOWrapper`，bash 路径用 `as_posix()`
- features.json 写入用原子操作（temp file + rename）

## 开发注意事项

- 改了 `store.py` 的数据模型，需同步检查 `verify.py`、`complete.py`、`status.py`
- 改了 prompt 模板，需检查 `briefing.py` 中的对应部分是否一致
- 改了目录结构，需更新 `orchestrator.py` 中的 `run_script()` 路径
- 新增脚本时：放 `core/` 或 `roles/`，在 `__init__.py` 旁边，确保 sys.path 正确
