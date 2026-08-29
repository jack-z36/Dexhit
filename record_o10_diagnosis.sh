#!/usr/bin/env bash
# Rokoko -> OmniHand O10 单手（左手）诊断对照实验的傻瓜式真机录制脚本。
#
# 用法示例（默认跑完整实验序列 E0 E5 E1 E2 E3）：
#   ./record_o10_diagnosis.sh
# 只跑指定实验：
#   ./record_o10_diagnosis.sh E0 E5
# 无副作用的流程演练（自动化验证用；不进安全门、不启动任何链路/录制）：
#   ./record_o10_diagnosis.sh --dry-run
#
# 安全边界：
#   - 本脚本不构造 SDK hand、不清故障、不发 clear_fault、不调用任何 arm。
#   - 真实链路由 start_omnihand_control.sh 拉起（--sides left），运动仍由
#     “新鲜合法目标直接驱动”，必须先过人工安全门。
#   - 录制目标只限左手话题。

set -Eeuo pipefail

COLLECTION_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
START_SCRIPT="$COLLECTION_ROOT/start_omnihand_control.sh"
INSTALL_SETUP="$COLLECTION_ROOT/install/setup.bash"

DEFAULT_EXPERIMENTS=(E0 E5 E1 E2 E3)
declare -A EXP_DESC=(
    [E0]="基线：无参数覆盖"
    [E1]="E1 控制节点错误轮询降频 left.error_poll_period=2.0"
    [E2]="E2 命令链三跳切 BestEffort/KeepLast(1)"
    [E3]="E3 关闭 provider 反馈周期读 o10.left.feedback_read_period=0"
    [E5]="E5 SDK 全局请求间隔设为不限速 o10.left.request_interval_ms=0"
)
# 实验名 -> 空格分隔的 key=value 参数覆盖
declare -A EXP_PARAMS=(
    [E0]=""
    [E1]="left.error_poll_period=2.0"
    [E2]="left.command_best_effort=true left.command_link_best_effort=true o10.left.command_best_effort=true"
    [E3]="o10.left.feedback_read_period=0"
    [E5]="o10.left.request_interval_ms=0"
)
SCENARIO_ORDER=(static slow fast)
declare -A SCENARIO_SECONDS=([static]=90 [slow]=90 [fast]=60)
declare -A SCENARIO_PROMPT=(
    [static]="静止：手放松，保持一个固定姿势不动"
    [slow]="慢动：缓慢张开 -> 握拳，约 8 个循环，节奏均匀"
    [fast]="快抓：快速张开 -> 抓握，约 12 个循环"
)

RECORD_TOPICS=(
    /rokoko/left/raw_hand
    /hand_retargeting/left/state
    /o10_control/left/command
    /o10_control/left/state
    /o10/left/joint_cmd
    /o10/left/joint_states
    /o10/left/joint_error_states
)

die() { echo "[record][FAIL] $*" >&2; exit 1; }
info() { echo "[record] $*"; }
warn() { echo "[record][WARN] $*" >&2; }

usage() {
    cat <<'EOF'
用法: ./record_o10_diagnosis.sh [--dry-run] [实验...]

实验可选: E0 E1 E2 E3 E5；默认序列: E0 E5 E1 E2 E3。
每个实验只启动左手链路(--sides left)，并依次录制 static(90s)/slow(90s)/fast(60s)
三个场景的七个左手话题到 runs/diagnosis_<UTC时间戳>/。

选项:
  --dry-run   跳过安全门且不启动任何节点/录制，只打印将执行的完整流程。
  -h, --help  显示本帮助。

安全边界：本脚本不驱动实体手的任何直接命令路径；真实运动由 start_omnihand_control.sh
按既有契约触发。开始前必须人工完成安全清单确认（输入 YES）。
EOF
}

