"""Game engine: reproducibility, the player's orders and account, news, the clock."""

import pytest

import game as g
from config import (
    FEE_PER_ORDER, GAME_TICKS, INITIAL_ASSETS, NEWS_DIFFUSION_TICKS, NEWS_DURATION_TICKS, NEWS_SENTIMENT, PROFILES,
    STARTING_CASH, STORYLINES, TICKS_PER_DAY, TICKS_PER_HOUR, TICKS_PER_WEEK, WILDCARD_WINDOW, WILDCARDS,
)
from market import PLAYER
from orderbook import BUY, SELL


def new(seed=7, running=False, storyline=None, days=None):
    game = g.Game(seed=seed, storyline=storyline, **({"days": days} if days else {}))
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
    executions = game.account_message()["executions"]
    assert {(e["ticker"], e["side"]) for e in executions} == {("ETH", BUY)}
    assert sum(e["qty"] for e in executions) == pytest.approx(1)
    assert executions[-1]["time"] == eth.candle["time"], "marked on the candle it filled in"


def test_month_end_cancels_resting_orders():
    game = new(running=True)
    place(game, "ETH", BUY, 1, "LIMIT", 100.0)
    game.tick = GAME_TICKS - 1
    out = game.advance()
    assert [m["type"] for m in out] == ["GAME_OVER", "ACCOUNT"]
    assert out[1]["orders"] == [] and not player_orders_in_book(game.markets["ETH"])
    ok, message, _ = place(game, "TCHN", BUY, 1)
    assert not ok and "over" in message


# --- executions (the chart's trade marks) ---

def test_fills_are_recorded_on_their_candle():
    game = new()
    ok, message, fill = place(game, "TCHN", BUY, 3)
    assert ok, message
    assert game.account_message()["executions"] == [
        {"ticker": "TCHN", "side": BUY, "qty": 3, "price": fill["avg"], "time": game.start_unix}]
    game.running = True
    for _ in range(TICKS_PER_HOUR + 1):
        game.advance()
    ok, message, fill = place(game, "TCHN", SELL, 1)
    assert ok, message
    last = game.account_message()["executions"][-1]
    assert last == {"ticker": "TCHN", "side": SELL, "qty": 1, "price": fill["avg"], "time": game.start_unix + 3600}
    assert last["time"] == game.markets["TCHN"].candle["time"]


def test_executions_carry_fractional_quantities_and_reset_with_the_game():
    game = new(seed=11)
    ok, message, _ = place(game, "BTC", BUY, 0.0123)
    assert ok, message
    assert [e["qty"] for e in game.snapshot()["account"]["executions"]] == [0.0123]
    game.new_game(running=False)
    assert game.account_message()["executions"] == []


def test_rejected_orders_record_nothing():
    game = new()
    place(game, "TCHN", SELL, 1)          # nothing to sell
    place(game, "TCHN", BUY, 1, "LIMIT", 1.0)  # rests without filling
    assert game.account_message()["executions"] == []


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

def check_event(event, where):
    targets = {"GLOBAL", *PROFILES, *(a["symbol"] for a in INITIAL_ASSETS)}
    assert event["impact"] in ("BOOM", "CRASH") and event["headline"] and event["body"], where
    assert event["effects"] and set(event["effects"]) <= targets, f"{where}: unknown target in {event['effects']}"
    assert all(move != 0 for move in event["effects"].values()), where


def test_storylines_and_wildcards_are_well_formed():
    assert len({story["id"] for story in STORYLINES}) == len(STORYLINES) >= 5
    for story in STORYLINES:
        assert story["title"] and story["summary"] and len(story["events"]) >= 4
        windows = [beat["window"] for beat in story["events"]]
        assert all(0 < lo < hi < 1 for lo, hi in windows), story["id"]
        assert all(a[1] <= b[0] for a, b in zip(windows, windows[1:])), f"{story['id']}: windows overlap or are out of order"
        assert story["events"][0].get("chance", 1) == 1, f"{story['id']}: the opening beat always happens"
        for beat in story["events"]:
            assert 0 < beat.get("chance", 1) <= 1
            for event in beat.get("variants", [beat]):
                check_event(event, story["id"])
    for card in WILDCARDS:
        check_event(card, "wildcard")
    assert any(card.get("rumor") for card in WILDCARDS) and not all(card.get("rumor") for card in WILDCARDS)


