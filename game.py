"""Server-side game engine: clock, news, markets and the player's account.

The server is authoritative: the browser renders what it receives over /ws and sends actions.
Each asset is a market.Market where agents trade through an order book; the player's orders
go through the same book. Exogenous inputs (the news schedule and each asset's true-value path)
are generated from the game seed at the start of the week; everything else is simulated live.

Account state (cash, fees, positions, orders) and completed candles live in SQLite;
markets, the clock and news live in memory and reset with each game.
"""

import math
import random
import time
from collections import defaultdict
from datetime import datetime, timezone

from config import (
    FEE_PER_ORDER, GAME_DAYS, GAME_TICKS, HISTORY_CANDLES, INITIAL_ASSETS, LOT_NOTIONAL, MARKET_ORDER_BAND,
    NEWS_DB, NEWS_DURATION_TICKS, NEWS_PER_GAME, NEWS_SENTIMENT, PORTFOLIO_ID, PROFILES,
    STARTING_CASH, TICKS_PER_DAY, TICKS_PER_HOUR,
)
from database import SessionLocal
from market import PLAYER, Market, true_value_path
from models import Candle, Order, Portfolio, Position
from orderbook import BUY, SELL


def money(value: float) -> str:
    return f"-${-value:,.2f}" if value < 0 else f"${value:,.2f}"


def clock_label(tick: int) -> str:
    """In-game clock: each day runs 24 in-game hours starting at 9 AM."""
    total_hours = tick // TICKS_PER_HOUR
    day = total_hours // 24 + 1
    hour = (total_hours % 24 + 9) % 24
    minutes = (tick % TICKS_PER_HOUR) * 60 // TICKS_PER_HOUR
    return f"Day {day} - {hour % 12 or 12:02d}:{minutes:02d} {'PM' if hour >= 12 else 'AM'}"


def _round_candle(candle: dict) -> dict:
    return {k: (v if k in ("time", "volume") else round(v, 4)) for k, v in candle.items()}


def _generate_history(price: float, start_unix: int, qty_step: float, rng: random.Random) -> list[dict]:
    """Random-walk hourly candles ending just before start_unix, scaled to close at price."""
    raw = []
    p = 1.0
    for _ in range(HISTORY_CANDLES):
        open_ = p
        close = p * (1 + (rng.random() - 0.48) * 0.02)
        high = max(open_, close) * (1 + rng.random() * 0.01)
        low = min(open_, close) * (1 - rng.random() * 0.01)
        raw.append((open_, high, low, close))
        p = close
    scale = price / p
    lot_qty = max(1, round(LOT_NOTIONAL / price / qty_step)) * qty_step
    return [
        {"time": start_unix - (HISTORY_CANDLES - i) * 3600, "open": o * scale, "high": h * scale,
         "low": lo * scale, "close": c * scale, "volume": round(lot_qty * rng.randint(20, 60), 6)}
        for i, (o, h, lo, c) in enumerate(raw)
    ]


def _schedule_news(rng: random.Random) -> list[dict]:
    """Pick this week's events, triggering on days 2-6 and never overlapping one another."""
    picks = rng.sample(NEWS_DB, NEWS_PER_GAME)
    while True:
        ticks = sorted(rng.randint(TICKS_PER_DAY, TICKS_PER_DAY * 6 - 1) for _ in picks)
        if all(later - earlier > NEWS_DURATION_TICKS for earlier, later in zip(ticks, ticks[1:])):
            return [{**news, "trigger_tick": tick} for news, tick in zip(picks, ticks)]


