#!/usr/bin/env bash
# Source the pinned x64/Jazzy Agilink OmniHand SDK from the Collection tree.

_OMNIHAND_SETUP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
_OMNIHAND_WORKSPACE_ROOT="$(cd -- "$_OMNIHAND_SETUP_DIR/../../../../.." && pwd -P)"
_OMNIHAND_DISTRO="jazzy"
_OMNIHAND_VENDOR_PREFIX="$_OMNIHAND_WORKSPACE_ROOT/src/collection/third_party/agillink_omnihand_sdk/linux/x64/ros2/$_OMNIHAND_DISTRO"
_OMNIHAND_NODE="$_OMNIHAND_VENDOR_PREFIX/lib/omnihand_node/omnihand_2025_node"

if [[ ! -f "/opt/ros/$_OMNIHAND_DISTRO/setup.bash" ]]; then
    echo "Error: ROS2 $_OMNIHAND_DISTRO is not installed." >&2
    return 1
fi
if [[ ! -f "$_OMNIHAND_VENDOR_PREFIX/setup.bash" ]]; then
    echo "Error: OmniHand SDK prefix is missing: $_OMNIHAND_VENDOR_PREFIX" >&2
    return 1
fi

set +u
# shellcheck disable=SC1091
source "/opt/ros/$_OMNIHAND_DISTRO/setup.bash"
# shellcheck disable=SC1090
source "$_OMNIHAND_VENDOR_PREFIX/setup.bash"
set -u

if [[ ! -x "$_OMNIHAND_NODE" ]]; then
    echo "Error: OmniHand node executable is missing: $_OMNIHAND_NODE" >&2
    return 1
fi
_OMNIHAND_LDD_OUTPUT="$(ldd "$_OMNIHAND_NODE" 2>&1)" || {
    echo "Error: failed to inspect OmniHand node dependencies:" >&2
    echo "$_OMNIHAND_LDD_OUTPUT" >&2
    return 1
}
_OMNIHAND_MISSING="$(awk '/not found/{print $1}' <<<"$_OMNIHAND_LDD_OUTPUT")"
if [[ -n "$_OMNIHAND_MISSING" ]]; then
    echo "Error: unresolved OmniHand SDK dependencies:" >&2
    sed 's/^/  /' <<<"$_OMNIHAND_MISSING" >&2
    return 1
fi

echo "OmniHand SDK 1.1.8 x64/Jazzy is ready: $_OMNIHAND_VENDOR_PREFIX"
unset _OMNIHAND_SETUP_DIR _OMNIHAND_WORKSPACE_ROOT _OMNIHAND_DISTRO
unset _OMNIHAND_VENDOR_PREFIX _OMNIHAND_NODE _OMNIHAND_LDD_OUTPUT _OMNIHAND_MISSING
