"""Behavior tests for the O10 probe CLI (DOCS/03_工程/10 frozen contract).

All SDK interaction goes through the single ``probe._create_hand`` seam, which
these tests monkeypatch with duck-typed fake hands; the fake ``omnihand``
module injection follows the ``test_agilink_backend.py`` pattern.
"""

from __future__ import annotations

import ast
import json
import sys
from datetime import datetime
from importlib import reload
from pathlib import Path
from types import SimpleNamespace

import pytest

from omnihand_o10_contracts import Side

from omnihand_o10_hardware_adapter import probe

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[4]
LAUNCHER_MARKER = "start_omnihand_control.sh"


class FakeVendorInfo:
    def __init__(self, product_seq_num: str, dof: int) -> None:
        self.product_seq_num = product_seq_num
        self.dof = dof


class FakeProbeHand:
    """Duck-typed SDK hand exposing exactly the probe read surface."""

    def __init__(self, product_seq_num: str = "", dof: int = 0, joints: list[float] | None = None) -> None:
        self.vendor = FakeVendorInfo(product_seq_num, dof)
        self.joints = list(joints or [])
        self.recv_timeouts: list[int] = []
        self.init_calls = 0

    def set_frame_recv_timeout(self, milliseconds: int) -> None:
        self.recv_timeouts.append(milliseconds)

    def init(self) -> bool:
        self.init_calls += 1
        return True

    def get_vendor_info(self) -> FakeVendorInfo:
        return self.vendor

    def get_all_joint_positions(self) -> list[float]:
        return list(self.joints)


def install_fake_hands(
    monkeypatch: pytest.MonkeyPatch,
    hands: dict[int, FakeProbeHand] | None = None,
) -> list[tuple[int, int]]:
    """Replace the single SDK seam; returns the captured (index, timeout) calls."""

    monkeypatch.setitem(sys.modules, "omnihand", SimpleNamespace())
    calls: list[tuple[int, int]] = []

    def fake_create(canfd_device_id: int, *, recv_timeout_ms: int) -> FakeProbeHand:
        calls.append((canfd_device_id, recv_timeout_ms))
        hand = (hands or {}).get(canfd_device_id)
        return hand if hand is not None else FakeProbeHand()

    monkeypatch.setattr(probe, "_create_hand", fake_create)
    return calls


def online_hand(serial: str) -> FakeProbeHand:
    return FakeProbeHand(serial, 10, [0.0] * 10)


def rec(index: int, *, online: bool = False, serial: str | None = None, dof: int = 0) -> dict[str, object]:
    return {"canfd_device_id": index, "hand_online": online, "product_seq_num": serial, "dof": dof}


def bound_entry(serial: str) -> dict[str, str]:
    return {"product_seq_num": serial, "bound_at": "2026-08-29T00:00:00+00:00", "bound_by": "bind"}


def run_cli(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], argv: list[str]) -> tuple[int, str, str]:
    monkeypatch.setenv("DEXHIT_COLLECTION_PREFIX", "/fake-prefix")
    exit_code = probe.main(argv)
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


# --- scan -------------------------------------------------------------------


def test_scan_prints_contract_json_and_builds_sequential_hcan_hands(monkeypatch, capsys):
    hands = {1: online_hand("SN-RIGHT")}
    calls = install_fake_hands(monkeypatch, hands)

    exit_code, out, err = run_cli(monkeypatch, capsys, ["scan", "--max-index", "2"])

    assert exit_code == 0
    assert json.loads(out) == [
        {"canfd_device_id": 0, "hand_online": False, "product_seq_num": None, "dof": 0},
        {"canfd_device_id": 1, "hand_online": True, "product_seq_num": "SN-RIGHT", "dof": 10},
        {"canfd_device_id": 2, "hand_online": False, "product_seq_num": None, "dof": 0},
    ]
    assert calls == [(0, 200), (1, 200), (2, 200)]
    assert "canfd_device_id=1" in err  # human progress on stderr only


def test_scan_forwards_custom_recv_timeout(monkeypatch, capsys):
    calls = install_fake_hands(monkeypatch, {})

    exit_code, out, _ = run_cli(
        monkeypatch, capsys, ["scan", "--max-index", "1", "--recv-timeout-ms", "123"]
    )

    assert exit_code == 0
    assert calls == [(0, 123), (1, 123)]


@pytest.mark.parametrize(
    ("serial", "dof", "joints"),
    [
        ("", 0, []),  # vendor seq and dof empty even though init() returned True
        ("SN", 0, [0.0] * 10),  # dof must be positive
        ("SN", 10, []),  # joint read must be non-empty
    ],
)
def test_scan_init_success_alone_is_never_online(monkeypatch, capsys, serial, dof, joints):
    install_fake_hands(monkeypatch, {0: FakeProbeHand(serial, dof, joints)})

    _, out, _ = run_cli(monkeypatch, capsys, ["scan", "--max-index", "0"])

    assert json.loads(out) == [
        {"canfd_device_id": 0, "hand_online": False, "product_seq_num": None, "dof": 0}
    ]


