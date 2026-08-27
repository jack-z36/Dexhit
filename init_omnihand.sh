#!/usr/bin/env bash
# Rokoko Smartgloves -> OmniHand O10 开工自检。
# 只准备和验证软件基线；不会启动 ROS 节点、发布命令、清故障或操作实体 O10。

set -Eeuo pipefail

COLLECTION_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
COLLECTION_SRC="$COLLECTION_ROOT/src/collection"
ROS_DISTRO_NAME="${ROS_DISTRO:-jazzy}"
ROS_SETUP="/opt/ros/$ROS_DISTRO_NAME/setup.bash"
NUMERIC_PYTHON="${DEXHIT_COLLECTION_PYTHON:-/home/hit/miniforge3/envs/dexhit_collection/bin/python}"
MODEL_FIXTURE="${OMNIHAND_O10_MODEL_FIXTURE:-/home/hit/dexhit-external/omnihand_o10_fixture-f4fd0d913c2151bcb4be0d29fbc02761b9638009}"
NUMERIC_PREFIX="$(cd -- "$(dirname -- "$NUMERIC_PYTHON")/.." && pwd -P)"
VENDOR_PREFIX="$COLLECTION_SRC/third_party/agillink_omnihand_sdk/linux/x64/ros2/jazzy"

PACKAGE_DIRS=(
    "$COLLECTION_SRC/rokoko_hand_receiver_node"
    "$COLLECTION_SRC/hand_retargeting_node"
    "$COLLECTION_SRC/omnihand_o10_control_node"
    "$COLLECTION_SRC/omnihand_o10_hardware_provider_node"
    "$COLLECTION_SRC/rokoko_omnihand_launchpad_node"
    "$COLLECTION_SRC/teleoperation_support/ros_interfaces"
    "$COLLECTION_SRC/teleoperation_support/o10_contracts"
    "$COLLECTION_SRC/teleoperation_support/o10_model_assets"
    "$COLLECTION_SRC/teleoperation_support/production_bringup"
    "$COLLECTION_SRC/teleoperation_support/system_tests"
    "$COLLECTION_SRC/teleoperation_support/architecture_tests"
)
CORE_PACKAGE_NAMES=(
    rokoko_hand_receiver
    hand_retargeting
    omnihand_o10_control
    omnihand_o10_hardware_adapter
    rokoko_omnihand_msgs
    omnihand_o10_contracts
    omnihand_o10_model
    rokoko_omnihand_bringup
    rokoko_omnihand_system_test
    rokoko_omnihand_architecture_test
)
ALL_PACKAGE_NAMES=("${CORE_PACKAGE_NAMES[@]}" rokoko_omnihand_launchpad)

SKIP_BUILD=0
SKIP_TESTS=0
INSTALL_DEPS=0
ALLOW_LIVE_GRAPH=0

