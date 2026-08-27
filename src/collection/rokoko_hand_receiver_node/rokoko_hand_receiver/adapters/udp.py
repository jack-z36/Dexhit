"""UDP ingress adapter with immediate per-datagram receive-time capture."""

import socket
from threading import Event, Thread
from typing import Callable


DatagramCallback = Callable[[bytes, int], None]


class UdpDatagramReceiver:
    """Own a UDP socket and deliver payload plus local receive time."""

    def __init__(
        self,
        bind_address: str,
        port: int,
        *,
        max_datagram_bytes: int,
        now_ns: Callable[[], int],
        callback: DatagramCallback,
    ) -> None:
        self._now_ns = now_ns
        self._callback = callback
        self._max_datagram_bytes = max_datagram_bytes
        self._stop = Event()
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self._socket.bind((bind_address, port))
            self._socket.settimeout(0.1)
        except BaseException:
            self._socket.close()
            raise
        self._thread = Thread(
            target=self._receive_loop,
            name="rokoko_udp_receiver",
            daemon=True,
        )
        self._thread.start()

    def _receive_loop(self) -> None:
        while not self._stop.is_set():
            try:
                payload, _ = self._socket.recvfrom(self._max_datagram_bytes)
            except TimeoutError:
                continue
            except OSError:
                if self._stop.is_set():
                    return
                raise
            received_at_ns = self._now_ns()
            self._callback(payload, received_at_ns)

    def close(self) -> None:
        """Stop receiving and release the bound socket."""
        if self._stop.is_set():
            return
        self._stop.set()
        self._socket.close()
        self._thread.join(timeout=1.0)
