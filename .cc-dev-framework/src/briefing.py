"""上下文压缩 — 为 Claude Code 调用生成聚焦的简报。

用单次上下文注入（~3000 tokens）替代多轮探索。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from store import (
    ARCHIVE_DIR,
    Feature,
    load_archive,
    load_feature_objects,
    load_features,
    list_archives,
)

# Maximum characters per briefing section
_MAX_TREE_CHARS = 3000
_MAX_CONFIG_CHARS = 2000
_MAX_ARCHIVE_CHARS = 2000
_MAX_TOTAL_CHARS = 12000


# ---------------------------------------------------------------------------
# Directory tree
# ---------------------------------------------------------------------------

def _dir_tree(project_dir: Path, max_depth: int = 3) -> str:
    """Generate a compact directory tree string, excluding common noise."""
    ignore = {
        ".git", "node_modules", "__pycache__", ".venv", "venv",
        ".tox", ".mypy_cache", ".pytest_cache", "dist", "build",
        ".next", ".nuxt", "target", ".gradle", ".idea", ".vscode",
        ".cc-dev-framework", "archive",
    }
    lines: list[str] = []

    def _walk(path: Path, prefix: str, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name))
        except PermissionError:
            return
        dirs = [e for e in entries if e.is_dir() and e.name not in ignore]
        files = [e for e in entries if e.is_file()]

        for f in files:
            lines.append(f"{prefix}{f.name}")
        for d in dirs:
            lines.append(f"{prefix}{d.name}/")
            _walk(d, prefix + "  ", depth + 1)

    _walk(project_dir, "", 0)
    tree = "\n".join(lines)
    if len(tree) > _MAX_TREE_CHARS:
        tree = tree[:_MAX_TREE_CHARS] + "\n...（已截断）"
    return tree


# ---------------------------------------------------------------------------
# Config file snippets
# ---------------------------------------------------------------------------

_CONFIG_FILES = [
    "package.json", "tsconfig.json", "pyproject.toml", "setup.py", "setup.cfg",
    "Cargo.toml", "build.gradle", "build.gradle.kts", "pom.xml",
    "requirements.txt", "Makefile", "CMakeLists.txt", "go.mod",
]


def _read_configs(project_dir: Path) -> str:
    """Read key config files, truncated."""
    parts: list[str] = []
    total = 0
    for name in _CONFIG_FILES:
        path = project_dir / name
        if path.exists() and path.is_file():
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
                if len(content) > 800:
                    content = content[:800] + "\n...（已截断）"
                parts.append(f"--- {name} ---\n{content}")
                total += len(parts[-1])
                if total > _MAX_CONFIG_CHARS:
                    break
            except Exception:
                continue
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Archive summary
# ---------------------------------------------------------------------------

def _archive_summary() -> str:
    """Summarize archived features to avoid re-planning them."""
    archives = list_archives()
    if not archives:
        return "没有已归档的迭代。"

    lines: list[str] = []
    for a in archives:
        ver = a.replace(".json", "")
        data = load_archive(ver)
        feats = data.get("features", [])
        lines.append(f"{ver}: {len(feats)} 个 feature")
        for f in feats:
            fid = f.get("id", "?")
            title = f.get("title", "?")
            lines.append(f"  - {fid}: {title}")

    text = "\n".join(lines)
    if len(text) > _MAX_ARCHIVE_CHARS:
        text = text[:_MAX_ARCHIVE_CHARS] + "\n...（已截断）"
    return text


# ---------------------------------------------------------------------------
# dev.sh content
# ---------------------------------------------------------------------------

def _read_dev_sh(project_dir: Path) -> str:
    """Read dev.sh content for executor context."""
    # dev.sh is in the framework dir, not project dir
    framework_dir = Path(__file__).parent.parent
    dev_sh = framework_dir / "dev.sh"
    if not dev_sh.exists():
        return "（未找到 dev.sh）"
    try:
        content = dev_sh.read_text(encoding="utf-8", errors="replace").strip()
        # Check if it's still the unconfigured template
        if "尚未配置" in content:
            return "（dev.sh 尚未配置）"
        return f"```bash\n{content}\n```"
    except Exception:
        return "（无法读取 dev.sh）"


def _read_init_sh() -> str:
    """Read init.sh content for executor context."""
    framework_dir = Path(__file__).parent.parent
    init_sh = framework_dir / "init.sh"
    if not init_sh.exists():
        return "（未找到 init.sh）"
    try:
        content = init_sh.read_text(encoding="utf-8", errors="replace").strip()
        if "not configured yet" in content.lower() or "尚未配置" in content:
            return "（init.sh 尚未配置）"
        return f"```bash\n{content}\n```"
    except Exception:
        return "（无法读取 init.sh）"


def _read_cleanup_sh() -> str:
    """Read cleanup.sh content for executor/e2e_tester context."""
    framework_dir = Path(__file__).parent.parent
    cleanup_sh = framework_dir / "cleanup.sh"
    if not cleanup_sh.exists():
        return "（未找到 cleanup.sh）"
    try:
        content = cleanup_sh.read_text(encoding="utf-8", errors="replace").strip()
        if "not configured yet" in content.lower() or "尚未配置" in content:
            return "（cleanup.sh 尚未配置）"
        return f"```bash\n{content}\n```"
    except Exception:
        return "（无法读取 cleanup.sh）"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_planner_briefing(project_dir: Path, goal: str) -> str:
    """生成 Planner 上下文：目录树、配置文件、归档摘要、规则提醒。

    目标：~3000 tokens（~12000 字符）。
    """
    tree = _dir_tree(project_dir)
    configs = _read_configs(project_dir)
    archive = _archive_summary()

    briefing = f"""\
