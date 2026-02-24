"""cc-dev-framework 主入口 — Python 编排工作流。

以 Python 控制流为主，Claude Code -p 做 AI 工作，脚本做机械验证。

Usage:
  python .cc-dev-framework/main.py [options]

Options:
  --auto-approve     跳过规划审批（默认：询问用户）
  --max-retries N    验证失败后的最大修复重试次数（默认 3，即首次验证 + 3 次修复）
  --max-e2e-retries N  E2E 失败后的最大修复重试次数（默认 2，即首次 E2E + 2 次修复）
  --goal "text"      覆盖目标（否则从 features.json 或交互输入获取）
  --feature ID       只处理指定 feature
  --dry-run          只展示执行计划，不实际调用 Claude
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
from datetime import date
from pathlib import Path

# Windows encoding fix — use reconfigure to avoid double-wrap issues
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

FRAMEWORK_DIR = Path(__file__).parent
sys.path.insert(0, str(FRAMEWORK_DIR / "src"))
sys.path.insert(0, str(FRAMEWORK_DIR / "roles"))
sys.path.insert(0, str(FRAMEWORK_DIR / "utils"))
from briefing import (
    generate_e2e_briefing,
    generate_executor_briefing,
    generate_planner_briefing,
    generate_preparer_briefing,
)
from log import get_logger, setup_logging
from planner import PLANNER_PROMPT
from executor import EXECUTOR_PROMPT
from fixer import FIX_PROMPT, FIX_E2E_PROMPT
from preparer import PREPARER_PROMPT
from e2e_tester import E2E_TESTER_PROMPT
from store import (
    Feature,
    get_feature,
    load_feature_objects,
    load_features,
    save_features,
    update_feature_field,
)
from validate_plan import validate_plan

PROJECT_DIR = FRAMEWORK_DIR.parent
PROGRESS_PATH = FRAMEWORK_DIR / "progress.json"

# Claude command timeout (seconds)
CLAUDE_TIMEOUT = 600  # 10 minutes

logger = get_logger("main")


# ===================================================================
# Signal handling — save state on SIGINT
# ===================================================================

_interrupted = False


def _handle_sigint(signum, frame):
    global _interrupted
    _interrupted = True
    msg = "被用户中断，正在保存状态..."
    print(f"\n[main] {msg}")
    logger.warning(msg)
    _save_progress("被用户中断", [])
    print()
    print("  重新运行即可从断点恢复:")
    print("    python .cc-dev-framework/main.py")
    sys.exit(130)


signal.signal(signal.SIGINT, _handle_sigint)


# ===================================================================
# Core: call Claude Code -p
# ===================================================================

def call_claude(
    prompt: str,
    max_turns: int = 10,
    allowed_tools: str | None = None,
    system_append: str | None = None,
) -> dict:
    """Call Claude Code in print mode.

    Always streams output to terminal in real-time (Popen + tee).
    Callers that need JSON should use _extract_json_from_output() on result.

    Returns dict with keys: result, cost, duration, is_error
    """
    cmd = [
        "claude",
        "-p", prompt,
        "--max-turns", str(max_turns),
    ]

    if allowed_tools:
        cmd.extend(["--allowedTools", allowed_tools])

    if system_append:
        cmd.extend(["--append-system-prompt", system_append])

    cmd.append("--dangerously-skip-permissions")

    # Remove CLAUDE_CODE environment variable to prevent nested-call blocking
    env = os.environ.copy()
    env.pop("CLAUDE_CODE", None)
    env.pop("CLAUDECODE", None)

    msg = f"正在调用 Claude (max_turns={max_turns})..."
    print(f"[main] {msg}")
    logger.info(msg)

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(PROJECT_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
        )
        collected_lines: list[str] = []
        try:
            for raw_line in proc.stdout:
                try:
                    line = raw_line.decode("utf-8", errors="replace")
                except Exception:
                    line = str(raw_line)
                sys.stdout.write(line)
                sys.stdout.flush()
                stripped = line.rstrip("\n\r")
                if stripped:
                    logger.info("[claude] %s", stripped)
                collected_lines.append(line)
            proc.wait(timeout=CLAUDE_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            logger.error("Claude 超时 (%ds)", CLAUDE_TIMEOUT)
            return {
                "result": "".join(collected_lines),
                "cost": None,
                "duration": CLAUDE_TIMEOUT,
                "is_error": True,
                "error": f"Claude 超时 ({CLAUDE_TIMEOUT}s)",
            }

        return {
            "result": "".join(collected_lines),
            "cost": None,
            "duration": 0,
            "is_error": proc.returncode != 0,
        }
    except FileNotFoundError:
        msg = "找不到 claude 命令。请确认 Claude Code CLI 已安装。"
        logger.error(msg)
        return {
            "result": "",
            "cost": None,
            "duration": 0,
            "is_error": True,
            "error": msg,
        }


# ===================================================================
# Script runners
# ===================================================================

def run_script(name: str, *args: str) -> int:
    """Run a framework script. Capture output, print to terminal, write to log.

    Returns exit code.
    """
    script = FRAMEWORK_DIR / name
    cmd = [sys.executable, str(script)] + list(args)
    msg = f"运行脚本: {name} {' '.join(args)}"
    print(f"[main] {msg}")
    logger.info(msg)
    proc = subprocess.run(
        cmd, cwd=str(PROJECT_DIR),
        capture_output=True,
        encoding="utf-8", errors="replace",
    )
    output = (proc.stdout + proc.stderr).strip()
    if output:
        print(output)
        for line in output.split("\n"):
            logger.info("[%s] %s", name, line)
    if proc.returncode != 0:
        logger.error("脚本 %s 退出码 %d", name, proc.returncode)
    return proc.returncode


def run_script_capture(name: str, *args: str) -> tuple[int, str]:
    """Run a framework script, capture output. Returns (exit_code, output)."""
    script = FRAMEWORK_DIR / name
    cmd = [sys.executable, str(script)] + list(args)
    msg = f"运行脚本: {name} {' '.join(args)}"
    print(f"[main] {msg}")
    logger.info(msg)
    proc = subprocess.run(
        cmd, cwd=str(PROJECT_DIR),
        capture_output=True,
        encoding="utf-8", errors="replace",
    )
    output = (proc.stdout + proc.stderr).strip()
    for line in output.split("\n"):
        logger.info("[%s] %s", name, line)
    if proc.returncode != 0:
        logger.error("脚本 %s 退出码 %d", name, proc.returncode)
    return proc.returncode, output


def run_init() -> bool:
    """Run init.sh. Returns True on success."""
    init_script = FRAMEWORK_DIR / "init.sh"
    if not init_script.exists():
        msg = "警告: 未找到 init.sh，跳过"
        print(f"[main] {msg}")
        logger.warning(msg)
        return True

    msg = "正在运行 init.sh..."
    print(f"[main] {msg}")
    logger.info(msg)
    # Use relative path from PROJECT_DIR to avoid WSL bash failing on
    # absolute Windows paths like "D:/cc/..." which it can't resolve.
    try:
        rel_path = init_script.relative_to(PROJECT_DIR)
    except ValueError:
        rel_path = init_script
    proc = subprocess.run(
        ["bash", rel_path.as_posix()],
        cwd=str(PROJECT_DIR),
        capture_output=True,
        encoding="utf-8", errors="replace",
    )
    output = (proc.stdout + proc.stderr).strip()
    if output:
        for line in output.split("\n"):
            print(f"  [init.sh] {line}")
            logger.info("[init.sh] %s", line)
    if proc.returncode != 0:
        msg = "错误: init.sh 执行失败"
        print(f"[main] {msg}")
        logger.error(msg)
        return False
    msg = "init.sh 执行成功"
    print(f"[main] {msg}")
    logger.info(msg)
    return True


def _ensure_git_repo() -> bool:
    """Initialize git repo if not already one. Returns True on success."""
    proc = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=str(PROJECT_DIR),
        capture_output=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode == 0:
        return True  # Already a git repo

    msg = "未检测到 git 仓库，正在初始化..."
    print(f"[main] {msg}")
    logger.info(msg)
    proc = subprocess.run(
        ["git", "init"],
        cwd=str(PROJECT_DIR),
        encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        msg = "错误: git init 失败"
        print(f"[main] {msg}")
        logger.error(msg)
        return False

    # Initial commit so branches can be created
    proc = subprocess.run(
        ["git", "add", "-A"],
        cwd=str(PROJECT_DIR),
        capture_output=True, encoding="utf-8", errors="replace",
    )
    proc = subprocess.run(
        ["git", "commit", "-m", "chore: initial commit", "--allow-empty"],
        cwd=str(PROJECT_DIR),
        capture_output=True, encoding="utf-8", errors="replace",
    )
    msg = "git 仓库已初始化。"
    print(f"[main] {msg}")
    logger.info(msg)
    return True


# ===================================================================
# Verify error extraction
# ===================================================================

def extract_verify_errors(output: str) -> dict:
    """Parse verify.py output into structured error info.

    Matches Chinese output from verify.py:
      - "验证失败" for gate failure summary
      - "失败的命令:" for failed commands block
      - [FAIL] tags kept in English (international convention)

    Returns:
        {
            "summary": "验证失败（N 项检查未通过）",
            "failed_gates": ["gate_name: detail", ...],
            "failed_commands": [{"command": "...", "exit_code": N, "output": "..."}, ...],
        }
    """
    result: dict = {
        "summary": "",
        "failed_gates": [],
        "failed_commands": [],
    }

    # Extract summary line
    for line in output.split("\n"):
        if "验证失败" in line:
            result["summary"] = line.strip()
            break

    # Extract [FAIL] gates
    for line in output.split("\n"):
        m = re.match(r"\s*\[FAIL\]\s+(.*)", line)
        if m:
            result["failed_gates"].append(m.group(1))

    # Extract failed commands block
    in_failed = False
    current_cmd: dict | None = None
    for line in output.split("\n"):
        if line.strip() == "失败的命令:":
            in_failed = True
            continue
        if in_failed:
            m_cmd = re.match(r"\s+\$ (.+)", line)
            m_exit = re.match(r"\s+exit=(\d+|-?\d+)", line)
            if m_cmd:
                if current_cmd:
                    result["failed_commands"].append(current_cmd)
                current_cmd = {"command": m_cmd.group(1), "exit_code": 0, "output": ""}
            elif m_exit and current_cmd:
                current_cmd["exit_code"] = int(m_exit.group(1))
            elif current_cmd and line.startswith("    "):
                current_cmd["output"] += line.strip() + "\n"
        if current_cmd and not line.startswith(" ") and line.strip() and in_failed:
            result["failed_commands"].append(current_cmd)
            current_cmd = None
            in_failed = False

    if current_cmd:
        result["failed_commands"].append(current_cmd)

    return result


# ===================================================================
# E2E output parsing
# ===================================================================

def _parse_e2e_result(output: str) -> tuple[str, str]:
    """Parse E2E tester output for result marker.

    Scans the last 20 lines for E2E_PASSED / E2E_SKIPPED / E2E_FAILED.

    Returns:
        (result, detail) where result is "passed", "skipped", or "failed".
        "skipped" is logically equivalent to "passed" (→ complete).
    """
    lines = output.strip().split("\n")
    # Search from the end
    for line in reversed(lines[-20:]):
        stripped = line.strip()
        if stripped == "E2E_PASSED":
            return "passed", ""
        if stripped.startswith("E2E_SKIPPED:"):
            detail = stripped[len("E2E_SKIPPED:"):].strip()
            return "skipped", detail
        if stripped == "E2E_SKIPPED":
            return "skipped", ""
        if stripped.startswith("E2E_FAILED:"):
            detail = stripped[len("E2E_FAILED:"):].strip()
            return "failed", detail

    # No marker found — treat as failed (not skipped)
    return "failed", "E2E 测试未输出结果标记"


# ===================================================================
# User interaction
# ===================================================================

def prompt_user_goal() -> str:
    """Ask user for the project goal interactively."""
    print()
    print("=" * 60)
    print("  请输入本轮迭代的目标：")
    print("=" * 60)
    try:
        goal = input("> ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(130)
    if not goal:
        msg = "未提供目标，退出。"
        print(f"[main] {msg}")
        logger.warning(msg)
        sys.exit(1)
    logger.info("用户输入目标: %s", goal)
    return goal


def prompt_user_approval(plan_data: dict) -> bool:
    """Show plan summary and ask for approval. Returns True if approved."""
    features = plan_data.get("features", [])
    print()
    print("=" * 60)
    print("  规划审批")
    print("=" * 60)
    print(f"  项目: {plan_data.get('project', '?')}")
    print(f"  目标: {plan_data.get('goal', '?')}")
    print(f"  功能数: {len(features)}")
    print()

    for f in features:
        fid = f.get("id", "?")
        title = f.get("title", "?")
        pri = f.get("priority", "?")
        steps = f.get("steps", [])
        vc = f.get("verify_commands", [])
        ftype = f.get("type", "feature")
        type_tag = f" [{ftype}]" if ftype != "feature" else ""

        print(f"  #{pri} {fid}: {title}{type_tag}")
        for i, s in enumerate(steps):
            print(f"      {i}: {s.get('description', '?')}")
        print(f"      验证命令: {', '.join(vc)}")
        print()

    print("=" * 60)
    try:
        answer = input("  批准此计划？[Y/n] > ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False

    approved = answer in ("", "y", "yes")
    logger.info("用户审批结果: %s", "批准" if approved else "拒绝")
    return approved


# ===================================================================
# Progress persistence
# ===================================================================

def _save_progress(summary: str, completed: list[str], in_progress: str | None = None,
                   current_step: int | None = None, blockers: list[str] | None = None) -> None:
    """Append a session entry to progress.json."""
    if PROGRESS_PATH.exists():
        try:
            with open(PROGRESS_PATH, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {"sessions": []}
    else:
        data = {"sessions": []}

    entry = {
        "date": date.today().isoformat(),
        "completed": completed,
        "in_progress": in_progress,
        "current_step": current_step,
        "summary": summary,
        "next": "",
        "blockers": blockers or [],
    }
    data.setdefault("sessions", []).append(entry)

    with open(PROGRESS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")

    logger.info("进度已保存: %s", summary)


# ===================================================================
# Plan extraction from Claude output
# ===================================================================

def _extract_json_from_output(text: str) -> dict | None:
    """Extract JSON from Claude's output (looks for ```json blocks)."""
    # Try to find ```json ... ``` block
    pattern = r"```json\s*\n(.*?)\n\s*```"
    matches = re.findall(pattern, text, re.DOTALL)
    if matches:
        # Use the last match (Claude might output explanations before the JSON)
        for m in reversed(matches):
            try:
                return json.loads(m)
            except json.JSONDecodeError:
                continue

    # Fallback: try parsing the entire text as JSON
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Fallback: find anything that looks like a JSON object
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start >= 0 and brace_end > brace_start:
        try:
            return json.loads(text[brace_start : brace_end + 1])
        except json.JSONDecodeError:
            pass

    return None


