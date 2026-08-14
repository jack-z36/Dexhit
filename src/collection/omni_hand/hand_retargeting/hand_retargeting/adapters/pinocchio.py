"""Pinocchio adapter exposing only tip translation and its full Jacobian."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from omnihand_o10_model.contract import full_joint_names, palm_frame


class PinocchioUnavailableError(RuntimeError):
    """The real numeric backend is not installed in the current environment."""


class PinocchioFingerKinematics:
    """Adapter for a mimic-disabled, 16-DoF Pinocchio model."""

    def __init__(self, model, side: str):
        self.model = model
        self.side = side
        self.data = model.createData()
        self.palm_id = model.getFrameId(palm_frame(side))
        if self.palm_id >= len(model.frames):
            raise ValueError(f"missing palm frame for {side}")
        if model.nq != 16 or model.nv != 16:
            raise ValueError(f"expected Pinocchio model nq=nv=16, got {model.nq}/{model.nv}")
        self._pin_q_indices = tuple(
            int(model.idx_qs[model.getJointId(name)])
            for name in full_joint_names(side)
        )
        if sorted(self._pin_q_indices) != list(range(16)):
            raise ValueError(
                "Pinocchio joint order does not cover the 16-joint O10 contract"
            )

    @classmethod
    def from_urdf(cls, urdf_path: str | Path, side: str) -> "PinocchioFingerKinematics":
        try:
            import pinocchio as pin
        except Exception as error:
            raise PinocchioUnavailableError(
                "BLOCKED_ENV: pinocchio (python bindings, import pinocchio) is unavailable"
            ) from error
        # ``mimic=False`` is deliberate: all 16 URDF joints remain in FK.
        model = pin.buildModelFromUrdf(str(urdf_path), mimic=False)
        return cls(model, side)

    def tip_position_and_jacobian(
        self, full_q: np.ndarray, tip_frame: str
    ) -> tuple[np.ndarray, np.ndarray]:
        import pinocchio as pin

        q_contract = np.asarray(full_q, dtype=np.float64)
        if q_contract.shape != (16,):
            raise ValueError("full state must be a 16-vector")
        q = np.empty(16, dtype=np.float64)
        q[list(self._pin_q_indices)] = q_contract
        pin.forwardKinematics(self.model, self.data, q)
        pin.updateFramePlacements(self.model, self.data)
        tip_id = self.model.getFrameId(tip_frame)
        if tip_id >= len(self.model.frames):
            raise ValueError(f"missing tip frame {tip_frame}")
        palm = self.data.oMf[self.palm_id]
        tip = self.data.oMf[tip_id]
        # LOCAL_WORLD_ALIGNED gives the derivative of the frame-origin
        # translation in fixed world axes.  ``WORLD`` is a spatial-velocity
        # representation whose linear block is not the direct translation
        # derivative needed by the IK chain rule at a non-root frame.
        jacobian = pin.computeFrameJacobian(
            self.model, self.data, q, tip_id, pin.ReferenceFrame.LOCAL_WORLD_ALIGNED
        )[:3, :]
        # Express both position and the complete translation Jacobian in palm
        # coordinates. No active-column extraction is permitted here.
        return (
            palm.rotation.T @ (tip.translation - palm.translation),
            palm.rotation.T @ jacobian[:, list(self._pin_q_indices)],
        )


def load_pinocchio_kinematics(assets, side: str) -> PinocchioFingerKinematics:
    """Construct the adapter from a verified model asset record."""
    return PinocchioFingerKinematics.from_urdf(assets.urdf_path, side)
