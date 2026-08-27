#!/usr/bin/env bash
set -Eeuo pipefail

# Dexhit Collection Launchpad 一键启动脚本。
# 只启动本机网页控制面，不自动启动业务节点，也不调用 arm。

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="/home/hit/miniforge3/envs/dexhit_collection/bin/python"
PYTHON_SITE="/home/hit/miniforge3/envs/dexhit_collection/lib/python3.12/site-packages"
CONDA_SH="/home/hit/miniforge3/etc/profile.d/conda.sh"
ROS_SETUP="/opt/ros/jazzy/setup.bash"
WORKSPACE_SETUP="$ROOT_DIR/install/setup.bash"
LAUNCHPAD_SRC="$ROOT_DIR/src/collection/rokoko_omnihand_launchpad_node"
URL="http://127.0.0.1:8710"

die() {
  echo "[Launchpad] 错误：$*" >&2
  exit 1
}

[[ -x "$PYTHON_BIN" ]] || die "找不到 dexhit_collection Python：$PYTHON_BIN"
[[ -f "$ROS_SETUP" ]] || die "找不到 ROS Jazzy 环境：$ROS_SETUP"
[[ -d "$LAUNCHPAD_SRC/rokoko_omnihand_launchpad" ]] || die "找不到 Launchpad 源码：$LAUNCHPAD_SRC"

# 激活项目约定的数值环境；source 失败时让错误保持可见。
if [[ -f "$CONDA_SH" ]]; then
  # shellcheck disable=SC1090
  source "$CONDA_SH"
  conda activate /home/hit/miniforge3/envs/dexhit_collection
fi

# ROS 的 Debian Python 包与 conda 数值环境并存。将 conda/user site 放在
# ROS 系统 site-packages 之前，避免 typing_extensions 版本被系统包覆盖；
# 同时保留 rclpy、PyYAML 和 click 等 ROS/系统依赖。
export PYTHONPATH="/home/hit/.local/lib/python3.12/site-packages:$PYTHON_SITE:/opt/ros/jazzy/lib/python3.12/site-packages:/usr/lib/python3/dist-packages:$LAUNCHPAD_SRC${PYTHONPATH:+:$PYTHONPATH}"

# 加载 ROS Jazzy，使 Launchpad 后续编排的 ros2 命令可见。
# shellcheck disable=SC1090
set +u
source "$ROS_SETUP"
if [[ -f "$WORKSPACE_SETUP" ]]; then
  # shellcheck disable=SC1090
  source "$WORKSPACE_SETUP"
fi
set -u

export PYTHONPATH="$LAUNCHPAD_SRC${PYTHONPATH:+:$PYTHONPATH}"
export ROS_LOG_DIR="${ROS_LOG_DIR:-/tmp/dexhit-ros-log}"
mkdir -p "$ROS_LOG_DIR"
cd "$ROOT_DIR"

"$PYTHON_BIN" - <<'PY'
for name in ("fastapi", "uvicorn", "click", "yaml", "rclpy", "pinocchio", "nlopt"):
    try:
        __import__(name)
    except Exception as exc:
        raise SystemExit(f"依赖检查失败：{name}: {exc}")
PY

echo "[Launchpad] 环境已就绪：$PYTHON_BIN"
echo "[Launchpad] 控制面地址：$URL"
echo "[Launchpad] 仅启动网页控制面；不会自动启动业务节点或 arm 灵巧手。"

if command -v xdg-open >/dev/null 2>&1 && [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
  (sleep 1; xdg-open "$URL" >/dev/null 2>&1) &
fi

exec "$PYTHON_BIN" -m rokoko_omnihand_launchpad
