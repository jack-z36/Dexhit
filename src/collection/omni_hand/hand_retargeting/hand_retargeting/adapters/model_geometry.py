"""Derive T05 robot geometry from the verified, version-locked O10 URDF."""

from __future__ import annotations

from omnihand_o10_model import load_model
from omnihand_o10_model.contract import joint_name, palm_frame, tip_link

from ..core.normalization import RobotHandGeometry


class RobotGeometryLoadError(RuntimeError):
    """The verified model cannot provide a valid T05 geometry contract."""


_FINGER_CHAINS = (
    ("thumb_roll", "thumb_abad", "thumb_mcp", "thumb_pip", "thumb_dip"),
    ("index_abad", "index_pip", "index_dip"),
    ("middle_pip", "middle_dip"),
    ("ring_abad", "ring_pip", "ring_dip"),
    ("pinky_abad", "pinky_pip", "pinky_dip"),
)
_TIP_BASES = ("thumb_tip", "index_tip", "middle_tip", "ring_tip", "pinky_tip")


def _unit(vector, label: str):
    import numpy as np

    norm = float(np.linalg.norm(vector))
    if not np.isfinite(norm) or norm <= 0.0:
        raise RobotGeometryLoadError(f"{label} is degenerate")
    return vector / norm


def load_robot_geometry(side: str) -> RobotHandGeometry:
    """Load, verify and derive roots, chain lengths and the shared mapping."""
    try:
        import numpy as np
        import pinocchio as pin

        assets = load_model()[side]
        model = pin.buildModelFromUrdf(str(assets.urdf_path))
        if model.nq != 16 or model.nv != 16:
            raise RobotGeometryLoadError(
                f"expected O10 nq=nv=16, got nq={model.nq} nv={model.nv}"
            )
        data = model.createData()
        pin.forwardKinematics(model, data, np.zeros(model.nq))
        pin.updateFramePlacements(model, data)
        palm_id = model.getFrameId(palm_frame(side))
        if palm_id >= len(model.frames):
            raise RobotGeometryLoadError(f"missing canonical palm frame for {side}")
        palm_in_world = data.oMf[palm_id]

        def in_palm(world_point):
            return palm_in_world.rotation.T @ (world_point - palm_in_world.translation)

        roots = []
        lengths = []
        for chain, tip_base in zip(_FINGER_CHAINS, _TIP_BASES):
            points = []
            for base in chain:
                joint_id = model.getJointId(joint_name(side, base))
                if joint_id == 0:
                    raise RobotGeometryLoadError(f"missing model joint {base!r}")
                points.append(in_palm(data.oMi[joint_id].translation))
            tip_name = tip_link(side, tip_base)
            tip_id = model.getFrameId(tip_name)
            if tip_id >= len(model.frames):
                raise RobotGeometryLoadError(f"missing model tip frame {tip_name!r}")
            points.append(in_palm(data.oMf[tip_id].translation))
            roots.append(tuple(float(value) for value in points[0]))
            lengths.append(sum(
                float(np.linalg.norm(points[index + 1] - points[index]))
                for index in range(len(points) - 1)
            ))

        center = sum((np.asarray(root) for root in roots[1:]), np.zeros(3)) / 4.0
        y_axis = _unit(center, "robot palm longitudinal axis")
        raw_x = (
            np.asarray(roots[1]) - np.asarray(roots[4])
            if side == "right"
            else np.asarray(roots[4]) - np.asarray(roots[1])
        )
        x_axis = _unit(raw_x - float(raw_x @ y_axis) * y_axis, "robot palm transverse axis")
        z_axis = np.cross(x_axis, y_axis)
        mapping = tuple(
            tuple(float(value) for value in column)
            for column in (x_axis, y_axis, z_axis)
        )
        # RobotHandGeometry stores rows for matrix-vector multiplication.  The
        # vectors above are the columns of A_s, so transpose them here.
        mapping_rows = tuple(zip(*mapping))
        return RobotHandGeometry(tuple(roots), tuple(lengths), mapping_rows)
    except RobotGeometryLoadError:
        raise
    except Exception as error:
        raise RobotGeometryLoadError(
            f"cannot derive {side} O10 geometry from verified model assets: {error}"
        ) from error


def load_runtime_assets(side: str):
    """Load the verified side record used by Pinocchio and coupling adapters."""
    try:
        return load_model()[side]
    except Exception as error:
        raise RobotGeometryLoadError(str(error)) from error