def test_news_breaks_in_order_inside_its_windows():
    import random
    for story in STORYLINES:
        headlines = {v["headline"]: beat["window"] for beat in story["events"] for v in beat.get("variants", [beat])}
        for i in range(200):
            events = g.plan_news(story, random.Random(i), GAME_TICKS)
            ticks = [e["trigger_tick"] for e in events]
            assert ticks == sorted(ticks) and all(b - a > NEWS_DURATION_TICKS for a, b in zip(ticks, ticks[1:]))
            assert ticks[-1] + NEWS_DURATION_TICKS < GAME_TICKS, "the last event plays out before the week ends"
            story_events = [e for e in events if e["headline"] in headlines]
            assert 1 <= len(events) - len(story_events) <= 2, "one or two wildcards"
            for e in events:
                lo, hi = headlines.get(e["headline"], WILDCARD_WINDOW)
                assert lo * GAME_TICKS <= e["trigger_tick"] < hi * GAME_TICKS, e["headline"]
            order = [list(headlines).index(e["headline"]) for e in story_events]
            assert order == sorted(order), "the story's beats keep their order"


def test_the_same_storyline_plays_out_differently():
    import random
    story = g.STORYLINES_BY_ID["crypto_winter"]
    runs = [g.plan_news(story, random.Random(i), GAME_TICKS) for i in range(100)]
    sequences = {tuple(e["headline"] for e in run) for run in runs}
    assert len(sequences) > 20, "beats branch, get skipped, and wildcards vary"
    endings = {run[-1]["headline"] for run in runs}
    assert len(endings) >= 3
    hack = [e["effects"]["CRYPTO"] for run in runs for e in run if e["headline"] == "Major Crypto Exchange Hacked"]
    assert len(hack) == 100, "the opening beat always happens"
    assert min(hack) < -0.18 * 0.8 and max(hack) > -0.18 * 1.2 and len({round(m, 6) for m in hack}) == 100, "sizes vary"
    assert all(-0.18 * 1.4 <= m <= -0.18 * 0.6 for m in hack)


def test_rumors_excite_traders_but_leave_values_alone():
    import math
    game = new(seed=3)
    rumor = {**g._instance(next(c for c in WILDCARDS if c["headline"].startswith("Reports Say TechNet")), 1.0),
             "trigger_tick": 1}
    game.active_news = rumor
    assert game._news_effect(game.markets["TCHN"]) == (NEWS_SENTIMENT, True)
    assert game._news_effect(game.markets["GLOB"]) == (0.0, False)
    for seed in range(40):
        game = g.Game(seed=seed)
        for rumor in (e for e in game.scheduled_news if e["rumor"]):
            t = rumor["trigger_tick"]
            for sym in rumor["effects"]:
                if sym in game.markets:
                    m = game.markets[sym]
                    shift = math.log(m.true_value[t + NEWS_DIFFUSION_TICKS] / m.true_value[t - 1])
                    assert abs(shift) < 0.04, f"seed {seed}: rumor moved {sym}'s value {shift:+.1%}"


def test_the_seed_picks_the_storyline():
    picks = {s: g.Game(seed=s).storyline["id"] for s in range(30)}
    assert set(picks.values()) == set(g.STORYLINES_BY_ID), "every storyline comes up"
    assert g.Game(seed=5).storyline["id"] == picks[5]
    assert g.Game(seed=5, storyline="chip_war").storyline["id"] == "chip_war"


def test_effects_add_up_per_asset():
    effects = {"STOCK": -0.05, "TCHN": 0.08, "GLOBAL": 0.01}
    assert g.asset_move(effects, "TCHN", "STOCK") == pytest.approx(0.04)
    assert g.asset_move(effects, "GLOB", "STOCK") == pytest.approx(-0.04)
    assert g.asset_move(effects, "BTC", "CRYPTO") == pytest.approx(0.01)
    assert g.asset_move({"REIT": 0.03}, "BTC", "CRYPTO") == 0