# ===================================================================
# Main flow
# ===================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="cc-dev-framework — 驱动 Claude Code 进行规划与执行"
    )
    parser.add_argument("--auto-approve", action="store_true",
                        help="跳过规划审批")
    parser.add_argument("--max-retries", type=int, default=3,
                        help="验证失败后的最大修复重试次数（默认 3，即首次验证 + 3 次修复）")
    parser.add_argument("--max-e2e-retries", type=int, default=2,
                        help="E2E 失败后的最大修复重试次数（默认 2，即首次 E2E + 2 次修复）")
    parser.add_argument("--goal", type=str, default=None,
                        help="覆盖项目目标")
    parser.add_argument("--feature", type=str, default=None,
                        help="只处理指定 feature ID")
    parser.add_argument("--dry-run", action="store_true",
                        help="只展示执行计划，不实际调用 Claude")
    args = parser.parse_args()

    setup_logging()
    logger.info("启动, args=%s", vars(args))

    print()
    print("=" * 60)
    print("  cc-dev-framework 编排器")
    print("=" * 60)
    print()

    # ---------------------------------------------------------------
    # 阶段 1: 初始化
    # ---------------------------------------------------------------
    print("[阶段 1] 正在初始化...")
    logger.info("=== 阶段 1: 初始化 ===")
    if not _ensure_git_repo():
        msg = "错误: 无法初始化 git 仓库，退出。"
        print(f"[main] {msg}")
        logger.error(msg)
        sys.exit(1)

    if not run_init():
        msg = "警告: init.sh 执行失败，继续执行。Executor 将负责环境配置。"
        print(f"[main] {msg}")
        logger.warning(msg)

    # ---------------------------------------------------------------
    # 阶段 2: 断点恢复检查
    # ---------------------------------------------------------------
    print()
    print("[阶段 2] 检查进行中的任务...")
    logger.info("=== 阶段 2: 断点恢复检查 ===")
    raw = load_features()
    all_features = [Feature.from_dict(fd) for fd in raw.get("features", [])]

    resume_feature: Feature | None = None
    for f in all_features:
        if f.status == "in_progress":
            resume_feature = f
            break

    if resume_feature:
        msg = f"恢复执行: {resume_feature.id} ({resume_feature.title})"
        print(f"[main] {msg}")
        logger.info(msg)
        # Skip to execution phase for this feature
        if args.dry_run:
            done = sum(1 for s in resume_feature.steps if s.done)
            print(f"  [dry-run] 将恢复 {resume_feature.id}，从步骤 {done} 开始")
            return
        success = _execute_feature(resume_feature, args.max_retries, args.max_e2e_retries)
        if not success:
            msg = f"Feature {resume_feature.id} 恢复执行失败，停止。"
            print(f"[main] {msg}")
            logger.error(msg)
            _save_progress(
                f"失败: {resume_feature.id}",
                [f.id for f in all_features if f.status == "completed"],
                in_progress=resume_feature.id,
            )
            sys.exit(1)
        # After resuming, fall through to process remaining features
        raw = load_features()
        all_features = [Feature.from_dict(fd) for fd in raw.get("features", [])]

    # ---------------------------------------------------------------
    # 阶段 3: 需求分析
    # ---------------------------------------------------------------
    pending = [f for f in all_features if f.status == "pending"]
    need_planning = len(all_features) == 0 or (
        len(all_features) == 1
        and all_features[0].id == "example-feature"
    )

    # Preparer + Planner only needed when planning is required
    goal = args.goal
    analyzed_requirements = None

    if need_planning:
        # Get goal first (needed for preparer)
        if not goal:
            goal = raw.get("goal", "")
        if not goal:
            if args.dry_run:
                print("  [dry-run] 将询问用户目标")
                return
            goal = prompt_user_goal()

        print()
        print("[阶段 3] 正在准备需求...")
        logger.info("=== 阶段 3: 需求准备 ===")

        if args.dry_run:
            print(f"  [dry-run] 将调用 Preparer 准备需求，目标: {goal}")
        else:
            preparer_briefing = generate_preparer_briefing(PROJECT_DIR, goal)
            preparer_prompt = PREPARER_PROMPT.format(briefing=preparer_briefing)
            system_note = (
                "你是需求准备者。主动转换不友好格式的资料，分析 MCP 工具需求。"
                "只输出一个 JSON 代码块。"
            )
            result = call_claude(
                preparer_prompt,
                max_turns=10,
                allowed_tools="Read,Glob,Grep,Bash",
                system_append=system_note,
            )

            if result.get("is_error"):
                msg = f"错误: Preparer 调用失败: {result.get('error', result.get('result', ''))}"
                print(f"[main] {msg}")
                logger.error(msg)
                sys.exit(1)

            analysis = _extract_json_from_output(result["result"])

            if analysis is None:
                # Preparer failed to produce JSON — log warning but continue with original goal
                msg = "警告: 无法从 Preparer 输出中提取 JSON，使用原始目标继续。"
                print(f"[main] {msg}")
                logger.warning(msg)
                analyzed_requirements = goal
            elif analysis.get("status") == "needs_human":
                print()
                print("=" * 60)
                print("  [准备] 需求资料不足，需要人类补充：")
                print("=" * 60)
                for item in analysis.get("missing", []):
                    print(f"  - {item}")
                for mat in analysis.get("materials", []):
                    if not mat.get("prepared"):
                        print(f"  - {mat['name']}: {mat.get('notes', '无法准备')}")
                # Show MCP tool issues if any
                for tool in analysis.get("mcp_tools", []):
                    if not tool.get("available"):
                        print(f"  - MCP 工具缺失: {tool['name']}（{tool.get('purpose', '')}）")
                print()
                logger.error("需求准备结果: needs_human")
                sys.exit(1)
            else:
                analyzed_requirements = analysis.get("requirements", goal)
                summary = analysis.get("summary", "")
                msg = f"需求准备完成: {summary}"
                print(f"[main] {msg}")
                logger.info(msg)

                # Report MCP tool status
                mcp_tools = analysis.get("mcp_tools", [])
                unavailable_tools = [t for t in mcp_tools if not t.get("available")]
                if unavailable_tools:
                    print("[main] MCP 工具提示（非阻塞）：")
                    for t in unavailable_tools:
                        print(f"  - {t['name']}: {t.get('purpose', '')}（未配置）")
                    logger.info("MCP 工具未配置: %s", [t["name"] for t in unavailable_tools])

        # -----------------------------------------------------------
        # 阶段 4: 规划
        # -----------------------------------------------------------
        print()
        print("[阶段 4] 正在规划...")
        logger.info("=== 阶段 4: 规划 ===")

        if args.dry_run:
            print(f"  [dry-run] 将调用 Claude Planner，目标: {goal}")
            return

        # Use analyzed requirements if available, otherwise original goal
        planner_goal = analyzed_requirements if analyzed_requirements else goal

        # Generate briefing
        briefing = generate_planner_briefing(PROJECT_DIR, planner_goal)

        # Call Claude for planning
        prompt = PLANNER_PROMPT.format(briefing=briefing, goal=planner_goal)
        system_note = (
            "你由编排器 调用。只输出一个 JSON 代码块。"
            "不要运行任何脚本，不要创建文件，只输出规划 JSON。"
        )
        result = call_claude(
            prompt,
            max_turns=10,
            allowed_tools="Read,Glob,Grep",
            system_append=system_note,
        )

        if result.get("is_error"):
            msg = f"错误: Claude 规划失败: {result.get('error', result.get('result', ''))}"
            print(f"[main] {msg}")
            logger.error(msg)
            sys.exit(1)

        # Extract JSON from output
        plan_data = _extract_json_from_output(result["result"])
        if plan_data is None:
            msg = "错误: 无法从 Claude 输出中提取规划 JSON。"
            print(f"[main] {msg}")
            logger.error(msg)
            print("[main] 原始输出（前 2000 字符）:")
            print(result["result"][:2000])
            logger.error("原始输出: %s", result["result"][:2000])
            sys.exit(1)

        # Validate plan
        from store import list_archives
        is_first = len(list_archives()) == 0
        errors = validate_plan(plan_data, is_first_iteration=is_first)

        if errors:
            msg = f"规划验证失败（{len(errors)} 个错误）:"
            print(f"[main] {msg}")
            logger.error(msg)
            for e in errors:
                print(f"  [FAIL] {e}")
                logger.error("  [FAIL] %s", e)

            # Give Claude one retry
            msg = "正在要求 Claude 修复规划..."
            print(f"[main] {msg}")
            logger.info(msg)
            fix_note = (
                "The plan you produced has validation errors:\n"
                + "\n".join(f"- {e}" for e in errors)
                + "\n\nPlease fix these errors and output a corrected JSON code block."
            )
            result = call_claude(
                prompt + "\n\n## Validation Errors\n" + fix_note,
                max_turns=10,
                allowed_tools="Read,Glob,Grep",
                system_append=system_note,
            )

            if result.get("is_error"):
                msg = "错误: Claude 重试失败。"
                print(f"[main] {msg}")
                logger.error(msg)
                sys.exit(1)

            plan_data = _extract_json_from_output(result["result"])
            if plan_data is None:
                msg = "错误: 重试后仍无法提取规划 JSON。"
                print(f"[main] {msg}")
                logger.error(msg)
                sys.exit(1)

            errors = validate_plan(plan_data, is_first_iteration=is_first)
            if errors:
                msg = "重试后规划仍不合格:"
                print(f"[main] {msg}")
                logger.error(msg)
                for e in errors:
                    print(f"  [FAIL] {e}")
                    logger.error("  [FAIL] %s", e)
                sys.exit(1)

        msg = f"规划验证通过: {len(plan_data.get('features', []))} 个 feature"
        print(f"[main] {msg}")
        logger.info(msg)

        # User approval
        if not args.auto_approve:
            if not prompt_user_approval(plan_data):
                msg = "用户拒绝了规划。"
                print(f"[main] {msg}")
                logger.info(msg)
                sys.exit(0)

        # Save plan
        save_features(plan_data)
        msg = "规划已保存。"
        print(f"[main] {msg}")
        logger.info(msg)

        # Reload
        raw = load_features()
        all_features = [Feature.from_dict(fd) for fd in raw.get("features", [])]

    # ---------------------------------------------------------------
    # 阶段 5: 执行
    # ---------------------------------------------------------------
    # Collect actionable features: pending + failed
    actionable = [f for f in all_features if f.status in ("pending", "failed")]

    if not actionable and not resume_feature:
        completed_count = sum(1 for f in all_features if f.status == "completed")
        if completed_count == len(all_features) and all_features:
            print()
            print("[阶段 6] 所有 feature 已完成！")
            logger.info("所有 feature 已完成")
        else:
            msg = "没有待执行的 feature。"
            print(f"[main] {msg}")
            logger.info(msg)
        # Jump to archive
    else:
        pending_count = sum(1 for f in actionable if f.status == "pending")
        failed_count = sum(1 for f in actionable if f.status == "failed")
        print()
        msg = f"正在执行 {len(actionable)} 个 feature（{pending_count} 待处理, {failed_count} 重试）..."
        print(f"[阶段 5] {msg}")
        logger.info("=== 阶段 5: 执行 (%d 个 feature, %d pending, %d failed) ===",
                     len(actionable), pending_count, failed_count)

        # Sort by priority
        actionable.sort(key=lambda f: f.priority)

        if args.feature:
            actionable = [f for f in actionable if f.id == args.feature]
            if not actionable:
                msg = f"Feature '{args.feature}' 未找到或非待执行状态。"
                print(f"[main] {msg}")
                logger.error(msg)
                sys.exit(1)

        if args.dry_run:
            for f in actionable:
                tag = "[重试]" if f.status == "failed" else ""
                print(f"  [dry-run] 将执行: #{f.priority} {f.id} ({f.title}) {tag}")
                for i, s in enumerate(f.steps):
                    print(f"    {i}: {s.description}")
                print(f"    验证命令: {', '.join(f.verify_commands)}")
            print("  [dry-run] 每个 feature 执行后将进行 E2E 测试")
            return

        for feature in actionable:
            success = _execute_feature(feature, args.max_retries, args.max_e2e_retries)
            if not success:
                msg = f"Feature {feature.id} 执行失败，停止执行。"
                print(f"[main] {msg}")
                logger.error(msg)
                _save_progress(
                    f"失败: {feature.id}",
                    [f.id for f in all_features if f.status == "completed"],
                    in_progress=feature.id,
                )
                sys.exit(1)

    # ---------------------------------------------------------------
    # 阶段 6: 归档
    # ---------------------------------------------------------------
    raw = load_features()
    all_features = [Feature.from_dict(fd) for fd in raw.get("features", [])]
    completed = [f for f in all_features if f.status == "completed"]

    if completed and len(completed) == len(all_features):
        print()
        print("[阶段 6] 正在归档已完成的 feature...")
        logger.info("=== 阶段 6: 归档 ===")
        run_script("src/archive.py")

    # ---------------------------------------------------------------
    # 完成
    # ---------------------------------------------------------------
    print()
    completed_ids = [f.id for f in all_features if f.status == "completed"]
    _save_progress(
        f"编排器运行完毕。{len(completed_ids)} 个 feature 已完成。",
        completed_ids,
    )
    msg = "执行完毕。"
    print(f"[main] {msg}")
    logger.info(msg)


