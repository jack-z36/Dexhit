#!/usr/bin/env bash
# 一键清除灵巧手 o10 控制节点的锁存故障（latched fault）。
#
# 用法:
#   ./clear_o10_fault.sh          # 清除左手（默认）
#   ./clear_o10_fault.sh left     # 清除左手
#   ./clear_o10_fault.sh right    # 清除右手
#   ./clear_o10_fault.sh both     # 左右手都清除
#
# 行为:
#   1. 读取 /o10_control/{side}/state，显示当前 fault_reason_mask 含义。
#   2. 检查 hardware_error_bits：若存在致命位（bit0-3: 堵转/过热/过流/电机故障，
#      即数值含 1,2,4,8），拒绝清除并提示先排查硬件。
#      vendor 的 COMMU_EXCEPT 位（16）只记录历史通信抖动，不算致命，允许清除。
#   3. 调用 clear_fault 服务并复述结果。
#
# 注意：清除成功的瞬间，手会立即追上手套当前姿态。请先把手套摆成自然张开姿态。

set -o pipefail

SIDE="${1:-left}"
[[ "$SIDE" =~ ^(left|right|both)$ ]] || { echo "用法: $0 [left|right|both]"; exit 1; }

# 锚定本 worktree 的 ROS 环境
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source /opt/ros/jazzy/setup.bash
[[ -f "$SCRIPT_DIR/install/setup.bash" ]] && source "$SCRIPT_DIR/install/setup.bash"

FATAL_MASK=15  # bit0-3 为致命硬件错误位

explain_mask() {
    local mask="$1"
    (( mask == 0 )) && { echo "  fault_reason_mask=$mask（无锁存）"; return; }
    echo "  fault_reason_mask=$mask："
    (( mask & 1 ))  && echo "    - 1  硬件错误（堵转/过热/过流/电机故障）"
    (( mask & 2 ))  && echo "    - 2  命令回读超时"
    (( mask & 4 ))  && echo "    - 4  无效反馈数据"
    (( mask & 8 ))  && echo "    - 8  安全校验失败（目标超出关节限位）"
    (( mask & 16 )) && echo "    - 16 组件掉线/心跳丢失"
    (( mask & 32 )) && echo "    - 32 错误监视超时"
}

clear_one_side() {
    local side="$1"
    echo "===== $side 侧 ====="

    local state
    state="$(timeout 5 ros2 topic echo "/o10_control/$side/state" --once 2>/dev/null || true)"
    if [[ -z "$state" ]]; then
        echo "  ⚠ 读不到 /o10_control/$side/state，跳过（控制节点未运行？）"
        return
    fi

    local latched mask
    latched="$(grep -m1 'fault_latched:' <<<"$state" | awk '{print $2}')"
    mask="$(grep -m1 'fault_reason_mask:' <<<"$state" | awk '{print $2}')"
    explain_mask "${mask:-0}"

    if [[ "$latched" != "true" ]]; then
        echo "  ✓ 当前没有锁存，无需清除"
        return
    fi

    # hardware_error_bits: 数组形式 [0, 0, 16, ...]
    local bits_line bits fatal
    bits_line="$(grep -A11 'hardware_error_bits:' <<<"$state" | grep -oE '\-?[0-9]+' | paste -sd, -)"
    bits="$(grep -A11 'hardware_error_bits:' <<<"$state" | grep -oE '\-?[0-9]+' | tr ',' '\n')"
    fatal=0
    for b in $bits; do
        if (( b & FATAL_MASK )); then fatal=1; echo "  ✗ 关节错误位 $b 含致命错误（bit0-3）"; fi
    done
    if (( fatal )); then
        echo "  ✗ 检测到致命硬件错误位，拒绝自动清除。请先排查硬件（断电检查），"
        echo "    确认致命位清零后再运行本脚本。当前错误位: [$bits_line]"
        return 1
    fi

    echo "  → 调用 clear_fault（错误位只有非致命位，可以安全清除）..."
    local resp
    resp="$(ros2 service call "/o10_control/$side/clear_fault" \
        rokoko_omnihand_msgs/srv/ControlOperation '{}' 2>&1)"
    if grep -q 'success=True' <<<"$resp"; then
        echo "  ✓ 清除成功，手已恢复可动。当前手套姿态会被立即跟随。"
    else
        echo "  ✗ 清除失败："
        echo "$resp"
        return 1
    fi
}

rc=0
if [[ "$SIDE" == "both" ]]; then
    clear_one_side left  || rc=1
    clear_one_side right || rc=1
else
    clear_one_side "$SIDE" || rc=1
fi
exit $rc
