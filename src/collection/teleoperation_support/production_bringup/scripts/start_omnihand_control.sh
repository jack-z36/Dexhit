#!/usr/bin/env bash
set -Eeuo pipefail

# Compatibility implementation for the canonical repository-root entrypoint:
#   ./start_omnihand_control.sh
# Agents and operators must use the root entrypoint. This package-local path
# remains valid for existing ROS/package documentation and tooling.

# Start the complete Rokoko -> O10 software/hardware graph.
#
# Safety boundary:
#   - The current control contract has no arm/disarm gate.
#   - Fresh valid targets can move the physical O10 after feedback is ready.
#   - Ctrl-C stops every child started by this script.
#
# The production launch file intentionally requires deployment-owned files.
# This operator launcher is the explicit, local HCAN setup for the verified
# workstation described by the collection runtime handoff.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT="$(cd -- "$SCRIPT_DIR/../../../../.." && pwd)"
INSTALL_PREFIX="$WORKSPACE_ROOT/install"
RETARGET_PARAMS="$WORKSPACE_ROOT/runs/retargeting_diag_params.yaml"
RETARGET_WRAPPER="$WORKSPACE_ROOT/src/collection/hand_retargeting_node/scripts/hand_retargeting_node"

ROS_SETUP="/opt/ros/jazzy/setup.bash"
RUNTIME_PREFIX="${DEXHIT_COLLECTION_PREFIX:-/home/hit/miniforge3/envs/dexhit_collection}"
MODEL_FIXTURE="${OMNIHAND_O10_MODEL_FIXTURE:-/home/hit/dexhit-external/omnihand_o10_fixture-f4fd0d913c2151bcb4be0d29fbc02761b9638009}"
UDP_PORT="${ROKOKO_UDP_PORT:-14043}"
ACTOR_INDEX="${ROKOKO_ACTOR_INDEX:-0}"
# HCAN adapter indices. The historical dual-adapter workstation enumerates
# left on Device 1 and right on Device 0 (see the bringup manual's successful
# log "Device 0 ... opened" + "Device 1 ... opened"). On a single-adapter
# station only Device 0 exists, so export
# OMNIHAND_O10_LEFT_CANFD_DEVICE_ID=0 before launching --sides left.
LEFT_CANFD_DEVICE_ID="${OMNIHAND_O10_LEFT_CANFD_DEVICE_ID:-1}"
RIGHT_CANFD_DEVICE_ID="${OMNIHAND_O10_RIGHT_CANFD_DEVICE_ID:-0}"

RUN_ID="$(date +%Y%m%d_%H%M%S)"
LOG_DIR="${OMNIHAND_LOG_DIR:-/tmp/omnihand-control-$RUN_ID}"
mkdir -p "$LOG_DIR"

declare -a CHILD_PIDS=()
declare -a CHILD_NAMES=()

log() {
  printf '[omnihand-launch] %s\n' "$*"
}

die() {
  log "ERROR: $*"
  exit 1
}

usage() {
  cat <<'EOF'
Usage: start_omnihand_control.sh [--sides left|right|both] [--param key=value] ...

Options:
  --sides left|right|both   Wire up only the given hand side(s). Default: both,
                            which reproduces the historical dual-side startup
                            exactly.
  --param key=value         Extra ROS parameter override passed through to the
                            retargeting, provider and control nodes (repeatable).
                            Diagnostics examples:
                              o10.left.request_interval_ms=0   (E5)
                              o10.left.feedback_read_period=0  (E3)
                              left.error_poll_period=2.0       (E1)
                              left.command_link_best_effort=true        (E2)
                              o10.left.command_best_effort=true         (E2)
  -h, --help                Show this help.

Environment overrides:
  OMNIHAND_O10_LEFT_CANFD_DEVICE_ID   HCAN device index for the left side.
                                      Default 1 (historical dual-adapter
                                      workstation). Use 0 on single-adapter
                                      stations where the SDK scan reports
                                      exactly one device.
  OMNIHAND_O10_RIGHT_CANFD_DEVICE_ID  HCAN device index for the right side.
                                      Default 0.

Automatic HCAN device binding:
  For every selected side whose OMNIHAND_O10_*_CANFD_DEVICE_ID is NOT
  explicitly set, the launcher runs `omnihand_o10_probe resolve` before
  wiring the graph. It matches each side to the hand's factory serial number
  (side -> serial persisted in o10_hand_binding.json at the worktree root)
  and looks the device index up fresh on every start, so adapters may sit on
  any USB port. Explicitly exporting OMNIHAND_O10_LEFT_CANFD_DEVICE_ID or
  OMNIHAND_O10_RIGHT_CANFD_DEVICE_ID is the per-side debug back door: it
  skips the probe for that side and keeps the value above.

Safety boundary is unchanged: there is no arm gate; fresh valid targets can
move the physical O10 after feedback is ready. Ctrl-C stops every child.
EOF
}