DRY_RUN=0
EXPERIMENTS=()
while (($# > 0)); do
    case "$1" in
        --dry-run) DRY_RUN=1 ;;
        -h|--help) usage; exit 0 ;;
        E0|E1|E2|E3|E5) EXPERIMENTS+=("$1") ;;
        *) die "未知参数: $1（使用 --help 查看用法）" ;;
    esac
    shift
done
if ((${#EXPERIMENTS[@]} == 0)); then
    EXPERIMENTS=("${DEFAULT_EXPERIMENTS[@]}")
fi

info "Repository: $COLLECTION_ROOT"
if [[ ! -f "$START_SCRIPT" ]]; then
    die "缺少根入口启动脚本: $START_SCRIPT"
fi
[[ -f "$INSTALL_SETUP" ]] || die "缺少构建产物: $INSTALL_SETUP（请先运行 ./init_omnihand.sh）"

RUN_STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_ROOT="$COLLECTION_ROOT/runs/diagnosis_$RUN_STAMP"

print_flow() {
    info "计划目录: $RUN_ROOT"
    for exp in "${EXPERIMENTS[@]}"; do
        info "--- 实验 $exp: ${EXP_DESC[$exp]}"
        local params=${EXP_PARAMS[$exp]}
        if [[ -n "$params" ]]; then
            info "    覆盖参数: $params"
        fi
        for scenario in "${SCENARIO_ORDER[@]}"; do
            info "    场景 $scenario (${SCENARIO_SECONDS[$scenario]}s): ${SCENARIO_PROMPT[$scenario]}"
        done
        info "    录制话题: ${RECORD_TOPICS[*]}"
        info "    启动命令: $START_SCRIPT --sides left ${params:+$(for p in $params; do printf -- '--param %q ' "$p"; done)}"
        info "    就绪判据(两级): L1 /rokoko/left/raw_hand 首条消息(15s)；L2 /o10_control/left/command 首条消息(45s)"
        info "    失败路径: EXIT/INT/TERM 均会自动 SIGINT->KILL 本脚本拉起的链路与录制进程，不留残留"
        info "    结束动作: 对进程组发 SIGINT 优雅停链路，并写 metadata.json"
    done
}

safety_gate() {
    cat <<'EOF'
==================== 真机安全清单（摘自全流程启动手册） ====================
1) 急停手段可达：随时可以 Ctrl-C 一键停止整条链路；
2) 实体灵巧手周围无障碍物、无人员、无易被夹持的线缆；
3) 本次只测【左手】：左手已上电并在位；不要触碰/评估右手输出；
4) 手套已正确佩戴，处于 Rokoko 有效采集区；
5) 已知悉：无 arm/disarm 门控——只要反馈/错误监控就绪且目标新鲜，实体手即跟随运动；
6) 出现 fault_latched 或硬件错误位(bit0–bit3)置位时：先停手套移动，排查后再处理。
==========================================================================
确认以上全部满足后输入 YES 继续；其他任意输入都会退出：
EOF
    read -r ANSWER
    [[ "$ANSWER" == "YES" ]] || die "安全门未通过（输入为 '$ANSWER'）；退出。"
}

on_exit_cleanup() {
    # 失败/中断路径也必须清理自己拉起的东西，绝不留残留进程。
    set +e
    if [[ -n "${CURRENT_BAG_PID:-}" ]] && kill -0 "$CURRENT_BAG_PID" 2>/dev/null; then
        info "中断路径：停止进行中的 ros2 bag 录制 (PID=$CURRENT_BAG_PID)"
        kill -INT "$CURRENT_BAG_PID" 2>/dev/null || true
        wait "$CURRENT_BAG_PID" 2>/dev/null || true
    fi
    CURRENT_BAG_PID=""
    stop_previous_run
}

