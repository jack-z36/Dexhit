"""FastAPI application for the T01 Launchpad skeleton."""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from .orchestrator import CleanupFailedError, Orchestrator, available_profiles, preflight, validate_blocks
from .data_stream import DataStreamStore
from .latency_events import LatencyEventsStore, read_events
from .run_session import delete_run_session, list_run_sessions
from .ros_runtime import RosMonitorState
from .status_monitor import StatusMonitor


PACKAGE_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_CANDIDATES = (
    PACKAGE_ROOT / "web" / "dist",
    Path(__file__).resolve().parents[4]
    / "share"
    / "rokoko_omnihand_launchpad"
    / "web",
)


def _frontend_dist() -> Path | None:
    for candidate in FRONTEND_CANDIDATES:
        if (candidate / "index.html").is_file():
            return candidate
    return None


def _placeholder_page() -> str:
    return """<!doctype html>
<html lang="zh-CN">
  <head><meta charset="utf-8"><title>Launchpad</title></head>
  <body>
    <main>
      <h1>Launchpad 控制面占位页</h1>
      <p>T01 包骨架已启动；业务节点尚未接入。</p>
    </main>
  </body>
</html>"""


def create_app(*, clock: Callable[[], float] | None = None, run_root: str | Path | None = None,
               recorder_command_factory=None, data_stream: DataStreamStore | None = None,
               latency_events: LatencyEventsStore | None = None,
               ros_monitor: RosMonitorState | None = None) -> FastAPI:
    """Create the HTTP application without starting ROS or business nodes."""

    app = FastAPI(title="Rokoko OmniHand Launchpad", version="0.1.0")
    orchestrator = Orchestrator(run_root=run_root, recorder_command_factory=recorder_command_factory)
    history_root = Path(run_root or os.environ.get("DEXHIT_LAUNCHPAD_RUN_ROOT", "runs/launchpad"))
    status_monitor = StatusMonitor(clock=clock or time.monotonic)
    data_stream = data_stream or DataStreamStore(clock=clock)
    latency_events = latency_events or LatencyEventsStore(clock=clock)
    ros_monitor = ros_monitor or RosMonitorState()
    app.state.orchestrator = orchestrator
    app.state.status_monitor = status_monitor
    app.state.data_stream = data_stream
    app.state.latency_events = latency_events
    app.state.ros_monitor = ros_monitor
    frontend_dist = _frontend_dist()
    frontend_html = (
        (frontend_dist / "index.html").read_text(encoding="utf-8")
        if frontend_dist
        else None
    )
    assets = frontend_dist / "assets" if frontend_dist else None
    if assets and assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="frontend-assets")

    @app.get("/", response_class=HTMLResponse, response_model=None)
    async def homepage() -> Response:
        if frontend_html is not None:
            return HTMLResponse(frontend_html)
        return HTMLResponse(_placeholder_page())

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "service": "rokoko_omnihand_launchpad"}

    @app.get("/api/profiles")
    async def profiles() -> dict[str, str]:
        return available_profiles()

    @app.get("/api/state")
    async def state() -> dict:
        snapshot = orchestrator.snapshot()
        snapshot["status"] = status_monitor.snapshot()
        snapshot["data_stream"] = data_stream.snapshot()
        snapshot["latency_events"] = latency_events.snapshot()
        snapshot["ros_monitor"] = ros_monitor.snapshot()
        snapshot["events"] = read_events(snapshot.get("run"))
        return snapshot

    @app.get("/api/data-stream")
    async def data_stream_snapshot() -> dict:
        """Return bounded, approximately 10Hz histories for the panel UI."""
        return data_stream.snapshot()

    @app.get("/api/latency-events")
    async def latency_events_snapshot() -> dict:
        run = orchestrator.snapshot().get("run")
        return {"latency_events": latency_events.snapshot(), "events": read_events(run)}

    @app.get("/api/runs")
    async def runs() -> dict:
        return {"root": str(history_root), "runs": list_run_sessions(history_root)}

    @app.delete("/api/runs/{run_id}")
    async def delete_run(run_id: str) -> dict[str, str]:
        active = orchestrator.snapshot().get("run")
        if active and Path(active).name == run_id:
            raise HTTPException(status_code=409, detail="cannot delete the active run")
        try:
            delete_run_session(history_root, run_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"run not found: {run_id}") from exc
        return {"deleted": run_id}

    @app.post("/api/validate")
    async def validate(payload: dict) -> dict:
        return validate_blocks(payload.get("blocks", []), confirmation=bool(payload.get("confirmation")))

    @app.post("/api/config")
    async def configure(payload: dict) -> dict:
        try:
            return orchestrator.configure(payload)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/preflight")
    async def run_preflight(payload: dict) -> dict:
        return preflight(payload.get("blocks", []), side=payload.get("side", "both"),
                         profile=payload.get("profile", "default"), checks=payload.get("checks"))

    @app.post("/api/start")
    async def start() -> dict:
        try:
            return orchestrator.start_all()
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/stop")
    async def stop() -> dict:
        return orchestrator.stop_all()

    @app.post("/api/restart")
    async def restart() -> dict:
        try:
            return orchestrator.restart()
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/nodes/{name}/start")
    async def start_node(name: str) -> dict:
        try:
            return orchestrator.start_node(name)
        except CleanupFailedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/nodes/{name}/stop")
    async def stop_node(name: str) -> dict:
        try:
            return orchestrator.stop_node(name)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/events")
    async def event(payload: dict) -> dict:
        try:
            return orchestrator.mark(str(payload.get("label", payload.get("message", ""))),
                                     message=payload.get("message"))
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/mark")
    async def mark(payload: dict) -> dict:
        try:
            return orchestrator.mark(str(payload.get("label", payload.get("message", ""))),
                                     message=payload.get("message"))
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.websocket("/ws")
    async def websocket(websocket: WebSocket) -> None:
        await websocket.accept()
        def snapshot() -> dict:
            state = orchestrator.snapshot()
            state["status"] = status_monitor.snapshot()
            state["data_stream"] = data_stream.snapshot()
            state["latency_events"] = latency_events.snapshot()
            state["ros_monitor"] = ros_monitor.snapshot()
            state["events"] = read_events(state.get("run"))
            return state

        await websocket.send_json(snapshot())
        try:
            while True:
                try:
                    await asyncio.wait_for(websocket.receive_text(), timeout=0.1)
                except asyncio.TimeoutError:
                    pass
                await websocket.send_json(snapshot())
        except Exception:
            return

    return app
