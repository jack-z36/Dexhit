"""O10 device auto-discovery and side-to-serial binding CLI.

Implements the frozen contract of ``DOCS/03_工程/10_O10设备自动绑定与探测.md``:
``scan`` reports which ``canfd_device_id`` indexes carry an online O10 hand,
``resolve`` maps the requested logical :class:`Side` onto discovered indexes
(persisting automatic side bindings), and ``bind`` registers one deliberately
connected hand under an explicitly chosen side.  The binding file stores
side -> factory serial only; the CANFD index is re-discovered on every run.

Layering: this module sits at the package top level next to ``backends.py``.
It must not import rclpy or ROS messages, and the external ``omnihand`` wheel
is imported lazily inside :func:`_create_hand` so that importing this module
(and installing the console script) never requires the SDK.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from omnihand_o10_contracts import Side

from .backends import AgilinkO10Backend

__all__ = [
    "ProbeFailure",
    "default_binding_path",
    "load_binding_table",
    "main",
    "resolve_assignments",
    "save_binding_table",
    "scan_buses",
]

DEFAULT_MAX_INDEX = 3
DEFAULT_RECV_TIMEOUT_MS = 200
BINDING_FILE_NAME = "o10_hand_binding.json"
_LAUNCHER_MARKER = "start_omnihand_control.sh"
_MAX_ROOT_SEARCH_LEVELS = 6
_ENV_PREFIX = "DEXHIT_COLLECTION_PREFIX"


class ProbeFailure(Exception):
    """One resolve/bind outcome frozen as abort-with-exit-1; message goes to stderr."""


# --- the single SDK seam ------------------------------------------------------


def _create_hand(canfd_device_id: int, *, recv_timeout_ms: int) -> object:
    """Construct one SDK hand handle for probing (the only SDK touch point).

    The connection mirrors the production hcan composition: ``hand_device_id=1,
    canfd_channel_id=0``.  ``init()`` is invoked for parity with the real link
    but its return value is deliberately ignored: the vendor SDK returns True
    even for indexes without a hand, so it is never an online signal.  Unit
    tests monkeypatch this function; nothing else in this module imports the
    vendor wheel.
    """

    connection = AgilinkO10Backend.connection_kwargs(
        transport="hcan",
        hand_device_id=1,
        canfd_device_id=canfd_device_id,
        canfd_channel_id=0,
    )
    try:
        from omnihand import OmniHand2025
    except ImportError as error:
        raise RuntimeError("Agilink O10 SDK wheel is not installed") from error

    factory = getattr(OmniHand2025, connection.pop("factory"))
    try:
        hand = factory(**connection)
    except Exception as error:
        raise RuntimeError("Agilink O10 SDK failed to construct the O10 hand") from error
    if hand is None:
        raise RuntimeError("Agilink O10 SDK could not create the O10 hand")
    try:
        hand.set_frame_recv_timeout(recv_timeout_ms)
        hand.init()
    except Exception as error:
        raise RuntimeError("Agilink O10 SDK initialization raised an exception") from error
    return hand


def _ensure_sdk_available() -> None:
    """Fail fast with the backend wording before any per-index probing."""

    try:
        import omnihand  # noqa: F401
    except ImportError as error:
        raise RuntimeError("Agilink O10 SDK wheel is not installed") from error


# --- scanning -----------------------------------------------------------------


def _probe_index(
    index: int,
    recv_timeout_ms: int,
    create_hand: Callable[..., object],
) -> dict[str, object]:
    """Probe one CANFD index and return the frozen scan record shape."""

    record: dict[str, object] = {
        "canfd_device_id": index,
        "hand_online": False,
        "product_seq_num": None,
        "dof": 0,
    }
    try:
        hand = create_hand(index, recv_timeout_ms=recv_timeout_ms)
        vendor = hand.get_vendor_info()
        joints = hand.get_all_joint_positions()
    except Exception as error:  # one flaky bus must not kill the whole scan
        print(f"probe: canfd_device_id={index} 探测异常: {error}", file=sys.stderr)
        return record
    serial = str(getattr(vendor, "product_seq_num", "") or "")
    try:
        dof = int(getattr(vendor, "dof", 0) or 0)
    except (TypeError, ValueError):
        dof = 0
    if serial and dof > 0 and joints:
        record.update(hand_online=True, product_seq_num=serial, dof=dof)
    return record


def scan_buses(
    max_index: int = DEFAULT_MAX_INDEX,
    recv_timeout_ms: int = DEFAULT_RECV_TIMEOUT_MS,
    create_hand: Callable[..., object] | None = None,
) -> list[dict[str, object]]:
    """Probe ``canfd_device_id`` 0..max_index and return the contract records.

    Online requires a non-empty vendor ``product_seq_num``, a positive ``dof``
    and a non-empty joint read; a successful construct/init is never
    sufficient.  All human progress goes to stderr; stdout stays reserved for
    the machine-readable JSON payload.  With the 200 ms default receive
    timeout the default four-index scan stays well inside a 5 s budget.
    """

    _ensure_sdk_available()
    create = create_hand if create_hand is not None else _create_hand
    records: list[dict[str, object]] = []
    for index in range(0, max_index + 1):
        record = _probe_index(index, recv_timeout_ms, create)
        records.append(record)
        if record["hand_online"]:
            print(
                f"probe: canfd_device_id={index} 在线 serial={record['product_seq_num']}",
                file=sys.stderr,
            )
        else:
            print(f"probe: canfd_device_id={index} 离线", file=sys.stderr)
    return records


# --- binding table ------------------------------------------------------------


def default_binding_path() -> Path:
    """Anchor the binding file at the worktree root.

    The root is the nearest ancestor (at most :data:`_MAX_ROOT_SEARCH_LEVELS`
    levels up, CWD included) that contains the launcher marker script; when no
    marker exists the CWD is used unchanged.
    """

    current = Path.cwd()
    for candidate in (current, *current.parents[:_MAX_ROOT_SEARCH_LEVELS]):
        if (candidate / _LAUNCHER_MARKER).is_file():
            return candidate / BINDING_FILE_NAME
    return current / BINDING_FILE_NAME


def load_binding_table(path: Path) -> dict[str, dict[str, object]]:
    """Load the side -> entry binding table; illegal content degrades to empty.

    A parse failure or an illegal structure (contract: JSON 解析失败或结构非法)
    yields an empty table plus one stderr warning instead of a crash.  Valid
    side entries are returned verbatim so untouched sides survive a re-save.
    """

    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(f"WARNING: binding file {path} is unreadable, treating as empty: {error}", file=sys.stderr)
        return {}
    if not isinstance(raw, dict):
        print(f"WARNING: binding file {path} has an illegal structure, treating as empty", file=sys.stderr)
        return {}
    for key, entry in raw.items():
        try:
            side = Side.from_value(key)
        except ValueError:
            print(
                f"WARNING: binding file {path} has an illegal side key {key!r}, treating as empty",
                file=sys.stderr,
            )
            return {}
        serial = entry.get("product_seq_num") if isinstance(entry, dict) else None
        if not isinstance(serial, str) or not serial:
            print(
                f"WARNING: binding file {path} has an illegal {side.value} entry, treating as empty",
                file=sys.stderr,
            )
            return {}
    return raw


def save_binding_table(path: Path, table: dict[str, dict[str, object]]) -> None:
    """Persist the binding table as pretty JSON with a trailing newline."""

    payload = json.dumps(table, ensure_ascii=False, indent=2, sort_keys=True)
    path.write_text(payload + "\n", encoding="utf-8")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- frozen resolve decision rules ---------------------------------------------


def resolve_assignments(
    sides: list[Side],
    records: list[dict[str, object]],
    table: dict[str, dict[str, object]],
) -> tuple[dict[Side, int], tuple[Side, str, int] | None]:
    """Apply the frozen decision rules 1-7 to one scan.

    Returns the resolved ``{side: canfd_device_id}`` assignments for exactly
    the requested sides plus an optional ``(side, serial, index)`` auto-bind
    the caller must persist (the table itself is not mutated here).  Raises
    :class:`ProbeFailure` for every frozen abort outcome.
    """

    online = [
        (int(record["canfd_device_id"]), str(record["product_seq_num"]))
        for record in records
        if record["hand_online"]
    ]
    if not online:
        # rule 4
        raise ProbeFailure("未发现任何在线的手：检查电源与 CAN 线")

    bound = {Side.from_value(key): str(entry["product_seq_num"]) for key, entry in table.items()}
    serial_to_side = {serial: side for side, serial in bound.items()}
    assignments: dict[Side, int] = {}

    # rules 1 and 5: bound sides follow their serial's discovered index
    for side in sides:
        if side not in bound:
            continue
        serial = bound[side]
        found = [index for index, candidate in online if candidate == serial]
        if len(found) == 1:
            assignments[side] = found[0]
        elif len(found) > 1:
            raise ProbeFailure(f"序列号 {serial} 同时出现在多个索引 {found}：请只连接该手后重试")
        else:
            raise ProbeFailure(
                f"已绑定的 {side.value} 手（product_seq_num={serial}）本次扫描未发现：该侧手掉电或拔线"
            )

    # rules 2, 3 and 6: unbound requested sides
    unbound = [side for side in sides if side not in bound]
    if not unbound:
        return assignments, None
    unknown = [(index, serial) for index, serial in online if serial not in serial_to_side]
    if not unknown:
        # rule 6
        names = "、".join(side.value for side in unbound)
        raise ProbeFailure(f"缺少 {names} 手：请求侧没有在线的手")
    if len(unbound) == 1 and len(unknown) == 1:
        # rule 2: the single unknown bus must be the single unbound slot
        side = unbound[0]
        index, serial = unknown[0]
        assignments[side] = index
        return assignments, (side, serial, index)
    # rule 3
    raise ProbeFailure("无法唯一排除未绑定的手：只保留一只手在线并运行 `omnihand_o10_probe bind --side <side>` 后重试")


# --- CLI -----------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="omnihand_o10_probe",
        description="O10 device auto-discovery and side-to-serial binding probe",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="report online hands per canfd_device_id")
    scan_parser.add_argument("--max-index", type=int, default=DEFAULT_MAX_INDEX)
    scan_parser.add_argument("--recv-timeout-ms", type=int, default=DEFAULT_RECV_TIMEOUT_MS)

    resolve_parser = subparsers.add_parser("resolve", help="map requested sides onto discovered indexes")
    resolve_parser.add_argument("--sides", choices=["left", "right", "both"], required=True)
    resolve_parser.add_argument("--file", default=None, help="explicit binding file path")
    resolve_parser.add_argument("--max-index", type=int, default=DEFAULT_MAX_INDEX)
    resolve_parser.add_argument("--recv-timeout-ms", type=int, default=DEFAULT_RECV_TIMEOUT_MS)

    bind_parser = subparsers.add_parser("bind", help="register the single online hand under a side")
    bind_parser.add_argument("--side", choices=["left", "right"], required=True)
    bind_parser.add_argument("--file", default=None, help="explicit binding file path")
    bind_parser.add_argument("--max-index", type=int, default=DEFAULT_MAX_INDEX)
    bind_parser.add_argument("--recv-timeout-ms", type=int, default=DEFAULT_RECV_TIMEOUT_MS)
    return parser


def _binding_path(file_argument: str | None) -> Path:
    return Path(file_argument) if file_argument else default_binding_path()


def _requested_sides(selection: str) -> list[Side]:
    if selection == "both":
        return [Side.LEFT, Side.RIGHT]
    return [Side.from_value(selection)]


def _run_scan(args: argparse.Namespace) -> int:
    records = scan_buses(max_index=args.max_index, recv_timeout_ms=args.recv_timeout_ms)
    print(json.dumps(records, ensure_ascii=False))
    return 0


def _run_resolve(args: argparse.Namespace) -> int:
    path = _binding_path(args.file)
    sides = _requested_sides(args.sides)
    records = scan_buses(max_index=args.max_index, recv_timeout_ms=args.recv_timeout_ms)
    table = load_binding_table(path)
    assignments, auto_bind = resolve_assignments(sides, records, table)
    if auto_bind is not None:
        side, serial, index = auto_bind
        table[side.value] = {
            "product_seq_num": serial,
            "bound_at": _utc_now_iso(),
            "bound_by": "auto",
        }
        save_binding_table(path, table)
        print(f"已自动绑定: {side.value}={serial} -> {path}", file=sys.stderr)
    for side in (Side.LEFT, Side.RIGHT):
        if side in assignments:
            print(f"解析: {side.value} -> canfd_device_id={assignments[side]}", file=sys.stderr)
            print(f"OMNIHAND_O10_{side.name}_CANFD_DEVICE_ID={assignments[side]}")
    return 0


def _run_bind(args: argparse.Namespace) -> int:
    path = _binding_path(args.file)
    records = scan_buses(max_index=args.max_index, recv_timeout_ms=args.recv_timeout_ms)
    online = [record for record in records if record["hand_online"]]
    if not online:
        raise ProbeFailure("未发现任何在线的手：检查电源与 CAN 线")
    if len(online) > 1:
        raise ProbeFailure(
            f"发现 {len(online)} 只在线的手：bind 要求恰有一只手在线，请只保留待绑定的那只手后重试"
        )
    record = online[0]
    side = Side.from_value(args.side)
    serial = str(record["product_seq_num"])
    table = load_binding_table(path)
    table[side.value] = {
        "product_seq_num": serial,
        "bound_at": _utc_now_iso(),
        "bound_by": "bind",
    }
    save_binding_table(path, table)
    print(
        f"已绑定: {side.value}={serial} (bound_by=bind, canfd_device_id={record['canfd_device_id']}) -> {path}",
        file=sys.stderr,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    """Console-script entry point; returns the process exit code."""

    args = _build_parser().parse_args(argv)
    if not os.environ.get(_ENV_PREFIX):
        print(
            "BLOCKED_ENV: set DEXHIT_COLLECTION_PREFIX to the collection runtime "
            "prefix before probing hardware",
            file=sys.stderr,
        )
        return 2
    try:
        if args.command == "scan":
            return _run_scan(args)
        if args.command == "resolve":
            return _run_resolve(args)
        return _run_bind(args)
    except (ProbeFailure, RuntimeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
