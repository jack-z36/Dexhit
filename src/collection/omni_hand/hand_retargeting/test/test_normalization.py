import math

from hand_retargeting.application.session import RetargetingSession
from hand_retargeting.contracts import RawHandFrameValue, RetargetingConfig
from hand_retargeting.core.normalization import RobotHandGeometry
from omnihand_o10_contracts import Side
import pytest


def _frame(side: Side, *, scale: float = 1.0, translate=(0.0, 0.0, 0.0)):
    prefix = side.value
    suffixes = (
        "Hand",
        "ThumbProximal", "ThumbMedial", "ThumbDistal", "ThumbTip",
        "IndexProximal", "IndexMedial", "IndexDistal", "IndexTip",
        "MiddleProximal", "MiddleMedial", "MiddleDistal", "MiddleTip",
        "RingProximal", "RingMedial", "RingDistal", "RingTip",
        "LittleProximal", "LittleMedial", "LittleDistal", "LittleTip",
    )
    # Right-hand geometry has anatomical +X from little to index.  The left
    # fixture is mirrored so its side-specific definition produces the same
    # palm-frame coordinates.
    x_sign = 1.0 if side is Side.RIGHT else -1.0
    roots_x = (0.8, 0.6, 0.2, -0.2, -0.6)
    positions = [(0.0, 0.0, 0.0)]
    for root_x in roots_x:
        x = x_sign * root_x
        positions.extend(
            [(x, 1.0, 0.0), (x, 1.4, 0.0), (x, 1.8, 0.0), (x, 2.2, 0.0)]
        )
    tx, ty, tz = translate
    transformed = tuple(
        (scale * x + tx, scale * y + ty, scale * z + tz)
        for x, y, z in positions
    )
    return RawHandFrameValue(
        node_names=tuple(prefix + suffix for suffix in suffixes),
        positions=transformed,
        received_at_ns=123,
    )


def _geometry():
    return RobotHandGeometry(
        finger_roots=tuple((float(index), 0.0, 0.0) for index in range(5)),
        finger_chain_lengths=(2.0, 3.0, 4.0, 5.0, 6.0),
        direction_mapping=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    )


def _config(**overrides):
    values = {
        "palm_y_epsilon": 1e-6,
        "palm_x_epsilon": 1e-6,
        "finger_length_epsilon": 1e-6,
        "length_window_size": 3,
        "stable_window_count": 2,
        "length_nmad_thresholds": (0.01,) * 5,
        "frozen_length_relative_thresholds": (0.10,) * 5,
        "ik_residual_thresholds": (0.05,) * 5,
        "ik_max_evaluations": 100,
        "ik_max_time_sec": 0.02,
        "smooth_time_constants": (0.1,) * 10,
        "stale_timeout_sec": 0.5,
        "recovery_min_valid_frames": 3,
        "recovery_min_duration_sec": 0.1,
    }
    values.update(overrides)
    return RetargetingConfig(**values)


@pytest.mark.parametrize("side", (Side.LEFT, Side.RIGHT))
def test_stable_sequence_freezes_lengths_then_exposes_scale_normalized_targets(side):
    session = RetargetingSession(side, _config(), _geometry())

    decisions = [session.process(_frame(side, scale=2.5)) for _ in range(4)]

    assert [decision.phase for decision in decisions] == [
        "collecting-lengths", "collecting-lengths",
        "collecting-lengths", "waiting-first-valid-ik"
    ]
    frozen = decisions[-1]
    assert frozen.all_lengths_frozen is True
    assert frozen.command_published is False
    assert frozen.length_frozen == (True,) * 5
    assert frozen.length_current_valid == (True,) * 5
    assert frozen.targets is not None
    # The scale=2.5 human hand still yields the same dimensionless proximal-tip
    # vector: (0, 3.0, 0) / full chain length 3.0.
    assert frozen.targets[0] == pytest.approx((0.0, 2.0, 0.0))
    assert frozen.targets[4] == pytest.approx((4.0, 6.0, 0.0))

    waiting = session.process(_frame(side, scale=2.5, translate=(8.0, -3.0, 4.0)))
    assert waiting.phase == "waiting-first-valid-ik"
    assert waiting.targets is not None
    assert frozen.targets is not None
    for actual, expected in zip(waiting.targets, frozen.targets):
        assert actual == pytest.approx(expected)

    other_operator = RetargetingSession(side, _config(), _geometry())
    for _ in range(4):
        other = other_operator.process(_frame(side, scale=1.0))
    assert other.targets is not None
    for actual, expected in zip(other.targets, frozen.targets):
        assert actual == pytest.approx(expected)