def test_scan_fails_with_backend_wording_when_sdk_is_missing(monkeypatch, capsys):
    monkeypatch.setenv("DEXHIT_COLLECTION_PREFIX", "/fake-prefix")
    monkeypatch.setitem(sys.modules, "omnihand", None)

    assert probe.main(["scan"]) == 1
    assert "Agilink O10 SDK wheel is not installed" in capsys.readouterr().err


def test_create_hand_uses_documented_hcan_connection_kwargs(monkeypatch):
    created_kwargs: dict[str, object] = {}

    def create(**kwargs):
        created_kwargs.update(kwargs)
        return FakeProbeHand()

    sdk_class = type("OmniHand2025", (), {"create_hand_by_hcan": staticmethod(create)})
    monkeypatch.setitem(
        sys.modules,
        "omnihand",
        SimpleNamespace(HandType=SimpleNamespace(LEFT="LEFT", RIGHT="RIGHT"), OmniHand2025=sdk_class),
    )

    hand = probe._create_hand(2, recv_timeout_ms=250)

    assert created_kwargs == {"hand_device_id": 1, "canfd_device_id": 2, "canfd_channel_id": 0}
    assert hand.recv_timeouts == [250]
    assert hand.init_calls == 1


def test_create_hand_requires_installed_sdk(monkeypatch):
    monkeypatch.setitem(sys.modules, "omnihand", None)

    with pytest.raises(RuntimeError, match="SDK wheel is not installed"):
        probe._create_hand(0, recv_timeout_ms=200)


# --- binding table file ------------------------------------------------------


def test_binding_table_roundtrip(tmp_path):
    path = tmp_path / "o10_hand_binding.json"
    table = {"left": bound_entry("SN-L")}

    probe.save_binding_table(path, table)

    assert probe.load_binding_table(path) == table


def test_missing_binding_file_loads_as_empty(tmp_path):
    assert probe.load_binding_table(tmp_path / "absent.json") == {}


@pytest.mark.parametrize(
    "content",
    [
        "{not json",  # JSON parse failure
        "[]",  # top level must be an object
        '{"middle": {"product_seq_num": "SN"}}',  # unknown side key
        '{"left": "SN-L"}',  # entry must be an object
        '{"left": {}}',  # entry must carry a serial
        '{"left": {"product_seq_num": ""}}',  # serial must be non-empty
    ],
)
def test_illegal_binding_file_is_treated_as_empty_with_warning(tmp_path, capsys, content):
    path = tmp_path / "o10_hand_binding.json"
    path.write_text(content, encoding="utf-8")

    assert probe.load_binding_table(path) == {}
    assert "WARNING" in capsys.readouterr().err


def test_default_binding_path_anchors_at_launcher_marker(tmp_path, monkeypatch):
    (tmp_path / LAUNCHER_MARKER).write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)

    assert probe.default_binding_path() == tmp_path / "o10_hand_binding.json"


def test_default_binding_path_falls_back_to_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    assert probe.default_binding_path() == tmp_path / "o10_hand_binding.json"


# --- resolve decision rules (frozen rules 1-7) --------------------------------


def test_rule1_bound_side_uses_index_where_serial_is_found():
    records = [rec(1, online=True, serial="SN-L"), rec(3, online=True, serial="SN-OTHER")]

    assignments, auto = probe.resolve_assignments([Side.LEFT], records, {"left": bound_entry("SN-L")})

    assert assignments == {Side.LEFT: 1}
    assert auto is None


def test_rule5_bound_side_missing_from_scan_aborts():
    records = [rec(0, online=True, serial="SN-OTHER")]

    with pytest.raises(probe.ProbeFailure, match="掉电或拔线"):
        probe.resolve_assignments([Side.LEFT], records, {"left": bound_entry("SN-L")})


def test_rule4_zero_online_hands_aborts():
    with pytest.raises(probe.ProbeFailure, match="未发现任何在线的手"):
        probe.resolve_assignments([Side.RIGHT], [rec(0), rec(1)], {})


def test_rule2_single_unknown_online_hand_auto_binds_requested_side():
    records = [rec(0, online=True, serial="SN-U")]

    assignments, auto = probe.resolve_assignments([Side.RIGHT], records, {})

    assert assignments == {Side.RIGHT: 0}
    assert auto == (Side.RIGHT, "SN-U", 0)


def test_rule2_exclusion_via_bound_side_serial():
    table = {"left": bound_entry("SN-L")}
    records = [rec(0, online=True, serial="SN-L"), rec(2, online=True, serial="SN-R")]

    assignments, auto = probe.resolve_assignments([Side.RIGHT], records, table)

    assert assignments == {Side.RIGHT: 2}
    assert auto == (Side.RIGHT, "SN-R", 2)


