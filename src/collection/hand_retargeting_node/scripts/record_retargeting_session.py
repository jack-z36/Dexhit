#!/usr/bin/env python3
"""Record one retargeting session to JSONL for offline IK diagnosis.

Subscribes to /rokoko/{side}/raw_hand and /hand_retargeting/{side}/state and
writes one JSON object per line.  The raw frames are the analysis input for
ik_failure_diagnose.py; the state lines are only used as the live-vs-offline
replay fidelity reference.  Orientations are not recorded: the retargeting
pipeline consumes positions only (see RawHandFrame.msg contract notes).

Pose marking: type a label in this terminal and press Enter at the moment a
pose starts, for example ``P0``, ``P4a`` or ``thumb-outward``.  A marker line
is written into the JSONL interleaved with the frames, and the offline
analysis segments frames per pose from these markers.  Stop with Ctrl-C.

Run it in the same shell/environment used to launch the retargeting nodes
(after sourcing the workspace install setup), for example:

    python3 scripts/record_retargeting_session.py --side left --output runs/session_left.jsonl

Diagnostic tool only: not installed by setup.py, not part of any launch, and
it never publishes anything.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import threading
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from rokoko_omnihand_msgs.msg import RawHandFrame, RetargetingState

_PHASE_NAMES = {
    RetargetingState.PHASE_INITIALIZING: "initializing",
    RetargetingState.PHASE_COLLECTING_LENGTHS: "collecting-lengths",
    RetargetingState.PHASE_WAITING_FIRST_VALID_IK: "waiting-first-valid-ik",
    RetargetingState.PHASE_TRACKING: "tracking",
    RetargetingState.PHASE_STALE: "stale",
    RetargetingState.PHASE_RECOVERY_CONFIRMING: "recovery-confirming",
    RetargetingState.PHASE_RECOVERY_RESUMING: "recovery-resuming",
    RetargetingState.PHASE_MODEL_ERROR: "model-error",
}
_IK_NAMES = {
    RetargetingState.IK_UNINITIALIZED: "uninitialized",
    RetargetingState.IK_VALID: "valid",
    RetargetingState.IK_INPUT_INVALID: "input-invalid",
    RetargetingState.IK_SIDE_INVALID: "side-invalid",
    RetargetingState.IK_RESIDUAL_EXCEEDED: "residual-exceeded",
    RetargetingState.IK_SOLVER_ERROR: "solver-error",
    RetargetingState.IK_NOT_RUN_LENGTH_COLLECTING: "not-run-length-collecting",
    RetargetingState.IK_NOT_RUN_STALE: "not-run-stale",
}
_LENGTH_NAMES = {
    RetargetingState.LENGTH_COLLECTING: "collecting",
    RetargetingState.LENGTH_FROZEN: "frozen",
    RetargetingState.LENGTH_CURRENT_INVALID: "current-invalid",
}


def _stamp_ns(stamp) -> int:
    return int(stamp.sec) * 1_000_000_000 + int(stamp.nanosec)


class SessionRecorder(Node):

    def __init__(self, side: str, output: Path) -> None:
        super().__init__("retargeting_session_recorder")
        self._side = side
        self._handle = open(output, "w", encoding="utf-8")
        self._write_lock = threading.Lock()
        self._handle.write(json.dumps({
            "type": "meta",
            "recorded_at_ns": time.time_ns(),
            "side": side,
            "output": str(output),
            "argv": sys.argv,
        }) + "\n")
        self._handle.flush()
        self.counts = {"raw": 0, "state": 0, "marker": 0}
        raw_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST, depth=1,
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
        )
        state_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST, depth=50,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
        )
        self.create_subscription(
            RawHandFrame, f"/rokoko/{side}/raw_hand", self._on_raw, raw_qos
        )
        self.create_subscription(
            RetargetingState, f"/hand_retargeting/{side}/state", self._on_state, state_qos
        )
        self.get_logger().info(f"recording side={side} to {output}")
        self.get_logger().info("type a pose label and press Enter to mark it")

    def _write(self, payload: dict) -> None:
        line = json.dumps(payload) + "\n"
        with self._write_lock:
            self._handle.write(line)
            self._handle.flush()

    def _marker_loop(self) -> None:
        for line in sys.stdin:
            label = line.strip()
            if not label:
                continue
            self.counts["marker"] += 1
            self._write({
                "type": "marker",
                "recorded_ns": time.time_ns(),
                "label": label,
            })
            self.get_logger().info(f"marked pose {label!r}")

    def _on_raw(self, message: RawHandFrame) -> None:
        self.counts["raw"] += 1
        self._write({
            "type": "raw",
            "recorded_ns": time.time_ns(),
            "header_stamp_ns": _stamp_ns(message.header.stamp),
            "actor_index": message.actor_index,
            "actor_name": message.actor_name,
            "source_timestamp": float(message.source_timestamp),
            "node_names": list(message.node_names),
            "positions": [[p.x, p.y, p.z] for p in message.positions],
        })

    def _on_state(self, message: RetargetingState) -> None:
        self.counts["state"] += 1
        self._write({
            "type": "state",
            "recorded_ns": time.time_ns(),
            "header_stamp_ns": _stamp_ns(message.header.stamp),
            "input_stamp_ns": _stamp_ns(message.input_stamp),
            "phase": _PHASE_NAMES.get(message.phase, str(message.phase)),
            "ready": bool(message.ready),
            "stale": bool(message.stale),
            "command_published": bool(message.command_published),
            "length_state": [
                _LENGTH_NAMES.get(value, str(value)) for value in message.length_state
            ],
            "ik_state": [_IK_NAMES.get(value, str(value)) for value in message.ik_state],
            "has_valid_ik": [bool(value) for value in message.has_valid_ik],
            "used_previous_valid_target": [
                bool(value) for value in message.used_previous_valid_target
            ],
            "residual_available": [bool(value) for value in message.residual_available],
            "normalized_residual": [float(v) for v in message.normalized_residual],
            "solver_result_code": [int(v) for v in message.solver_result_code],
            "solver_evaluations": [int(v) for v in message.solver_evaluations],
        })

    def close(self) -> None:
        self._handle.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--side", default="left", choices=("left", "right"))
    parser.add_argument(
        "--output", default=None,
        help="output JSONL path (default retargeting_session_<side>_<time>.jsonl)",
    )
    arguments = parser.parse_args(argv)
    output = Path(
        arguments.output
        or f"retargeting_session_{arguments.side}_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"
    )
    output.parent.mkdir(parents=True, exist_ok=True)

    rclpy.init(args=argv)
    recorder = SessionRecorder(arguments.side, output)
    marker_thread = threading.Thread(target=recorder._marker_loop, daemon=True)
    marker_thread.start()
    try:
        rclpy.spin(recorder)
    except KeyboardInterrupt:
        pass
    except rclpy.executors.ExternalShutdownException:
        pass
    finally:
        counts = dict(recorder.counts)
        recorder.close()
        recorder.destroy_node()
        try:
            if rclpy.ok():
                rclpy.shutdown()
        except Exception:  # noqa: BLE001 - shutdown may race signal handlers
            pass
    print(f"recorded {counts['raw']} raw frames and {counts['state']} states to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
