# cc-dev-framework — 框架内部文档

> 本文件是框架内部参考文档，供开发者和维护者阅读。
> Claude Code 不会自动读取本文件。AI 的行为由 `orchestrator.py` + `prompts.py` 控制。

---

## 架构概述

```
用户 → python orchestrator.py --goal "..." → Claude Code -p (AI) + 脚本 (验证)
```

orchestrator.py 是主入口，控制完整工作流：

| 阶段 | 执行者 | 做什么 |
|------|--------|--------|
| INIT | orchestrator | git init + init.sh |
| RESUME | orchestrator | 检测 in_progress feature，恢复执行 |
| PLAN | Claude (Planner) | 分析项目，输出 features.json |
| validate | validate_plan.py | 机械检查规划质量 |
| seal | store.py | hash 锁定 verify_commands |
| EXECUTE | Claude (Executor) | 逐步实现代码，调 step.py 记录证据 |
| VERIFY | verify.py | 5 项门禁检查 |
| FIX | Claude (Fixer) | 根据 verify 失败修复代码 |
| COMPLETE | complete.py | commit + merge + 标记 completed |
| ARCHIVE | archive.py | 完成的 feature 移入 vN.json |

---

## 脚本清单

| 脚本 | 用途 | 由谁调用 |
|------|------|----------|
| `orchestrator.py` | 主入口，驱动全流程 | 用户 |
| `prompts.py` | Planner/Executor/Fixer 角色 prompt | orchestrator |
| `briefing.py` | 上下文压缩，注入项目信息 | orchestrator |
| `validate_plan.py` | 规划质量门禁（8 项检查） | orchestrator |
| `store.py` | 数据模型 + 原子读写 features.json | 所有脚本 |
| `verify.py` | 5 项门禁检查 | orchestrator |
| `seal.py` | 计算 verify_commands hash | orchestrator / store.py |
| `start.py` | 建 feature 分支 + 设 in_progress | orchestrator |
| `step.py` | 标记步骤完成 + 写证据 | Claude (Executor) |
| `complete.py` | verify → commit → merge → completed | orchestrator |
| `archive.py` | 归档已完成 feature 到 vN.json | orchestrator |
| `status.py` | 显示进度（独立使用） | 用户 |
| `init.sh` | 项目环境初始化（依赖 + 冒烟测试） | orchestrator |

---

## 核心概念

### features.json 结构

```json
{
  "project": "project-name",
  "goal": "目标描述",
  "features": [
    {
      "id": "kebab-case-id",
      "title": "Feature Title",
      "priority": 1,
      "status": "pending | in_progress | completed | failed",
      "type": "feature | bugfix | improvement",
      "steps": [
        {"description": "...", "done": false, "evidence": null}
      ],
      "verify_commands": ["compile cmd", "test cmd"],
      "verify_commands_hash": "seal 后写入",
      "done_evidence": { "verify_results": [], "gate_checks": [], "all_passed": false, "verified_at": null },
      "commit_hash": null,
      "error": null
    }
  ]
}
```

### verify_commands — 测试合约

verify_commands 是规划阶段定下的测试合约，而非事后验收。

**两层要求：**
1. **代码检查**（编译/类型检查）— 语法和类型正确性
2. **测试执行**（指定具体测试文件）— 行为正确性

```json
// Python 项目示例
"verify_commands": [
  "python -m py_compile src/todo/add.py",
  "pytest tests/test_add.py -x"
]

// Node/TS 项目示例
"verify_commands": [
  "npx tsc --noEmit",
  "npx jest tests/AddTask.test.tsx"
]
```

测试文件是交付物。Executor 看到 `pytest tests/test_add.py` 就知道必须编写该文件且测试必须通过。

### hash 锁定

`seal.py` 在规划完成后计算每个 feature 的 verify_commands SHA-256 hash（16 字符），存入 `verify_commands_hash`。verify.py 门禁检查 hash 一致性——执行阶段若修改 verify_commands，hash 不匹配，门禁 FAIL。

### 5 项门禁 (verify.py)

1. **steps_done** — 所有步骤标记 done
2. **steps_evidence** — 每个 done 步骤有 evidence
3. **verify_integrity** — verify_commands hash 匹配
4. **verify_commands** — 所有命令 exit 0
5. **git_branch** — 在正确的 feature 分支上

### 规划质量门禁 (validate_plan.py)

1. JSON 结构正确
2. feature 数量 2-8
3. step 数量 2-6
4. verify_commands 至少 2 条（编译 + 测试）
5. ID 为 kebab-case
6. 无重复 ID
7. 无重复 priority
8. 首轮首个 feature 必须是 `project-setup`

---

## 使用方式

```bash
python .cc-dev-framework/orchestrator.py [options]

选项：
  --goal "text"      项目目标
  --auto-approve     跳过规划审批
  --max-retries N    verify 失败重试次数（默认 3）
  --feature ID       只处理指定 feature
  --dry-run          查看执行计划，不调用 Claude
```

---

## 平台说明

- Windows：使用 `python` 而非 `python3`
- Windows：脚本内用 `sys.stdout.reconfigure(encoding="utf-8")` 处理编码
- init.sh 路径传给 bash 时用 `as_posix()` 转换
- features.json 写入用原子操作（temp file + rename）
