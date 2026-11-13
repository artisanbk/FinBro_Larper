"""The /ws protocol against a live server, as the browser uses it."""

import json
import time

import pytest

from wsutil import collect, connect, fresh_game, order, recv_until, run, send


def test_snapshot_on_connect(server):
    async def body():
        async with connect(server) as ws:
            snap = await recv_until(ws, "SNAPSHOT")
            assert isinstance(snap["seed"], int)
            assert len(snap["assets"]) == 8
            assert snap["account"]["cash"] == snap["account"]["available_cash"] == 10000.0
            for asset in snap["assets"]:
                times = [c["time"] for c in asset["history"]]
                assert times == sorted(set(times)), f"{asset['symbol']}: candle times must strictly increase"
    run(body())


def test_play_and_pause(server):
    async def body():
        async with connect(server) as ws:
            await recv_until(ws, "SNAPSHOT")
            await fresh_game(ws)
            await send(ws, action="PLAY")
            assert (await recv_until(ws, "STATUS"))["running"] is True
            ticks = [m for m in await collect(ws, 1.5) if m["type"] == "TICK"]
            assert len(ticks) >= 12 and ticks[-1]["clock"] != ticks[0]["clock"]
            await send(ws, action="PAUSE")
            await recv_until(ws, "STATUS", pred=lambda m: not m["running"])
            assert not [m for m in await collect(ws, 0.5) if m["type"] == "TICK"]
    run(body())


def test_steady_tick_rate(server):
    async def body():
        async with connect(server) as ws:
            await recv_until(ws, "SNAPSHOT")
            await fresh_game(ws)
            await send(ws, action="PLAY")
            start = time.monotonic()
            ticks = [m for m in await collect(ws, 3.0) if m["type"] == "TICK"]
            rate = len(ticks) / (time.monotonic() - start)
            assert 9 <= rate <= 11, f"{rate:.1f} ticks/s"
            await send(ws, action="PAUSE")
    run(body())


def test_market_order_while_paused(server):
    async def body():
        async with connect(server) as ws:
            await recv_until(ws, "SNAPSHOT")
            await fresh_game(ws)
            await send(ws, action="SUBSCRIBE", symbol="TCHN")
            await recv_until(ws, "BOOK")
            await send(ws, action="ORDER", ticker="TCHN", side="BUY", type="MARKET", quantity=40)
            got = {}
            for m in await collect(ws, 1.0):
                got.setdefault(m["type"], m)
            result = got["ORDER_RESULT"]
            assert result["ok"] and result["message"].startswith("Bought 40 TCHN")
            assert result["fill"]["qty"] == 40 and result["fill"]["remaining"] == 0
            position = got["ACCOUNT"]["positions"][0]
            assert position["ticker"] == "TCHN" and position["qty"] == 40
            assert position["avg_cost"] == pytest.approx(result["fill"]["avg"])
            [execution] = got["ACCOUNT"]["executions"]
            assert execution["ticker"] == "TCHN" and execution["side"] == "BUY" and execution["qty"] == 40
            assert execution["price"] == pytest.approx(result["fill"]["avg"])
            assert "TCHN" in got["TICK"]["updates"], "charts update even while paused"
            assert any(t[3] for t in got["BOOK"]["trades"]), "the book push includes the player's trades"
    run(body())


def test_resting_order_shows_in_book_and_cancels(server):
    async def body():
        async with connect(server) as ws:
            await recv_until(ws, "SNAPSHOT")
            await fresh_game(ws)
            await send(ws, action="SUBSCRIBE", symbol="SPY")
            book = await recv_until(ws, "BOOK")
            price = round(book["bids"][0][0] * 0.99, 2)
            result = await order(ws, ticker="SPY", side="BUY", type="LIMIT", quantity=2, limit_price=price)
            assert result["ok"] and result["fill"] is None
            account = await recv_until(ws, "ACCOUNT")
            assert account["available_cash"] < account["cash"]  # reserved
            book = await recv_until(ws, "BOOK")
            assert any(level[0] == price and level[2] == 2 for level in book["bids"]), "shown as ours in the book"
            await send(ws, action="CANCEL", order_id=account["orders"][0]["id"])
            assert (await recv_until(ws, "ORDER_RESULT"))["ok"]
            account = await recv_until(ws, "ACCOUNT")
            assert account["orders"] == [] and account["available_cash"] == account["cash"]
    run(body())