def test_hand_orientation_is_not_part_of_the_public_normalization_input():
    frame = _frame(Side.RIGHT)
    assert not hasattr(frame, "orientations")
    session = RetargetingSession(Side.RIGHT, _config(), _geometry())
    for _ in range(4):
        result = session.process(frame)
    assert result.all_lengths_frozen


def test_degenerate_palm_rejects_whole_side_without_advancing_length_windows():
    session = RetargetingSession(Side.RIGHT, _config(), _geometry())
    frame = _frame(Side.RIGHT)
    positions = list(frame.positions)
    for index in (5, 9, 13, 17):
        positions[index] = positions[0]
    invalid = RawHandFrameValue(frame.node_names, tuple(positions), frame.received_at_ns)

    rejected = session.process(invalid)
    subsequent = [session.process(frame) for _ in range(4)]

    assert rejected.side_valid is False
    assert rejected.targets is None
    assert [item.phase for item in subsequent] == [
        "collecting-lengths", "collecting-lengths",
        "collecting-lengths", "waiting-first-valid-ik"
    ]


def test_unstable_window_resets_consecutive_stability_before_freezing():
    session = RetargetingSession(
        Side.RIGHT,
        _config(length_window_size=4, length_nmad_thresholds=(0.001,) * 5),
        _geometry(),
    )
    scales = (1.0, 1.0, 1.0, 1.0, 2.0, 2.0, 1.0, 1.0, 1.0, 1.0)
    decisions = [session.process(_frame(Side.RIGHT, scale=scale)) for scale in scales]
    assert decisions[3].all_lengths_frozen is False
    assert decisions[-1].all_lengths_frozen is True


def test_frozen_single_finger_length_anomaly_does_not_change_frozen_value():
    session = RetargetingSession(Side.RIGHT, _config(), _geometry())
    frame = _frame(Side.RIGHT)
    for _ in range(4):
        frozen = session.process(frame)
    before = frozen.length_frozen

    positions = list(frame.positions)
    positions[4] = (positions[4][0], positions[4][1] + 2.0, positions[4][2])
    anomalous = RawHandFrameValue(frame.node_names, tuple(positions), 456)
    result = session.process(anomalous)

    assert result.side_valid is True
    assert result.length_current_valid[0] is False
    assert all(result.length_current_valid[1:])
    assert result.targets[0] is None
    assert all(target is not None for target in result.targets[1:])
    assert result.length_frozen == before


def test_left_and_right_sessions_do_not_share_mutable_length_history():
    left = RetargetingSession(Side.LEFT, _config(), _geometry())
    right = RetargetingSession(Side.RIGHT, _config(), _geometry())
    for _ in range(4):
        left_result = left.process(_frame(Side.LEFT))

    right_result = right.process(_frame(Side.RIGHT))
    assert left_result.all_lengths_frozen is True
    assert right_result.all_lengths_frozen is False


def test_config_rejects_unmarked_experimental_defaults_and_bad_threshold_shapes():
    with pytest.raises(TypeError):
        RetargetingConfig()
    with pytest.raises(ValueError, match="five"):
        _config(length_nmad_thresholds=(0.01,))
    with pytest.raises(ValueError, match="positive"):
        _config(palm_y_epsilon=math.nan)


def test_direction_mapping_multiplies_like_a_fixed_rotation_matrix():
    # A 90-degree rotation about +z, expressed as ROW vectors of A_s so that
    # map_vector computes A_s @ v (equation 38 of the algorithm baseline).
    rotation = ((0.0, -1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    geometry = RobotHandGeometry(
        finger_roots=tuple((float(index), 0.0, 0.0) for index in range(5)),
        finger_chain_lengths=(2.0, 3.0, 4.0, 5.0, 6.0),
        direction_mapping=rotation,
    )
    assert geometry.map_vector((1.0, 0.0, 0.0)) == pytest.approx((0.0, 1.0, 0.0))
    assert geometry.map_vector((0.0, 1.0, 0.0)) == pytest.approx((-1.0, 0.0, 0.0))
    assert geometry.map_vector((0.0, 0.0, 1.0)) == pytest.approx((0.0, 0.0, 1.0))


def test_robot_geometry_rejects_non_orthonormal_mapping():
    bad = ((1.0, 0.0, 0.0), (0.0, 2.0, 0.0), (0.0, 0.0, 1.0))
    with pytest.raises(ValueError, match="orthonormal"):
        RobotHandGeometry(
            finger_roots=tuple((float(index), 0.0, 0.0) for index in range(5)),
            finger_chain_lengths=(2.0, 3.0, 4.0, 5.0, 6.0),
            direction_mapping=bad,
        )
