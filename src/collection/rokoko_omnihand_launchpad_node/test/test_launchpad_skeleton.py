"""Black-box checks for the T01 control-plane skeleton."""

from __future__ import annotations

import asyncio
import errno
import fcntl
import json
from typing import Any

import rokoko_omnihand_launchpad.app as app_module
from rokoko_omnihand_launchpad.app import create_app
from rokoko_omnihand_launchpad.instance_lock import (
    InstanceAlreadyRunning,
    InstanceLock,
)


async def _get(app: Any, path: str) -> tuple[int, bytes]:
    """Send one ASGI request without requiring the optional httpx2 client."""

    messages: list[dict[str, Any]] = []
    request_consumed = False

    async def receive() -> dict[str, Any]:
        nonlocal request_consumed
        if request_consumed:
            return {"type": "http.disconnect"}
        request_consumed = True
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    await app(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 1),
            "root_path": "",
        },
        receive,
        send,
    )
    start = next(message for message in messages if message["type"] == "http.response.start")
    body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    return int(start["status"]), body


def test_homepage_is_chinese_and_has_no_business_node_side_effect():
    status, body = asyncio.run(_get(create_app(), "/"))

    text = body.decode()
    assert status == 200
    assert 'lang="zh-CN"' in text
    assert "Launchpad 控制面" in text
    assert "id=\"app\"" in text or "业务节点尚未接入" in text


def test_homepage_serves_built_html_without_file_response_thread(tmp_path, monkeypatch):
    built_html = "<!doctype html><html lang=\"zh-CN\"><body>built launchpad</body></html>"
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text(built_html, encoding="utf-8")
    (dist / "assets").mkdir()
    monkeypatch.setattr(app_module, "FRONTEND_CANDIDATES", (dist,))

    status, body = asyncio.run(_get(create_app(), "/"))

    assert status == 200
    assert body.decode() == built_html


def test_homepage_keeps_placeholder_without_built_html(monkeypatch):
    monkeypatch.setattr(app_module, "FRONTEND_CANDIDATES", ())

    status, body = asyncio.run(_get(create_app(), "/"))

    assert status == 200
    assert "业务节点尚未接入" in body.decode()


def test_health_endpoint_is_local_control_plane_probe():
    status, body = asyncio.run(_get(create_app(), "/healthz"))

    assert status == 200
    assert json.loads(body) == {
        "status": "ok",
        "service": "rokoko_omnihand_launchpad",
    }


def test_second_instance_is_rejected_and_release_leaves_no_file():
    name = "rokoko_omnihand_launchpad_test"
    first = InstanceLock(name)
    second = InstanceLock(name)
    first.acquire()
    try:
        try:
            second.acquire()
        except InstanceAlreadyRunning as exc:
            assert "拒绝启动第二个控制面" in str(exc)
        else:
            raise AssertionError("second Launchpad instance was not rejected")
    finally:
        first.release()
        second.release()

    # Abstract Unix sockets have no filesystem pathname to clean up.
    assert first._socket is None
    assert second._socket is None


class _AbstractSocketUnavailable:
    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    def bind(self, _address: str) -> None:
        raise OSError(errno.EPERM, "Operation not permitted")

    def close(self) -> None:
        pass


def test_abstract_socket_permission_error_uses_flock_fallback(tmp_path):
    name = "rokoko_omnihand_launchpad_fallback"
    first = InstanceLock(name, lock_dir=tmp_path, socket_factory=_AbstractSocketUnavailable)
    second = InstanceLock(name, lock_dir=tmp_path, socket_factory=_AbstractSocketUnavailable)

    first.acquire()
    try:
        assert first._socket is None
        assert first._lock_file is not None
        assert first._lock_path == tmp_path / f"{name}.lock"

        try:
            second.acquire()
        except InstanceAlreadyRunning as exc:
            assert "拒绝启动第二个控制面" in str(exc)
        else:
            raise AssertionError("second fallback instance was not rejected")
    finally:
        first.release()
        second.release()

    # The inode may remain as a stale marker, but no valid flock remains.
    with first._lock_path.open("a+") as probe:
        fcntl.flock(probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(probe.fileno(), fcntl.LOCK_UN)


def test_stale_fallback_file_is_reusable(tmp_path):
    name = "rokoko_omnihand_launchpad_stale"
    lock_path = tmp_path / f"{name}.lock"
    lock_path.write_text("stale", encoding="utf-8")

    lock = InstanceLock(name, lock_dir=tmp_path, socket_factory=_AbstractSocketUnavailable)
    lock.acquire()
    lock.release()


class _SocketBindError:
    def __init__(self, error: OSError) -> None:
        self._error = error

    def __call__(self, *_args: Any, **_kwargs: Any):
        error = self._error

        class Socket:
            def bind(self, _address: str) -> None:
                raise error

            def close(self) -> None:
                pass

        return Socket()


def test_eaddrinuse_never_falls_back(tmp_path):
    lock = InstanceLock(
        "rokoko_omnihand_launchpad_busy",
        lock_dir=tmp_path,
        socket_factory=_SocketBindError(OSError(errno.EADDRINUSE, "Address already in use")),
    )

    try:
        lock.acquire()
    except InstanceAlreadyRunning:
        pass
    else:
        raise AssertionError("EADDRINUSE was not reported as an active instance")

    assert not lock._lock_path.exists()
