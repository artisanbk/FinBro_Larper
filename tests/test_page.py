"""The page's real JavaScript, driven in Node against a live server (see page_harness.js)."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

NODE = shutil.which("node")


def node_has_websocket() -> bool:
    if not NODE:
        return False
    out = subprocess.run([NODE, "-e", "process.stdout.write(typeof WebSocket)"], capture_output=True, text=True)
    return out.stdout == "function"


@pytest.mark.skipif(not node_has_websocket(), reason="needs Node 22+ (global WebSocket)")
def test_page_script(server_factory):
    server = server_factory()  # fresh: the harness expects an untouched, paused game
    result = subprocess.run(
        [NODE, str(ROOT / "tests" / "page_harness.js"), str(ROOT / "static" / "index.html"), server.host],
        capture_output=True, text=True, timeout=120,
    )
    failures = [line for line in result.stdout.splitlines() if line.startswith("FAIL")]
    assert result.returncode == 0, "\n".join(failures) or result.stdout + result.stderr
    # A crash before the results (e.g. a syntax error in the page) must not pass as "no failures".
    assert "ALL PASSED" in result.stdout, result.stdout + result.stderr
