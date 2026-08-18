"""One-Hz process resource sampler."""

from __future__ import annotations

import os
import resource
import threading
import time
from pathlib import Path
from typing import Callable


_last_cpu = (time.monotonic(), resource.getrusage(resource.RUSAGE_SELF).ru_utime)


def _sample() -> dict[str, float | int | None]:
    global _last_cpu
    now = time.monotonic()
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_utime
    previous_time, previous_usage = _last_cpu
    _last_cpu = (now, usage)
    elapsed = now - previous_time
    cpu_percent = ((usage - previous_usage) / elapsed * 100.0) if elapsed > 0 else 0.0
    memory: int | None = None
    try:
        for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                memory = int(line.split()[1]) * 1024
                break
    except (OSError, ValueError):
        pass
    return {"timestamp": time.time(), "cpu_percent": cpu_percent, "memory_bytes": memory,
            "pid": os.getpid()}


class SystemMonitor:
    def __init__(self, path: Path, *, interval: float = 1.0,
                 sampler: Callable[[], dict] = _sample) -> None:
        self.path = Path(path)
        self.interval = interval
        self.sampler = sampler
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="launchpad-sysmon", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        with self.path.open("a", encoding="utf-8") as output:
            while not self._stop.is_set():
                import json
                output.write(json.dumps(self.sampler(), sort_keys=True) + "\n")
                output.flush()
                self._stop.wait(self.interval)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=max(2.0, self.interval + 1.0))
        self._thread = None
