"""Game engine: reproducibility, the player's orders and account, news, the clock."""

import pytest

import game as g
from config import FEE_PER_ORDER, GAME_TICKS, NEWS_DB, NEWS_DURATION_TICKS, STARTING_CASH, TICKS_PER_DAY
from market import PLAYER
from orderbook import BUY, SELL


def new(seed=7, running=False):
    game = g.Game(seed=seed)
    game.running = running
    return game


def place(game, ticker, side, quantity, type_="MARKET", limit_price=None):
    payload = {"ticker": ticker, "side": side, "type": type_, "quantity": quantity}
    if limit_price is not None:
        payload["limit_price"] = limit_price
    return game.place_order(payload)


def player_orders_in_book(market):
    return [o for o in market.book.orders.values() if o.owner is PLAYER]


# --- reproducibility ---

def price_path(seed, ticks=600):
    game = new(seed, running=True)
    path = []
    for _ in range(ticks):
        game.advance()
        path.append(tuple(round(m.price, 6) for m in game.markets.values()))
    return path


def test_same_seed_replays_identically():
    assert price_path(42) == price_path(42)


def test_different_seeds_differ():
    assert price_path(42) != price_path(43)


# --- market orders ---

def test_market_buy_fills_at_the_best_ask():
    game = new()
    best_ask = game.markets["TCHN"].depth(SELL)[0][0]
    ok, message, fill = place(game, "TCHN", BUY, 1)
    assert ok, message
    assert fill == {"side": BUY, "ticker": "TCHN", "qty": 1, "avg": best_ask, "remaining": 0}
    assert game.cash == pytest.approx(STARTING_CASH - best_ask - FEE_PER_ORDER)


def test_large_market_buy_slips_and_pays_one_fee():
    game = new()
    best_ask = game.markets["TCHN"].depth(SELL)[0][0]
    ok, message, fill = place(game, "TCHN", BUY, 50)
    assert ok, message
    assert fill["avg"] > best_ask  # walked up the book
    assert game.positions["TCHN"]["qty"] == 50
    assert game.fees_paid == FEE_PER_ORDER  # once per order, not per fill


def test_market_buy_is_capped_by_available_cash():
    game = new()
    ok, message, fill = place(game, "BTC", BUY, 1)  # about $42,000 with $10,000 cash
    assert ok and "of 1 BTC" in message
    assert 0 < fill["qty"] < 1
    assert 0 <= game.cash < 100


def test_out_of_cash_market_buy_is_rejected():
    game = new()
    place(game, "BTC", BUY, 1)  # spend nearly everything
    ok, message, fill = place(game, "SPY", BUY, 1000)
    assert not ok and message == "Insufficient available cash." and fill is None


def test_market_sell_needs_holdings():
    game = new()
    ok, message, _ = place(game, "TCHN", SELL, 1)
    assert not ok and "holdings" in message.lower()


# --- limit orders and reservations ---

def test_limit_buy_rests_and_reserves_cash():
    game = new()
    ok, message, fill = place(game, "GLOB", BUY, 100, "LIMIT", 40.0)
    assert ok and "placed" in message and fill is None
    assert game.reserved_cash == pytest.approx(100 * 40.0 + FEE_PER_ORDER)
    assert len(player_orders_in_book(game.markets["GLOB"])) == 1


def test_reserved_cash_is_not_spendable():
    game = new()
    place(game, "GLOB", BUY, 100, "LIMIT", 40.0)
    ok, message, _ = place(game, "GLOB", BUY, 140, "LIMIT", 45.0)
    assert not ok and "reserve" in message


def test_cancel_releases_the_reservation():
    game = new()
    place(game, "GLOB", BUY, 100, "LIMIT", 40.0)
    ok, _ = game.cancel_order(game.pending_orders[0]["id"])
    assert ok and game.reserved_cash == 0 and not player_orders_in_book(game.markets["GLOB"])
    ok, message = game.cancel_order(12345)
    assert not ok and "not found" in message.lower()


def test_marketable_limit_fills_at_the_book_price():
    game = new()
    best_ask = game.markets["GLOB"].depth(SELL)[0][0]
    ok, message, fill = place(game, "GLOB", BUY, 5, "LIMIT", round(best_ask + 0.5, 2))
    assert ok and "filled" in message
    assert fill["avg"] <= best_ask + 1e-9  # price improvement over the limit
    assert not game.pending_orders


def test_self_trade_is_prevented():
    game = new()
    place(game, "GLOB", BUY, 5, "MARKET")
    ok, _, _ = place(game, "GLOB", SELL, 5, "LIMIT", 60.0)
    assert ok
    ok, message, _ = place(game, "GLOB", BUY, 1, "LIMIT", 61.0)
    assert not ok and "own" in message


def test_holdings_under_a_resting_sell_cannot_be_sold_again():
    game = new()
    place(game, "GLOB", BUY, 5, "MARKET")
    place(game, "GLOB", SELL, 5, "LIMIT", 60.0)
    ok, message, _ = place(game, "GLOB", SELL, 1, "MARKET")
    assert not ok and "reserve" in message


def test_agents_fill_a_resting_order():
    game = new(seed=9)
    eth = game.markets["ETH"]
    ok, message, _ = place(game, "ETH", BUY, 1, "LIMIT", round(eth.mid() * 0.998, 1))
    assert ok, message
    game.running = True
    fills = []
    for _ in range(3000):
        fills += [m for m in game.advance() if m["type"] == "FILL"]
        if game.positions.get("ETH"):
            break
    assert game.positions["ETH"]["qty"] == 1
    assert fills and fills[-1]["fill"]["remaining"] == 0
    assert game.reserved_cash == 0