# ===================================================================
# Feature execution
# ===================================================================

def _execute_feature(feature: Feature, max_retries: int, max_e2e_retries: int) -> bool:
    """Execute a single feature: start -> code -> verify loop -> E2E loop.

    The verify loop distinguishes two failure modes:
      - steps_done failure -> re-run Executor to complete remaining steps
      - verify_commands failure -> run Fixer to repair code

    After verify passes, runs E2E testing loop:
      - E2E_PASSED / E2E_SKIPPED -> complete
      - E2E_FAILED -> Fixer repairs code -> re-verify -> re-E2E

    Returns True on success, False if retries exhausted.
    """
    print()
    print(f"{'=' * 60}")
    print(f"  正在执行: {feature.id} ({feature.title})")
    print(f"{'=' * 60}")
    logger.info("开始执行 feature: %s (%s)", feature.id, feature.title)

    # Start feature (create branch + set in_progress) if pending or failed
    if feature.status in ("pending", "failed"):
        rc = run_script("src/start.py", "-f", feature.id)
        if rc != 0:
            msg = f"错误: start.py 对 {feature.id} 执行失败"
            print(f"[main] {msg}")
            logger.error(msg)
            update_feature_field(feature.id, status="failed", error="start.py 执行失败")
            return False

    # Run executor for the first time
    _run_executor(feature)

    # --- Verify + retry loop (unified — single implementation) ---
    if not _run_verify_loop(feature, max_retries):
        update_feature_field(feature.id, status="failed",
                             error=f"验证在 {max_retries} 次重试后仍失败")
        return False

    # --- E2E testing loop ---
    # Semantics: first E2E test + up to max_e2e_retries fix-then-retest cycles.
    # So max_e2e_retries=2 means: 1 initial E2E + 2 fix attempts = 3 E2E tests total.

    # Initial E2E test
    msg = f"E2E 测试: {feature.id}"
    print(f"\n[main] {msg}")
    logger.info(msg)

    e2e_result, e2e_detail, e2e_output = _run_e2e_tester(feature)

    if e2e_result in ("passed", "skipped"):
        return _complete_feature(feature, e2e_result, e2e_detail)

    msg = f"E2E 测试失败: {e2e_detail}"
    print(f"\n[main] {msg}")
    logger.error(msg)

    # Fix + re-E2E retries
    for retry in range(max_e2e_retries):
        msg = f"E2E 修复重试 {retry + 1}/{max_e2e_retries}: {feature.id}"
        print(f"\n[main] {msg}")
        logger.info(msg)

        # Reload feature
        feature = get_feature(feature.id)
        if feature is None:
            msg = "错误: feature 已消失"
            print(f"[main] {msg}")
            logger.error(msg)
            return False

        _run_fixer_e2e(feature, e2e_output)

        # Re-verify after fix (fixer may have changed code)
        if not _run_verify_loop(feature, max_retries):
            update_feature_field(feature.id, status="failed",
                                 error="E2E fix 后验证失败")
            return False

        # Re-run E2E test
        e2e_result, e2e_detail, e2e_output = _run_e2e_tester(feature)

        if e2e_result in ("passed", "skipped"):
            return _complete_feature(feature, e2e_result, e2e_detail)

        msg = f"E2E 测试失败: {e2e_detail}"
        print(f"\n[main] {msg}")
        logger.error(msg)

    # E2E retries exhausted
    msg = f"E2E 测试在 {max_e2e_retries} 次修复重试后仍失败"
    print(f"[main] {msg}")
    logger.error(msg)
    update_feature_field(feature.id, status="failed",
                         error=f"E2E 测试在 {max_e2e_retries} 次修复重试后仍失败")
    return False


