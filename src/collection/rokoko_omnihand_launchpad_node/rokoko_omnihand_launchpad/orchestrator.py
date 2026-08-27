"""Process orchestration model for the Launchpad control plane.

This module deliberately knows only process names and configuration.  It does
not import ROS or copy business-node state; real adapters can replace the
stand-in command without changing the HTTP contract.
"""

from __future__ import annotations

import ctypes
import os
import signal
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from .recording import Recorder, RecorderUnavailable
from .latency_events import read_events
from .process_lifecycle import TeardownResult, spawn_managed_process, stop_process_group
from .run_session import RunSession
from .sim_provider import SimProviderUnavailable, command as sim_provider_command
from .sysmon import SystemMonitor

try:
    import yaml
except ImportError:  # pragma: no cover - production dependency, env probe covers it
    yaml = None


BLOCKS = (
    "rokoko_receiver",
    "hand_retargeting",
    "omnihand_o10_control",
    "hcan_provider",
    "sim_provider",
    "synthetic_input",
    "recorder",
)
SIDES = ("both", "left", "right")
ROKOKO_UDP_PORT = 14043
START_ORDER = (
    "rokoko_receiver",
    "synthetic_input",
    "hcan_provider",
    "sim_provider",
    "hand_retargeting",
    "omnihand_o10_control",
    "recorder",
)
DEPENDENTS = {
    "rokoko_receiver": ("hand_retargeting", "omnihand_o10_control", "recorder"),
    "hand_retargeting": ("omnihand_o10_control", "recorder"),
    "hcan_provider": ("omnihand_o10_control",),
    "sim_provider": ("omnihand_o10_control",),
    "synthetic_input": ("rokoko_receiver", "hand_retargeting"),
    "omnihand_o10_control": ("recorder",),
}


def _profile_dirs() -> tuple["Path", ...]:
    from pathlib import Path

    source_root = Path(__file__).resolve().parents[2]
    return (
        Path(os.environ["DEXHIT_LAUNCHPAD_PROFILES"])
        if os.environ.get("DEXHIT_LAUNCHPAD_PROFILES")
        else source_root / "teleoperation_support" / "production_bringup" / "launchpad",
        Path(__file__).resolve().parents[4]
        / "share" / "rokoko_omnihand_bringup" / "launchpad",
    )


def available_profiles() -> dict[str, str]:
    """Return profile IDs visible to the control-plane UI."""
    profiles: dict[str, str] = {}
    for directory in _profile_dirs():
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.yaml")):
            profiles.setdefault(path.stem, str(path))
    return profiles


def _load_profile(profile: str) -> tuple[dict[str, Any] | None, str | None]:
    path = available_profiles().get(profile)
    if not path:
        return None, f"parameter profile does not exist: {profile}"
    if yaml is None:
        return None, "PyYAML is not importable"
    try:
        with open(path, encoding="utf-8") as stream:
            value = yaml.safe_load(stream) or {}
    except (OSError, yaml.YAMLError) as exc:
        return None, f"cannot read parameter profile {profile}: {exc}"
    if not isinstance(value, dict):
        return None, f"parameter profile is not a mapping: {profile}"
    return value, None


def _contains_system_test(value: Any) -> bool:
    """Return whether a composition profile names the mock-only package."""

    if isinstance(value, str):
        marker = "_".join(("rokoko", "omnihand", "system", "test"))
        return marker in value
    if isinstance(value, dict):
        return any(_contains_system_test(key) or _contains_system_test(item)
                   for key, item in value.items())
    if isinstance(value, (list, tuple, set)):
        return any(_contains_system_test(item) for item in value)
    return False


def _side_values(side: str) -> tuple[str, ...]:
    return ("left", "right") if side == "both" else (side,)


def _resolve_profile_path(raw: Any) -> str:
    """Expand a profile path entry, including bash-style ``${VAR:-default}``.

    ``os.path.expandvars`` does not understand ``${VAR:-default}`` and leaves
    the literal string in place, which previously reached ``--params-file``
    verbatim and crashed the retargeting node at rcl init.
    """
    text = str(raw).strip()
    if text.startswith("${") and text.endswith("}"):
        inner = text[2:-1]
        name, sep, default = inner.partition(":-")
        if sep:
            text = os.environ.get(name.strip()) or default.strip()
        else:
            text = os.environ.get(inner.strip(), "")
    return os.path.expandvars(text)