class Game:
    """One 7-day trading week. Methods are synchronous and return messages to broadcast."""

    def __init__(self, seed: int | None = None) -> None:
        self.new_game(running=False, seed=seed)

    # --- lifecycle ---

    def new_game(self, running: bool, seed: int | None = None) -> None:
        # Same seed + same player actions at the same ticks = the same week.
        self.seed = seed if seed is not None else random.randrange(2**31)
        self.tick = 0
        self.running = running
        self.ended = False
        self.report: dict | None = None
        self.start_unix = int(time.time()) // 3600 * 3600
        self.active_news: dict | None = None  # the NEWS_DB entry currently live
        self.news_until = 0
        self.news_log: list[dict] = []        # public record of this week's headlines, oldest first
        self.scheduled_news = _schedule_news(random.Random(f"{self.seed}:news"))

        self.markets: dict[str, Market] = {}
        for spec in INITIAL_ASSETS:
            symbol, profile = spec["symbol"], PROFILES[spec["type"]]
            events = [n for n in self.scheduled_news if n["target"] in ("GLOBAL", spec["type"])]
            value_path = true_value_path(spec["price"], profile, events,
                                         random.Random(f"{self.seed}:{symbol}:value"), GAME_TICKS)
            rng = random.Random(f"{self.seed}:{symbol}:agents")
            history = _generate_history(spec["price"], self.start_unix, spec["qty_step"], rng)
            self.markets[symbol] = Market(spec, profile, value_path, rng, self.start_unix, history)

        self.player_orders: dict[int, tuple[str, int]] = {}  # DB order id -> (symbol, book order id)
        self._reset_account()
        self.net_worth_history = [round(self.net_worth(), 2)]

    def set_running(self, running: bool) -> dict:
        if not self.ended:
            self.running = running
        return self.status_message()

    def fast_forward(self) -> list[dict]:
        return [] if self.ended else self._end_game()

    def _end_game(self) -> list[dict]:
        self.ended = True
        self.running = False
        self._clear_news()
        self._cancel_resting_orders()
        net_worth = round(self.net_worth(), 2)
        self.net_worth_history.append(net_worth)
        self.report = {
            "net_worth": net_worth,
            "profit": round(net_worth - STARTING_CASH, 2),
            "fees_paid": round(self.fees_paid, 2),
            "net_worth_history": self.net_worth_history,
        }
        return [{"type": "GAME_OVER", **self.report}, self.account_message()]

    # --- simulation ---

    def advance(self) -> list[dict]:
        """Run one tick of the game loop."""
        if not self.running or self.ended:
            return []
        self.tick += 1
        if self.tick >= GAME_TICKS:
            return self._end_game()

        messages = self._update_news()
        period = self.start_unix + (self.tick // TICKS_PER_HOUR) * 3600
        for market in self.markets.values():
            market.period = period
            sentiment, excited = self._news_effect(market.type)
            market.step(self.tick, sentiment, excited)

        self._save_candles()
        if self.tick % TICKS_PER_HOUR == 0:
            self.net_worth_history.append(round(self.net_worth(), 2))
        messages.append({
            "type": "TICK",
            "clock": clock_label(self.tick),
            "updates": self._collect_updates(),
            "net_worth": round(self.net_worth(), 2),
        })
        messages.extend(self._settle_resting_fills())
        return messages

    def market_update(self) -> dict | None:
        """A TICK-shaped message for trades made between ticks, or None if nothing traded."""
        updates = self._collect_updates()
        if not updates:
            return None
        return {"type": "TICK", "clock": clock_label(min(self.tick, GAME_TICKS - 1)),
                "updates": updates, "net_worth": round(self.net_worth(), 2)}

    def _collect_updates(self) -> dict[str, dict]:
        """Assets that traded since the last report (including between ticks, by the player)."""
        updates = {}
        for symbol, market in self.markets.items():
            if market.traded:
                market.traded = False
                updates[symbol] = {"price": round(market.price, 4), "candle": _round_candle(market.candle)}
        return updates

    def _news_effect(self, asset_type: str) -> tuple[float, bool]:
        news = self.active_news
        if news is None or news["target"] not in ("GLOBAL", asset_type):
            return 0.0, False
        return (NEWS_SENTIMENT if news["impact"] == "BOOM" else -NEWS_SENTIMENT), True

    def _update_news(self) -> list[dict]:
        messages = []
        if self.active_news is not None and self.tick >= self.news_until:
            self._clear_news()
            messages.append(self.news_message())
        for news in self.scheduled_news:
            if news["trigger_tick"] == self.tick:
                self._clear_news()
                self.active_news = news
                self.news_until = self.tick + NEWS_DURATION_TICKS
                self.news_log.append({
                    "id": len(self.news_log) + 1,
                    **{k: news[k] for k in ("headline", "body", "target", "impact")},
                    "clock": clock_label(self.tick),
                    "active": True,
                })
                messages.append(self.news_message())
        return messages

    def _clear_news(self) -> None:
        self.active_news = None
        for entry in self.news_log:
            entry["active"] = False

    def _save_candles(self) -> None:
        completed = [(m.symbol, c) for m in self.markets.values() for c in m.completed]
        if not completed:
            return
        for market in self.markets.values():
            market.completed = []
        with SessionLocal() as db:
            for symbol, c in completed:
                db.add(Candle(
                    ticker=symbol,
                    timestamp=datetime.fromtimestamp(c["time"], timezone.utc).replace(tzinfo=None),
                    open_price=c["open"], high_price=c["high"], low_price=c["low"], close_price=c["close"],
                    volume=c["volume"],
                ))
            db.commit()

    # --- account ---

    def _reset_account(self) -> None:
        with SessionLocal() as db:
            for model in (Order, Position, Candle, Portfolio):
                db.query(model).delete()
            db.add(Portfolio(id=PORTFOLIO_ID, cash_balance=STARTING_CASH, total_fees_paid=0.0))
            db.commit()
        self._load_account()

    def _load_account(self) -> None:
        """Refresh the in-memory read model from the database (the source of truth).

        "units" are integer multiples of the asset's qty_step (what the engine uses);
        "qty" is shares/coins (what people see).
        """
        with SessionLocal() as db:
            portfolio = db.get(Portfolio, PORTFOLIO_ID)
            assert portfolio is not None
            self.cash: float = portfolio.cash_balance
            self.fees_paid: float = portfolio.total_fees_paid
            self.positions = {
                p.ticker: {"units": p.qty, "qty": self.markets[p.ticker].qty(p.qty), "avg_cost": p.average_cost}
                for p in db.query(Position).filter(Position.qty > 0).order_by(Position.ticker)
            }
            self.pending_orders = [
                {"id": o.id, "ticker": o.ticker, "side": o.side, "units": o.qty, "filled_units": o.filled_qty,
                 "limit_price": o.limit_price}
                for o in db.query(Order).filter(Order.status == "PENDING").order_by(Order.id)
            ]
        # Resting orders reserve what they could spend or deliver, so a fill can always settle.
        self.reserved_cash = sum(
            self.markets[o["ticker"]].qty(o["units"] - o["filled_units"]) * o["limit_price"]
            + (FEE_PER_ORDER if o["filled_units"] == 0 else 0)
            for o in self.pending_orders if o["side"] == BUY
        )
        self.reserved_units: dict[str, int] = defaultdict(int)
        for o in self.pending_orders:
            if o["side"] == SELL:
                self.reserved_units[o["ticker"]] += o["units"] - o["filled_units"]

    def net_worth(self) -> float:
        return self.cash + sum(p["qty"] * self.markets[t].price for t, p in self.positions.items())

    def _apply_fills(self, db, fills: list[tuple[int, str, float, int]]) -> dict[int, dict]:
        """Settle the player's fills (ref, side, price, units) into the database, per order."""
        by_order: dict[int, list[tuple[float, int]]] = defaultdict(list)
        sides: dict[int, str] = {}
        for ref, side, price, units in fills:
            by_order[ref].append((price, units))
            sides[ref] = side
        portfolio = db.get(Portfolio, PORTFOLIO_ID)
        summary = {}
        for ref, parts in by_order.items():
            order = db.get(Order, ref)
            market = self.markets[order.ticker]
            units = sum(u for _, u in parts)
            qty = market.qty(units)
            notional = sum(price * market.qty(u) for price, u in parts)
            if not order.fees:
                order.fees = FEE_PER_ORDER
                portfolio.cash_balance -= FEE_PER_ORDER
                portfolio.total_fees_paid += FEE_PER_ORDER
            position = db.query(Position).filter(Position.ticker == order.ticker).first()
            if sides[ref] == BUY:
                portfolio.cash_balance -= notional
                if position is None:
                    position = Position(ticker=order.ticker, qty=0, average_cost=0.0)
                    db.add(position)
                held = market.qty(position.qty)
                position.average_cost = (held * position.average_cost + notional) / (held + qty)
                position.qty += units
            else:
                portfolio.cash_balance += notional
                position.qty -= units
                if position.qty == 0:
                    db.delete(position)
            previous = market.qty(order.filled_qty)
            order.avg_fill_price = ((order.avg_fill_price or 0.0) * previous + notional) / (previous + qty)
            order.filled_qty += units
            if order.order_type == "LIMIT" and order.filled_qty == order.qty:
                order.status = "FILLED"
                self.player_orders.pop(ref, None)
            db.flush()
            summary[ref] = {"order": order, "units": units, "avg": notional / qty}
        return summary

    def _settle_resting_fills(self) -> list[dict]:
        """Settle fills agents made against the player's resting limit orders this tick."""
        fills = [f for m in self.markets.values() for f in m.drain_player_fills()]
        if not fills:
            return []
        messages = []
        with SessionLocal() as db:
            for ref, info in self._apply_fills(db, fills).items():
                o = info["order"]
                market = self.markets[o.ticker]
                left = o.qty - o.filled_qty
                status = "filled" if left == 0 else f"{market.fmt_qty(left)} left"
                messages.append({
                    "type": "FILL",
                    "fill": {"side": o.side, "ticker": o.ticker, "qty": market.qty(info["units"]),
                             "avg": round(info["avg"], 4), "remaining": market.qty(left)},
                    "message": f"Limit {o.side} {o.ticker}: {market.fmt_qty(info['units'])} filled at "
                               f"{money(info['avg'])} ({status}).",
                })
            db.commit()
        self._load_account()
        messages.append(self.account_message())
        return messages

    def place_order(self, payload: dict) -> tuple[bool, str, dict | None]:
        """Returns (ok, message, fill); fill summarizes what executed immediately, if anything."""
        if self.ended:
            return False, "The trading week is over. Start a new game to keep trading.", None
        ticker = payload.get("ticker")
        side = payload.get("side")
        order_type = payload.get("type")
        quantity = payload.get("quantity")
        limit_price = payload.get("limit_price")

        market = self.markets.get(ticker) if isinstance(ticker, str) else None
        if market is None:
            return False, "Unknown ticker.", None
        if side not in (BUY, SELL):
            return False, "Side must be BUY or SELL.", None
        if order_type not in ("MARKET", "LIMIT"):
            return False, "Order type must be MARKET or LIMIT.", None
        units = None
        if not isinstance(quantity, bool) and isinstance(quantity, (int, float)) and math.isfinite(quantity):
            units = market.units(quantity)
        if units is None:
            if market.qty_step == 1:
                return False, "Enter a whole number of shares greater than zero.", None
            return False, f"Enter a quantity in steps of {market.fmt_qty(1)} {ticker}.", None

        if order_type == "LIMIT":
            if (isinstance(limit_price, bool) or not isinstance(limit_price, (int, float))
                    or not math.isfinite(limit_price) or market.to_ticks(limit_price) < 1):
                return False, "Enter a limit price greater than zero.", None
            limit = market.to_ticks(limit_price)
            limit_price = market.to_price(limit)  # snapped to the asset's tick size
        else:
            limit = market.band_limit(side)

        # Self-trade prevention: don't let the player's order hit their own resting order.
        for o in self.pending_orders:
            if o["ticker"] == ticker and o["side"] != side:
                own = market.to_ticks(o["limit_price"])
                if (own <= limit) if side == BUY else (own >= limit):
                    return False, f"This would trade against your own pending {o['side']} order. Cancel it first.", None

        available_cash = self.cash - self.reserved_cash
        exec_units = units
        if side == BUY:
            if order_type == "MARKET":
                exec_units = market.affordable_buy(units, limit, available_cash - FEE_PER_ORDER)
                if exec_units == 0:
                    asks_in_band = any(p <= limit for p, _ in market.book.levels(SELL, 1))
                    return False, ("Insufficient available cash." if asks_in_band
                                   else f"No sellers within {MARKET_ORDER_BAND:.0%} of the last price."), None
            elif available_cash < market.qty(units) * limit_price + FEE_PER_ORDER:
                return False, "Insufficient available cash (your pending buy orders reserve cash).", None
        else:
            owned = self.positions.get(ticker, {}).get("units", 0) - self.reserved_units[ticker]
            if owned < units:
                return False, "Insufficient holdings (your pending sell orders reserve what they'd sell).", None

        q = market.fmt_qty
        with SessionLocal() as db:
            order = Order(ticker=ticker, order_type=order_type, side=side, qty=units,
                          limit_price=limit_price if order_type == "LIMIT" else None,
                          status="PENDING", filled_qty=0, fees=0.0)
            db.add(order)
            db.flush()
            _, resting = market.execute(PLAYER, side, exec_units, limit, rest=order_type == "LIMIT", ref=order.id)
            summary = self._apply_fills(db, market.drain_player_fills()).get(order.id)
            filled = summary["units"] if summary else 0
            avg = summary["avg"] if summary else 0.0
            verb = "Bought" if side == BUY else "Sold"
            if order_type == "MARKET":
                if filled == 0:
                    db.rollback()
                    return False, f"No {'sellers' if side == BUY else 'buyers'} within {MARKET_ORDER_BAND:.0%} of the last price.", None
                order.status = "FILLED"
                if filled == units:
                    message = f"{verb} {q(filled)} {ticker} at avg {money(avg)}."
                else:
                    message = (f"{verb} {q(filled)} of {q(units)} {ticker} at avg {money(avg)}; the rest was cancelled "
                               f"(not enough {'cash or ' if side == BUY else ''}liquidity within {MARKET_ORDER_BAND:.0%}).")
            else:
                if resting is not None:
                    self.player_orders[order.id] = (ticker, resting.oid)
                if filled == 0:
                    message = f"Limit {side} {q(units)} {ticker} @ {money(limit_price)} placed."
                elif filled == units:
                    message = f"Limit {side} {q(units)} {ticker} filled at avg {money(avg)}."
                else:
                    message = (f"Limit {side} {q(units)} {ticker}: {q(filled)} filled at avg {money(avg)}, "
                               f"{q(units - filled)} resting @ {money(limit_price)}.")
            db.commit()
        self._load_account()
        fill = None
        if filled:
            remaining = units - filled if order_type == "LIMIT" else 0
            fill = {"side": side, "ticker": ticker, "qty": market.qty(filled), "avg": round(avg, 4),
                    "remaining": market.qty(remaining)}
        return True, message, fill

    def cancel_order(self, order_id) -> tuple[bool, str]:
        if isinstance(order_id, bool) or not isinstance(order_id, int) or order_id not in self.player_orders:
            return False, "Order not found or no longer pending."
        symbol, oid = self.player_orders.pop(order_id)
        self.markets[symbol].book.cancel(oid)
        with SessionLocal() as db:
            order = db.get(Order, order_id)
            order.status = "CANCELLED"
            filled = order.filled_qty
            db.commit()
        self._load_account()
        return True, "Order cancelled." + (f" ({self.markets[symbol].fmt_qty(filled)} had already filled.)" if filled else "")

    def _cancel_resting_orders(self) -> None:
        if not self.player_orders:
            return
        with SessionLocal() as db:
            for order_id, (symbol, oid) in self.player_orders.items():
                self.markets[symbol].book.cancel(oid)
                db.get(Order, order_id).status = "CANCELLED"
            db.commit()
        self.player_orders = {}
        self._load_account()

    # --- messages ---

    def status_message(self) -> dict:
        return {"type": "STATUS", "running": self.running, "ended": self.ended}

    def _news_state(self) -> dict:
        # Copies: log entries mutate when an event ends, and messages may be serialized later.
        log = [dict(entry) for entry in self.news_log]
        return {"news": next((entry for entry in log if entry["active"]), None), "news_log": log}

    def news_message(self) -> dict:
        return {"type": "NEWS", **self._news_state()}

    def _account(self) -> dict:
        return {
            "cash": round(self.cash, 2),
            "available_cash": round(self.cash - self.reserved_cash, 2),
            "fees_paid": round(self.fees_paid, 2),
            "net_worth": round(self.net_worth(), 2),
            "positions": [{"ticker": t, "qty": p["qty"], "avg_cost": round(p["avg_cost"], 4)} for t, p in self.positions.items()],
            "orders": [
                {"id": o["id"], "ticker": o["ticker"], "side": o["side"], "limit_price": o["limit_price"],
                 "qty": self.markets[o["ticker"]].qty(o["units"]),
                 "filled": self.markets[o["ticker"]].qty(o["filled_units"])}
                for o in self.pending_orders
            ],
        }

    def account_message(self) -> dict:
        return {"type": "ACCOUNT", **self._account()}

    def book_message(self, symbol: str, since_seq: int) -> tuple[dict, int]:
        """The symbol's order book and its trades after since_seq; returns the new seq too."""
        m = self.markets[symbol]
        trades = [[price, qty, side, mine] for seq, price, qty, side, mine in m.trade_log if seq > since_seq]
        return {
            "type": "BOOK",
            "symbol": symbol,
            "bids": m.depth(BUY),
            "asks": m.depth(SELL),
            "trades": trades,
        }, m.trade_seq

    def trade_seq(self, symbol: str) -> int:
        return self.markets[symbol].trade_seq

    def snapshot(self) -> dict:
        return {
            "type": "SNAPSHOT",
            "config": {"fee": FEE_PER_ORDER, "starting_cash": STARTING_CASH, "game_days": GAME_DAYS,
                       "market_band": MARKET_ORDER_BAND},
            "seed": self.seed,
            "running": self.running,
            "ended": self.ended,
            "clock": clock_label(min(self.tick, GAME_TICKS - 1)),
            "assets": [
                {"symbol": m.symbol, "name": m.name, "type": m.type, "price": round(m.price, 4), "qty_step": m.qty_step,
                 "history": [_round_candle(c) for c in m.history] + [_round_candle(m.candle)]}
                for m in self.markets.values()
            ],
            "account": self._account(),
            **self._news_state(),
            "report": self.report,
        }