def _complete_feature(feature: Feature, e2e_result: str, e2e_detail: str) -> bool:
    """Complete a feature after E2E passes/skips. Returns True on success."""
    label = "通过" if e2e_result == "passed" else "无需"
    detail_msg = f"（{e2e_detail}）" if e2e_detail else ""
    msg = f"E2E 测试{label}: {feature.id}{detail_msg}"
    print(f"\n[main] {msg}")
    logger.info(msg)
    commit_msg = f"feat({feature.id}): {feature.title}"
    rc = run_script("src/complete.py", "-f", feature.id, "-m", commit_msg, "--skip-verify")
    if rc != 0:
        msg = f"警告: complete.py 对 {feature.id} 执行失败"
        print(f"[main] {msg}")
        logger.error(msg)
        update_feature_field(feature.id, status="failed", error="complete.py 执行失败")
        return False
    logger.info("feature %s 完成", feature.id)
    return True


def _run_verify_loop(feature: Feature, max_retries: int) -> bool:
    """Run verify + fix loop. Returns True if verify passes.

    Semantics: first verification + up to max_retries fix-then-reverify cycles.
    So max_retries=3 means: 1 initial verify + 3 fix attempts = 4 verifications total.
    """
    # --- Initial verification ---
    msg = f"验证: {feature.id}"
    print(f"\n[main] {msg}")
    logger.info(msg)

    rc, verify_output = run_script_capture("src/verify.py", "-f", feature.id)
    print(verify_output)

    if rc == 0:
        msg = f"验证通过: {feature.id}"
        print(f"\n[main] {msg}")
        logger.info(msg)
        return True

    # --- Fix + re-verify retries ---
    for retry in range(max_retries):
        msg = f"修复重试 {retry + 1}/{max_retries}: {feature.id}"
        print(f"\n[main] {msg}")
        logger.info(msg)

        # Reload feature
        fresh = get_feature(feature.id)
        if fresh is not None:
            feature = fresh

        errors = extract_verify_errors(verify_output)
        failed_gate_names = {g.split(":")[0].strip() for g in errors["failed_gates"]}
        steps_incomplete = "steps_done" in failed_gate_names or "steps_evidence" in failed_gate_names

        if steps_incomplete:
            _run_executor(feature)
        else:
            _run_fixer(feature, verify_output)

        # Re-verify
        rc, verify_output = run_script_capture("src/verify.py", "-f", feature.id)
        print(verify_output)

        if rc == 0:
            msg = f"验证通过: {feature.id}"
            print(f"\n[main] {msg}")
            logger.info(msg)
            return True

    return False


