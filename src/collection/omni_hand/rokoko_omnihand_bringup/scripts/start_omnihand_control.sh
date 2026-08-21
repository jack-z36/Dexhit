#!/usr/bin/env bash
set -Eeuo pipefail

# Compatibility implementation for the canonical repository-root entrypoint:
#   ./start_omnihand_control.sh
# Agents and operators must use the root entrypoint. This package-local path
# remains valid for existing ROS/package documentation and tooling.

# Start the complete Rokoko -> O10 software/hardware graph.
#
# Safety boundary:
#   - This script never calls an arm service.
#   - The O10 control node therefore starts disarmed.
#   - Ctrl-C stops every child started by this script.
#
# The production launch file intentionally requires deployment-owned files.
# This operator launcher is the explicit, local HCAN setup for the verified
# workstation described by the collection runtime handoff.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT="$(cd -- "$SCRIPT_DIR/../../../../.." && pwd)"
INSTALL_PREFIX="$WORKSPACE_ROOT/install"
RETARGET_PARAMS="$WORKSPACE_ROOT/runs/retargeting_diag_params.yaml"
RETARGET_WRAPPER="$WORKSPACE_ROOT/src/collection/omni_hand/hand_retargeting/scripts/hand_retargeting_node"

ROS_SETUP="/opt/ros/jazzy/setup.bash"
RUNTIME_PREFIX="${DEXHIT_COLLECTION_PREFIX:-/home/hit/miniforge3/envs/dexhit_collection}"
MODEL_FIXTURE="${OMNIHAND_O10_MODEL_FIXTURE:-/home/hit/dexhit-external/omnihand_o10_fixture-f4fd0d913c2151bcb4be0d29fbc02761b9638009}"
UDP_PORT="${ROKOKO_UDP_PORT:-14043}"
ACTOR_INDEX="${ROKOKO_ACTOR_INDEX:-0}"

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

cleanup() {
  local index pid
  trap - EXIT INT TERM
  set +e
  if ((${#CHILD_PIDS[@]} > 0)); then
    log "stopping child nodes"
  fi
  for ((index=${#CHILD_PIDS[@]}-1; index>=0; index--)); do
    pid="${CHILD_PIDS[index]}"
    kill -TERM "$pid" 2>/dev/null || true
  done
  for pid in "${CHILD_PIDS[@]}"; do
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

start_node() {
  local name="$1"
  local log_file="$LOG_DIR/$name.log"
  shift
  CHILD_NAMES+=("$name")
  log "starting $name; log=$log_file"
  "$@" >"$log_file" 2>&1 &
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

log "logs: $LOG_DIR"
log "hardware safety: disarmed; no arm service will be called"

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
    -p recovery_confirmation_timeout_sec:=0.5
wait_for_node /hand_retargeting

start_node "omnihand_o10_hardware_provider" \
  ros2 run omnihand_o10_hardware_adapter omnihand_o10_hardware_provider \
    --ros-args \
    -p o10.left.transport:=hcan \
    -p o10.left.hand_device_id:=1 \
    -p o10.left.canfd_device_id:=0 \
    -p o10.left.canfd_channel_id:=0 \
    -p o10.right.transport:=hcan \
    -p o10.right.hand_device_id:=1 \
    -p o10.right.canfd_device_id:=1 \
    -p o10.right.canfd_channel_id:=0
sleep 2
wait_for_processes
wait_for_node /omnihand_o10_hardware_provider

CONTROL_PARAMS=(
  --ros-args
  -p 'left.max_joint_rates:=[8.221747440645,12.055238476275,6.011412609369,1.171863926339,10.596641887108,10.596641887108,1.209263838882,10.596641887108,1.321463576510,10.596641887108]'
  -p left.max_time_credit:=0.1
  -p 'left.slew_compare_epsilon:=[0.0001,0.0001,0.0001,0.0001,0.0001,0.0001,0.0001,0.0001,0.0001,0.0001]'
  -p left.target_input_stale_timeout:=2.0
  -p left.target_receive_stale_timeout:=2.0
  -p left.control_check_period:=0.05
  -p left.error_poll_period:=0.2
  -p left.error_query_timeout:=2.0
  -p left.command_readback_timeout:=4.0
  -p left.provider_heartbeat_timeout:=5.0
  -p left.init_read_retry_period:=0.1
  -p left.init_error_retry_period:=0.1
  -p left.read_service_timeout:=1.0
  -p left.clear_fault_error_timeout:=1.0
  -p left.clear_fault_read_timeout:=1.0
  -p 'right.max_joint_rates:=[8.221747440645,12.055238476275,6.011412609369,1.171863926339,10.596641887108,10.596641887108,1.209263838882,10.596641887108,1.321463576510,10.596641887108]'
  -p right.max_time_credit:=0.1
  -p 'right.slew_compare_epsilon:=[0.0001,0.0001,0.0001,0.0001,0.0001,0.0001,0.0001,0.0001,0.0001,0.0001]'
  -p right.target_input_stale_timeout:=2.0
  -p right.target_receive_stale_timeout:=2.0
  -p right.control_check_period:=0.05
  -p right.error_poll_period:=0.2
  -p right.error_query_timeout:=2.0
  -p right.command_readback_timeout:=4.0
  -p right.provider_heartbeat_timeout:=5.0
  -p right.init_read_retry_period:=0.1
  -p right.init_error_retry_period:=0.1
  -p right.read_service_timeout:=1.0
  -p right.clear_fault_error_timeout:=1.0
  -p right.clear_fault_read_timeout:=1.0
)

start_node "o10_control_node" ros2 run omnihand_o10_control o10_control_node "${CONTROL_PARAMS[@]}"
wait_for_node /o10_control_node

log "all nodes are running"
log "left command: ros2 topic hz /o10_control/left/command"
log "left state:   ros2 topic echo /o10_control/left/state"
log "left arm is intentionally NOT called"
log "press Ctrl-C to stop all nodes started by this script"

while true; do
  wait_for_processes
  sleep 2
done