## 项目目录结构
```
{tree}
```

## 配置文件
{configs if configs else "（未找到标准配置文件）"}

## 历史迭代（已归档的 feature —— 不要重复实现）
{archive}

## 规划规则提醒
- 每个 feature 是可独立验证的功能单元
- 步骤粒度：一次 AI 对话能做好的工作量
- verify_commands 至少 1 条，建议包含构建检查 + 测试
- ID：kebab-case，priority 唯一
- 如果 init.sh / dev.sh 未配置，安排步骤填写
- 不要设置 verify_commands_hash
"""

    if len(briefing) > _MAX_TOTAL_CHARS:
        briefing = briefing[:_MAX_TOTAL_CHARS] + "\n...（已截断）"
    return briefing


def generate_executor_briefing(
    project_dir: Path,
    feature: Feature,
    start_step: int = 0,
) -> str:
    """生成 Executor 上下文：feature 详情、步骤状态、目录树。

    目标：~3000 tokens（~12000 字符）。
    """
    # Feature details
    steps_text = ""
    for i, s in enumerate(feature.steps):
        marker = "x" if s.done else " "
        current = " <-- 从这里开始" if i == start_step and not s.done else ""
        evidence = f" | {s.evidence}" if s.evidence else ""
        steps_text += f"  [{marker}] {i}: {s.description}{evidence}{current}\n"

    vc_text = "\n".join(f"  {cmd}" for cmd in feature.verify_commands)

    tree = _dir_tree(project_dir, max_depth=2)
    dev_sh = _read_dev_sh(project_dir)
    init_sh = _read_init_sh()
    cleanup_sh = _read_cleanup_sh()

    briefing = f"""\
## Feature: {feature.id}
标题: {feature.title}
类型: {feature.type}
优先级: {feature.priority}

## 步骤
{steps_text}
## verify_commands（不要修改）
{vc_text}

## 项目启动方式（dev.sh）
{dev_sh}

## 依赖安装（init.sh）
{init_sh}

## 进程清理（cleanup.sh）
{cleanup_sh}

## 项目结构
```
{tree}
```

## 提醒
- 每完成一个步骤后运行 \
`python .cc-dev-framework/src/step.py -f {feature.id} -s <N> -e "完成证据"`。
- 不要运行 verify.py / complete.py / archive.py。
- 编写 verify_commands 中引用的测试文件。
- 所有步骤完成后输出 EXECUTOR_DONE。
"""

    if len(briefing) > _MAX_TOTAL_CHARS:
        briefing = briefing[:_MAX_TOTAL_CHARS] + "\n...（已截断）"
    return briefing


def generate_preparer_briefing(project_dir: Path, goal: str) -> str:
    """生成 Preparer 上下文：用户目标 + 目录树 + 配置文件。

    不包含归档信息（准备阶段不关心历史）。
    """
    tree = _dir_tree(project_dir, max_depth=2)
    configs = _read_configs(project_dir)

    briefing = f"""\
## 用户目标
{goal}

## 项目目录结构
```
{tree}
```

## 配置文件
{configs if configs else "（未找到标准配置文件）"}
"""

    if len(briefing) > _MAX_TOTAL_CHARS:
        briefing = briefing[:_MAX_TOTAL_CHARS] + "\n...（已截断）"
    return briefing


def generate_e2e_briefing(project_dir: Path, feature: Feature) -> str:
    """生成 E2E 测试简报：feature 详情 + dev.sh + 项目树。

    提供 feature 的完整信息，以及如何启动项目。
    """
    steps_text = ""
    for i, s in enumerate(feature.steps):
        marker = "x" if s.done else " "
        evidence = f" | {s.evidence}" if s.evidence else ""
        steps_text += f"  [{marker}] {i}: {s.description}{evidence}\n"

    vc_text = "\n".join(f"  {cmd}" for cmd in feature.verify_commands)
    tree = _dir_tree(project_dir, max_depth=2)
    dev_sh = _read_dev_sh(project_dir)
    cleanup_sh = _read_cleanup_sh()

    briefing = f"""\
## Feature: {feature.id}
标题: {feature.title}
类型: {feature.type}

## 步骤
{steps_text}
## verify_commands（已全部通过）
{vc_text}

## 项目启动方式（dev.sh）
{dev_sh}

## 进程清理（cleanup.sh）
{cleanup_sh}

## 项目结构
```
{tree}
```

## 提醒
- 你是 E2E 测试专员，只负责测试，不要修改代码
- 机械验证已经通过（编译 + 单元测试），现在需要验证功能逻辑
- 测试完成后在最后一行输出 E2E_PASSED / E2E_SKIPPED / E2E_FAILED
"""

    if len(briefing) > _MAX_TOTAL_CHARS:
        briefing = briefing[:_MAX_TOTAL_CHARS] + "\n...（已截断）"
    return briefing