def test_rejections_keep_the_connection_open(server):
    async def body():
        async with connect(server) as ws:
            await recv_until(ws, "SNAPSHOT")
            await fresh_game(ws)
            for payload, expected in [
                ({"ticker": "NOPE", "side": "BUY", "type": "MARKET", "quantity": 1}, "Unknown ticker"),
                ({"ticker": "TCHN", "side": "SELL", "type": "MARKET", "quantity": 3}, "Insufficient holdings"),
                ({"ticker": "TCHN", "side": "BUY", "type": "MARKET", "quantity": 1.5}, "whole number"),
                ({"ticker": "TCHN", "side": "BUY", "type": "LIMIT", "quantity": 1, "limit_price": -1}, "limit price"),
            ]:
                result = await order(ws, **payload)
                assert not result["ok"] and expected in result["message"]
            await send(ws, action="CANCEL", order_id=999999)
            assert not (await recv_until(ws, "ORDER_RESULT"))["ok"]
            await ws.send("not json")
            assert "JSON" in (await recv_until(ws, "ERROR"))["message"]
            await send(ws, action="SUBSCRIBE", symbol="NOPE")
            assert "symbol" in (await recv_until(ws, "ERROR"))["message"].lower()
            await send(ws, action="DANCE")
            assert "Unknown action" in (await recv_until(ws, "ERROR"))["message"]
            assert (await order(ws, ticker="TCHN", side="BUY", type="MARKET", quantity=1))["ok"], "still usable"
    run(body())


def test_second_client_sees_the_same_game(server):
    async def body():
        async with connect(server) as ws:
            await recv_until(ws, "SNAPSHOT")
            await fresh_game(ws)
            await order(ws, ticker="GLOB", side="BUY", type="MARKET", quantity=3)
            async with connect(server) as other:
                snap = await recv_until(other, "SNAPSHOT")
                assert snap["account"]["positions"][0]["qty"] == 3
    run(body())


def test_skip_month_plays_out_and_reports(server):
    async def body():
        async with connect(server) as ws:
            await recv_until(ws, "SNAPSHOT")
            await send(ws, action="NEW_GAME", seed=1, running=False, days=2)  # short, so the skip is quick
            snapshot = await recv_until(ws, "SNAPSHOT", pred=lambda m: m["seed"] == 1)
            assert snapshot["config"]["game_days"] == 2 and snapshot["day"] == 1 and snapshot["fast_forward"] is None
            await order(ws, ticker="TCHN", side="BUY", type="MARKET", quantity=1)
            await send(ws, action="FAST_FORWARD", until="END")
            status = await recv_until(ws, "STATUS")
            assert status["running"] and status["fast_forward"] == {"until": "END", "target_day": 3}
            tick = await recv_until(ws, "TICK")
            assert tick["day"] >= 1 and len(tick["updates"]) >= 1
            report = await recv_until(ws, "GAME_OVER", timeout=30)  # 2 days at 2 days a second; slow CI runners lag
            assert report["fees_paid"] == 5.0 and len(report["net_worth_history"]) >= 2 * 24
            assert [h["ticker"] for h in report["holdings"]] == ["TCHN"] and report["cash"] < 10000
            assert report["events"] and all(e["assets"] for e in report["events"])
            result = await order(ws, ticker="TCHN", side="BUY", type="MARKET", quantity=1)
            assert not result["ok"] and "over" in result["message"]
            await send(ws, action="NEW_GAME")
            snap = await recv_until(ws, "SNAPSHOT")
            assert snap["running"] and not snap["ended"] and snap["report"] is None
            assert snap["account"]["cash"] == 10000.0 and snap["account"]["positions"] == []
    run(body())


def test_new_game_can_pick_the_storyline(server):
    async def body():
        async with connect(server) as ws:
            await recv_until(ws, "SNAPSHOT")
            await send(ws, action="NEW_GAME", seed=3, running=False, storyline="chip_war", days=2)
            snapshot = await recv_until(ws, "SNAPSHOT", pred=lambda m: m["seed"] == 3)
            assert "chip_war" not in json.dumps(snapshot), "the storyline stays hidden while playing"
            await send(ws, action="FAST_FORWARD")
            report = await recv_until(ws, "GAME_OVER", timeout=30)  # CI's Windows runner is several times slower
            assert report["storyline"]["id"] == "chip_war" and report["storyline"]["title"] == "Chip War"
            await send(ws, action="NEW_GAME", storyline="no_such_story")
            error = await recv_until(ws, "ERROR")
            assert "storyline" in error["message"]
            await send(ws, action="NEW_GAME", days=40)
            assert "days" in (await recv_until(ws, "ERROR"))["message"]
            await send(ws, action="FAST_FORWARD", until="TOMORROW")
            assert "until" in (await recv_until(ws, "ERROR"))["message"]
    run(body())


def test_seed_determines_the_week(server):
    async def opening(seed):
        async with connect(server) as ws:
            await recv_until(ws, "SNAPSHOT")
            snapshot = await fresh_game(ws, seed=seed)
            await send(ws, action="SUBSCRIBE", symbol="BTC")
            book = await recv_until(ws, "BOOK", pred=lambda m: m["symbol"] == "BTC")
            # Candle times follow the wall clock, so compare prices only.
            history = [[(c["open"], c["close"], c["volume"]) for c in a["history"]] for a in snapshot["assets"]]
            return history, (book["bids"], book["asks"])
    first, again, other = run(opening(123)), run(opening(123)), run(opening(124))
    assert first == again, "same seed, started paused: identical week"
    assert first[0] != other[0], "a different seed generates a different history"
    # (The opening book is only the market maker's quotes around the fixed starting price,
    # so it's the same for every seed until the first tick.)
