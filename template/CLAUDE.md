# CLAUDE.md — cc-dev-framework 开发框架规则

> 本文件配合 `.cc-dev-framework/` 目录使用。Claude Code 启动时自动读取并遵守以下规则。
> 项目信息存储在 `.cc-dev-framework/features.json`。

---

## 核心原则

**证据优先：** 每一步完成都必须有证据。不是"我觉得做完了"，而是"这是证明"。
**恢复优先：** 中断后恢复是第一优先级。永远先检查是否有未完成的工作。
**角色分离：** 你（AI）负责规划和编码。脚本负责验证和门禁。你不能自己判"通过"。

---

## 0. 工作流程

你是 AI 开发大脑，`.cc-dev-framework/` 里的脚本是你的验证工具。

```
用户说需求 → 你规划 features → 逐个实现 → 脚本门禁验证 → 提交
```

**脚本命令（你来调用）：**

| 命令 | 作用 |
|------|------|
| `python .cc-dev-framework/status.py` | 显示进度 + 恢复信息 |
| `python .cc-dev-framework/start.py -f <id>` | 开始功能：建分支 + 设 in_progress |
| `python .cc-dev-framework/step.py -f <id> -s <N> -e "evidence"` | 标记步骤完成 + 写证据 |
| `python .cc-dev-framework/verify.py -f <id>` | 跑 4 项门禁检查（**脚本判断**，不是你） |
| `python .cc-dev-framework/complete.py -f <id> -m "commit msg"` | 完成功能：verify → commit → merge → 标记 completed |
| `python .cc-dev-framework/archive.py` | 归档已完成功能到 vN.json |
| `python .cc-dev-framework/seal.py` | 规划完成后锁定 verify_commands（计算 hash） |
| `bash .cc-dev-framework/init.sh` | 项目环境初始化（安装依赖等） |

---

## 1. 会话启动 — 恢复优先

每次会话开始，**必须按以下顺序执行**：

1. 运行 `bash .cc-dev-framework/init.sh` 初始化环境（安装依赖 + 冒烟测试）。**如果失败，说明项目处于坏状态，优先修复**
2. 读取 `.cc-dev-framework/progress.json`，了解上次会话的进度摘要
3. 运行 `python .cc-dev-framework/status.py` 查看当前状态
4. 如果输出中有 `RESUME:` 段落：
   - 这是被中断的工作，**必须优先恢复**
   - 检查分支是否正确（status 会告诉你）
   - 从 `Next step` 指示的步骤继续
5. 如果没有 `RESUME:`：
   - 读取 `.cc-dev-framework/features.json`
   - 如果 features 只有示例功能（id 为 `example-feature`），替换为真实规划
   - 否则选择下一个 `pending` 功能（按 priority）
6. **禁止**无视 RESUME 信息直接开始新功能

---

## 2. 角色分离

### 你（AI）负责：
- 分析项目、规划功能
- 编写代码、实现功能
- 填写每个 step 的 `evidence` 字段（你做了什么的证据）
- 运行门禁脚本并根据结果修复问题

### 脚本（verify.py）负责：
- 检查所有 steps 是否 done
- 检查每个 done step 是否有 evidence
- 运行 verify_commands
- 检查 git 分支是否正确
- 检查工作区是否干净
- **输出最终裁决：GATE PASSED 或 GATE FAILED**

**你不能自己判定功能完成。只有脚本输出 `GATE PASSED` 才算通过。**

---

## 3. 逐步实现 — 证据优先

对于每个功能：

1. 开始：`python .cc-dev-framework/start.py -f <id>`（自动建分支 + 设 in_progress）
2. 按 steps 数组顺序逐步实现代码
3. 每完成一步：`python .cc-dev-framework/step.py -f <id> -s <N> -e "做了什么的证据"`

evidence 要写清楚做了什么，例如：
```
python .cc-dev-framework/step.py -f add-command -s 0 -e "Created todo/add.py with add_task(title), writes to tasks.json"
```

**没有 evidence 的 step，门禁不会通过。**
**不要手动编辑 features.json 来标记步骤完成，用 step.py。**

---

## 4. 完成功能

所有 steps 完成后，一条命令搞定 verify + commit + merge：

```bash
python .cc-dev-framework/complete.py -f <id> -m "feat(<id>): 功能标题"
```

`complete.py` 自动执行：
1. 跑 `verify.py` 门禁检查（5 项：steps_done / steps_evidence / verify_integrity / verify_commands / git_branch）
2. GATE PASSED → `git add -A && git commit`
3. 切到 main/master → merge → 删除 feature 分支
4. 更新 features.json：status=completed + commit_hash

