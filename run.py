"""Launch Pro Trader Sim: start the server and open the game in the browser.

This is the entry point of the packaged app (see pro_trader_sim.spec). It also works from source:
    venv/bin/python run.py [--port 8000] [--no-browser]
"""

import argparse
import os
import socket
import sys
import threading
import time
import webbrowser

import uvicorn

from database import DB_PATH, engine
from main import app


def free_port(preferred: int) -> int:
    """The preferred port if it's free, otherwise any free port."""
    for candidate in (preferred, 0):
        with socket.socket() as s:
            if os.name != "nt":
                # Match uvicorn's own socket options, or a port still in TIME_WAIT from the last run
                # looks busy and a quick restart lands on a random port. (On Windows this option
                # would let us bind a port another app is using, and TIME_WAIT doesn't block binds.)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", candidate))
                return s.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("No free port available")


def main() -> None:
    parser = argparse.ArgumentParser(description="Pro Trader Sim")
    parser.add_argument("--port", type=int, default=8000, help="port to serve on (another is used if it's taken)")
    parser.add_argument("--no-browser", action="store_true", help="don't open the browser")
    args = parser.parse_args()

    port = free_port(args.port)
    url = f"http://127.0.0.1:{port}/"
    # Name every uvicorn component explicitly: its auto-detection imports modules by name at
    # runtime, which PyInstaller can't see, and a packaged build would then fail to start.
    server = uvicorn.Server(uvicorn.Config(
        app, host="127.0.0.1", port=port, http="h11", ws="websockets", loop="asyncio",
        lifespan="on", log_level="warning",
    ))

    def announce_when_ready() -> None:
        while not server.started:
            if server.should_exit:
                return
            time.sleep(0.1)
        print(f"Pro Trader Sim is running at {url}\nClose this window or press Ctrl+C to quit.", flush=True)
        if not args.no_browser:
            webbrowser.open(url)

    threading.Thread(target=announce_when_ready, daemon=True).start()
    try:
        server.run()
    finally:
        engine.dispose()
        if getattr(sys, "frozen", False):
            DB_PATH.unlink(missing_ok=True)  # the packaged app's per-process temp database


if __name__ == "__main__":
    main()
