import asyncio
import json
import logging
import sys
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

import models  # noqa: F401  (registers the tables on Base.metadata)
from database import Base, engine
from config import TICK_SECONDS
from game import Game

logger = logging.getLogger("finbro_larper")
# In a PyInstaller build, bundled files are unpacked to sys._MEIPASS rather than next to this module.
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
STATIC_DIR = BUNDLE_DIR / "static"

# Messages buffered per client before it's considered stuck (~30 s of ticks). A stuck client,
# e.g. a frozen background tab, is disconnected; the page reconnects and resyncs when it wakes.
SEND_QUEUE_LIMIT = 300


class Client:
    """One browser connection with its own outbound queue.

    Sending never blocks the caller, so a client that stops reading can't stall the market loop.
    """

    def __init__(self, websocket: WebSocket) -> None:
        self.websocket = websocket
        self.symbol: str | None = None  # asset whose order book this client watches
        self.trade_seq = 0              # last trade of that asset already sent
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=SEND_QUEUE_LIMIT)
        self.sender = asyncio.create_task(self._send_loop())

    async def _send_loop(self) -> None:
        try:
            while True:
                await self.websocket.send_text(await self.queue.get())
        except asyncio.CancelledError:
            raise
        except Exception:
            drop(self)  # connection is gone; the receive loop will see the disconnect

    def push(self, message: dict | str) -> None:
        text = message if isinstance(message, str) else json.dumps(message)
        try:
            self.queue.put_nowait(text)
        except asyncio.QueueFull:
            logger.warning("Client stopped reading; disconnecting it so the market keeps running")
            drop(self)


clients: set[Client] = set()
background_tasks: set[asyncio.Task] = set()


def drop(client: Client) -> None:
    if client not in clients:
        return
    clients.discard(client)
    client.sender.cancel()
    # Closing may itself wait on the stuck peer, so do it off the hot path.
    task = asyncio.create_task(_close(client.websocket))
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)


async def _close(websocket: WebSocket) -> None:
    # The websockets library aborts the connection itself if the peer never answers the close.
    with suppress(Exception):
        await websocket.close(code=1013)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Every server start is a fresh week, so rebuilding the schema loses nothing and means
    # model changes never need a migration.
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    app.state.game = Game()
    # Holding the task in this frame keeps a strong reference for the app's lifetime.
    task = asyncio.create_task(market_simulation_loop(app.state.game))
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def root():
    return RedirectResponse(url="/static/index.html")


def broadcast(message: dict) -> None:
    text = json.dumps(message)
    for client in list(clients):
        client.push(text)


def push_books(game: Game, symbol: str | None = None) -> None:
    """Send each client the order book (and new trades) of the asset it watches."""
    for client in list(clients):
        if client.symbol is not None and symbol in (None, client.symbol):
            message, client.trade_seq = game.book_message(client.symbol, client.trade_seq)
            client.push(message)


def handle_action(client: Client, game: Game, payload: dict) -> None:
    action = payload.get("action")
    if action == "SUBSCRIBE":
        symbol = payload.get("symbol")
        if not isinstance(symbol, str) or symbol not in game.markets:
            client.push({"type": "ERROR", "message": "Unknown symbol."})
            return
        client.symbol = symbol
        client.trade_seq = max(0, game.trade_seq(symbol) - 30)  # start the tape with recent trades
        message, client.trade_seq = game.book_message(symbol, client.trade_seq)
        client.push(message)
    elif action in ("PLAY", "PAUSE"):
        broadcast(game.set_running(action == "PLAY"))
    elif action in ("ORDER", "CANCEL"):
        fill = None
        if action == "ORDER":
            ok, message, fill = game.place_order(payload)
        else:
            ok, message = game.cancel_order(payload.get("order_id"))
        client.push({"type": "ORDER_RESULT", "ok": ok, "message": message, "fill": fill})
        if ok:
            broadcast(game.account_message())
            update = game.market_update()  # the order's trades, so charts move even while paused
            if update:
                broadcast(update)
            push_books(game)
    elif action == "FAST_FORWARD":
        for message in game.fast_forward():
            broadcast(message)
    elif action == "NEW_GAME":
        seed = payload.get("seed")
        running = payload.get("running", True)  # false: start paused, e.g. for an exact seeded replay
        game.new_game(running=running is not False,
                      seed=seed if isinstance(seed, int) and not isinstance(seed, bool) else None)
        for c in clients:
            c.trade_seq = 0
        broadcast(game.snapshot())  # pages re-subscribe to their asset on SNAPSHOT
    else:
        client.push({"type": "ERROR", "message": f"Unknown action: {action!r}"})


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    game: Game = websocket.app.state.game
    await websocket.accept()
    client = Client(websocket)
    clients.add(client)
    try:
        client.push(game.snapshot())
        while True:
            try:
                raw = await websocket.receive_text()
            except RuntimeError:  # we already closed this connection as stuck
                break
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                client.push({"type": "ERROR", "message": "Messages must be JSON."})
                continue
            if not isinstance(payload, dict):
                client.push({"type": "ERROR", "message": "Messages must be JSON objects."})
                continue
            handle_action(client, game, payload)
    except WebSocketDisconnect:
        pass
    finally:
        clients.discard(client)
        client.sender.cancel()


async def market_simulation_loop(game: Game) -> None:
    """Advance the game at a fixed rate on the server clock, independent of any browser.

    Nothing here awaits the network, so slow or frozen clients can't hold the market back.
    """
    loop = asyncio.get_running_loop()
    next_tick = loop.time()
    while True:
        try:
            messages = game.advance()
            for message in messages:
                broadcast(message)
            if messages:
                push_books(game)
        except Exception:
            # Never let one bad tick kill the loop; that would silently freeze the market.
            logger.exception("Market tick failed")
        next_tick += TICK_SECONDS
        delay = next_tick - loop.time()
        if delay < -1:  # far behind (e.g. the machine slept): resume pacing instead of bursting
            next_tick = loop.time()
            delay = 0
        await asyncio.sleep(max(delay, 0))