def _run_executor(feature: Feature) -> bool:
    """Call Claude executor to implement feature steps.

    Returns True on success, False if Claude returned an error.
    """
    # Reload to get current step status
    fresh = get_feature(feature.id)
    if fresh is not None:
        feature = fresh

    # Determine start step (first undone)
    start_step = 0
    for i, s in enumerate(feature.steps):
        if not s.done:
            start_step = i
            break
    else:
        # All steps already done — nothing for executor to do
        msg = f"{feature.id} 所有步骤已完成"
        print(f"[main] {msg}")
        logger.info(msg)
        return True

    done_count = sum(1 for s in feature.steps if s.done)
    total = len(feature.steps)
    msg = f"Executor: {feature.id} — 步骤 {start_step}/{total}（已完成 {done_count}）"
    print(f"[main] {msg}")
    logger.info(msg)

    briefing = generate_executor_briefing(PROJECT_DIR, feature, start_step)
    prompt = EXECUTOR_PROMPT.format(
        briefing=briefing,
        feature_id=feature.id,
        start_step=start_step,
    )
    system_note = (
        "你由编排器 以 executor 模式调用。"
        "按步骤实现功能，用 step.py 记录进度。"
        "不要运行 verify.py / complete.py / archive.py。"
    )

    result = call_claude(
        prompt,
        max_turns=30,
        system_append=system_note,
    )

    if result.get("is_error"):
        msg = f"Claude Executor 返回了非零退出码"
        print(f"[main] {msg}")
        logger.error(msg)
        update_feature_field(feature.id, error="Executor 出错")
        # Don't mark failed — verify loop will assess the situation
        return False
    return True