def _set_pdeathsig() -> None:
    """Make a child die when its orchestrator parent dies (Linux only)."""
    if sys.platform != "linux":
        return
    parent_pid = os.getppid()
    libc = ctypes.CDLL(None, use_errno=True)
    pr_set_pdeathsig = 1
    if libc.prctl(pr_set_pdeathsig, signal.SIGKILL, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "prctl(PR_SET_PDEATHSIG) failed")
    # Close the small fork/prctl race: if the parent died before prctl ran,
    # the kernel cannot deliver the requested signal retroactively.
    if os.getppid() != parent_pid:
        os.kill(os.getpid(), signal.SIGKILL)


def validate_blocks(blocks: Iterable[str], *, confirmation: bool = False) -> dict[str, Any]:
    selected = set(blocks)
    errors: list[str] = []
    warnings: list[str] = []
    confirmations: list[str] = []
    unknown = sorted(selected - set(BLOCKS))
    if unknown:
        errors.append(f"unknown blocks: {', '.join(unknown)}")
    if {"hcan_provider", "sim_provider"} <= selected:
        errors.append("hcan_provider and sim_provider are mutually exclusive")
    if {"synthetic_input", "hcan_provider"} <= selected:
        confirmations.append("synthetic_input+hcan_provider can drive real hardware")
        if not confirmation:
            errors.append("confirmation required for synthetic_input+hcan_provider")
    if "synthetic_input" in selected:
        warnings.append("synthetic input may mix with live Rokoko UDP traffic")
    if "omnihand_o10_control" in selected and not ({"hcan_provider", "sim_provider"} & selected):
        warnings.append("orphan combination: control has no provider")
    if "hand_retargeting" in selected and "rokoko_receiver" not in selected and "synthetic_input" not in selected:
        warnings.append("orphan combination: retargeting has no receiver")
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "confirmations": confirmations,
    }


def _real_check(name: str, *, selected: set[str], profile: str) -> bool:
    if name == "ros2_available":
        return shutil.which("ros2") is not None
    if name == "numeric_import":
        try:
            __import__("pinocchio")
            __import__("nlopt")
        except ImportError:
            return False
        return True
    if name == "parameter_profile":
        return _load_profile(profile)[0] is not None
    if name == "duplicate_nodes":
        if shutil.which("ros2") is None:
            return True
        try:
            output = subprocess.run(
                ["ros2", "node", "list"], capture_output=True, text=True, timeout=3, check=False
            ).stdout.splitlines()
        except (OSError, subprocess.TimeoutExpired):
            return False
        names = set(output)
        return not names.intersection({
            "/rokoko_hand_receiver", "/hand_retargeting",
            "/omnihand_o10_hardware_provider", "/o10_control_node",
        })
    if name == "usb_canfd":
        if shutil.which("lsusb") is None:
            return False
        return subprocess.run(
            ["lsusb", "-d", "a8fa:8598"], capture_output=True, check=False
        ).returncode == 0
    if name == "sim_provider_available":
        return shutil.which("ros2") is not None
    if name == "synthetic_generator_available":
        try:
            from .synthetic_input import payloads
            next(payloads(side="left", count=1))
        except (ImportError, ModuleNotFoundError, OSError, ValueError):
            return False
        return True
    return False


