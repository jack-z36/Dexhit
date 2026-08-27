"""Persistent, thread-safe artifacts for one Launchpad run."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO


def _safe_label(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return value.strip("._-")[:80]


def _git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
            timeout=2, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _usb_devices() -> list[str] | None:
    if not shutil_which("lsusb"):
        return None
    try:
        result = subprocess.run(["lsusb"], capture_output=True, text=True, timeout=2, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return [line for line in result.stdout.splitlines() if line.strip()]


def shutil_which(command: str) -> str | None:
    # Kept as a tiny seam so metadata collection remains deterministic in tests.
    import shutil
    return shutil.which(command)


def _directory_size(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        if item.is_file() and not item.is_symlink():
            try:
                total += item.stat().st_size
            except OSError:
                continue
    return total


def _artifact_kind(path: Path) -> str:
    return {"bag": "mcap", "metadata.json": "metadata", "events.jsonl": "events",
            "sysmon.jsonl": "sysmon", "logs": "logs"}.get(path.name, path.name)


def list_run_sessions(root: str | os.PathLike[str]) -> list[dict[str, Any]]:
    """Read run summaries without creating or changing files."""
    run_root = Path(root)
    if not run_root.is_dir():
        return []
    summaries: list[dict[str, Any]] = []
    for path in run_root.iterdir():
        if not path.is_dir() or path.is_symlink():
            continue
        metadata: dict[str, Any] = {}
        try:
            metadata = json.loads((path / "metadata.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
        artifacts = []
        try:
            children = sorted(path.iterdir(), key=lambda item: item.name)
        except OSError:
            children = []
        for child in children:
            try:
                size = _directory_size(child) if child.is_dir() else child.stat().st_size
            except OSError:
                size = 0
            artifacts.append({"name": child.name, "kind": _artifact_kind(child), "size_bytes": size})
        try:
            fallback_time = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
        except OSError:
            fallback_time = ""
        params = metadata.get("params") if isinstance(metadata.get("params"), dict) else {}
        summaries.append({
            "id": path.name,
            "created_at": metadata.get("created_at") or fallback_time,
            "template": metadata.get("template", params.get("template", "custom")) or "custom",
            "label": metadata.get("label", params.get("label", "")) or "",
            "size_bytes": _directory_size(path),
            "artifacts": artifacts,
        })
    return sorted(summaries, key=lambda item: item["created_at"], reverse=True)


def delete_run_session(root: str | os.PathLike[str], run_id: str) -> None:
    """Explicitly delete one direct child of root, never an arbitrary path."""
    if not run_id or Path(run_id).name != run_id or run_id in {".", ".."}:
        raise ValueError("run id must be a direct run directory name")
    run_root = Path(root).resolve()
    target = (run_root / run_id).resolve()
    if target.parent != run_root or not target.is_dir() or target.is_symlink():
        raise FileNotFoundError(run_id)
    shutil.rmtree(target)


class RunSession:
    """Own the run directory and append-only event/metadata files."""

    def __init__(self, root: Path, *, config: dict[str, Any]) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        raw_label = str(config.get("label", ""))
        label = _safe_label(raw_label)
        template = _safe_label(str(config.get("template", "custom"))) or "custom"
        suffix = f"{template}_{label}" if label else template
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        self.path = self.root / f"{stamp}_{suffix}"
        self.path.mkdir()
        self.logs = self.path / "logs"
        self.logs.mkdir()
        self.events_path = self.path / "events.jsonl"
        self._lock = threading.RLock()
        self._event_file: TextIO = self.events_path.open("a", encoding="utf-8")
        metadata = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "blocks": list(config.get("blocks", [])),
            "template": config.get("template", "custom"),
            "label": raw_label,
            "profile": config.get("profile", "default"),
            "git_commit": _git_commit(),
            "usb_devices": _usb_devices(),
            "execution_mode": config.get("execution_mode", "real"),
            "mode": config.get("mode", config.get("execution_mode", "real")),
            "side": config.get("side", "both"),
            "params": dict(config),
        }
        self.metadata_path = self.path / "metadata.json"
        self.metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.event("run_created", metadata={"path": str(self.path)})

    def log_path(self, name: str) -> Path:
        return self.logs / f"{_safe_label(name) or 'process'}.log"

    def event(self, event_type: str, **fields: Any) -> dict[str, Any]:
        event = {"timestamp": datetime.now(timezone.utc).isoformat(), "type": event_type, **fields}
        with self._lock:
            self._event_file.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
            self._event_file.flush()
        return event

    def close(self) -> None:
        with self._lock:
            if not self._event_file.closed:
                self._event_file.flush()
                self._event_file.close()