- 如果门禁失败，脚本会停下来，输出失败原因
- 修复后重新运行 `complete.py`
- **不要手动修改 done_evidence，它由 verify.py 写入**

---

## 5. 单独跑门禁（可选）

如果想在 complete 之前先检查门禁状态：

```bash
python .cc-dev-framework/verify.py -f <id>
```

通常不需要单独跑，因为 `complete.py` 已经内置了 verify。

---

## 6. 功能规划指南

当 `features.json` 中 features 为空或只有示例功能时，规划功能：

1. 从 features.json 的 `goal` 字段了解目标（如果为空，问用户）
2. 将 `project` 字段设为项目目录名
3. 分析项目结构
4. 如果 `.cc-dev-framework/archive/` 存在，读取归档了解已有功能（避免重复实现）
5. 分解为 2-8 个独立功能
6. 每个功能 2-6 个步骤
7. **每个功能必须有 verify_commands**（至少 1 条可执行命令），且必须遵守下方的 verify_commands 质量要求
8. priority: 1 = 最高优先，按依赖排序
9. feature id 使用 kebab-case
10. 写入 `.cc-dev-framework/features.json`
11. **第一轮迭代的第一个功能必须是 project-setup**：填写 `.cc-dev-framework/init.sh`（安装依赖 + 冒烟测试）。init.sh 必须确保：依赖已安装（npm install / pip install 等）、项目能编译/运行。后续所有 verify_commands 都依赖 init.sh 建立的环境

功能 JSON 结构：
```json
{
  "id": "feature-id",
  "title": "功能标题",
  "priority": 1,
  "status": "pending",
  "type": "feature",
  "steps": [
    {"description": "步骤描述", "done": false, "evidence": null}
  ],
  "verify_commands": [
    "npx tsc --noEmit",
    "npx jest tests/feature-id.test.tsx"
  ],
  "verify_commands_hash": null,
  "done_evidence": {
    "verify_results": [],
    "gate_checks": [],
    "all_passed": false,
    "verified_at": null
  },
  "commit_hash": null,
  "error": null
}
```

### verify_commands — 规划阶段的测试合约

verify_commands 不只是验收工具，而是**规划阶段的测试合约**。在规划时就决定"这个功能怎么证明它对了"，实现时按合约交付代码和测试。

**每个功能的 verify_commands 必须包含两层：**

1. **代码检查**（编译/类型检查） — 证明代码在语法和类型层面是正确的
2. **测试执行**（单元测试或集成测试） — 证明功能的行为是正确的

**规划阶段写 verify_commands 时，必须指明要验证的具体测试文件：**

```json
// Node/TS 项目
"verify_commands": [
  "npx tsc --noEmit",
  "npx jest tests/AddTask.test.tsx"
]

// Java 项目
"verify_commands": [
  "./gradlew compileJava",
  "./gradlew test --tests com.example.AddTaskTest"
]

// Python 项目
"verify_commands": [
  "python -m py_compile src/todo/add.py",
  "pytest tests/test_add.py -x"
]
```

这样做的效果：执行者看到 `npx jest tests/AddTask.test.tsx`，就知道必须编写 `tests/AddTask.test.tsx`，而且测试必须通过。**测试文件是交付物，不是可选项。**

### verify_commands 锁定（seal）

规划完成后，必须运行 `python .cc-dev-framework/seal.py` 锁定 verify_commands。

seal.py 计算每个 feature 的 verify_commands 的 SHA-256 hash，存入 `verify_commands_hash` 字段。之后 verify.py 门禁会检查 hash 是否一致——如果执行者修改了 verify_commands，hash 不匹配，门禁直接 FAIL。

**规划完成的标准流程：**
1. 写好 features.json（含两层 verify_commands）
2. 运行 `python .cc-dev-framework/seal.py`
3. 确认所有 feature 都被 SEAL
4. 然后才开始实现

**原则：verify_commands 在规划时定死并锁定。执行阶段不能修改，只能达标。**

### type 字段

| 值 | 含义 |
|---|------|
| `feature` | 新功能（默认） |
| `bugfix` | 修复已有功能的 bug |
| `improvement` | 改进已有功能 |

---

## 7. 迭代与归档

一轮迭代的所有功能完成后，归档已完成功能，为下一轮迭代腾出空间：

```bash
python .cc-dev-framework/archive.py
```

此命令会：
- 将 features.json 中所有 `completed` 的功能移到 `.cc-dev-framework/archive/vN.json`
- features.json 只保留未完成的功能（通常为空，准备下一轮规划）

### 归档后开始新迭代

1. 用户提出新需求
2. 在 features.json 中规划新功能
3. 正常走 分支 → 编码 → 门禁 → 合并 流程

### 不要手动管理归档

