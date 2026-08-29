"""Structural guard for the direct launcher's probe-driven autodetect step.

Between check_prerequisites and the first start_node call, the launcher must
run `omnihand_o10_probe resolve` for exactly the selected sides the operator
did NOT pin via OMNIHAND_O10_*_CANFD_DEVICE_ID, apply the probe's eval-able
output back onto LEFT/RIGHT_CANFD_DEVICE_ID, and keep a probe failure fatal.
"""

from pathlib import Path


ROOT = Path(__file__).parents[1]
LAUNCHER = ROOT / "scripts" / "start_omnihand_control.sh"


def _launcher_text() -> str:
    return LAUNCHER.read_text(encoding="utf-8")


def _autodetect_block() -> str:
    text = _launcher_text()
    return text.split("autodetect_canfd_device_ids() {", 1)[1].split("\n}\n", 1)[0]


def _usage_text() -> str:
    text = _launcher_text()
    return text.split("EOF", 1)[1].split("\nEOF\n", 1)[0]


def test_probe_resolve_is_invoked_with_the_selected_sides():
    block = _autodetect_block()
    assert (
        'ros2 run omnihand_o10_hardware_adapter omnihand_o10_probe resolve --sides "$probe_sides"'
        in block
    )


def test_autodetect_runs_between_check_prerequisites_and_first_start_node():
    text = _launcher_text()
    assert "autodetect_canfd_device_ids() {" in text
    call_anchor = "check_prerequisites\nautodetect_canfd_device_ids"
    assert call_anchor in text
    assert text.index(call_anchor) < text.index('start_node "rokoko_hand_receiver"')


def test_probe_lines_overwrite_the_launcher_knobs():
    block = _autodetect_block()
    assert 'eval "$probe_lines"' in block
    assert 'LEFT_CANFD_DEVICE_ID="${OMNIHAND_O10_LEFT_CANFD_DEVICE_ID:-$LEFT_CANFD_DEVICE_ID}"' in block
    assert 'RIGHT_CANFD_DEVICE_ID="${OMNIHAND_O10_RIGHT_CANFD_DEVICE_ID:-$RIGHT_CANFD_DEVICE_ID}"' in block


def test_probe_output_is_validated_before_eval():
    block = _autodetect_block()
    assert "CANFD_DEVICE_ID=[0-9]+$" in block
    assert "|| die" in block


def test_pinned_sides_are_detected_via_plus_x_expansion():
    block = _autodetect_block()
    assert '"${OMNIHAND_O10_LEFT_CANFD_DEVICE_ID+x}"' in block
    assert '"${OMNIHAND_O10_RIGHT_CANFD_DEVICE_ID+x}"' in block


def test_fully_pinned_selection_skips_the_probe():
    block = _autodetect_block()
    assert '[[ -n "$probe_sides" ]] || return 0' in block


def test_sides_selection_maps_onto_the_unset_sides():
    block = _autodetect_block()
    assert 'case "$SIDES" in' in block
    assert 'probe_sides="left"' in block
    assert 'probe_sides="right"' in block
    assert 'probe_sides="both"' in block


def test_usage_documents_autodetect_and_the_pinned_side_back_door():
    usage = _usage_text()
    assert "Automatic HCAN device binding" in usage
    assert "o10_hand_binding.json" in usage
    assert "omnihand_o10_probe resolve" in usage
    assert "debug back door" in usage