def test_week_end_cancels_resting_orders():
    game = new(running=True)
    place(game, "ETH", BUY, 1, "LIMIT", 100.0)
    game.tick = GAME_TICKS - 1
    out = game.advance()
    assert [m["type"] for m in out] == ["GAME_OVER", "ACCOUNT"]
    assert out[1]["orders"] == [] and not player_orders_in_book(game.markets["ETH"])
    ok, message, _ = place(game, "TCHN", BUY, 1)
    assert not ok and "over" in message


# --- fractional crypto ---

def test_crypto_trades_in_fractions():
    game = new(seed=11)
    btc = game.markets["BTC"]
    assert btc.qty_step == 0.0001 and btc.lot > 100  # agents trade ~$4,000 lots, not whole coins
    ok, message, fill = place(game, "BTC", BUY, 0.05)
    assert ok, message
    assert game.positions["BTC"]["qty"] == 0.05 and fill["qty"] == 0.05
    assert STARTING_CASH - game.cash == pytest.approx(0.05 * fill["avg"] + FEE_PER_ORDER, abs=0.01)


@pytest.mark.parametrize("ticker, quantity, expected", [
    ("BTC", 0.00005, "steps of 0.0001 BTC"),
    ("ETH", 0.0005, "steps of 0.001 ETH"),
    ("TCHN", 1.5, "whole number"),
    ("TCHN", 0, "whole number"),
    ("TCHN", True, "whole number"),
])
def test_invalid_quantities_are_rejected(ticker, quantity, expected):
    ok, message, _ = place(new(), ticker, BUY, quantity)
    assert not ok and expected in message


def test_fractional_reservations_and_partial_sells():
    game = new(seed=11)
    place(game, "BTC", BUY, 0.05)
    ok, _, fill = place(game, "BTC", SELL, 0.02, "LIMIT", game.markets["BTC"].price * 1.2)
    assert ok and fill is None
    assert game.account_message()["orders"][0]["qty"] == 0.02
    ok, message, _ = place(game, "BTC", SELL, 0.04)
    assert not ok and "reserve" in message
    ok, _, fill = place(game, "BTC", SELL, 0.03)
    assert ok and fill["qty"] == 0.03 and game.positions["BTC"]["qty"] == 0.02


def test_quantity_formatting():
    game = new()
    assert game.markets["BTC"].fmt_qty(500) == "0.05"
    assert game.markets["TCHN"].fmt_qty(1200) == "1,200"


# --- book view ---

def test_book_message_marks_player_trades_and_never_repeats_them():
    game = new()
    place(game, "TCHN", BUY, 1)
    message, seq = game.book_message("TCHN", 0)
    assert message["bids"] and message["asks"]
    assert any(trade[3] for trade in message["trades"])
    again, _ = game.book_message("TCHN", seq)
    assert again["trades"] == []


def test_snapshot_carries_seed_steps_and_volume():
    snapshot = new(seed=5).snapshot()
    assert snapshot["seed"] == 5
    assert {a["symbol"]: a["qty_step"] for a in snapshot["assets"]}["BTC"] == 0.0001
    assert all("volume" in c for a in snapshot["assets"] for c in a["history"])


# --- news and clock ---

def test_news_schedule_is_days_2_to_6_and_never_overlaps():
    import random
    for i in range(500):
        events = g._schedule_news(random.Random(i))
        ticks = [e["trigger_tick"] for e in events]
        assert len({e["headline"] for e in events}) == len(events) == 2
        assert all(TICKS_PER_DAY <= t < TICKS_PER_DAY * 6 for t in ticks)
        assert all(b - a > NEWS_DURATION_TICKS for a, b in zip(ticks, ticks[1:]))


def test_news_lifecycle():
    game = new(running=True)
    game.scheduled_news = [{**NEWS_DB[1], "trigger_tick": 1}]
    started = [m for m in game.advance() if m["type"] == "NEWS"]
    assert started and started[0]["news"]["headline"] == NEWS_DB[1]["headline"] and "move" not in started[0]["news"]
    for _ in range(NEWS_DURATION_TICKS - 1):
        game.advance()
    assert game.active_news is not None
    ended = [m for m in game.advance() if m["type"] == "NEWS"]
    assert ended and ended[0]["news"] is None and ended[0]["news_log"][0]["active"] is False
    game.fast_forward()
    assert game.snapshot()["news_log"][0]["clock"].startswith("Day 1")


def test_week_ends_after_seven_days():
    game = new(running=True)
    game.tick = GAME_TICKS - 2
    assert game.advance()[0]["type"] != "GAME_OVER"
    assert game.advance()[0]["type"] == "GAME_OVER"
    assert game.ended and game.advance() == [] and game.set_running(True)["running"] is False


@pytest.mark.parametrize("tick, label", [
    (0, "Day 1 - 09:00 AM"),
    (25 * 15, "Day 1 - 12:00 AM"),
    (600, "Day 2 - 09:00 AM"),
    (GAME_TICKS - 1, "Day 7 - 08:57 AM"),
])
def test_clock_labels(tick, label):
    assert g.clock_label(tick) == label