def _run_fixer(feature: Feature, verify_output: str) -> None:
    """Call Claude fixer to repair code based on verify errors."""
    vc_text = "\n".join(f"  {cmd}" for cmd in feature.verify_commands)

    prompt = FIX_PROMPT.format(
        feature_id=feature.id,
        feature_title=feature.title,
        verify_errors=verify_output,
        verify_commands=vc_text,
    )
    system_note = (
        "你由编排器 以 fix 模式调用。"
        "修复代码使 verify_commands 全部通过。"
        "不要运行 verify.py / complete.py，不要修改 verify_commands。"
    )

    logger.info("运行 Fixer: %s", feature.id)
    result = call_claude(
        prompt,
        max_turns=20,
        system_append=system_note,
    )

    if result.get("is_error"):
        msg = "Claude Fixer 返回了非零退出码"
        print(f"[main] {msg}")
        logger.error(msg)


def _run_fixer_e2e(feature: Feature, e2e_output: str) -> None:
    """Call Claude fixer to repair code based on E2E test failure."""
    vc_text = "\n".join(f"  {cmd}" for cmd in feature.verify_commands)

    prompt = FIX_E2E_PROMPT.format(
        feature_id=feature.id,
        feature_title=feature.title,
        e2e_output=e2e_output,
        verify_commands=vc_text,
    )
    system_note = (
        "你由编排器 以 fix 模式调用。"
        "修复 E2E 测试失败的问题，使功能正确工作。"
        "不要运行 verify.py / complete.py，不要修改 verify_commands。"
    )

    logger.info("运行 Fixer (E2E): %s", feature.id)
    result = call_claude(
        prompt,
        max_turns=20,
        system_append=system_note,
    )

    if result.get("is_error"):
        msg = "Claude Fixer (E2E) 返回了非零退出码"
        print(f"[main] {msg}")
        logger.error(msg)


