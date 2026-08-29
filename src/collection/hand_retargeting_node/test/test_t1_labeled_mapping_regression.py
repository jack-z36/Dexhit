"""T1 RED regressions for labeled hand-mapping behavior.

The real-frame tests use the small derivatives in
``t1_real_left_raw_frames.py``.  The lateral tests deliberately use a
canonical synthetic palm with pure per-finger lateral direction changes so
they isolate mapping from human scale and pose changes.
"""

from __future__ import annotations

from hand_retargeting.adapters.model_geometry import load_robot_geometry
from hand_retargeting.adapters.nlopt import NloptSlsqpOptimizer
from hand_retargeting.adapters.pinocchio import PinocchioFingerKinematics
from hand_retargeting.application.session import (
    FINGER_TIP_BASES,
    RetargetingSession,
)
from hand_retargeting.contracts import RawHandFrameValue, RetargetingConfig
from hand_retargeting.core.coupling import CouplingModel
import numpy as np
from omnihand_o10_contracts import ACTIVE_JOINT_NAMES, JOINT_LIMITS, Side
from omnihand_o10_model import load_model
from omnihand_o10_model.contract import tip_link
import pytest
from t1_real_left_raw_frames import REAL_LEFT_FLEX_G, REAL_LEFT_OPEN_I


pytestmark = pytest.mark.skipif(
    not __import__("os").environ.get("OMNIHAND_O10_MODEL_FIXTURE"),
    reason="T1 real-model regression requires OMNIHAND_O10_MODEL_FIXTURE",
)


def _real_left_session():
    assets = load_model()["left"]
    geometry = load_robot_geometry("left")
    kinematics = PinocchioFingerKinematics.from_urdf(assets.urdf_path, "left")
    coupling = CouplingModel.from_mjcf(assets.coupling_model)
    config = RetargetingConfig(
        1e-6, 1e-6, 1e-6, 3, 2,
        (0.01,) * 5, (0.10,) * 5, (0.05,) * 5,
        500, 0.5, (0.1,) * 10, 0.5, 3, 0.1, 0.5,
    )
    session = RetargetingSession(
        Side.LEFT,
        config,
        geometry,
        coupling=coupling,
        kinematics=kinematics,
        optimizer=NloptSlsqpOptimizer(coupling, kinematics, 500, 0.5),
    )
    return geometry, kinematics, coupling, session


def _real_right_session():
    assets = load_model()["right"]
    geometry = load_robot_geometry("right")
    kinematics = PinocchioFingerKinematics.from_urdf(assets.urdf_path, "right")
    coupling = CouplingModel.from_mjcf(assets.coupling_model)
    config = RetargetingConfig(
        1e-6, 1e-6, 1e-6, 3, 2,
        (0.01,) * 5, (0.10,) * 5, (0.05,) * 5,
        500, 0.5, (0.1,) * 10, 0.5, 3, 0.1, 0.5,
    )
    session = RetargetingSession(
        Side.RIGHT,
        config,
        geometry,
        coupling=coupling,
        kinematics=kinematics,
        optimizer=NloptSlsqpOptimizer(coupling, kinematics, 500, 0.5),
    )
    return geometry, kinematics, coupling, session


def _process_after_freezing(session, frame, start_ns):
    decisions = []
    for index in range(4):
        decisions.append(session.process(
            RawHandFrameValue(frame.node_names, frame.positions, start_ns + index * 100_000_000)
        ))
    return decisions[-1]


def _canonical_lateral_frame(lateral_by_finger, stamp_ns):
    """Build a pure-lateral 21-node left frame with constant finger lengths."""
    suffixes = (
        "Hand", "ThumbProximal", "ThumbMedial", "ThumbDistal", "ThumbTip",
        "IndexProximal", "IndexMedial", "IndexDistal", "IndexTip",
        "MiddleProximal", "MiddleMedial", "MiddleDistal", "MiddleTip",
        "RingProximal", "RingMedial", "RingDistal", "RingTip",
        "LittleProximal", "LittleMedial", "LittleDistal", "LittleTip",
    )
    roots_x = (0.8, 0.6, 0.2, -0.2, -0.6)
    positions = [(0.0, 0.0, 0.0)]
    for finger_index, root_x in enumerate(roots_x):
        direction = np.asarray((lateral_by_finger[finger_index], 1.0, 0.0))
        direction /= np.linalg.norm(direction)
        root = np.asarray((root_x, 1.0, 0.0))
        for fraction in (0.0, 1 / 3, 2 / 3, 1.0):
            positions.append(tuple(root + fraction * direction))
    return RawHandFrameValue(
        tuple("left" + suffix for suffix in suffixes),
        tuple(positions),
        stamp_ns,
    )


def _canonical_right_lateral_frame(lateral_by_finger, stamp_ns):
    """Encode physical lateral directions in the inferred right glove convention.

    `lateral_by_finger` keeps its physical meaning: positive values are
    displacements toward the index side.  The hypothesized Rokoko right
    glove encoding inverts the lateral sign, so the fixture negates the
    palm-frame X displacement before the left builder is reused.
    """
    inverted = tuple(-value for value in lateral_by_finger)
    left = _canonical_lateral_frame(inverted, stamp_ns)
    return RawHandFrameValue(
        tuple(name.replace("left", "right", 1) for name in left.node_names),
        left.positions,
        left.received_at_ns,
    )