# --- argument parsing -------------------------------------------------------
SIDES="both"
declare -a EXTRA_PARAM_ARGS=()

while (($# > 0)); do
  case "$1" in
    --sides)
      [[ $# -ge 2 ]] || die "--sides requires a value: left|right|both"
      SIDES="$2"
      shift
      ;;
    --sides=*)
      SIDES="${1#*=}"
      ;;
    --param)
      [[ $# -ge 2 ]] || die "--param requires a key=value argument"
      EXTRA_PARAM_ARGS+=("$2")
      shift
      ;;
    --param=*)
      EXTRA_PARAM_ARGS+=("${1#*=}")
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown option: $1 (see --help)"
      ;;
  esac
  shift
done

case "$SIDES" in
  left|right|both) ;;
  *) die "invalid --sides value: '$SIDES' (expected left|right|both)" ;;
esac

side_selected() {
  [[ "$SIDES" == "both" || "$SIDES" == "$1" ]]
}

# Generic override passthrough (E1/E2/E3/E5 diagnostics): rendered as ROS `-p`
# flags and handed to every managed node. Nodes simply ignore overrides they
# never declare, so one shared list cannot poison unrelated nodes.
declare -a OVERRIDE_FLAGS=()
for kv in "${EXTRA_PARAM_ARGS[@]:-}"; do
  [[ -n "$kv" ]] || continue
  [[ "$kv" == *=* ]] || die "invalid --param argument (expected key=value): $kv"
  OVERRIDE_FLAGS+=("-p" "${kv/=/:=}")
done

