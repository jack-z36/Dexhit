"""Process-lifetime single-instance lock for the local Launchpad."""

from __future__ import annotations

import errno
import fcntl
import os
from pathlib import Path
import socket
from collections.abc import Callable


class InstanceAlreadyRunning(RuntimeError):
    """Raised when another Launchpad control plane owns the lock."""


_ABSTRACT_SOCKET_FALLBACK_ERRNOS = frozenset(
    {
        errno.EPERM,
        errno.EAFNOSUPPORT,
        errno.ENOSYS,
        errno.EOPNOTSUPP,
    }
)


class InstanceLock:
    """Own a kernel-scoped single-instance lock for one process lifetime.

    Linux removes an abstract socket when its owning file descriptor closes,
    including after an ungraceful process exit.  That gives us a real
    single-instance guard without a lock file.  On systems that explicitly
    reject abstract sockets, a POSIX advisory lock under ``/tmp`` is used.
    """

    def __init__(
        self,
        name: str = "rokoko_omnihand_launchpad",
        *,
        lock_dir: str | os.PathLike[str] = "/tmp",
        socket_factory: Callable[..., socket.socket] = socket.socket,
    ) -> None:
        if not name or Path(name).name != name:
            raise ValueError("Launchpad instance lock name must be a simple filename")
        self._address = "\0" + name
        self._lock_path = Path(lock_dir) / f"{name}.lock"
        self._socket_factory = socket_factory
        self._socket: socket.socket | None = None
        self._lock_file = None

    def acquire(self) -> None:
        if self._socket is not None or self._lock_file is not None:
            raise RuntimeError("Launchpad instance lock is already acquired")

        lock_socket = None
        try:
            lock_socket = self._socket_factory(socket.AF_UNIX, socket.SOCK_STREAM)
            lock_socket.bind(self._address)
            lock_socket.listen(1)
        except OSError as exc:
            if exc.errno == errno.EADDRINUSE:
                if lock_socket is not None:
                    lock_socket.close()
                raise InstanceAlreadyRunning(
                    "Launchpad 已有实例运行，拒绝启动第二个控制面。"
                ) from exc
            if exc.errno not in _ABSTRACT_SOCKET_FALLBACK_ERRNOS:
                if lock_socket is not None:
                    lock_socket.close()
                raise
            if lock_socket is not None:
                lock_socket.close()
            self._acquire_file_lock()
            return
        self._socket = lock_socket

    def _acquire_file_lock(self) -> None:
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_file = None
        try:
            descriptor = os.open(
                self._lock_path,
                os.O_CREAT | os.O_RDWR,
                0o600,
            )
            lock_file = os.fdopen(descriptor, "a+b", buffering=0)
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if lock_file is not None:
                lock_file.close()
            if exc.errno in (errno.EACCES, errno.EAGAIN):
                raise InstanceAlreadyRunning(
                    "Launchpad 已有实例运行，拒绝启动第二个控制面。"
                ) from exc
            raise
        self._lock_file = lock_file

    def release(self) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        if self._lock_file is not None:
            self._lock_file.close()
            self._lock_file = None

    def __enter__(self) -> "InstanceLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.release()
