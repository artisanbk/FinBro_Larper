"""Behaviour of the agent market over whole simulated weeks.

Guards the calibration: if a change to agents or profiles breaks price discovery (prices stop
tracking the true value, books empty out, news stops moving markets), these fail.
Seeds are fixed, so results are deterministic.
"""

import math
import statistics

import pytest

import game as g
from config import NEWS_DURATION_TICKS, PROFILES
from orderbook import BUY, SELL

# (seed, storyline): the storylines with the biggest moves, including a symbol-only event (chip_war)
# and large REIT moves (housing_squeeze), the least active market.
WEEKS = ((1000, "crypto_winter"), (1001, "chip_war"), (1002, "housing_squeeze"))


def simulate(seed, storyline=None, days=7):
    # Week-long games keep the suite quick; a storyline scales to the game's length, so a week
    # packs a month's events closer together, which is the harder case.
    game = g.Game(seed=seed, storyline=storyline, days=days)
    game.running = True
    stats = {sym: {"dev": [], "spread": [], "empty": 0} for sym in game.markets}
    before = {}
    reactions = []  # (symbol, headline, price move, true-value move) over each event's window
    for _ in range(game.total_ticks - 1):
        game.advance()
        t = game.tick
        for sym, m in game.markets.items():
            s = stats[sym]
            s["dev"].append(abs(math.log(m.price / m.true_value[t])))
            bid, ask = m.book.best(BUY), m.book.best(SELL)
            if bid is None or ask is None:
                s["empty"] += 1
            else:
                s["spread"].append((ask - bid) / ((ask + bid) / 2) * 1e4)
            for event in game.scheduled_news:
                start = event["trigger_tick"]
                if event["rumor"] or not g.asset_move(event["effects"], sym, m.type):
                    continue
                if t == start - 1:
                    before[(sym, start)] = (m.price, m.true_value[t])
                elif t == start + NEWS_DURATION_TICKS and (sym, start) in before:
                    price0, value0 = before[(sym, start)]
                    reactions.append((sym, event["headline"], m.price / price0 - 1, m.true_value[t] / value0 - 1))
    return game, stats, reactions


@pytest.fixture(scope="module")
def weeks():
    return [simulate(seed, storyline) for seed, storyline in WEEKS]


def test_prices_track_the_true_value(weeks):
    for game, stats, _ in weeks:
        for sym, s in stats.items():
            mean_dev = statistics.mean(s["dev"])
            assert mean_dev < 0.025, f"seed {game.seed} {sym}: price strays {mean_dev:.1%} from value on average"


def test_books_never_empty(weeks):
    for game, stats, _ in weeks:
        for sym, s in stats.items():
            assert s["empty"] == 0, f"seed {game.seed} {sym}: one side of the book was empty for {s['empty']} ticks"


def test_spreads_are_near_the_market_makers_quote(weeks):
    for game, stats, _ in weeks:
        for sym, s in stats.items():
            target = PROFILES[game.markets[sym].type].spread_bps
            median = statistics.median(s["spread"])
            assert 0.2 * target <= median <= 2.0 * target, f"seed {game.seed} {sym}: median spread {median:.1f} bps vs {target}"


def test_big_news_moves_prices_like_it_moves_value(weeks):
    checked = 0
    for game, _, reactions in weeks:
        for sym, headline, price_move, value_move in reactions:
            if abs(value_move) < 0.05:
                continue  # small shifts get lost in normal volatility
            checked += 1
            assert math.copysign(1, price_move) == math.copysign(1, value_move), \
                f"seed {game.seed} {sym} '{headline}': price {price_move:+.1%} vs value {value_move:+.1%}"
            assert 0.5 <= price_move / value_move <= 1.6, \
                f"seed {game.seed} {sym} '{headline}': price {price_move:+.1%} vs value {value_move:+.1%}"
    assert checked >= 3, "the seeds should include some big news events"