def test_a_symbol_event_moves_only_that_symbol():
    import math
    game = new(seed=3, storyline="chip_war")
    [deal] = [e for e in game.scheduled_news if e["headline"] == "TechNet Locks In Exclusive Chip Supply"]
    t = deal["trigger_tick"]
    for sym, m in game.markets.items():
        shift = math.log(m.true_value[t + NEWS_DIFFUSION_TICKS] / m.true_value[t - 1])
        if sym == "TCHN":
            assert shift > 0.04, f"TCHN value moved {shift:+.1%}"  # at least 0.6 x 9%, less noise
        else:
            assert abs(shift) < 0.04, f"{sym} value moved {shift:+.1%} on a TCHN-only event"
    game.active_news = deal
    assert game._news_effect(game.markets["TCHN"]) == (NEWS_SENTIMENT, True)
    assert game._news_effect(game.markets["GLOB"]) == (0.0, False)
    [shortage] = [e for e in game.scheduled_news if e["headline"] == "Tech Sector Faces Chip Shortage"]  # always first
    game.active_news = shortage
    assert game._news_effect(game.markets["QQQ"]) == (-NEWS_SENTIMENT, True)  # its own symbol effect
    assert game._news_effect(game.markets["SPY"]) == (0.0, False)


def test_news_lifecycle():
    game = new(running=True)
    event = {**g._instance(STORYLINES[0]["events"][0], 1.0), "trigger_tick": 1}
    game.scheduled_news = [event]
    started = [m for m in game.advance() if m["type"] == "NEWS"]
    assert started
    news = started[0]["news"]
    assert news["headline"] == event["headline"] and news["impact"] == event["impact"]
    assert news["targets"] == [{"target": "CRYPTO", "direction": "DOWN"}]
    assert not {"effects", "move", "rumor"} & set(news), "how far it moves, and whether it's a rumor, stay on the server"
    for _ in range(NEWS_DURATION_TICKS - 1):
        game.advance()
    assert game.active_news is not None
    ended = [m for m in game.advance() if m["type"] == "NEWS"]
    assert ended and ended[0]["news"] is None and ended[0]["news_log"][0]["active"] is False
    game._end_game()
    assert game.snapshot()["news_log"][0]["clock"].startswith("Day 1")


def test_the_storyline_stays_hidden_until_the_report():
    game = new(storyline="housing_squeeze")
    assert "housing_squeeze" not in str(game.snapshot()) and "Housing Squeeze" not in str(game.snapshot())
    game._end_game()
    assert game.report["storyline"] == {"id": "housing_squeeze", "title": "Housing Squeeze",
                                        "summary": g.STORYLINES_BY_ID["housing_squeeze"]["summary"]}
    assert game.snapshot()["report"]["storyline"]["title"] == "Housing Squeeze"


def test_month_ends_after_28_days():
    game = new(running=True)
    game.tick = GAME_TICKS - 2
    assert game.advance()[0]["type"] != "GAME_OVER"
    assert game.advance()[0]["type"] == "GAME_OVER"
    assert game.ended and game.advance() == [] and game.set_running(True)["running"] is False


@pytest.mark.parametrize("tick, label", [
    (0, "Day 1 - 09:00 AM"),
    (25 * 15, "Day 1 - 12:00 AM"),
    (600, "Day 2 - 09:00 AM"),
    (4200, "Day 8 - 09:00 AM"),
    (GAME_TICKS - 1, "Day 28 - 08:57 AM"),
])
def test_clock_labels(tick, label):
    assert g.clock_label(tick) == label


# --- skipping ahead (fast-forward) ---

def run_skip(game, until, max_frames=10_000):
    """Start a skip and run frames until it stops; returns every message, frame by frame."""
    frames = [game.fast_forward(until)]
    while game.ff is not None and len(frames) < max_frames:
        frames.append(game.frame())
    return frames