@pytest.mark.parametrize(
    ("sides", "records"),
    [
        # two online buses with unknown serials cannot be excluded
        ([Side.RIGHT], [rec(0, online=True, serial="SN-A"), rec(1, online=True, serial="SN-B")]),
        # both sides unbound while both hands are online
        (
            [Side.LEFT, Side.RIGHT],
            [rec(0, online=True, serial="SN-A"), rec(1, online=True, serial="SN-B")],
        ),
        # one unknown hand online but two empty slots
        ([Side.LEFT, Side.RIGHT], [rec(0, online=True, serial="SN-A")]),
    ],
)
def test_rule3_ambiguous_unbound_sides_abort_with_bind_guidance(sides, records):
    with pytest.raises(probe.ProbeFailure, match="只保留一只手在线"):
        probe.resolve_assignments(sides, records, {})


def test_rule6_requested_side_has_no_online_hand_reports_missing_side():
    records = [rec(0, online=True, serial="SN-L")]

    with pytest.raises(probe.ProbeFailure, match="right"):
        probe.resolve_assignments(
            [Side.LEFT, Side.RIGHT], records, {"left": bound_entry("SN-L")}
        )


def test_rule7_unrequested_bus_is_never_resolved_or_bound():
    records = [rec(0, online=True, serial="SN-L"), rec(2, online=True, serial="SN-UNKNOWN")]

    assignments, auto = probe.resolve_assignments([Side.LEFT], records, {"left": bound_entry("SN-L")})

    assert assignments == {Side.LEFT: 0}
    assert auto is None


# --- resolve CLI --------------------------------------------------------------


def test_resolve_auto_bind_persists_file_and_traces_stderr(monkeypatch, capsys, tmp_path):
    path = tmp_path / "binding.json"
    install_fake_hands(monkeypatch, {0: online_hand("SN-R")})

    exit_code, out, err = run_cli(
        monkeypatch, capsys, ["resolve", "--sides", "right", "--file", str(path)]
    )

    assert exit_code == 0
    assert out == "OMNIHAND_O10_RIGHT_CANFD_DEVICE_ID=0\n"
    table = json.loads(path.read_text(encoding="utf-8"))
    assert table["right"]["product_seq_num"] == "SN-R"
    assert table["right"]["bound_by"] == "auto"
    datetime.fromisoformat(table["right"]["bound_at"])
    assert "已自动绑定: right=SN-R" in err


def test_resolve_auto_bind_preserves_existing_side_and_prints_both_lines(monkeypatch, capsys, tmp_path):
    path = tmp_path / "binding.json"
    existing = {"left": bound_entry("SN-L")}
    path.write_text(json.dumps(existing), encoding="utf-8")
    install_fake_hands(monkeypatch, {0: online_hand("SN-L"), 1: online_hand("SN-R")})

    exit_code, out, err = run_cli(
        monkeypatch, capsys, ["resolve", "--sides", "both", "--file", str(path)]
    )

    assert exit_code == 0
    assert out == "OMNIHAND_O10_LEFT_CANFD_DEVICE_ID=0\nOMNIHAND_O10_RIGHT_CANFD_DEVICE_ID=1\n"
    table = json.loads(path.read_text(encoding="utf-8"))
    assert table["left"] == existing["left"]  # untouched side preserved verbatim
    assert table["right"]["product_seq_num"] == "SN-R"
    assert table["right"]["bound_by"] == "auto"


def test_resolve_bound_serial_follows_new_index_without_rewriting_file(monkeypatch, capsys, tmp_path):
    path = tmp_path / "binding.json"
    existing = {"right": bound_entry("SN-R")}
    path.write_text(json.dumps(existing), encoding="utf-8")
    install_fake_hands(monkeypatch, {3: online_hand("SN-R")})

    exit_code, out, err = run_cli(
        monkeypatch, capsys, ["resolve", "--sides", "right", "--file", str(path)]
    )

    assert exit_code == 0
    assert out == "OMNIHAND_O10_RIGHT_CANFD_DEVICE_ID=3\n"
    assert path.read_text(encoding="utf-8") == json.dumps(existing)
    assert "已自动绑定" not in err


def test_resolve_failure_exits_1_without_stdout_or_file_write(monkeypatch, capsys, tmp_path):
    path = tmp_path / "binding.json"
    install_fake_hands(
        monkeypatch, {0: online_hand("SN-A"), 1: online_hand("SN-B")}
    )

    exit_code, out, err = run_cli(
        monkeypatch, capsys, ["resolve", "--sides", "right", "--file", str(path)]
    )

    assert exit_code == 1
    assert out == ""
    assert not path.exists()
    assert "只保留一只手在线" in err


