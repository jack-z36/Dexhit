#!/usr/bin/env bash
# 安装 acceptance-testing 的四个角色文件到 ~/.codex/agents/。
# 说明：当前 Codex 构建（0.147.0-alpha.6.6）未证实支持 ~/.codex/agents/ 角色文件机制；
# 本脚本是"未来构建支持时"的安装入口，主派发路径不依赖角色文件
# （编排者直接使用 skills/acceptance-testing/references/agent-roles.md 模板组装 message）。
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$SKILL_DIR/agents/codex-roles"
DEST="${CODEX_HOME:-$HOME/.codex}/agents"

if [[ "${1:-}" == "--dry-run" ]]; then
  echo "[dry-run] 将复制:"
  for f in "$SRC"/*.md; do
    echo "  $(basename "$f") -> $DEST/$(basename "$f")"
  done
  exit 0
fi

mkdir -p "$DEST"
for f in "$SRC"/*.md; do
  cp "$f" "$DEST/$(basename "$f")"
  echo "installed: $DEST/$(basename "$f")"
done
echo "done. 注意：仅当当前 Codex 构建支持 agent_type 角色文件时这些文件才会被识别。"
