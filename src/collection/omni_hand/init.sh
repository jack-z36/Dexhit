#!/usr/bin/env bash
# Rokoko Smartgloves -> OmniHand O10 开工自检。
# 只准备和验证软件基线；不会启动 ROS 节点、发布命令、清故障或操作实体 O10。

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
COLLECTION_ROOT="$(cd -- "$SCRIPT_DIR/../../.." && pwd -P)"
OMNI_HAND_ROOT="$SCRIPT_DIR"
ROS_DISTRO_NAME="${ROS_DISTRO:-jazzy}"
ROS_SETUP="/opt/ros/$ROS_DISTRO_NAME/setup.bash"
NUMERIC_PYTHON="${DEXHIT_COLLECTION_PYTHON:-/home/hit/miniforge3/envs/dexhit_collection/bin/python}"
MODEL_FIXTURE="${OMNIHAND_O10_MODEL_FIXTURE:-/home/hit/dexhit-external/omnihand_o10_fixture-f4fd0d913c2151bcb4be0d29fbc02761b9638009}"
NUMERIC_PREFIX="$(cd -- "$(dirname -- "$NUMERIC_PYTHON")/.." && pwd -P)"

SKIP_BUILD=0
SKIP_TESTS=0
INSTALL_DEPS=0
ALLOW_LIVE_GRAPH=0

usage() {
    cat <<'EOF'
用法: src/collection/omni_hand/init.sh [选项]

默认行为：检查 worktree、ROS/数值环境，构建 OmniHand 软件包并运行其测试。

选项：
  --install             运行 rosdep 安装缺失的 ROS 依赖（可能需要网络或 sudo）
  --skip-build          跳过 colcon build
  --skip-tests          跳过 colcon test
  --allow-live-graph    允许已有 Rokoko/O10 ROS 节点存在（默认 fail-closed）
  -h, --help            显示帮助

安全边界：本脚本不启动节点、不发布 ROS 命令、不清除故障、不连接或驱动实体手。
EOF
}

die() { echo "[init][FAIL] $*" >&2; exit 1; }
info() { echo "[init] $*"; }
warn() { echo "[init][WARN] $*" >&2; }

while (($# > 0)); do
    case "$1" in
        --install) INSTALL_DEPS=1 ;;
        --skip-build) SKIP_BUILD=1 ;;
        --skip-tests) SKIP_TESTS=1 ;;
        --allow-live-graph) ALLOW_LIVE_GRAPH=1 ;;
        -h|--help) usage; exit 0 ;;
        *) die "未知选项: $1（使用 --help 查看用法）" ;;
    esac
    shift
done

[[ -d "$COLLECTION_ROOT/.git" || -f "$COLLECTION_ROOT/.git" ]] \
    || die "不是 Dexhit collection worktree: $COLLECTION_ROOT"
[[ -d "$OMNI_HAND_ROOT/rokoko_hand_receiver" ]] \
    || die "OmniHand 源码目录不完整: $OMNI_HAND_ROOT"

cd "$COLLECTION_ROOT"
info "Repository: $COLLECTION_ROOT"
info "Scope: $OMNI_HAND_ROOT"

command -v python3 >/dev/null || die "缺少 python3"
command -v colcon >/dev/null || die "缺少 colcon；请先安装 ROS 2 Jazzy 开发工具"
[[ -f "$ROS_SETUP" ]] || die "缺少 ROS setup: $ROS_SETUP"
[[ -x "$NUMERIC_PYTHON" ]] || die "缺少项目数值 Python: $NUMERIC_PYTHON"
[[ -d "$MODEL_FIXTURE" ]] || die "缺少只读 OmniHand 模型 fixture: $MODEL_FIXTURE"

