"""Shared setup for the test suite.

- Points the app's database at a temp file *before* any app module is imported, so tests
  never touch the real simulator.db.
- Provides live uvicorn servers (real sockets, real /ws) for the protocol and page tests.
"""

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="finbro_larper_tests_"))
os.environ["FINBRO_LARPER_DB"] = str(TMP / "engine.db")


@pytest.fixture(scope="session", autouse=True)
def engine_db():
    """Create the tables for in-process engine tests (the server's lifespan does this normally)."""
    import models  # noqa: F401  (registers the tables)
    from database import Base, engine

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    engine.dispose()
    shutil.rmtree(TMP, ignore_errors=True)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LiveServer:
    def __init__(self, port: int, process: subprocess.Popen) -> None:
        self.port = port
        self.process = process
        self.host = f"127.0.0.1:{port}"
        self.ws_url = f"ws://{self.host}/ws"


@contextmanager
def run_server(*uvicorn_args: str):
    """Start `uvicorn main:app` on a free port with its own database; stop it afterwards."""
    port = free_port()
    env = {**os.environ, "FINBRO_LARPER_DB": str(TMP / f"server_{port}.db")}
    log = open(TMP / f"server_{port}.log", "w+")
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--port", str(port), "--log-level", "warning", *uvicorn_args],
        cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.time() + 20
        while True:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/static/index.html", timeout=1).close()
                break
            except OSError:
                if process.poll() is not None or time.time() > deadline:
                    log.seek(0)
                    pytest.fail(f"server didn't start:\n{log.read()}")
                time.sleep(0.2)
        yield LiveServer(port, process)
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        log.seek(0)
        errors = [line for line in log.read().splitlines() if "Traceback" in line or "ERROR" in line]
        log.close()
        assert not errors, f"server logged errors: {errors}"


@pytest.fixture(scope="module")
def server():
    """One live server per test module. Tests reset it with NEW_GAME (see wsutil.fresh_game)."""
    with run_server() as live:
        yield live


@pytest.fixture
def server_factory():
    """Start a dedicated server with custom uvicorn options, e.g. short keepalive pings."""
    stack = []

    def start(*uvicorn_args: str) -> LiveServer:
        cm = run_server(*uvicorn_args)
        stack.append(cm)
        return cm.__enter__()

    yield start
    for cm in reversed(stack):
        cm.__exit__(None, None, None)