def preflight(
    blocks: Iterable[str], *, side: str, profile: str = "default",
    checks: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """Run only checks relevant to the selected blocks.

    ``checks`` is an injectable observation seam for black-box tests and real
    adapters.  A missing check is reported as pending rather than fabricated.
    """
    selected = set(blocks)
    checks = checks or {}
    required: list[str] = []
    if selected:
        required += ["ros2_available", "numeric_import", "parameter_profile", "duplicate_nodes"]
    if "hcan_provider" in selected:
        required.append("usb_canfd")
    if "sim_provider" in selected:
        required.append("sim_provider_available")
    if "synthetic_input" in selected:
        required.append("synthetic_generator_available")
    results = {
        name: (checks[name] if checks is not None and name in checks
               else _real_check(name, selected=selected, profile=profile))
        for name in required
    }
    reasons = {
        name: "ok" if passed else {
            "ros2_available": "ROS 2 command ros2 is not available",
            "numeric_import": "numeric runtime cannot import pinocchio and nlopt",
            "parameter_profile": f"parameter profile does not exist or cannot be read: {profile}",
            "duplicate_nodes": ("one or more real graph nodes are already running; "
                                "if nodes were just stopped, wait a few seconds for "
                                "discovery to settle and retry"),
            "usb_canfd": "HCAN selected but USB-CANFD a8fa:8598 was not detected",
        }.get(name, f"preflight check failed: {name}")
        for name, passed in results.items()
    }
    return {
        "side": side, "profile": profile, "required": required,
        "results": results, "reasons": reasons, "passed": all(results.values()),
    }


@dataclass
class NodeRuntime:
    expected: bool = False
    actual: str = "stopped"
    pid: int | None = None
    pgid: int | None = None
    process: subprocess.Popen[bytes] | None = field(default=None, repr=False)
    exit_code: int | None = None
    started_at: float | None = None
    alert: str | None = None

    def public(self) -> dict[str, Any]:
        return {"expected": self.expected, "actual": self.actual, "pid": self.pid,
                "pgid": self.pgid, "exit_code": self.exit_code, "alert": self.alert}


class CleanupFailedError(ValueError):
    """A managed process group remained after bounded cleanup attempts."""


class Orchestrator:
    def __init__(self, *, command_factory: Callable[[str, dict[str, Any]], list[str]] | None = None,
                 run_root: str | os.PathLike[str] | None = None,
                 recorder_command_factory: Callable[[Any, Iterable[str]], list[str]] | None = None,
                 term_timeout: float = 5.0, kill_timeout: float = 3.0,
                 ready_grace: float = 2.0,
                 duplicate_settle_timeout: float = 8.0) -> None:
        self._lock = threading.RLock()
        self._ready_grace = ready_grace
        self._duplicate_settle_timeout = duplicate_settle_timeout
        self._nodes = {name: NodeRuntime() for name in BLOCKS}
        self._config: dict[str, Any] = {
            "blocks": [], "side": "both", "profile": "default", "label": "",
            "execution_mode": "real",
        }
        self._standins: dict[str, dict[str, Any]] = {}
        self._command_factory = command_factory or self._default_command
        self._events: list[dict[str, Any]] = []
        self._run_root = run_root
        self._recorder_command_factory = recorder_command_factory
        self._session: RunSession | None = None
        self._sysmon: SystemMonitor | None = None
        self._recorder: Recorder | None = None
        self._term_timeout = term_timeout
        self._kill_timeout = kill_timeout
        self._stop_epoch = {name: 0 for name in BLOCKS}
        self._generation = {name: 0 for name in BLOCKS}

    @staticmethod
    def _default_command(name: str, options: dict[str, Any]) -> list[str]:
        if name in {"sim_provider", "recorder"} or options.get("execution_mode", "real") == "stub":
            return [sys.executable, "-m", "rokoko_omnihand_launchpad.stub_process", name,
                    "--delay", str(float(options.get("delay", 0))),
                    "--crash-after", str(float(options.get("crash_after", 0)))]
        if name == "synthetic_input":
            return [sys.executable, "-m", "rokoko_omnihand_launchpad.synthetic_input",
                    "--host", "127.0.0.1", "--port", str(int(options.get("udp_port", 14043))),
                    "--side", str(options.get("side", "both")), "--fps", "30",
                    "--initial-delay", "0.05"]
        profile = options.get("profile_data") or {}
        command = list(profile.get("commands", {}).get(name, []))
        if not command:
            raise ValueError(f"profile has no real command for {name}")
        side = str(options.get("side", "both"))
        if name == "hand_retargeting":
            from pathlib import Path
            wrapper = (
                Path(__file__).resolve().parents[2]
                / "hand_retargeting_node"
                / "scripts"
                / "hand_retargeting_node"
            )
            params = _resolve_profile_path(profile.get("retargeting_params", ""))
            if params and not os.path.isabs(params):
                params = str(Path(__file__).resolve().parents[4] / params)
            command = ["bash", str(wrapper), "--ros-args"]
            if params:
                command += ["--params-file", str(params)]
        else:
            # ros2 run 命令本身不含 --ros-args；在其后追加 -p 参数必须先进入
            # ROS 参数作用域，否则 rcl 会把 key:=value 解析成 remap，业务
            # 必填参数全部丢失（provider/control 启动即退出的根因）。
            command += ["--ros-args"]
        command += ["-p", f"side:={side}"]
        if name == "rokoko_receiver":
            command += ["-p", f"udp_port:={ROKOKO_UDP_PORT}",
                        "-p", f"actor_index:={int(options.get('actor', 0))}"]
        for key, value in (profile.get("parameters", {}).get(name, {}) or {}).items():
            rendered = "[" + ",".join(str(item) for item in value) + "]" if isinstance(value, list) else str(value)
            command += ["-p", f"{key}:={rendered}"]
        return command

    def configure(self, payload: dict[str, Any]) -> dict[str, Any]:
        blocks = payload.get("blocks", [])
        side = payload.get("side", "both")
        if side not in SIDES:
            raise ValueError(f"side must be one of {SIDES}")
        result = validate_blocks(blocks, confirmation=bool(payload.get("confirmation")))
        if not result["valid"]:
            raise ValueError("; ".join(result["errors"]))
        if "rokoko_receiver" in blocks and payload.get("udp_port", ROKOKO_UDP_PORT) != ROKOKO_UDP_PORT:
            raise ValueError(f"rokoko_receiver udp_port must be {ROKOKO_UDP_PORT}")
        profile = str(payload.get("profile", "default"))
        profile_data, profile_error = _load_profile(profile)
        requested_mode = payload.get("execution_mode")
        template = payload.get("template", "custom")
        execution_mode = requested_mode or ("sim" if template == "sim" else
                                            ("stub" if payload.get("standins") else "real"))
        if profile_error and execution_mode != "stub":
            raise ValueError(profile_error)
        if execution_mode == "real" and profile_data and _contains_system_test(profile_data):
            raise ValueError(
                "real composition profile must not reference the system-test package"
            )
        with self._lock:
            if self._sysmon:
                self._sysmon.stop()
            if self._session:
                self._session.close()
            self._config = {"blocks": list(dict.fromkeys(blocks)), "side": side,
                            "profile": profile, "label": payload.get("label", ""),
                            "template": template,
                            "mode": payload.get("mode", execution_mode),
                            "udp_port": ROKOKO_UDP_PORT, "actor": payload.get("actor", 0),
                            "can_channel": payload.get("can_channel", "can0"),
                            "execution_mode": execution_mode,
                            "confirmed": bool(payload.get("confirmation"))}
            self._standins = dict(payload.get("standins", {}))
            root = self._run_root or os.environ.get("DEXHIT_LAUNCHPAD_RUN_ROOT", "runs/launchpad")
            self._session = RunSession(root, config=self._config)
            # Snapshot events are an in-memory mirror of the active run.  A
            # new RunSession starts a new event scope; historical events stay
            # available only through the closed run's append-only file.
            self._events.clear()
            self._sysmon = SystemMonitor(self._session.path / "sysmon.jsonl")
            self._sysmon.start()
            self._recorder = Recorder(self._session.path,
                                      command_factory=self._recorder_command_factory,
                                      pdeathsig=_set_pdeathsig)
            self._record_event("configured", blocks=self._config["blocks"],
                               side=side, profile=profile)
            for name in BLOCKS:
                self._nodes[name].expected = name in self._config["blocks"]
        return self.snapshot()

    def _watch(self, name: str, process: subprocess.Popen[bytes], generation: int) -> None:
        code = process.wait()
        with self._lock:
            node = self._nodes[name]
            if node.process is not process or self._generation[name] != generation:
                return
            node.exit_code = code
            if node.expected and code != 0:
                node.actual = "crashed"
                node.alert = f"{name} exited with code {code}; not restarted"
                if self._session:
                    self._record_event("process_crashed", node=name, exit_code=code)

    def start_node(self, name: str) -> dict[str, Any]:
        if name not in BLOCKS:
            raise ValueError(f"unknown block: {name}")
        with self._lock:
            node = self._nodes[name]
            if node.process and node.process.poll() is None and node.actual not in {"stopping", "cleanup_failed"}:
                return node.public()
            residual_pgid, residual_process = node.pgid, node.process
            if residual_pgid is not None:
                node.expected = False
                node.actual = "stopping"
        if residual_pgid is not None:
            result = stop_process_group(residual_pgid, residual_process,
                                        self._term_timeout, self._kill_timeout)
            with self._lock:
                node = self._nodes[name]
                if result.outcome != "stopped":
                    node.actual = "cleanup_failed"
                    node.alert = f"{name} cleanup failed; residual pids: {list(result.remaining_pids)}"
                    raise CleanupFailedError(node.alert)
                node.process = node.pid = node.pgid = None
                node.actual = "stopped"
        with self._lock:
            node = self._nodes[name]
            node.expected = True
            options = dict(self._standins.get(name, {}))
            options.update({"profile_data": _load_profile(self._config["profile"])[0],
                            "side": self._config["side"], "udp_port": self._config["udp_port"],
                            "actor": self._config["actor"], "can_channel": self._config["can_channel"],
                            "execution_mode": self._config["execution_mode"]})
            if self._session is None:
                raise ValueError("run session has not been configured")
            if name == "recorder":
                if self._recorder is None:
                    raise ValueError("recorder is not initialized")
                try:
                    process = self._recorder.start()
                except RecorderUnavailable as exc:
                    raise ValueError(str(exc)) from exc
            else:
                try:
                    command = self._command_factory(name, options)
                    if name == "sim_provider" and self._config.get("execution_mode") == "sim":
                        command = sim_provider_command(side=self._config["side"])
                    spawn_kwargs: dict[str, Any] = {}
                    if name not in {"sim_provider", "synthetic_input"} and options.get("execution_mode") != "stub":
                        # 真节点经 ros2 run/wrapper 派生孙进程；直接子进程挂
                        # PDEATHSIG 只能杀到 ros2 run 一层，真节点会孤儿化并残
                        # 留在 ROS 图里阻塞后续启动。改由 guard 作为直接子进程
                        # 接管父死亡时的整组清理。
                        command = [sys.executable, "-m", "rokoko_omnihand_launchpad.pdeath_guard",
                                   "--", *command]
                        spawn_kwargs["pdeathsig"] = lambda: None
                    if name not in {"sim_provider", "synthetic_input", "recorder"}:
                        # 真节点子进程继承编排器环境，并叠加档案声明的环境变量；
                        # retargeting wrapper 的环境守卫要求这两个变量必须存在。
                        profile_env = dict((options.get("profile_data") or {}).get("env") or {})
                        if name == "hand_retargeting":
                            profile_env.setdefault("DEXHIT_COLLECTION_PREFIX", sys.prefix)
                        if profile_env:
                            spawn_kwargs["env"] = {**os.environ, **profile_env}
                    spawn_options: dict[str, Any] = {"pdeathsig": _set_pdeathsig}
                    spawn_options.update(spawn_kwargs)
                    process = spawn_managed_process(command, self._session.log_path(name),
                                                    **spawn_options)
                except SimProviderUnavailable as exc:
                    raise ValueError(str(exc)) from exc
            node.process, node.pid, node.pgid, node.actual = process, process.pid, process.pid, "starting"
            self._generation[name] += 1
            generation = self._generation[name]
            node.exit_code, node.alert, node.started_at = None, None, time.monotonic()
            event = self._session.event("block_started", node=name, pid=process.pid)
            self._events.append(event)
            threading.Thread(target=self._watch, args=(name, process, generation), daemon=True).start()
            return node.public()

    def stop_node(self, name: str) -> dict[str, Any]:
        if name not in BLOCKS:
            raise ValueError(f"unknown block: {name}")
        with self._lock:
            node = self._nodes[name]
            node.expected = False
            node.actual = "stopping"
            self._stop_epoch[name] += 1
            epoch = self._stop_epoch[name]
            process, pgid = node.process, node.pgid
            impacts = [child for child in DEPENDENTS.get(name, ()) if self._nodes[child].expected]
        if name == "recorder" and self._recorder and pgid is not None:
            result = self._recorder.stop(term_timeout=self._term_timeout, kill_timeout=self._kill_timeout)
        elif pgid is not None:
            result = stop_process_group(pgid, process, self._term_timeout, self._kill_timeout)
        else:
            result = TeardownResult("stopped", (), node.exit_code)
        with self._lock:
            node = self._nodes[name]
            if epoch != self._stop_epoch[name]:
                return {"node": name, "state": node.public(), "downstream_impact": impacts}
            if result.outcome == "stopped":
                node.actual = "stopped"
                node.process = node.pid = node.pgid = None
                event_type = "block_stopped"
            else:
                node.actual = "cleanup_failed"
                node.alert = f"{name} cleanup failed; residual pids: {list(result.remaining_pids)}"
                event_type = "block_cleanup_failed"
            node.exit_code = result.exit_code
            event = {"type": event_type, "node": name}
            if result.remaining_pids:
                event["remaining_pids"] = list(result.remaining_pids)
            if self._session:
                self._record_event(event_type, **{key: value for key, value in event.items()
                                                  if key != "type"})
            return {"node": name, "state": node.public(), "downstream_impact": impacts}

    def start_all(self) -> dict[str, Any]:
        selected = set(self._config["blocks"])
        if not selected:
            raise ValueError("no blocks selected — light at least one block before starting")
        if self._config.get("execution_mode") in {"real", "sim"}:
            # 刚停止的节点在 DDS 发现里仍会停留数十秒；当且仅当
            # duplicate_nodes 是唯一失败项时，有界等待其清退后重试，
            # 避免 /api/restart 被自己刚停掉的节点误拒。
            deadline = time.monotonic() + self._duplicate_settle_timeout
            while True:
                result = preflight(selected, side=self._config["side"],
                                   profile=self._config["profile"])
                failed = {name for name, passed in result["results"].items() if not passed}
                if not failed:
                    break
                if failed != {"duplicate_nodes"} or time.monotonic() >= deadline:
                    reasons = "; ".join(result["reasons"][name] for name, passed
                                        in result["results"].items() if not passed)
                    raise ValueError(f"preflight rejected real-node start: {reasons}")
                time.sleep(1.0)
        for name in START_ORDER:
            if name in selected:
                self.start_node(name)
        return self.snapshot()

    def stop_all(self) -> dict[str, Any]:
        for name in reversed(START_ORDER):
            if self._nodes[name].expected or self._nodes[name].process or self._nodes[name].pgid:
                self.stop_node(name)
        return self.snapshot()

    def restart(self) -> dict[str, Any]:
        self.stop_all()
        return self.start_all()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            # starting→running 的唯一转换点：进程在宽限期内未退出即视为运行。
            # 业务级就绪（TRACKING、fault 等）由状态监控与数据流层另行表达。
            now = time.monotonic()
            for name in BLOCKS:
                node = self._nodes[name]
                if (node.actual == "starting" and node.process is not None
                        and node.process.poll() is None and node.started_at is not None
                        and now - node.started_at >= self._ready_grace):
                    node.actual = "running"
                    if self._session:
                        self._record_event("block_running", node=name)
            validation = validate_blocks(self._config["blocks"],
                                         confirmation=bool(self._config.get("confirmed")))
            events = read_events(self._session.path) if self._session else []
            return {"config": dict(self._config), "run": str(self._session.path) if self._session else None,
                    "nodes": {n: self._nodes[n].public() for n in BLOCKS},
                    "validation": validation, "events": events}

    def mark(self, label: str, **fields: Any) -> dict[str, Any]:
        with self._lock:
            if self._session is None:
                raise ValueError("run session has not been configured")
            return self._record_event("web_mark", label=label, **fields)

    def _record_event(self, event_type: str, **fields: Any) -> dict[str, Any]:
        """Persist one active-run event before mirroring the same object in memory."""
        if self._session is None:
            raise ValueError("run session has not been configured")
        event = self._session.event(event_type, **fields)
        self._events.append(event)
        return event

    def close(self) -> None:
        self.stop_all()
        with self._lock:
            if self._sysmon:
                self._sysmon.stop()
                self._sysmon = None
            if self._session:
                self._session.event("run_closed")
                self._session.close()
                self._session = None
