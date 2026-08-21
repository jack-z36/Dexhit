#!/usr/bin/env bash
# Canonical first-priority entrypoint for Rokoko -> OmniHand O10 teleoperation.
#
# Keep the implementation under the bringup package so ROS/package-local users
# retain their existing path. This root entrypoint is what agents and
# operators must use from the repository root.

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
WORKSPACE_ROOT="$SCRIPT_DIR"
IMPLEMENTATION="$WORKSPACE_ROOT/src/collection/omni_hand/rokoko_omnihand_bringup/scripts/start_omnihand_control.sh"

[[ -f "$WORKSPACE_ROOT/AGENTS.md" ]] \
  || { echo "[omnihand-launch] ERROR: not a Dexhit collection root: $WORKSPACE_ROOT" >&2; exit 1; }
[[ -x "$IMPLEMENTATION" ]] \
  || { echo "[omnihand-launch] ERROR: missing executable launcher: $IMPLEMENTATION" >&2; exit 1; }

cd "$WORKSPACE_ROOT"
exec bash "$IMPLEMENTATION" "$@"
