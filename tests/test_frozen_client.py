"""A browser that stops reading (e.g. a frozen background tab) must not stall the market.

Regression test: the market loop used to await each send, so one stuck client whose keepalive
ping timed out froze the whole market and no limit orders filled.
"""

import base64
import os
import socket
import time

from wsutil import connect, recv_until, run, send


def frozen_client(port: int) -> socket.socket:
    """Open a WebSocket at the TCP level, then never read from it."""
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)  # fill up fast
    sock.connect(("127.0.0.1", port))
    key = base64.b64encode(os.urandom(16)).decode()
    sock.sendall((f"GET /ws HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                  f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
    return sock


def closed_by_server(sock: socket.socket, timeout: float) -> bool:
    """Drain what the server sent; True once it closes the connection."""
    sock.settimeout(timeout)
    try:
        while sock.recv(65536):
            pass
        return True
    except (ConnectionResetError, ConnectionAbortedError):
        return True
    except socket.timeout:
        return False


def test_frozen_client_does_not_stall_the_market(server_factory):
    # Short keepalive so the stuck client's ping times out within the test (the path that used to stall).
    server = server_factory("--ws-ping-interval", "1", "--ws-ping-timeout", "1")

    async def body():
        async with connect(server) as ws:
            await recv_until(ws, "SNAPSHOT")
            await send(ws, action="PLAY")
            await recv_until(ws, "STATUS", pred=lambda m: m["running"])
            stuck = frozen_client(server.port)
            last = start = time.monotonic()
            longest_gap, ticks = 0.0, 0
            while time.monotonic() - start < 8:
                await recv_until(ws, "TICK", timeout=3)
                now = time.monotonic()
                longest_gap = max(longest_gap, now - last)
                last = now
                ticks += 1
            await send(ws, action="PAUSE")
            return stuck, longest_gap, ticks / (time.monotonic() - start)

    stuck, longest_gap, rate = run(body())
    assert longest_gap < 0.5, f"market stalled for {longest_gap:.2f}s"
    assert rate > 9, f"{rate:.1f} ticks/s"
    assert closed_by_server(stuck, timeout=20), "the stuck client should be disconnected"
    stuck.close()