def test_real_labeled_thumb_flexion_has_deeper_left_thumb_mcp():
    """Real G flex must be deeper than real I open at thumb_mcp."""
    geometry, kinematics, coupling, session = _real_left_session()
    flex = _process_after_freezing(session, REAL_LEFT_FLEX_G, 2_000_000_000)
    opened = session.process(
        RawHandFrameValue(
            REAL_LEFT_OPEN_I.node_names,
            REAL_LEFT_OPEN_I.positions,
            2_500_000_000,
        )
    )

    assert flex.command_positions is not None
    assert opened.command_positions is not None
    assert flex.has_valid_ik == (True,) * 5
    assert opened.has_valid_ik == (True,) * 5
    limits = JOINT_LIMITS[Side.LEFT]
    assert limits.contains(np.asarray(flex.command_positions))
    assert limits.contains(np.asarray(opened.command_positions))
    assert flex.command_positions[2] < opened.command_positions[2], (
        "G_FLEX_HOLD vs I_OPEN_HOLD: expected flex thumb_mcp to be more negative; "
        f"flex={flex.command_positions[2]!r}, "
        f"open={opened.command_positions[2]!r}, "
        f"flex_ik={flex.ik_state!r}, open_ik={opened.ik_state!r}"
    )

    flex_q = coupling.evaluate(np.asarray(flex.command_positions))
    open_q = coupling.evaluate(np.asarray(opened.command_positions))
    flex_tip = kinematics.tip_position_and_jacobian(
        flex_q, tip_link("left", "thumb_tip")
    )[0]
    open_tip = kinematics.tip_position_and_jacobian(
        open_q, tip_link("left", "thumb_tip")
    )[0]
    palm_center = np.mean(np.asarray(geometry.finger_roots[1:]), axis=0)
    assert np.linalg.norm(flex_tip - palm_center) < np.linalg.norm(
        open_tip - palm_center
    )


def test_right_glove_convention_thumb_adduction_has_flexion_semantics():
    """The inferred right glove encoding must still produce thumb adduction.

    Inference from the real-machine-verified left correction: both Rokoko
    gloves are hypothesized to deliver a laterally inverted component
    encoding, so a physical right-thumb adduction (toward the little side)
    arrives as a positive palm-frame X displacement.  This locks the
    inferred production convention; it is not evidence from a real right
    glove.
    """
    geometry, kinematics, coupling, session = _real_right_session()
    baseline = _canonical_right_lateral_frame((0.0,) * 5, 2_000_000_000)
    adducted_frame = _canonical_right_lateral_frame(
        (-0.25, 0.0, 0.0, 0.0, 0.0), 2_500_000_000
    )
    base = _process_after_freezing(session, baseline, 2_000_000_000)
    adducted = session.process(
        RawHandFrameValue(
            adducted_frame.node_names,
            adducted_frame.positions,
            2_500_000_000,
        )
    )

    assert base.command_positions is not None
    assert adducted.command_positions is not None
    assert base.has_valid_ik == (True,) * 5
    assert adducted.has_valid_ik == (True,) * 5
    assert JOINT_LIMITS[Side.RIGHT].contains(np.asarray(base.command_positions))
    assert JOINT_LIMITS[Side.RIGHT].contains(
        np.asarray(adducted.command_positions)
    )
    assert adducted.command_positions[2] > base.command_positions[2]

    base_tip = kinematics.tip_position_and_jacobian(
        coupling.evaluate(np.asarray(base.command_positions)),
        tip_link("right", "thumb_tip"),
    )[0]
    adducted_tip = kinematics.tip_position_and_jacobian(
        coupling.evaluate(np.asarray(adducted.command_positions)),
        tip_link("right", "thumb_tip"),
    )[0]
    palm_center = np.mean(np.asarray(geometry.finger_roots[1:]), axis=0)
    assert np.linalg.norm(adducted_tip - palm_center) < np.linalg.norm(
        base_tip - palm_center
    )


