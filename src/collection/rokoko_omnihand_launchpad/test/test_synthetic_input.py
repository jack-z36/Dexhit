from __future__ import annotations

import json
import socket
import subprocess
import sys
import time

from rokoko_omnihand_launchpad.synthetic_input import payloads


def test_same_configuration_replays_the_same_sequence():
    first = list(payloads(side="left", count=3))
    second = list(payloads(side="left", count=3))

    assert first == second
    assert [json.loads(frame)["scene"]["timestamp"] for frame in first] == [
        2000.0, 2000.0 + 1 / 60, 2000.0 + 2 / 60
    ]
    assert all("leftHand" in json.loads(frame)["scene"]["actors"][0]["body"] for frame in first)
    assert all("rightHand" not in json.loads(frame)["scene"]["actors"][0]["body"] for frame in first)


def test_cli_sends_json_v3_over_udp_loopback():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
        receiver.bind(("127.0.0.1", 0))
        receiver.settimeout(2.0)
        process = subprocess.Popen([
            sys.executable, "-m", "rokoko_omnihand_launchpad.synthetic_input",
            "--port", str(receiver.getsockname()[1]), "--side", "right",
            "--count", "2", "--fps", "120",
        ])
        try:
            frames = [receiver.recvfrom(65535)[0] for _ in range(2)]
        finally:
            process.wait(timeout=2)
    assert process.returncode == 0
    documents = [json.loads(frame) for frame in frames]
    assert [document["version"] for document in documents] == [3, 3]
    assert [document["scene"]["timestamp"] for document in documents] == [
        2000.0, 2000.0 + 1 / 60
    ]
    assert "rightHand" in documents[0]["scene"]["actors"][0]["body"]
    assert "leftHand" not in documents[0]["scene"]["actors"][0]["body"]


def test_orchestrator_starts_and_stops_real_synthetic_process():
    from rokoko_omnihand_launchpad.orchestrator import Orchestrator

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
        receiver.bind(("127.0.0.1", 0))
        receiver.settimeout(2.0)
        orchestrator = Orchestrator()
        try:
            configured = orchestrator.configure({
                "blocks": ["synthetic_input"],
                "side": "left",
                "udp_port": receiver.getsockname()[1],
                "execution_mode": "mock",
            })
            started = orchestrator.start_node("synthetic_input")
            frame = receiver.recvfrom(65535)[0]
            assert configured["config"]["side"] == "left"
            assert started["pid"] is not None
            assert json.loads(frame)["version"] == 3
        finally:
            stopped = orchestrator.stop_node("synthetic_input")
            orchestrator.close()
    assert stopped["state"]["expected"] is False
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and stopped["state"]["pid"] is not None:
        time.sleep(0.01)


def test_http_main_seam_reuses_synthetic_udp_source():
    """The public Launchpad seam can configure/start/stop the same source."""
    import pytest

    pytest.importorskip("fastapi")
    from rokoko_omnihand_launchpad.app import create_app

    async def request(app, method, path, payload=None):
        body = json.dumps(payload or {}).encode()
        messages = []
        consumed = False

        async def receive():
            nonlocal consumed
            if consumed:
                return {"type": "http.disconnect"}
            consumed = True
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message):
            messages.append(message)

        await app({
            "type": "http", "http_version": "1.1", "method": method,
            "path": path, "raw_path": path.encode(), "query_string": b"",
            "headers": [(b"content-type", b"application/json")],
            "scheme": "http", "server": ("test", 80), "client": ("test", 1),
            "root_path": "",
        }, receive, send)
        start = next(item for item in messages if item["type"] == "http.response.start")
        raw = b"".join(item.get("body", b"") for item in messages if item["type"] == "http.response.body")
        return int(start["status"]), json.loads(raw)

    import asyncio

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
        receiver.bind(("127.0.0.1", 0))
        receiver.settimeout(2.0)
        app = create_app()
        try:
            status, _ = asyncio.run(request(app, "POST", "/api/config", {
                "blocks": ["synthetic_input"], "side": "left",
                "udp_port": receiver.getsockname()[1], "execution_mode": "mock",
            }))
            assert status == 200
            status, started = asyncio.run(request(app, "POST", "/api/start"))
            assert status == 200 and started["nodes"]["synthetic_input"]["pid"]
            frame = receiver.recvfrom(65535)[0]
            assert json.loads(frame)["version"] == 3
        finally:
            asyncio.run(request(app, "POST", "/api/stop"))
