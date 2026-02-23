#!/bin/bash
# 清理脚本 — 在 feature 合并前杀掉所有后台进程。
#
# 作用：
#   1. 杀掉开发过程中启动的后台进程（uvicorn, node, etc.）
#   2. 释放被锁定的文件（如 SQLite .db 文件）
#
# cleanup.sh not configured yet.
# Executor 在开发过程中按需填写。

# 示例：
# pkill -f uvicorn || true
# pkill -f "node.*dev" || true
# lsof -ti:8000 | xargs kill -9 2>/dev/null || true
# lsof -ti:3000 | xargs kill -9 2>/dev/null || true

exit 0