@pytest.mark.parametrize(
    ("finger_index", "abad_index"),
    ((1, 3), (3, 6), (4, 8)),
    ids=("right-index", "right-ring", "right-pinky"),
)
@pytest.mark.parametrize("lateral", (0.25, -0.25), ids=("index-side", "little-side"))
def test_right_signed_lateral_input_moves_tip_in_physical_direction(
    finger_index, abad_index, lateral
):
    """Right physical lateral directions follow the inferred glove encoding.

    Physical lateral intents (positive toward the index side) are encoded
    with an inverted palm-frame X by the inferred Rokoko right-glove
    convention; the FK outcome must still follow the verified O10 root
    ordering.  This is an inference, not real right-glove evidence.
    """
    geometry, kinematics, coupling, session = _real_right_session()
    baseline = _canonical_right_lateral_frame((0.0,) * 5, 3_000_000_000)
    shifted_values = [0.0] * 5
    shifted_values[finger_index] = lateral
    shifted = _canonical_right_lateral_frame(shifted_values, 3_500_000_000)
    before = _process_after_freezing(session, baseline, 3_000_000_000)
    after = session.process(shifted)

    assert before.command_positions is not None
    assert after.command_positions is not None
    assert after.has_valid_ik == (True,) * 5
    assert JOINT_LIMITS[Side.RIGHT].contains(np.asarray(before.command_positions))
    assert JOINT_LIMITS[Side.RIGHT].contains(np.asarray(after.command_positions))
    before_tip = kinematics.tip_position_and_jacobian(
        coupling.evaluate(np.asarray(before.command_positions)),
        tip_link("right", FINGER_TIP_BASES[finger_index]),
    )[0]
    after_tip = kinematics.tip_position_and_jacobian(
        coupling.evaluate(np.asarray(after.command_positions)),
        tip_link("right", FINGER_TIP_BASES[finger_index]),
    )[0]
    expected_robot_delta = (
        np.asarray(geometry.finger_roots[1])
        - np.asarray(geometry.finger_roots[4])
    )
    expected_robot_delta /= np.linalg.norm(expected_robot_delta)
    physical_delta = np.asarray(after_tip) - np.asarray(before_tip)
    signed_physical_delta = float(np.dot(physical_delta, expected_robot_delta))
    if finger_index == 1 and lateral < 0.0:
        # Right index ABAD is one-sided [-0.164, 0].  From the neutral upper
        # bound it cannot travel toward the little-finger side; the correct
        # bounded behavior is negligible motion, never a reversed response.
        assert after.command_positions[abad_index] == pytest.approx(
            JOINT_LIMITS[Side.RIGHT].upper[abad_index], abs=1e-4
        )
        assert abs(signed_physical_delta) < 1e-4
    else:
        assert abs(signed_physical_delta) > 1e-4
    assert lateral * signed_physical_delta >= 0.0, (
        f"finger={finger_index}, abad={ACTIVE_JOINT_NAMES[abad_index]}, "
        f"lateral={lateral!r}, signed_delta={signed_physical_delta!r}, "
        f"before={before.command_positions[abad_index]!r}, "
        f"after={after.command_positions[abad_index]!r}, "
        f"before_ik={before.ik_state!r}, after_ik={after.ik_state!r}, "
        f"used_previous={after.used_previous_valid_target!r}, "
        f"residual={after.normalized_residual!r}, "
        f"projection={after.target_projection_applied!r}"
    )


@pytest.mark.parametrize(
    ("finger_index", "abad_index"),
    ((1, 3), (3, 6), (4, 8)),
    ids=("index", "ring", "pinky"),
)
def test_synthetic_lateral_separation_moves_abad_in_anatomical_direction(
    finger_index, abad_index
):
    """Pure human +X must produce the same physical lateral direction in FK."""
    geometry, kinematics, coupling, session = _real_left_session()
    baseline = _canonical_lateral_frame((0.0,) * 5, 3_000_000_000)
    shifted_values = [0.0] * 5
    shifted_values[finger_index] = 0.25
    shifted = _canonical_lateral_frame(shifted_values, 3_500_000_000)
    before = _process_after_freezing(session, baseline, 3_000_000_000)
    after = session.process(shifted)

    assert before.command_positions is not None
    assert after.command_positions is not None
    assert after.has_valid_ik == (True,) * 5
    before_q = coupling.evaluate(np.asarray(before.command_positions))
    after_q = coupling.evaluate(np.asarray(after.command_positions))
    before_tip = kinematics.tip_position_and_jacobian(
        before_q, tip_link("left", FINGER_TIP_BASES[finger_index])
    )[0]
    after_tip = kinematics.tip_position_and_jacobian(
        after_q, tip_link("left", FINGER_TIP_BASES[finger_index])
    )[0]
    # With the anatomical +X fixture, positive human X is toward the index
    # side.  The verified left O10 roots place that side at negative robot Y.
    # Derive the physical expected direction from verified O10 root geometry,
    # not from the current direction mapping.  Index-side is index-root minus
    # little-root in the O10 palm frame.
    expected_robot_delta = (
        np.asarray(geometry.finger_roots[1])
        - np.asarray(geometry.finger_roots[4])
    )
    expected_robot_delta /= np.linalg.norm(expected_robot_delta)
    physical_delta = np.asarray(after_tip) - np.asarray(before_tip)
    assert np.dot(physical_delta, expected_robot_delta) > 0.0, (
        f"finger={finger_index}, abad={ACTIVE_JOINT_NAMES[abad_index]}, "
        f"before={before.command_positions[abad_index]!r}, "
        f"after={after.command_positions[abad_index]!r}, "
        f"before_ik={before.ik_state!r}, after_ik={after.ik_state!r}, "
        f"used_previous={after.used_previous_valid_target!r}, "
        f"residual={after.normalized_residual!r}, "
        f"projection={after.target_projection_applied!r}"
    )