cleanup() {
  local index pid attempts
  trap - EXIT INT TERM
  set +e
  if ((${#CHILD_PIDS[@]} > 0)); then
    log "stopping child nodes"
  fi
  for ((index=${#CHILD_PIDS[@]}-1; index>=0; index--)); do
    pid="${CHILD_PIDS[index]}"
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
  done
  # Bounded grace period, then escalate to KILL for stubborn grandchildren.
  for attempts in 1 2 3 4 5 6; do
    local alive=0
    for pid in "${CHILD_PIDS[@]}"; do
      kill -0 "$pid" 2>/dev/null && alive=1
    done
    ((alive)) || break
    sleep 0.5
  done
  for pid in "${CHILD_PIDS[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
    fi
    wait "$pid" 2>/dev/null || true
  done
}

trap cleanup EXIT INT TERM

source_environment() {
  [[ -f "$ROS_SETUP" ]] || die "missing ROS setup: $ROS_SETUP"
  [[ -f "$INSTALL_PREFIX/setup.bash" ]] || die "missing workspace install: $INSTALL_PREFIX/setup.bash"
  # ROS setup files are not nounset-safe: they may read variables that are
  # intentionally absent in a fresh shell.  Keep strict mode for our code.
  set +u
  # shellcheck disable=SC1090
  source "$ROS_SETUP"
  # shellcheck disable=SC1090
  source "$INSTALL_PREFIX/setup.bash"
  set -u

  export DEXHIT_COLLECTION_PREFIX="$RUNTIME_PREFIX"
  export OMNIHAND_O10_MODEL_FIXTURE="$MODEL_FIXTURE"
  export PYTHONNOUSERSITE=1
  export PYTHONPATH="$RUNTIME_PREFIX/lib/python3.12/site-packages${PYTHONPATH:+:$PYTHONPATH}"
  export LD_LIBRARY_PATH="$RUNTIME_PREFIX/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
}

check_prerequisites() {
  command -v ros2 >/dev/null 2>&1 || die "ros2 is not available after sourcing ROS"
  command -v lsusb >/dev/null 2>&1 || die "lsusb is required for the HCAN preflight"
  [[ -x "$RETARGET_WRAPPER" ]] || die "missing retargeting runtime wrapper: $RETARGET_WRAPPER"
  [[ -f "$RETARGET_PARAMS" ]] || die "missing retargeting parameters: $RETARGET_PARAMS"
  [[ -f "$MODEL_FIXTURE/provenance.json" ]] || die "missing O10 model fixture provenance: $MODEL_FIXTURE/provenance.json"
  [[ -d "$RUNTIME_PREFIX/lib/python3.12/site-packages" ]] || die "missing Python 3.12 runtime: $RUNTIME_PREFIX"

  "$RUNTIME_PREFIX/bin/python" -c 'import pinocchio, nlopt, omnihand' \
    >/dev/null 2>"$LOG_DIR/runtime-import.error" \
    || die "runtime import check failed; see $LOG_DIR/runtime-import.error"

  if ! lsusb -d a8fa:8598 >/dev/null 2>&1; then
    die "HCAN USB-CANFD device a8fa:8598 was not detected"
  fi

  local existing
  existing="$(ros2 node list 2>/dev/null || true)"
  for node in /rokoko_hand_receiver /hand_retargeting /omnihand_o10_hardware_provider /o10_control_node; do
    if grep -Fxq "$node" <<<"$existing"; then
      die "$node is already running; stop the old graph before using this launcher"
    fi
  done
}

# Resolve HCAN adapter indices for every selected side that was NOT pinned via
# OMNIHAND_O10_*_CANFD_DEVICE_ID: omnihand_o10_probe maps each hand's factory
# serial number (side -> serial persisted in o10_hand_binding.json) onto the
# SDK's per-start device enumeration, so adapters may sit on any USB port. A
# pinned side is a deliberate debug back door and skips the probe entirely.
autodetect_canfd_device_ids() {
  local left_pinned="${OMNIHAND_O10_LEFT_CANFD_DEVICE_ID+x}"
  local right_pinned="${OMNIHAND_O10_RIGHT_CANFD_DEVICE_ID+x}"
  local probe_sides=""
  case "$SIDES" in
    left)
      [[ -n "$left_pinned" ]] || probe_sides="left"
      ;;
    right)
      [[ -n "$right_pinned" ]] || probe_sides="right"
      ;;
    both)
      if [[ -z "$left_pinned" && -z "$right_pinned" ]]; then
        probe_sides="both"
      elif [[ -z "$left_pinned" ]]; then
        probe_sides="left"
      elif [[ -z "$right_pinned" ]]; then
        probe_sides="right"
      fi
      ;;
  esac
  [[ -n "$probe_sides" ]] || return 0

  log "autodetect: resolving canfd device id(s) for: $probe_sides"
  local probe_lines
  probe_lines="$(ros2 run omnihand_o10_hardware_adapter omnihand_o10_probe resolve --sides "$probe_sides")" \
    || die "omnihand_o10_probe resolve --sides $probe_sides failed; fix the probe error above"
  # probe stdout is exactly OMNIHAND_O10_*_CANFD_DEVICE_ID=<int> lines; refuse
  # to eval anything else so stray output can never execute in this shell.
  local line
  while IFS= read -r line; do
    [[ -n "$line" ]] || continue
    [[ "$line" =~ ^OMNIHAND_O10_(LEFT|RIGHT)_CANFD_DEVICE_ID=[0-9]+$ ]] \
      || die "unexpected probe output line; refusing to apply: $line"
  done <<<"$probe_lines"
  eval "$probe_lines"
  LEFT_CANFD_DEVICE_ID="${OMNIHAND_O10_LEFT_CANFD_DEVICE_ID:-$LEFT_CANFD_DEVICE_ID}"
  RIGHT_CANFD_DEVICE_ID="${OMNIHAND_O10_RIGHT_CANFD_DEVICE_ID:-$RIGHT_CANFD_DEVICE_ID}"
  if [[ "$probe_sides" == "left" || "$probe_sides" == "both" ]]; then
    log "autodetect: left -> canfd_device_id=$LEFT_CANFD_DEVICE_ID"
  fi
  if [[ "$probe_sides" == "right" || "$probe_sides" == "both" ]]; then
    log "autodetect: right -> canfd_device_id=$RIGHT_CANFD_DEVICE_ID"
  fi
}

start_node() {
  local name="$1"
  local log_file="$LOG_DIR/$name.log"
  shift
  CHILD_NAMES+=("$name")
  log "starting $name; log=$log_file"
  # Own session per child: lets cleanup TERM the whole ros2-run tree via its
  # process group instead of only the CLI wrapper PID.
  setsid "$@" >"$log_file" 2>&1 &
  CHILD_PIDS+=("$!")
}

wait_for_node() {
  local expected="$1"
  local timeout_seconds="${2:-30}"
  local deadline=$((SECONDS + timeout_seconds))
  while ((SECONDS < deadline)); do
    if ros2 node list 2>/dev/null | grep -Fxq "$expected"; then
      log "$expected is visible in the ROS graph"
      return 0
    fi
    sleep 1
  done
  die "timed out waiting for $expected; inspect $LOG_DIR"
}

wait_for_processes() {
  local index pid
  for index in "${!CHILD_PIDS[@]}"; do
    pid="${CHILD_PIDS[index]}"
    if ! kill -0 "$pid" 2>/dev/null; then
      die "${CHILD_NAMES[index]} exited during startup; inspect $LOG_DIR/${CHILD_NAMES[index]}.log"
    fi
  done
}

source_environment
check_prerequisites
autodetect_canfd_device_ids

log "logs: $LOG_DIR"
log "hardware safety: no arm gate; fresh valid targets can move the physical O10"

start_node "rokoko_hand_receiver" \
  ros2 run rokoko_hand_receiver rokoko_hand_receiver_node --ros-args \
    -p bind_address:=0.0.0.0 \
    -p udp_port:="$UDP_PORT" \
    -p actor_index:="$ACTOR_INDEX"
wait_for_node /rokoko_hand_receiver

start_node "hand_retargeting" \
  bash "$RETARGET_WRAPPER" \
    --ros-args \
    --params-file "$RETARGET_PARAMS" \
    -p 'smooth_time_constants:=[0.02,0.02,0.02,0.02,0.02,0.02,0.02,0.02,0.02,0.02]' \
    -p recovery_confirmation_timeout_sec:=0.5 \
    -p "sides:=$SIDES" \
    "${OVERRIDE_FLAGS[@]}"
wait_for_node /hand_retargeting

PROVIDER_PARAMS=(
  --ros-args
  -p "sides:=$SIDES"
)
if side_selected left; then
  PROVIDER_PARAMS+=(
    -p o10.left.transport:=hcan \
    -p o10.left.hand_device_id:=1 \
    -p "o10.left.canfd_device_id:=$LEFT_CANFD_DEVICE_ID" \
    -p o10.left.canfd_channel_id:=0 \
    -p o10.left.command_best_effort:=false
  )
fi
if side_selected right; then
  PROVIDER_PARAMS+=(
    -p o10.right.transport:=hcan \
    -p o10.right.hand_device_id:=1 \
    -p "o10.right.canfd_device_id:=$RIGHT_CANFD_DEVICE_ID" \
    -p o10.right.canfd_channel_id:=0 \
    -p o10.right.command_best_effort:=false
  )
fi
PROVIDER_PARAMS+=("${OVERRIDE_FLAGS[@]}")

start_node "omnihand_o10_hardware_provider" \
  ros2 run omnihand_o10_hardware_adapter omnihand_o10_hardware_provider \
    "${PROVIDER_PARAMS[@]}"
sleep 2
wait_for_processes
wait_for_node /omnihand_o10_hardware_provider

add_control_params() {
  local side="$1"
  CONTROL_PARAMS+=(
    -p "${side}.max_joint_rates:=[8.221747440645,12.055238476275,6.011412609369,1.171863926339,10.596641887108,10.596641887108,1.209263838882,10.596641887108,1.321463576510,10.596641887108]"
    -p "${side}.max_time_credit:=0.1"
    -p "${side}.slew_compare_epsilon:=[0.0001,0.0001,0.0001,0.0001,0.0001,0.0001,0.0001,0.0001,0.0001,0.0001]"
    -p "${side}.target_input_stale_timeout:=2.0"
    -p "${side}.target_receive_stale_timeout:=2.0"
    -p "${side}.control_check_period:=0.05"
    -p "${side}.error_poll_period:=0.2"
    -p "${side}.error_query_timeout:=2.0"
    -p "${side}.command_readback_timeout:=4.0"
    -p "${side}.provider_heartbeat_timeout:=5.0"
    -p "${side}.init_read_retry_period:=0.1"
    -p "${side}.init_error_retry_period:=0.1"
    -p "${side}.read_service_timeout:=1.0"
    -p "${side}.clear_fault_error_timeout:=1.0"
    -p "${side}.clear_fault_read_timeout:=1.0"
  )
}

CONTROL_PARAMS=( --ros-args )

if side_selected left; then add_control_params left; fi
if side_selected right; then add_control_params right; fi

start_node "o10_control_node" \
  ros2 run omnihand_o10_control o10_control_node \
    "${CONTROL_PARAMS[@]}" \
    -p "sides:=$SIDES" \
    "${OVERRIDE_FLAGS[@]}"
wait_for_node /o10_control_node

log "all nodes are running"
if side_selected left; then
  log "left command: ros2 topic hz /o10_control/left/command"
  log "left state:   ros2 topic echo /o10_control/left/state"
fi
if side_selected right; then
  log "right command: ros2 topic hz /o10_control/right/command"
  log "right state:   ros2 topic echo /o10_control/right/state"
fi
log "arms are intentionally NOT called"
log "press Ctrl-C to stop all nodes started by this script"

while true; do
  wait_for_processes
  sleep 2
done
