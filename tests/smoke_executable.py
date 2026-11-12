"""Smoke-test a built executable: start it, check the bundled page, trade over /ws, and stop it.

    venv/bin/python tests/smoke_executable.py dist/FinBro_Larper

Used by .github/workflows/build.yml on every OS it builds. Exits non-zero on failure.
It isn't collected by pytest (no test_ prefix), because it needs a built executable.
"""

import asyncio
import glob
import json
import os
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import websockets

STARTUP_TIMEOUT = 60  # a one-file build unpacks itself first, which is slow on a cold CI runner


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.read()


def wait_until_serving(base: str, process: subprocess.Popen) -> str:
    deadline = time.time() + STARTUP_TIMEOUT
    while True:
        try:
            return get(f"{base}/static/index.html").decode()
        except OSError:
            if process.poll() is not None:
                raise SystemExit(f"FAIL: the executable exited with code {process.returncode} before serving")
            if time.time() > deadline:
                raise SystemExit(f"FAIL: not serving after {STARTUP_TIMEOUT} s")
            time.sleep(0.5)


async def recv(ws, msg_type: str, timeout: float = 10.0) -> dict:
    async def wait():
        while True:
            message = json.loads(await ws.recv())
            if message["type"] == msg_type:
                return message
    return await asyncio.wait_for(wait(), timeout)


async def play(port: int) -> None:
    async with websockets.connect(f"ws://127.0.0.1:{port}/ws", max_size=None) as ws:
        snapshot = await recv(ws, "SNAPSHOT")
        assert len(snapshot["assets"]) == 8, snapshot["assets"]
        await ws.send(json.dumps({"action": "ORDER", "ticker": "TCHN", "side": "BUY", "type": "MARKET", "quantity": 1}))
        result = await recv(ws, "ORDER_RESULT")
        assert result["ok"], result
        await ws.send(json.dumps({"action": "PLAY"}))
        tick = await recv(ws, "TICK")
        print(f"ok   traded and ticked: {result['message']} / clock {tick['clock']}")


def stop(process: subprocess.Popen) -> None:
    if os.name == "nt":
        # A one-file build is a launcher plus the game process it unpacks and starts, and
        # terminate() would only end the launcher. Kill the whole tree instead.
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
    else:
        process.send_signal(signal.SIGINT)  # Ctrl+C: the launcher's normal way to quit (forwarded to the game)
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        raise SystemExit("FAIL: didn't exit within 15 s of being stopped")
    time.sleep(1)  # let the OS release the game's files and port


def main() -> None:
    exe = Path(sys.argv[1]).resolve()
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    tmp = tempfile.gettempdir()
    dbs_before = set(glob.glob(os.path.join(tmp, "finbro_larper_*.db")))

    # Run from another directory, so nothing can be picked up from the source tree.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as cwd:
        process = subprocess.Popen([str(exe), "--no-browser", "--port", str(port)], cwd=cwd)
        try:
            page = wait_until_serving(base, process)
            assert "<title>FinBro_Larper</title>" in page, "page title"
            scripts = re.findall(r'<script src="([^"]+)"', page)
            assert scripts, "no vendored scripts referenced"
            for src in scripts:
                assert get(f"{base}/static/{src}"), src
            print(f"ok   page and {len(scripts)} vendored scripts are bundled")
            asyncio.run(play(port))
        finally:
            stop(process)
        # The game process must be gone too, not just the one-file launcher that started it.
        try:
            get(f"{base}/static/index.html")
            raise SystemExit("FAIL: still serving after it was stopped")
        except OSError:
            pass

    if os.name != "nt":  # on Windows it's hard-killed, which skips the cleanup
        left = set(glob.glob(os.path.join(tmp, "finbro_larper_*.db"))) - dbs_before
        assert not left, f"temp database not deleted on exit: {left}"
        print("ok   quit cleanly and deleted its temp database")
    print("PASS")


if __name__ == "__main__":
    main()
