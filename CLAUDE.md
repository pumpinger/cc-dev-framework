# CLAUDE.md — cc-dev-framework 开发上下文

> 本文件供 Claude Code 在开发此框架时阅读。
> 框架本身被拷贝到目标项目后，AI 的行为由 `main.py` + `roles/*.py` 控制，不依赖本文件。

## 这是什么

cc-dev-framework 是一个 Python 编排框架，用于驱动 Claude Code (`claude -p`) 自动完成软件开发：
- **Python 控制流** — main.py 控制准备→规划→执行→验证→修复→E2E 测试→完成的全流程
- **Claude 做 AI 工作** — Preparer 准备需求、Planner 规划 feature、Executor 写代码、Fixer 修 bug、E2E Tester 端到端验证
- **脚本做机械验证** — verify.py 跑 4 项门禁检查，validate_plan.py 检查规划质量

## 仓库结构

```
cc-dev-framework/               ← 仓库根目录
├── CLAUDE.md                   ← 本文件（框架开发上下文）
├── README.md                   ← 用户使用说明
├── .gitignore
└── .cc-dev-framework/          ← 被拷贝到目标项目的框架目录
    ├── main.py                 ← 主入口
    ├── status.py               ← 进度查看
    ├── init.sh                 ← 依赖安装 + 冒烟测试（project-setup 填写）
    ├── dev.sh                  ← 项目启动命令（project-setup 填写）
    ├── features.json           ← 功能规划数据
    ├── progress.json           ← 会话进度记录
    ├── session.log             ← 运行日志（每次运行清空）
    ├── roles/                  ← AI 角色（prompt 模板）
    │   ├── preparer.py         ← Preparer prompt 模板（需求准备）
    │   ├── planner.py          ← Planner prompt 模板（规划）
    │   ├── executor.py         ← Executor prompt 模板
    │   ├── fixer.py            ← Fixer prompt 模板
    │   └── e2e_tester.py       ← E2E Tester prompt 模板（端到端测试）
    ├── src/                    ← 框架业务逻辑 + 验证
    │   ├── store.py            ← 数据模型 + features.json 原子读写
    │   ├── briefing.py         ← 上下文压缩，注入项目信息给 Claude
    │   ├── start.py            ← 建 feature 分支 + 设 in_progress
    │   ├── step.py             ← Executor 调用：标记步骤完成 + 写证据
    │   ├── complete.py         ← commit → merge → 标记 completed（支持 --skip-verify）
    │   ├── archive.py          ← 归档已完成 feature 到 vN.json
    │   ├── verify.py           ← 4 项门禁（steps_done, evidence, commands, branch）
    │   └── validate_plan.py    ← 规划质量检查（8 项）
    └── utils/                  ← 通用工具（与框架业务无关）
        └── log.py              ← 日志模块（setup_logging + get_logger）
```

## 角色说明

| 角色 | 文件 | 职责 |
|------|------|------|
| Preparer | `roles/preparer.py` | 主动准备需求物料，转换不友好格式，分析 MCP 工具需求 |
| Planner | `roles/planner.py` | 分析项目，输出 features.json 规划 |
| Executor | `roles/executor.py` | 按步骤实现代码 |
| Fixer | `roles/fixer.py` | 根据验证错误或 E2E 失败修复代码（FIX_PROMPT + FIX_E2E_PROMPT） |
| E2E Tester | `roles/e2e_tester.py` | 端到端验证功能正确性 |

## 工作流（main.py 的 6 个阶段）

```
INIT → RESUME → PREPARE → PLAN → EXECUTE → ARCHIVE
```

| 阶段 | 做什么 |
|------|--------|
| INIT | git init + 运行 init.sh 安装依赖 |
| RESUME | 检测 in_progress feature，断点恢复（失败则退出） |
| PREPARE | Claude (Preparer) 准备需求物料 → 转换格式 → 分析 MCP 工具 → 输出结构化需求给 Planner |
| PLAN | Claude (Planner) 分析项目 → 输出 features.json → validate_plan 检查 → 用户审批 |
| EXECUTE | 按 priority 逐个 feature（含 pending + failed）：start → executor → [verify ←→ fix] → [e2e_test ←→ fix] → complete（所有 feature 统一走 E2E，E2E Tester 自行判断是否跳过） |
| ARCHIVE | 所有 feature 完成后归档到 archive/vN.json |

### EXECUTE 内部 per-feature 流程

```
start → executor → [verify ←→ fix] → [e2e_test ←→ fix] → complete
```

