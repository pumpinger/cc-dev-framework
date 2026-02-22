# cc-dev-framework

用 Python 编排 Claude Code，自动完成软件项目开发。

你给一个目标，框架驱动 Claude 自动规划 feature、写代码、跑测试、修 bug、提交合并。

## 前置条件

- Python 3.10+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) 已安装并登录（终端运行 `claude` 能用）
- Git
- Bash（Windows 用户需要 Git Bash 或 WSL）

## 快速开始

### 1. 拷贝框架到你的项目

```bash
# 新项目
mkdir my-project && cd my-project
cp -r /path/to/cc-dev-framework/.cc-dev-framework .

# 已有项目
cd my-project
cp -r /path/to/cc-dev-framework/.cc-dev-framework .
```

### 2. 启动

```bash
python .cc-dev-framework/main.py --goal "用 FastAPI 写一个 TODO API，支持增删改查"
```

框架会自动：
1. 初始化 git 仓库
2. 调用 Claude 规划 feature（展示计划让你审批）
3. 逐个 feature 执行：建分支 → Claude 写代码 → 验证 → 通过后合并
4. 全部完成后归档

### 3. 查看进度

```bash
python .cc-dev-framework/status.py
```

### 4. 断点恢复

中途中断了？再跑一次就行，框架会自动检测 in_progress 的 feature 并恢复：

```bash
python .cc-dev-framework/main.py
```

## 命令参数

```
python .cc-dev-framework/main.py [options]

--goal "text"      项目目标（首次运行必填）
--auto-approve     跳过规划审批，直接开始执行
--max-retries N    每个 feature 验证失败后的最大重试次数（默认 3）
--feature ID       只处理指定 feature
--dry-run          只展示执行计划，不实际调用 Claude
```

## 工作流

```
你输入目标
    ↓
[Planner] Claude 分析项目，输出 features.json（2-8 个 feature）
    ↓
你审批规划（或 --auto-approve 跳过）
    ↓
[Executor] Claude 逐个 feature 写代码（实时显示工作过程）
    ↓
[Verify] 脚本自动跑 4 项门禁检查
    ↓ 失败？
[Fixer] Claude 根据错误修复代码 → 重新验证（最多重试 N 次）
    ↓ 通过？
[Complete] git commit + merge 到主分支
    ↓
[Archive] 全部完成后归档到 archive/vN.json
```

## 目录结构

拷贝到目标项目后：

```
my-project/
├── .cc-dev-framework/
│   ├── main.py                 ← 主入口
│   ├── status.py               ← 查进度
│   ├── init.sh                 ← 环境初始化（自动被 Planner 填充）
│   ├── features.json           ← 功能规划数据
│   ├── progress.json           ← 会话记录
│   ├── main.log        ← 运行日志（自动生成，每次清空）
│   ├── roles/                  ← AI 角色 + 验证
│   │   ├── planner.py
│   │   ├── executor.py
│   │   ├── fixer.py
│   │   ├── briefing.py
│   │   ├── verify.py
│   │   └── validate_plan.py
│   └── core/                   ← 基础设施
│       ├── store.py
│       ├── log.py
│       ├── start.py
│       ├── step.py
│       ├── complete.py
│       └── archive.py
├── (你的项目代码，由 Claude 生成)
└── .git/
```

## 示例

### Python 后端项目

```bash
python .cc-dev-framework/main.py \
  --goal "Build a REST API with FastAPI + SQLite for a todo app with user auth"
```

### React 前端项目

```bash
python .cc-dev-framework/main.py \
  --goal "Create a React + TypeScript dashboard with charts, auth, and dark mode"
```

### 全栈项目

```bash
python .cc-dev-framework/main.py \
  --goal "Build an OA system: FastAPI backend, React frontend, SQLite. Modules: auth, attendance, leave requests, announcements"
```

### 只看计划不执行

```bash
python .cc-dev-framework/main.py --dry-run --goal "..."
```

### 跳过审批直接跑

```bash
python .cc-dev-framework/main.py --auto-approve --goal "..."
```

## 4 项验证门禁

每个 feature 完成后自动跑：

| 门禁 | 检查内容 |
|------|---------|
| steps_done | 所有步骤标记完成 |
| steps_evidence | 每个步骤有完成证据 |
| verify_commands | 编译/测试命令全部 exit 0 |
| git_branch | 在正确的 feature 分支上 |

## 日志

每次运行会生成日志文件 `.cc-dev-framework/main.log`（每次运行清空）。

日志记录：
- 每个阶段的开始/结束
- Claude 调用参数和返回状态
- stream 模式下 Claude 的完整输出
- 子脚本执行结果
- 错误和警告详情

出问题时先查日志：

```bash
cat .cc-dev-framework/main.log
```

## 中文输出

框架所有终端输出均为中文。prompt 模板和 system_note 都是中文，Claude 自然以中文回复。

## 平台支持

- **macOS / Linux**：直接可用
- **Windows**：需要 Git Bash。脚本已内置 Windows 编码处理（UTF-8）

## 常见问题

**Q: Claude 跑到一半断了怎么办？**
A: 再运行一次 `python .cc-dev-framework/main.py`，会自动恢复。

**Q: 规划不满意怎么办？**
A: 审批时输入 `n` 拒绝，然后换个 goal 描述重新跑。

**Q: 某个 feature 反复验证失败？**
A: 框架会在 max-retries 次后标记为 failed 并停止。检查 `status.py` 看错误信息，手动修复后可以用 `--feature ID` 单独重跑。

**Q: 想增加新一轮 feature？**
A: 上一轮完成后 features 已归档，直接再跑一次 `python .cc-dev-framework/main.py` 并给新 goal 即可。