def test_skip_week_plays_the_market_to_the_next_week_and_pauses():
    game = new(seed=4, running=True)
    for _ in range(100):
        game.advance()
    frames = run_skip(game, "WEEK")
    assert frames[0] == [game.status_message() | {"running": True, "fast_forward": {"until": "WEEK", "target_day": 8}}]
    assert game.tick == TICKS_PER_WEEK and not game.running and not game.ended and game.day() == 8
    assert frames[-1][-1] == {"type": "STATUS", "running": False, "ended": False, "fast_forward": None}
    assert all(sum(m["type"] == "TICK" for m in f) <= 1 for f in frames), "one TICK per frame"
    assert len(frames) < (TICKS_PER_WEEK - 100) / 50, "it batches many ticks per frame"
    headlines = [m["news"]["headline"] for f in frames for m in f if m["type"] == "NEWS" and m["news"]]
    assert headlines == [e["headline"] for e in game.scheduled_news if 100 < e["trigger_tick"] <= TICKS_PER_WEEK]
    assert headlines, "news breaks during the skip"
    assert game.frame() == [], "paused at the boundary"


def test_a_skip_plays_exactly_like_normal_ticks():
    a, b = new(seed=12, running=True), new(seed=12)
    for _ in range(TICKS_PER_WEEK):
        a.advance()
    run_skip(b, "WEEK")
    assert [m.price for m in a.markets.values()] == [m.price for m in b.markets.values()]
    assert a.net_worth_history == b.net_worth_history


def test_skipping_sends_every_candle_so_the_chart_has_no_gaps():
    game = new(seed=5)
    chart = {sym: [dict(c) for c in m.history] + [dict(m.candle)] for sym, m in game.markets.items()}
    for frame in run_skip(game, "WEEK"):
        for message in frame:
            if message["type"] != "TICK":
                continue
            for sym, update in message["updates"].items():
                for candle in update.get("completed", []) + [update["candle"]]:
                    history = chart[sym]
                    if history[-1]["time"] == candle["time"]:
                        history[-1] = candle
                    elif candle["time"] > history[-1]["time"]:
                        history.append(candle)
    for sym, m in game.markets.items():
        server = m.history + [m.candle]
        assert [c["time"] for c in chart[sym]] == [c["time"] for c in server], sym
        assert [c["close"] for c in chart[sym]] == pytest.approx([c["close"] for c in server]), sym
        assert [c["volume"] for c in chart[sym]] == pytest.approx([c["volume"] for c in server]), sym


def test_resting_orders_fill_during_a_skip():
    game = new(seed=9)
    eth = game.markets["ETH"]
    ok, message, _ = place(game, "ETH", BUY, 1, "LIMIT", round(eth.mid() * 0.99, 1))
    assert ok, message
    frames = run_skip(game, "WEEK")
    fills = [m for f in frames for m in f if m["type"] == "FILL"]
    assert fills and game.positions["ETH"]["qty"] == 1
    assert all(sum(m["type"] == "ACCOUNT" for m in f) <= 1 for f in frames), "one ACCOUNT per frame at most"


def test_pausing_cancels_a_skip():
    game = new(seed=4)
    game.fast_forward("END")
    game.frame()
    assert game.ff is not None and game.status_message()["fast_forward"] == {"until": "END", "target_day": 29}
    assert game.set_running(False) == {"type": "STATUS", "running": False, "ended": False, "fast_forward": None}
    tick = game.tick
    assert game.frame() == [] and game.tick == tick
    game.set_running(True)
    game.frame()
    assert game.tick == tick + 1, "back to normal speed"


def test_skip_month_plays_out_the_rest_and_ends():
    game = new(seed=6, days=2)
    frames = run_skip(game, "END")
    over = [m for f in frames for m in f if m["type"] == "GAME_OVER"]
    assert over and game.ended and game.tick == 2 * TICKS_PER_DAY and game.ff is None
    assert game.fast_forward("WEEK") == [] and game.frame() == []


def test_skip_week_in_the_last_week_skips_to_the_end():
    game = new(seed=6, days=8)
    game.tick = TICKS_PER_WEEK + 10
    game.fast_forward("WEEK")
    assert game.ff == {"until": "END", "target_tick": 8 * TICKS_PER_DAY}