E2E 测试三种结果：
1. **E2E_PASSED** → complete
2. **E2E_SKIPPED**（无法测试或无需测试）→ complete
3. **E2E_FAILED** → Fixer（E2E 专用 prompt，含完整 E2E 输出）修复 → 重新 verify → 重新 E2E
4. **无标记输出** → 视为 E2E_FAILED

verify-fix 和 E2E-fix **分开计数**，各自有独立的 max_retries。
E2E 修复使用 `FIX_E2E_PROMPT`（`roles/fixer.py`），传入完整 E2E 输出而非摘要。

**重试语义：** `--max-retries N` = 首次测试 + N 次修复重试（共 N+1 次测试）。E2E 同理。
**failed 恢复：** status=failed 的 feature 会在阶段 5 自动重新执行（与 pending 一起）。

## init.sh 与 dev.sh

- `init.sh` — 依赖安装 + 冒烟测试。main.py 阶段 1 运行，失败则阻止继续
- `dev.sh` — 项目启动命令。不由 main.py 运行，而是注入到 executor/e2e_tester briefing 中，让 Claude 知道怎么跑项目
- 两者都是模板文件，由 Planner 规划的 `project-setup` feature 中由 Executor 填写
- Planner prompt 规则第 6 条要求首轮迭代的 project-setup 同时填写这两个文件

## call_claude() 统一流式输出

所有角色统一使用 `Popen` + tee 模式：逐行读取并同时打印到终端、写入日志、收集到 result。
用户可以实时看到每个角色的工作过程。需要 JSON 的调用方（Preparer/Planner）通过 `_extract_json_from_output()` 从收集到的文本中提取 JSON。

## 日志系统

- `utils/log.py` 提供 `setup_logging()` + `get_logger()`
- 日志文件：`.cc-dev-framework/session.log`，每次运行 `mode="w"` 清空
- 格式：`[2026-02-22 14:30:05] [INFO] main: 消息`
- main.py 在 `main()` 开头调 `setup_logging()`，所有关键操作同时 print + logger

## 中文化策略

- 所有脚本的 print 输出为中文（用户可见部分）
- `preparer.py`/`planner.py`/`executor.py`/`fixer.py`/`e2e_tester.py` prompt 模板为中文（Claude 整个上下文都是中文，自然中文回复）
- `briefing.py` 生成的简报为中文
- main.py 的 system_note 为中文
- `store.py` 无 print，不涉及
- `[FAIL]`/`[PASS]` 标签保留英文（国际通用标记）
- E2E 结果标记保留英文（`E2E_PASSED`/`E2E_FAILED`/`E2E_SKIPPED`）
- verify.py 输出中文后，main.py 的 `extract_verify_errors()` 正则已同步更新

## 关键设计约定

- 所有路径用 `Path(__file__).parent` 计算，拷贝到任何项目后自动适配
- `src/store.py` 定义 `FRAMEWORK_DIR` 和 `PROJECT_DIR`，其他脚本 import 它
- `roles/` 下脚本需要 store 时：`sys.path.insert(0, str(Path(__file__).parent.parent / "src"))`
- Windows 兼容：`reconfigure(encoding="utf-8")` 或 `TextIOWrapper`，bash 路径用 `as_posix()`
- features.json 写入用原子操作（temp file + rename）

## 开发注意事项

- 改了 `store.py` 的数据模型，需同步检查 `verify.py`、`complete.py`、`status.py`
- 改了 prompt 模板（`roles/*.py`），需检查 `briefing.py` 中的对应部分是否一致
- 改了目录结构，需更新 `main.py` 中的 `run_script()` 路径
- 新增脚本时：放 `src/`（框架逻辑）或 `utils/`（通用工具），确保 sys.path 正确
- 改了 `verify.py` 的输出格式，需同步更新 `main.py` 的 `extract_verify_errors()` 正则
- 改了 E2E tester 的输出标记，需同步更新 `main.py` 的 `_parse_e2e_result()` 解析
- `complete.py` 由编排器调用时传 `--skip-verify`（编排器已验证过），独立使用时仍自带验证；`complete.py` 容忍 "nothing to commit"（Claude 可能已在执行中提交）
- `_run_fixer_e2e()` 使用 `FIX_E2E_PROMPT`，接收完整 E2E 输出；`_run_fixer()` 使用 `FIX_PROMPT`，接收 verify 输出
- `_complete_feature()` 是 E2E 通过后的完成逻辑辅助函数，被 `_execute_feature` 中的 E2E 循环调用
- verify 和 E2E 循环采用"首次测试 + N 次修复重试"结构，改 max_retries 语义时需同步两个循环
- `.cc-dev-framework/session.log` 已加入 `.gitignore`（`*.log` 规则覆盖），不提交到仓库
