#!/usr/bin/env zsh
# Source the pinned x64/Jazzy Agilink OmniHand SDK from the Collection tree.

setopt local_options no_unset
_OMNIHAND_SETUP_DIR="${0:A:h}"
_OMNIHAND_WORKSPACE_ROOT="${_OMNIHAND_SETUP_DIR}/../../../../.."
_OMNIHAND_WORKSPACE_ROOT="${_OMNIHAND_WORKSPACE_ROOT:A}"
_OMNIHAND_DISTRO="jazzy"
_OMNIHAND_VENDOR_PREFIX="$_OMNIHAND_WORKSPACE_ROOT/src/collection/third_party/agillink_omnihand_sdk/linux/x64/ros2/$_OMNIHAND_DISTRO"
_OMNIHAND_NODE="$_OMNIHAND_VENDOR_PREFIX/lib/omnihand_node/omnihand_2025_node"

if [[ ! -f "/opt/ros/$_OMNIHAND_DISTRO/setup.zsh" ]]; then
    echo "Error: ROS2 $_OMNIHAND_DISTRO is not installed." >&2
    return 1
fi
if [[ ! -f "$_OMNIHAND_VENDOR_PREFIX/setup.zsh" ]]; then
    echo "Error: OmniHand SDK prefix is missing: $_OMNIHAND_VENDOR_PREFIX" >&2
    return 1
fi

source "/opt/ros/$_OMNIHAND_DISTRO/setup.zsh" || return 1
source "$_OMNIHAND_VENDOR_PREFIX/setup.zsh" || return 1

if [[ ! -x "$_OMNIHAND_NODE" ]]; then
    echo "Error: OmniHand node executable is missing: $_OMNIHAND_NODE" >&2
    return 1
fi
_OMNIHAND_LDD_OUTPUT="$(ldd "$_OMNIHAND_NODE" 2>&1)" || {
    echo "Error: failed to inspect OmniHand node dependencies:" >&2
    echo "$_OMNIHAND_LDD_OUTPUT" >&2
    return 1
}
_OMNIHAND_MISSING="$(echo "$_OMNIHAND_LDD_OUTPUT" | awk '/not found/{print $1}')"
if [[ -n "$_OMNIHAND_MISSING" ]]; then
    echo "Error: unresolved OmniHand SDK dependencies:" >&2
    echo "$_OMNIHAND_MISSING" | sed 's/^/  /' >&2
    return 1
fi

echo "OmniHand SDK 1.1.8 x64/Jazzy is ready: $_OMNIHAND_VENDOR_PREFIX"
unset _OMNIHAND_SETUP_DIR _OMNIHAND_WORKSPACE_ROOT _OMNIHAND_DISTRO
unset _OMNIHAND_VENDOR_PREFIX _OMNIHAND_NODE _OMNIHAND_LDD_OUTPUT _OMNIHAND_MISSING