stop_previous_run() {
    # 只停本脚本自己拉起的进程组；绝不触碰系统中无关进程。
    if [[ -n "${CURRENT_PGID:-}" ]] && kill -0 "-$CURRENT_PGID" 2>/dev/null; then
        info "停止上一条链路进程组 PGID=$CURRENT_PGID (SIGINT)"
        kill -INT "-$CURRENT_PGID" 2>/dev/null || true
        for _ in $(seq 1 20); do
            kill -0 "-$CURRENT_PGID" 2>/dev/null || break
            sleep 0.5
        done
        kill -KILL "-$CURRENT_PGID" 2>/dev/null || true
    fi
    CURRENT_PGID=""
}

ensure_ros_env() {
    set +u
    source /opt/ros/jazzy/setup.bash >/dev/null 2>&1 || true
    source "$INSTALL_SETUP" >/dev/null 2>&1 || true
    export DEXHIT_COLLECTION_PREFIX="${DEXHIT_COLLECTION_PREFIX:-/home/hit/miniforge3/envs/dexhit_collection}"
    export OMNIHAND_O10_MODEL_FIXTURE="${OMNIHAND_O10_MODEL_FIXTURE:-/home/hit/dexhit-external/omnihand_o10_fixture-f4fd0d913c2151bcb4be0d29fbc02761b9638009}"
    export PYTHONPATH="/home/hit/miniforge3/envs/dexhit_collection/lib/python3.12/site-packages${PYTHONPATH:+:$PYTHONPATH}"
    set -u
}

wait_first_message() {
    # $1 topic, $2 timeout_sec, $3 ok_hint, $4 fail_hint(with next actions)
    local topic="$1" timeout_s="$2" ok_hint="$3" fail_hint="$4"
    ensure_ros_env
    info "等待 $topic 首条消息（${timeout_s}s 超时）..."
    if timeout "$timeout_s" ros2 topic echo --once --no-arr "$topic" >/dev/null 2>&1; then
        info "就绪：$ok_hint"
        return 0
    fi
    die "等待 $topic 首条消息超时（${timeout_s}s）。$fail_hint"
}

countdown() {
    local seconds="$1"
    local n
    for ((n = seconds; n > 0; n--)); do
        printf '\r[record] %ds 后开始录制... ' "$n"
        sleep 1
    done
    printf '\r[record] 开始录制                    \n'
}

run_scenario() {
    local exp="$1"
    local scenario="$2"
    local out_dir="$RUN_ROOT/${exp}_${scenario}"
    local duration=${SCENARIO_SECONDS[$scenario]}

    echo
    info "=== [$exp/$scenario] 动作说明：${SCENARIO_PROMPT[$scenario]}"
    countdown 3

    mkdir -p "$out_dir"
    info "开始 ros2 bag 录制 (${duration}s) -> $out_dir"
    ensure_ros_env
    ros2 bag record -s mcap -o "$out_dir" "${RECORD_TOPICS[@]}" &
    CURRENT_BAG_PID=$!
    sleep "$duration"
    kill -INT "$CURRENT_BAG_PID" 2>/dev/null || true
    wait "$CURRENT_BAG_PID" 2>/dev/null || true
    CURRENT_BAG_PID=""
    info "场景 $scenario 录制完成。"

    info "场景间休息 10 秒..."
    sleep 10
}

write_metadata() {
    local exp="$1"
    local started="$2"
    local ended
    ended="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    local rev
    rev="$(git -C "$COLLECTION_ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"
    local meta_file="$RUN_ROOT/metadata_${exp}.json"
    {
        echo "{"
        echo "  \"experiment\": \"$exp\","
        echo "  \"description\": \"${EXP_DESC[$exp]}\","
        echo "  \"param_overrides\": [$(local p; for p in ${EXP_PARAMS[$exp]}; do printf '"%s", ' "$p"; done | sed 's/, $//')],"
        echo "  \"git_rev\": \"$rev\","
        echo "  \"started_utc\": \"$started\","
        echo "  \"ended_utc\": \"$ended\","
        echo "  \"scenarios_seconds\": {\"static\": 90, \"slow\": 90, \"fast\": 60},"
        echo "  \"side\": \"left\","
        echo "  \"topics\": [$(printf '"%s", ' "${RECORD_TOPICS[@]}" | sed 's/, $//')]"
        echo "}"
    } >"$meta_file"
    info "写实验元数据: $meta_file"
}