- 归档由 `archive.py` 脚本完成
- 不要手动移动 features.json 中的内容
- 不要修改已归档的 vN.json 文件

---

## 8. 进度日志（跨会话记忆）

`.cc-dev-framework/progress.json` 是你的跨会话记忆文件：

- **每完成一个功能**，追加一条记录：完成了什么、下一步做什么
- **每次会话结束前**，追加当前进度摘要
- **每次会话启动时**，读取此文件 + `status.py` 输出，快速恢复上下文

每次追加一条 session 记录到 `sessions` 数组：
```json
{
  "date": "2025-01-15",
  "completed": ["add-task"],
  "in_progress": "list-tasks",
  "current_step": 1,
  "summary": "完成了添加任务功能，通过门禁。开始列表功能，step 0 完成。",
  "next": "继续 list-tasks 的 step 1",
  "blockers": []
}
```

**这是你与下一次会话的自己沟通的方式。写清楚，下次恢复更快。**

---

## 9. 恢复与重试

- 运行 `python .cc-dev-framework/status.py` 获取恢复信息
- 读取 `.cc-dev-framework/progress.json` 了解上次会话做了什么
- `in_progress` 功能：从第一个 `done: false` 的 step 继续
- `failed` 功能：查看 `error` 和 gate_checks 了解失败原因，修复后重新 verify

---

## 10. Shell / 平台规则

- Windows 环境：使用 `python` 而不是 `python3`
- 不要使用 heredoc（`<<EOF`）
- 路径用 `/` 或 `\\`
- 多行写入用 Python 脚本

---

## 11. 环境问题处理

当 verify_commands 依赖的工具无法运行时（npm install 失败、gradle 报错、依赖缺失等）：

1. **停下来。** 不要继续写代码
2. **报告阻塞。** 明确告诉用户：哪个命令失败了、错误信息是什么
3. **修复环境。** 与用户一起解决（配置 npm token、修复路径、安装依赖等）
4. **环境修好后再继续**

**绝对禁止：把"环境跑不了"当作降级 verify_commands 的理由。**
- npm install 失败 → 不能把 `npx tsc --noEmit` 换成 `test -f xxx.tsx`
- gradle 路径有问题 → 不能把 `./gradlew compileJava` 换成 `ls build/`
- 任何时候把编译/测试验证降级为文件存在性检查，都是错误的

verify_commands 写在规划阶段，是承诺要达到的验证标准。实现阶段遇到困难不能降低标准，只能解决困难。

---

## 12. 用户上下文

用户在对话中提供的项目信息（部署方式、CI/CD、技术约束等）是重要上下文：

- **记住并遵守用户说的约束。** 如果用户说"代码推送即自动部署"，不要问部署相关的问题
- **用户上下文不能替代本地验证。** CI 在 push 之后运行，verify_commands 在 commit 之前运行——它们是不同的检查点。即使有 CI，本地 verify_commands 仍然必须有意义
- **有疑问时回看对话历史。** 不要忽略用户之前说过的信息

---

## 13. 禁止事项

- 禁止跳过 verify 直接标记 completed
- 禁止自己判定"验证通过"（只有脚本能判）
- 禁止 step 标记 done 但不填 evidence
- 禁止同时处理多个功能
- 禁止无视 RESUME 信息
- 禁止在 main 分支上直接开发
- 禁止 GATE FAILED 时 merge
- 禁止手动修改 done_evidence（由脚本写入）
- **禁止在实现阶段修改 verify_commands**（已被 seal.py hash 锁定，verify.py 会检测篡改）
- **禁止忽略用户在对话中提供的项目信息**

---

## 14. Orchestrator 模式

当由 `orchestrator.py` 调用时，你通过 `--append-system-prompt` 接收角色指令（Planner / Executor / Fixer）。

**在 orchestrator 模式下：**

- orchestrator 负责调用 start.py / verify.py / complete.py / archive.py
- 你只做 orchestrator 要求的事：
  - **Planner**：分析项目，输出 features.json 的 JSON
  - **Executor**：逐步实现代码，每完成一步调 `step.py` 记录证据
  - **Fixer**：根据 verify 失败的错误信息修复代码
- **不要运行** verify.py / complete.py / archive.py（orchestrator 会处理）
- **不要直接修改** features.json（用 step.py 记录步骤进度）
- 实现阶段每完成一步必须调用 `python .cc-dev-framework/step.py -f <id> -s <N> -e "evidence"`

### 启动方式

```bash
python .cc-dev-framework/orchestrator.py [options]
  --auto-approve     跳过规划审批
  --max-retries N    verify 失败最多重试次数（默认 3）
  --goal "text"      覆盖 goal
  --feature ID       只处理指定 feature
  --dry-run          查看执行计划（不实际调用 Claude）
```
