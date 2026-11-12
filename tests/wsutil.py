"""Helpers for talking to a live server over /ws. Every wait has a timeout, so a bug fails fast."""

import asyncio
import json

import websockets


def connect(server):
    return websockets.connect(server.ws_url, max_size=None)


async def send(ws, **payload) -> None:
    await ws.send(json.dumps(payload))


async def recv_until(ws, msg_type: str, timeout: float = 5.0, pred=lambda m: True) -> dict:
    """Skip messages until one of msg_type that satisfies pred arrives."""
    async def wait():
        while True:
            message = json.loads(await ws.recv())
            if message["type"] == msg_type and pred(message):
                return message
    return await asyncio.wait_for(wait(), timeout)


async def collect(ws, seconds: float) -> list[dict]:
    """Every message received over the next few seconds."""
    messages = []
    loop = asyncio.get_running_loop()
    end = loop.time() + seconds
    while (left := end - loop.time()) > 0:
        try:
            messages.append(json.loads(await asyncio.wait_for(ws.recv(), left)))
        except asyncio.TimeoutError:
            break
    return messages


async def fresh_game(ws, seed: int = 1) -> dict:
    """Start a new week, paused from the first instant (so it's exactly reproducible); returns its SNAPSHOT."""
    await send(ws, action="NEW_GAME", seed=seed, running=False)
    snapshot = await recv_until(ws, "SNAPSHOT", pred=lambda m: m["seed"] == seed)
    assert not snapshot["running"]
    return snapshot


async def order(ws, **payload) -> dict:
    """Place an order and return its ORDER_RESULT."""
    await send(ws, action="ORDER", **payload)
    return await recv_until(ws, "ORDER_RESULT")


def run(coro):
    return asyncio.run(coro)