def test_resolve_reports_power_lost_side_and_keeps_file(monkeypatch, capsys, tmp_path):
    path = tmp_path / "binding.json"
    existing = {"left": bound_entry("SN-L")}
    path.write_text(json.dumps(existing), encoding="utf-8")
    install_fake_hands(monkeypatch, {0: online_hand("SN-L")})

    exit_code, out, err = run_cli(
        monkeypatch, capsys, ["resolve", "--sides", "both", "--file", str(path)]
    )

    assert exit_code == 1
    assert out == ""
    assert path.read_text(encoding="utf-8") == json.dumps(existing)
    assert "right" in err


# --- bind CLI -----------------------------------------------------------------


def test_bind_registers_single_online_hand_as_requested_side(monkeypatch, capsys, tmp_path):
    path = tmp_path / "binding.json"
    install_fake_hands(monkeypatch, {2: online_hand("SN-ONLY")})

    exit_code, out, err = run_cli(
        monkeypatch, capsys, ["bind", "--side", "left", "--file", str(path)]
    )

    assert exit_code == 0
    assert out == ""
    table = json.loads(path.read_text(encoding="utf-8"))
    assert table["left"]["product_seq_num"] == "SN-ONLY"
    assert table["left"]["bound_by"] == "bind"
    datetime.fromisoformat(table["left"]["bound_at"])
    assert "SN-ONLY" in err


def test_bind_with_zero_online_hands_fails_without_writing(monkeypatch, capsys, tmp_path):
    path = tmp_path / "binding.json"
    install_fake_hands(monkeypatch, {})

    exit_code, out, err = run_cli(
        monkeypatch, capsys, ["bind", "--side", "right", "--file", str(path)]
    )

    assert exit_code == 1
    assert out == ""
    assert not path.exists()
    assert "未发现任何在线的手" in err


def test_bind_with_two_online_hands_fails_with_guidance(monkeypatch, capsys, tmp_path):
    path = tmp_path / "binding.json"
    install_fake_hands(monkeypatch, {0: online_hand("SN-A"), 1: online_hand("SN-B")})

    exit_code, out, err = run_cli(
        monkeypatch, capsys, ["bind", "--side", "right", "--file", str(path)]
    )

    assert exit_code == 1
    assert out == ""
    assert not path.exists()
    assert "恰有一只" in err


# --- main: environment isolation and exit codes --------------------------------


def test_main_blocked_without_environment_prefix(monkeypatch, capsys):
    monkeypatch.delenv("DEXHIT_COLLECTION_PREFIX", raising=False)

    assert probe.main(["scan"]) == 2
    assert "BLOCKED_ENV" in capsys.readouterr().err


def test_main_returns_zero_for_successful_scan(monkeypatch, capsys):
    install_fake_hands(monkeypatch, {})
    exit_code, _, _ = run_cli(monkeypatch, capsys, ["scan", "--max-index", "0"])

    assert exit_code == 0


# --- source-structure guarantees ------------------------------------------------


def test_probe_module_import_never_touches_sdk(monkeypatch):
    monkeypatch.setitem(sys.modules, "omnihand", None)

    reload(probe)  # must not raise: the SDK wheel is imported lazily at call time


def test_probe_source_has_no_module_level_sdk_import():
    tree = ast.parse((PACKAGE_ROOT / "omnihand_o10_hardware_adapter" / "probe.py").read_text(encoding="utf-8"))

    for node in tree.body:
        if isinstance(node, ast.Import):
            assert all(alias.name != "omnihand" for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert module != "omnihand" and not module.startswith("omnihand.")


def test_probe_source_has_no_hardcoded_vendor_paths():
    text = (PACKAGE_ROOT / "omnihand_o10_hardware_adapter" / "probe.py").read_text(encoding="utf-8")

    # Markers are assembled at runtime so this file itself stays clean for the A19 scan.
    for marker in (
        "src/collection/omni_hand/" "jazzy",
        "third_party/agillink_omnihand_" "sdk",
        "/jazzy/" "lib/",
        "miniforge",
        "/home/",
    ):
        assert marker not in text


def test_setup_py_keeps_provider_entry_and_appends_probe_entry():
    setup_py = (PACKAGE_ROOT / "setup.py").read_text(encoding="utf-8")

    assert "omnihand_o10_hardware_provider = omnihand_o10_hardware_adapter.node:main" in setup_py
    assert "omnihand_o10_probe = omnihand_o10_hardware_adapter.probe:main" in setup_py


def test_root_gitignore_ignores_binding_file():
    gitignore = REPO_ROOT / ".gitignore"
    if not gitignore.is_file():
        pytest.skip("root .gitignore is not colocated with this test run")
    assert "o10_hand_binding.json" in gitignore.read_text(encoding="utf-8")