def test_shorter_games_scale_the_story_and_the_clock():
    game = new(seed=6, days=1)
    assert game.total_ticks == TICKS_PER_DAY and game.snapshot()["config"]["game_days"] == 1
    assert all(e["trigger_tick"] < TICKS_PER_DAY for e in game.scheduled_news)
    assert len(game.markets["TCHN"].true_value) == TICKS_PER_DAY + 1


# --- the report: holdings and how prices reacted ---

def test_report_lists_holdings_at_final_prices():
    game = new(seed=8)
    place(game, "TCHN", BUY, 2)
    place(game, "BTC", BUY, 0.05)
    game.running = True
    for _ in range(50):
        game.advance()
    out = game._end_game()
    report = out[0]
    holdings = {h["ticker"]: h for h in report["holdings"]}
    assert set(holdings) == {"BTC", "TCHN"}
    btc = holdings["BTC"]
    assert btc["qty"] == 0.05 and btc["name"] == "Bitcoin"
    assert btc["value"] == pytest.approx(0.05 * game.markets["BTC"].price, abs=0.01)
    assert btc["pl"] == pytest.approx(btc["value"] - 0.05 * btc["avg_cost"], abs=0.01)
    assert btc["pl_pct"] == pytest.approx(btc["pl"] / (0.05 * btc["avg_cost"]) * 100, abs=0.01)
    assert report["cash"] + sum(h["value"] for h in holdings.values()) == pytest.approx(report["net_worth"], abs=0.02)


def test_report_in_cash_has_no_holdings():
    game = new()
    report = game._end_game()[0]
    assert report["holdings"] == [] and report["cash"] == STARTING_CASH == report["net_worth"]


def test_report_shows_how_prices_reacted_to_each_headline():
    game = new(seed=21, storyline="chip_war", days=7)
    run_skip(game, "END")
    events = game.report["events"]
    assert [e["headline"] for e in events] == [e["headline"] for e in game.scheduled_news]
    shortage = events[0]
    assert shortage["headline"] == "Tech Sector Faces Chip Shortage" and shortage["impact"] == "CRASH"
    assert {a["symbol"] for a in shortage["assets"]} == {"TCHN", "GLOB", "QQQ"}, "only what it moves"
    for a in shortage["assets"]:
        hours = [h for h, _ in a["path"]]
        assert hours == list(range(-6, 25)), "6 hours before to 24 after"
        assert a["expected"] < 0 and a["at_6h"] < 0, f"{a['symbol']} fell with the news"
        assert a["at_2h"] == dict(a["path"])[2] and a["at_24h"] == dict(a["path"])[24]
        assert abs(a["peak"]) >= max(abs(p) for h, p in a["path"] if h >= 0) - 1e-9
        assert a["volume_x"] > 1, "news brings volume"
        assert abs(dict(a["path"])[-6]) < 0.05, "before the headline, prices hadn't moved much yet"
    tchn = next(a for a in shortage["assets"] if a["symbol"] == "TCHN")
    assert tchn["expected"] == pytest.approx(next(e for e in game.scheduled_news if e["headline"] == shortage["headline"])["effects"]["STOCK"], abs=1e-5)


def test_report_reveals_rumors():
    for seed in range(60):
        game = new(seed=seed, days=7)
        if any(e["rumor"] for e in game.scheduled_news):
            break
    run_skip(game, "END")
    rumors = [e for e in game.report["events"] if e["rumor"]]
    assert rumors and all(a["expected"] == 0 for e in rumors for a in e["assets"])
    assert all("rumor" not in entry for entry in game.news_log), "only the report says so"


def test_an_event_near_the_end_has_a_shorter_window():
    game = new(seed=3, days=1)
    game.scheduled_news = [{**g._instance(STORYLINES[0]["events"][0], 1.0), "trigger_tick": TICKS_PER_DAY - 3 * TICKS_PER_HOUR}]
    run_skip(game, "END")
    [event] = game.report["events"]
    assert all(max(h for h, _ in a["path"]) <= 3 and a["at_24h"] is None for a in event["assets"])