# source 只影响本脚本进程，避免给调用者的 shell 造成隐式修改。
# ROS Jazzy 的 generated setup 脚本会读取未必已 export 的可选变量；只在
# source 边界暂时关闭 nounset，初始化脚本自身仍保持严格模式。
set +u
# shellcheck disable=SC1090
source "$ROS_SETUP"
set -u
export PYTHONNOUSERSITE="${PYTHONNOUSERSITE:-1}"
export OMNIHAND_O10_MODEL_FIXTURE="$MODEL_FIXTURE"
export DEXHIT_COLLECTION_PREFIX="${DEXHIT_COLLECTION_PREFIX:-$NUMERIC_PREFIX}"
export LD_LIBRARY_PATH="$NUMERIC_PREFIX/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

if [[ -f "$COLLECTION_ROOT/install/setup.bash" ]]; then
    # shellcheck disable=SC1091
    set +u
    source "$COLLECTION_ROOT/install/setup.bash"
    set -u
else
    warn "当前没有 install/setup.bash；构建完成后会再次加载安装空间。"
fi

"$NUMERIC_PYTHON" - <<'PY'
import importlib
import sys

required = ("numpy", "pinocchio", "nlopt")
missing = []
for name in required:
    try:
        importlib.import_module(name)
    except ImportError:
        missing.append(name)
if missing:
    raise SystemExit(f"numeric runtime missing: {', '.join(missing)}")
print(f"numeric runtime ok: {sys.executable}")
PY

if ((INSTALL_DEPS)); then
    command -v rosdep >/dev/null || die "--install 需要 rosdep"
    info "Installing ROS dependencies for $OMNI_HAND_ROOT"
    rosdep install --from-paths "$OMNI_HAND_ROOT" --ignore-src --rosdistro "$ROS_DISTRO_NAME" -r -y
else
    info "Dependency installation skipped (use --install when dependency installation is authorized)."
fi

if ((ALLOW_LIVE_GRAPH == 0)) && command -v ros2 >/dev/null; then
    live_nodes="$(timeout 5 ros2 node list 2>/dev/null || true)"
    if [[ -n "$live_nodes" ]] && grep -Eiq 'rokoko|omnihand|o10|retarget' <<<"$live_nodes"; then
        echo "$live_nodes" >&2
        die "检测到 Rokoko/OmniHand 相关 ROS 节点仍在运行；请先安全停止旧进程，或明确使用 --allow-live-graph。"
    fi
fi

if ((SKIP_BUILD == 0)); then
    info "Building OmniHand packages (software only; no nodes are started)."
    colcon build --base-paths "$OMNI_HAND_ROOT" --symlink-install --event-handlers console_direct+
    [[ -f "$COLLECTION_ROOT/install/setup.bash" ]] \
        || die "构建完成但缺少 install/setup.bash"
    # shellcheck disable=SC1091
    set +u
    source "$COLLECTION_ROOT/install/setup.bash"
    set -u
else
    info "Build skipped."
fi

for package in rokoko_hand_receiver hand_retargeting omnihand_o10_control \
    omnihand_o10_hardware_adapter rokoko_omnihand_bringup; do
    ros2 pkg prefix "$package" >/dev/null \
        || die "ROS package 不可见: $package（请先构建并 source install/setup.bash）"
done

if ((SKIP_TESTS == 0)); then
    info "Running OmniHand package tests."
    colcon test --base-paths "$OMNI_HAND_ROOT" --event-handlers console_direct+
    colcon test-result --verbose
else
    info "Tests skipped."
fi

cat <<EOF
[init][OK] Rokoko -> OmniHand software baseline is ready.
  Root: $COLLECTION_ROOT
  ROS:  $ROS_SETUP
  Python: $NUMERIC_PYTHON
  Fixture: $MODEL_FIXTURE

Next standard bringup command (not executed by init.sh):
  cd $COLLECTION_ROOT
  bash ./start_omnihand_control.sh

注意：完整 bringup 会在目标和反馈就绪后驱动实体 O10；启动前必须按全流程手册完成安全确认。
EOF