def _run_e2e_tester(feature: Feature) -> tuple[str, str, str]:
    """Run E2E tester for a feature.

    Returns:
        (result, detail, full_output) where result is "passed", "skipped", or "failed".
    """
    # Reload feature
    fresh = get_feature(feature.id)
    if fresh is not None:
        feature = fresh

    msg = f"E2E 测试: {feature.id} ({feature.title})"
    print(f"[main] {msg}")
    logger.info(msg)

    briefing = generate_e2e_briefing(PROJECT_DIR, feature)
    prompt = E2E_TESTER_PROMPT.format(briefing=briefing)
    system_note = (
        "你由编排器 以 E2E 测试模式调用。"
        "执行端到端功能测试，不要修改代码。"
        "完成后在最后一行输出 E2E_PASSED / E2E_SKIPPED / E2E_FAILED。"
    )

    result = call_claude(
        prompt,
        max_turns=30,
        system_append=system_note,
    )

    output = result.get("result", "")

    if result.get("is_error"):
        msg = "Claude E2E Tester 返回了非零退出码"
        print(f"[main] {msg}")
        logger.error(msg)
        # Still try to parse — the marker may have been output before the error
        return *_parse_e2e_result(output), output

    return *_parse_e2e_result(output), output


# ===================================================================
# Entry point
# ===================================================================

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        # SIGINT handler already prints a message; this is a fallback.
        pass
    except Exception as exc:
        # Unexpected crash — print resume hint so user knows they can re-run.
        print()
        print("=" * 60)
        print("  程序异常退出")
        print("=" * 60)
        print(f"  错误: {exc}")

        # Try to show which feature was in progress
        try:
            raw = load_features()
            for fd in raw.get("features", []):
                if fd.get("status") == "in_progress":
                    print(f"  当前 feature: {fd['id']} ({fd.get('title', '')})")
                    break
        except Exception:
            pass

        print()
        print("  重新运行即可从断点恢复:")
        print("    python .cc-dev-framework/main.py")
        print("=" * 60)
        logger.error("异常退出: %s", exc, exc_info=True)
        sys.exit(1)