run_experiment() {
    local exp="$1"
    local started
    started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

    stop_previous_run

    local flags=()
    local param
    for param in ${EXP_PARAMS[$exp]}; do
        flags+=(--param "$param")
    done

    local log_file="/tmp/omnihand-diagnosis-$exp-$RUN_STAMP.log"
    info "拉起单手链路: $START_SCRIPT --sides left ${flags[*]+${flags[*]}} (日志: $log_file)"
    setsid bash "$START_SCRIPT" --sides left ${flags[@]+"${flags[@]}"} >"$log_file" 2>&1 &
    CURRENT_PGID="$!"

    # 两级就绪检测：
    # L1 手套数据流先进 receiver；
    # L2 控制命令流证明整条链路活着。
    wait_first_message /rokoko/left/raw_hand 15 \
        "Rokoko 数据流已进入本机 receiver。" \
        "未收到 /rokoko/left/raw_hand——通常是 Rokoko Studio 未串流或手套未佩戴。请先恢复手套数据流再重试。"
    wait_first_message /o10_control/left/command 45 \
        "整条左手链路已就绪，收到第一条控制命令。" \
        "控制命令迟迟未出现，多半是 provider 启动失败（例如日志含 '[HCAN ERROR] Device ID 1 exceeds device count 1' 时，表示所用设备号超出了本机实际适配器数；正常情况下启动时会按手的出厂序列号自动探测设备号，此报错一般只出现在该侧被 OMNIHAND_O10_LEFT_CANFD_DEVICE_ID 显式固定的调试场合，此时改用实际在线索引（单适配器机器通常为 0）重新运行即可）。请查看链路日志 $log_file 及其头部给出的节点日志目录（omnihand_o10_hardware_provider.log 等）。"

    local index=0
    for scenario in "${SCENARIO_ORDER[@]}"; do
        ((index += 1))
        run_scenario "$exp" "$scenario"
    done

    stop_previous_run
    write_metadata "$exp" "$started"
}

summary_table() {
    info "录制文件清单："
    printf '  %-14s %-8s %s\n' "实验" "场景" "目录"
    for exp in "${EXPERIMENTS[@]}"; do
        for scenario in "${SCENARIO_ORDER[@]}"; do
            printf '  %-14s %-8s %s\n' "$exp" "$scenario" "$RUN_ROOT/${exp}_${scenario}"
        done
    done
    info "把 $RUN_ROOT 目录路径告诉 Agent 即可离线分析。"
}

if ((DRY_RUN)); then
    info "DRY-RUN：仅打印流程，零副作用（不建目录、不启链路、不录包）。"
    print_flow
    summary_table >/dev/null
    info "DRY-RUN 完成。"
    exit 0
fi

trap 'on_exit_cleanup; exit 130' INT TERM
trap on_exit_cleanup EXIT

if command -v ss >/dev/null 2>&1 && ss -uln 2>/dev/null | grep -q ":14043 "; then
    warn "UDP:14043 已有监听——可能存在残留的 rokoko_hand_receiver；建议先排查旧进程再继续。"
fi
if [[ -z "${OMNIHAND_O10_LEFT_CANFD_DEVICE_ID:-}" ]]; then
    info "提示：未 export OMNIHAND_O10_LEFT_CANFD_DEVICE_ID 时，启动会自动探测该侧设备号（按手的出厂序列号现场解析，适配器可插任意 USB 口），一般无需手动设置；left=1/right=0 只是脚本的兜底默认，仅在调试需要跳过该侧自动探测时才 export。"
fi

safety_gate
mkdir -p "$RUN_ROOT"
for exp in "${EXPERIMENTS[@]}"; do
    info "########## 开始实验 $exp ##########"
    run_experiment "$exp"
done
summary_table