usage() {
    cat <<'EOF'
用法: ./init_omnihand.sh [选项]

默认行为：检查 worktree、ROS/数值环境，构建 11 个 Collection 软件包并运行测试。

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
for package_dir in "${PACKAGE_DIRS[@]}"; do
    [[ -f "$package_dir/package.xml" ]] || die "Collection package 目录不完整: $package_dir"
done
[[ -f "$COLLECTION_SRC/third_party/COLCON_IGNORE" ]] \
    || die "third_party 缺少 COLCON_IGNORE"
[[ -f "$VENDOR_PREFIX/setup.bash" ]] || die "缺少 x64/Jazzy OmniHand SDK: $VENDOR_PREFIX"

cd "$COLLECTION_ROOT"
info "Repository: $COLLECTION_ROOT"
info "Collection source: $COLLECTION_SRC"
info "Packages: ${#PACKAGE_DIRS[@]} owned packages (third_party excluded explicitly)"

command -v python3 >/dev/null || die "缺少 python3"
command -v colcon >/dev/null || die "缺少 colcon；请先安装 ROS 2 Jazzy 开发工具"
[[ -f "$ROS_SETUP" ]] || die "缺少 ROS setup: $ROS_SETUP"
[[ -x "$NUMERIC_PYTHON" ]] || die "缺少项目数值 Python: $NUMERIC_PYTHON"
[[ -d "$MODEL_FIXTURE" ]] || die "缺少只读 OmniHand 模型 fixture: $MODEL_FIXTURE"

# source 只影响本脚本进程。ROS 与 SDK 的 generated setup 脚本会读取未必已
# export 的可选变量，因此只在 source 边界暂时关闭 nounset。
set +u
# shellcheck disable=SC1090
source "$ROS_SETUP"
# shellcheck disable=SC1090
source "$VENDOR_PREFIX/setup.bash"
set -u
export PYTHONNOUSERSITE="${PYTHONNOUSERSITE:-1}"
export PYTHONPATH="${DEXHIT_COLLECTION_USER_SITE:-/home/hit/.local/lib/python3.12/site-packages}:/usr/lib/python3/dist-packages${PYTHONPATH:+:$PYTHONPATH}"
export OMNIHAND_O10_MODEL_FIXTURE="$MODEL_FIXTURE"
export DEXHIT_COLLECTION_PREFIX="${DEXHIT_COLLECTION_PREFIX:-$NUMERIC_PREFIX}"
export LD_LIBRARY_PATH="$NUMERIC_PREFIX/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

if ((SKIP_BUILD)); then
    if [[ -f "$COLLECTION_ROOT/install/setup.bash" ]]; then
        set +u
        # shellcheck disable=SC1091
        source "$COLLECTION_ROOT/install/setup.bash"
        set -u
    else
        warn "跳过构建且当前没有 install/setup.bash；package 可见性检查将失败。"
    fi
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
    info "Installing ROS dependencies for the 11 owned packages"
    rosdep install --from-paths "${PACKAGE_DIRS[@]}" \
        --ignore-src --rosdistro "$ROS_DISTRO_NAME" -r -y
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
    stale_build_cache=0
    for package in "${ALL_PACKAGE_NAMES[@]}"; do
        package_build="$COLLECTION_ROOT/build/$package"
        if [[ -L "$package_build/setup.py" ]] \
            && [[ "$(readlink "$package_build/setup.py")" == *"/src/collection/omni_hand/"* ]]; then
            stale_build_cache=1
        fi
        if [[ -f "$package_build/CMakeCache.txt" ]] \
            && grep -Fq "/src/collection/omni_hand/" "$package_build/CMakeCache.txt"; then
            stale_build_cache=1
        fi
    done
    if ((stale_build_cache)); then
        warn "检测到目录迁移前的 generated build cache；将重建 11 个受管 package 的 build 目录。"
        for package in "${ALL_PACKAGE_NAMES[@]}"; do
            rm -rf -- "$COLLECTION_ROOT/build/$package"
        done
    fi
    info "Building 11 Collection packages (software only; no nodes are started)."
    PATH="/usr/bin:/bin:$PATH" colcon build --base-paths "${PACKAGE_DIRS[@]}" \
        --symlink-install --cmake-clean-cache --event-handlers console_direct+ \
        --cmake-args \
        -DPython3_EXECUTABLE=/usr/bin/python3.12 \
        -DPYTHON_EXECUTABLE=/usr/bin/python3.12
    [[ -f "$COLLECTION_ROOT/install/setup.bash" ]] \
        || die "构建完成但缺少 install/setup.bash"
    set +u
    # shellcheck disable=SC1091
    source "$COLLECTION_ROOT/install/setup.bash"
    set -u
else
    info "Build skipped."
fi

for package in "${ALL_PACKAGE_NAMES[@]}"; do
    ros2 pkg prefix "$package" >/dev/null \
        || die "ROS package 不可见: $package（请先构建并 source install/setup.bash）"
done

if ((SKIP_TESTS == 0)); then
    info "Running the original 10-package software baseline."
    PATH="/usr/bin:/bin:$PATH" colcon test --packages-select "${CORE_PACKAGE_NAMES[@]}" \
        --event-handlers console_direct+
    info "Running the Launchpad package baseline separately."
    PATH="/usr/bin:/bin:$PATH" colcon test --packages-select rokoko_omnihand_launchpad \
        --event-handlers console_direct+
    info "Combined test result (existing baseline failures remain visible)."
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
  Vendor: $VENDOR_PREFIX

Next standard bringup command (not executed by init_omnihand.sh):
  cd $COLLECTION_ROOT
  bash ./start_omnihand_control.sh

注意：完整 bringup 会在目标和反馈就绪后驱动实体 O10；启动前必须按全流程手册完成安全确认。
EOF
