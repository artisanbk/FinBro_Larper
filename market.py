"""One asset's market: its order book, the agents trading in it, and its exogenous inputs.

Prices are not generated: they emerge from agents' orders matching in the book.
The only pre-generated input is the asset's "true value" path (with news baked in),
which value traders try to track. Everything else is simulated live, so the player's
orders affect what the agents see and do.
"""

import heapq
import math
import random
from collections import deque

from config import (
    BOOK_LEVELS, LOT_NOTIONAL, MARKET_ORDER_BAND, NEWS_DIFFUSION_TICKS, NEWS_DURATION_TICKS,
    TICKS_PER_DAY, Profile,
)
from orderbook import BUY, SELL, Fill, OrderBook

PLAYER = "PLAYER"  # owner tag for the player's orders

N_NOISE = 20
N_VALUE = 10
N_MOMENTUM = 6
MM_LEVELS = 5           # price levels the market maker quotes per side
MM_REFRESH_TICKS = 3    # how often it re-quotes
FLOW_IMPACT = 0.03      # market maker's price shift per lot of aggressive volume, as a share of daily volatility
NOISE_MAX_LOTS = 4      # random traders' position limit, so they can't absorb unlimited flow
VALUE_THRESHOLD = 0.08  # value traders ignore gaps smaller than this share of daily volatility
INVENTORY_SKEW = 2.0    # quote shift at full inventory, in half-spreads
PRICE_MEMORY = 300      # ticks of last-price history kept for momentum traders
NEWS_ACTIVITY = 2.0     # traders act this much more often while news is live


def true_value_path(price: float, profile: Profile, events: list[dict], rng: random.Random,
                    n_ticks: int) -> list[float]:
    """Pre-generate the asset's true value for every tick: drift + noise + news shifts."""
    sigma = profile.daily_vol / math.sqrt(TICKS_PER_DAY)
    mu = math.log(1 + profile.weekly_drift) / n_ticks
    shift = [0.0] * (n_ticks + 1)
    vol_mult = [1.0] * (n_ticks + 1)
    for event in events:
        start = event["trigger_tick"]
        step = math.log(1 + event["move"]) / NEWS_DIFFUSION_TICKS
        for t in range(start, min(start + NEWS_DIFFUSION_TICKS, n_ticks + 1)):
            shift[t] += step
        for t in range(start, min(start + NEWS_DURATION_TICKS, n_ticks + 1)):
            vol_mult[t] = 2.0
    path = [price]
    log_value = math.log(price)
    for t in range(1, n_ticks + 1):
        log_value += mu + shift[t] + sigma * vol_mult[t] * rng.gauss(0, 1)
        path.append(math.exp(log_value))
    return path


class Agent:
    rate = 0.0  # chance of acting each tick, before the market's activity scaling

    def __init__(self, market: "Market", rng: random.Random) -> None:
        self.market = market
        self.rng = rng
        self.position = 0

    def on_fill(self, side: str, qty: int) -> None:
        self.position += qty if side == BUY else -qty

    def act(self, tick: int, sentiment: float) -> None:
        raise NotImplementedError

    def trade_toward(self, target: int, max_lots: int, limit_price: float | None = None) -> None:
        """Send an immediate-or-cancel order that moves the position toward target."""
        m = self.market
        gap = target - self.position
        qty = min(abs(gap), m.lot * max_lots)
        if qty <= 0:
            return
        side = BUY if gap > 0 else SELL
        limit = m.band_limit(side)
        if limit_price is not None:
            own = m.to_ticks(limit_price)
            limit = min(limit, own) if side == BUY else max(limit, own)
        m.execute(self, side, qty, limit, rest=False)


class MarketMaker(Agent):
    """Always quotes both sides around its reference price.

    The reference follows trades and shifts with the order flow on the tape (aggressive buying
    suggests the price should be higher), and quotes skew to shed inventory. That is what lets
    informed traders move the price, whoever ends up on the other side of their trades.
    """

    def __init__(self, market: "Market", rng: random.Random) -> None:
        super().__init__(market, rng)
        self.max_inventory = market.lot * 25
        self.oids: list[int] = []

    def observe(self, aggressor_side: str, qty: int) -> None:
        m = self.market
        direction = 1.0 if aggressor_side == BUY else -1.0
        m.ref *= 1 + direction * FLOW_IMPACT * (qty / m.lot) * m.profile.daily_vol

    def act(self, tick: int, sentiment: float) -> None:
        m = self.market
        for oid in self.oids:
            m.book.cancel(oid)
        self.oids = []
        m.ref += 0.2 * (m.price - m.ref)
        half = m.half_spread()
        inventory = self.position / self.max_inventory
        center = m.ref * (1 - inventory * INVENTORY_SKEW * half)
        for level in range(MM_LEVELS):
            size = m.lot * (level + 1)
            offset = half * (1 + level)
            # Long: quote smaller bids (buy less); short: smaller asks. Never go dark on a side.
            bid_size = max(1, round(size * min(1.0, max(0.2, 1 - inventory))))
            ask_size = max(1, round(size * min(1.0, max(0.2, 1 + inventory))))
            self._quote(BUY, bid_size, math.floor(center * (1 - offset) / m.tick_size))
            self._quote(SELL, ask_size, math.ceil(center * (1 + offset) / m.tick_size))

    def _quote(self, side: str, size: int, price: int) -> None:
        if price < 1:
            return
        _, resting = self.market.execute(self, side, size, price, rest=True)
        if resting is not None:
            self.oids.append(resting.oid)


class NoiseTrader(Agent):
    """Trades randomly: mostly passive limit orders near the price, sometimes market orders."""
    rate = 0.05

    def act(self, tick: int, sentiment: float) -> None:
        m, rng = self.market, self.rng
        side = BUY if rng.random() < 0.5 + sentiment else SELL
        limit = m.lot * NOISE_MAX_LOTS
        if (side == BUY and self.position >= limit) or (side == SELL and self.position <= -limit):
            side = SELL if side == BUY else BUY
        qty = max(1, round(m.lot * rng.uniform(0.2, 1.5)))
        if rng.random() < 0.25:
            m.execute(self, side, qty, m.band_limit(side), rest=False)
            return
        half = m.half_spread()
        offset = abs(rng.gauss(0, half * 4)) - half * 0.5  # mostly behind the quotes, now and then crossing
        price = m.mid() * (1 - offset if side == BUY else 1 + offset)
        m.execute(self, side, qty, max(1, m.to_ticks(price)), rest=True,
                  expire_at=tick + rng.randint(30, 300))


class ValueTrader(Agent):
    """Trades around its (noisy, slightly lagged) estimate of the true value.

    It keeps standing orders just below and above its estimate, so the book reflects beliefs
    about value, and trades aggressively when the price strays far from it.
    """
    rate = 0.05

    def __init__(self, market: "Market", rng: random.Random) -> None:
        super().__init__(market, rng)
        self.bias = rng.gauss(0, 0.003)  # each has its own opinion of the value
        self.lag = rng.randint(0, 40)    # and hears news at a different time
        self.threshold = market.profile.daily_vol * VALUE_THRESHOLD * rng.uniform(0.5, 1.5)
        self.max_position = market.lot * 10
        self.oids: list[int] = []

    def act(self, tick: int, sentiment: float) -> None:
        m = self.market
        for oid in self.oids:
            m.book.cancel(oid)
        self.oids = []
        estimate = m.true_value[max(0, tick - self.lag)] * (1 + self.bias)
        gap = (estimate - m.price) / m.price
        if abs(gap) > 2 * self.threshold:
            target = round(math.copysign(self.max_position * min(1.0, abs(gap) / (self.threshold * 6)), gap))
            self.trade_toward(target, max_lots=2, limit_price=estimate)  # never pays past its estimate
        expire = tick + 120
        if self.position < self.max_position:
            self._post(BUY, m.to_ticks(estimate * (1 - self.threshold)), expire)
        if self.position > -self.max_position:
            self._post(SELL, m.to_ticks(estimate * (1 + self.threshold)), expire)

    def _post(self, side: str, price: int, expire: int) -> None:
        if price < 1:
            return
        _, resting = self.market.execute(self, side, self.market.lot, price, rest=True, expire_at=expire)
        if resting is not None:
            self.oids.append(resting.oid)


class MomentumTrader(Agent):
    """Follows trends: long after a rise over its lookback window, short after a fall."""
    rate = 0.04

    def __init__(self, market: "Market", rng: random.Random) -> None:
        super().__init__(market, rng)
        self.lookback = rng.randint(20, 250)
        expected_move = market.profile.daily_vol * math.sqrt(self.lookback / TICKS_PER_DAY)
        # Ignore wiggles within a few spreads, or bid/ask bounce alone would trigger it.
        self.threshold = max(expected_move * rng.uniform(1.0, 2.0), 8 * market.profile.spread_bps / 2e4)
        self.max_position = market.lot * 8

    def act(self, tick: int, sentiment: float) -> None:
        m = self.market
        signal = m.price_memory[-1] / m.price_memory[-self.lookback] - 1
        if signal > self.threshold:
            target = self.max_position
        elif signal < -self.threshold:
            target = -self.max_position
        elif abs(signal) < self.threshold / 2:
            target = 0
        else:
            return
        self.trade_toward(target, max_lots=1)


class Market:
    def __init__(self, spec: dict, profile: Profile, true_value: list[float], rng: random.Random,
                 start_unix: int, history: list[dict]) -> None:
        self.symbol = spec["symbol"]
        self.name = spec["name"]
        self.type = spec["type"]
        self.tick_size = spec["tick"]
        # Quantities are integer units of qty_step everywhere inside the engine (exact matching);
        # qty() converts to shares/coins at the edges.
        self.qty_step = spec["qty_step"]
        self.qty_decimals = max(0, -math.floor(math.log10(self.qty_step) + 1e-9))
        self.profile = profile
        self.true_value = true_value
        self.rng = rng
        self.book = OrderBook()
        self.last = self.to_ticks(spec["price"])
        self.ref = spec["price"]  # market maker's smoothed reference price
        self.lot = max(1, round(LOT_NOTIONAL / spec["price"] / self.qty_step))  # in units
        self.normal_vol = profile.daily_vol / math.sqrt(TICKS_PER_DAY)
        self.variance = self.normal_vol ** 2  # EWMA of squared per-tick returns
        self.smoothed = spec["price"]  # EMA of the mid price, which momentum traders watch
        self.price_memory = deque([spec["price"]] * PRICE_MEMORY, maxlen=PRICE_MEMORY)

        self.period = start_unix
        self.history = history  # completed hourly candles, oldest first
        self.candle = {"time": start_unix, "open": spec["price"], "high": spec["price"],
                       "low": spec["price"], "close": spec["price"], "volume": 0}
        self.completed: list[dict] = []  # candles finished since the game last saved them

        self.traded = False  # set by any trade; the game clears it after reporting
        self.trade_seq = 0
        self.trade_log: deque[tuple] = deque(maxlen=200)  # (seq, price, qty, aggressor side, involves player)
        self.player_fills: list[tuple[int, str, float, int]] = []  # (ref, side, price, qty)
        self._expiries: list[tuple[int, int]] = []  # heap of (tick, oid) for agents' resting orders

        self.market_maker = MarketMaker(self, rng)
        self.traders: list[Agent] = (
            [NoiseTrader(self, rng) for _ in range(N_NOISE)]
            + [ValueTrader(self, rng) for _ in range(N_VALUE)]
            + [MomentumTrader(self, rng) for _ in range(N_MOMENTUM)]
        )
        self.market_maker.act(0, 0.0)  # seed the book with quotes

    # --- prices ---

    def to_ticks(self, price: float) -> int:
        return round(price / self.tick_size)

    def to_price(self, ticks: int) -> float:
        return round(ticks * self.tick_size, 6)

    @property
    def price(self) -> float:
        return self.to_price(self.last)

    def qty(self, units: int) -> float:
        """Units -> shares/coins."""
        return round(units * self.qty_step, self.qty_decimals)

    def units(self, qty: float) -> int | None:
        """Shares/coins -> units, or None if qty isn't a positive multiple of qty_step."""
        units = round(qty / self.qty_step)
        if units <= 0 or abs(units * self.qty_step - qty) > self.qty_step * 1e-6:
            return None
        return units

    def fmt_qty(self, units: int) -> str:
        text = f"{self.qty(units):,.{self.qty_decimals}f}"
        return text.rstrip("0").rstrip(".") if self.qty_decimals else text

    def mid(self) -> float:
        bid, ask = self.book.best(BUY), self.book.best(SELL)
        if bid is None or ask is None:
            return self.price
        return self.to_price(bid + ask) / 2

    def half_spread(self) -> float:
        """Market maker's half-spread as a fraction of price; widens when the market is volatile."""
        vol_ratio = math.sqrt(self.variance) / self.normal_vol
        return self.profile.spread_bps / 2e4 * max(1.0, vol_ratio)

    def band_limit(self, side: str) -> int:
        """Worst price a market order may fill at."""
        return self.to_ticks(self.price * (1 + MARKET_ORDER_BAND if side == BUY else 1 - MARKET_ORDER_BAND))

    # --- trading ---

    def execute(self, owner: object, side: str, qty: int, limit: int, rest: bool,
                expire_at: int | None = None, ref: int | None = None):
        fills, resting = self.book.submit(owner, side, qty, limit, rest, ref)
        for fill in fills:
            self._record(fill, ref)
        if resting is not None and expire_at is not None:
            heapq.heappush(self._expiries, (expire_at, resting.oid))
        return fills, resting

    def _record(self, fill: Fill, taker_ref: int | None) -> None:
        price = self.to_price(fill.price)
        for owner, side, ref in ((fill.maker.owner, fill.maker.side, fill.maker.ref),
                                 (fill.taker_owner, fill.taker_side, taker_ref)):
            if owner is PLAYER:
                assert ref is not None
                self.player_fills.append((ref, side, price, fill.qty))
            else:
                owner.on_fill(side, fill.qty)  # type: ignore[attr-defined]
        if fill.taker_owner is not self.market_maker:
            self.market_maker.observe(fill.taker_side, fill.qty)
        self.last = fill.price
        self.traded = True
        self.trade_seq += 1
        mine = fill.maker.owner is PLAYER or fill.taker_owner is PLAYER
        self.trade_log.append((self.trade_seq, price, self.qty(fill.qty), fill.taker_side, mine))
        self._update_candle(price, fill.qty)

    def _update_candle(self, price: float, qty: int) -> None:
        if self.candle["time"] != self.period:
            self.history.append(self.candle)
            self.completed.append(self.candle)
            prev = self.candle["close"]
            self.candle = {"time": self.period, "open": prev, "high": prev, "low": prev, "close": prev, "volume": 0}
        c = self.candle
        c["high"] = max(c["high"], price)
        c["low"] = min(c["low"], price)
        c["close"] = price
        c["volume"] = round(c["volume"] + self.qty(qty), self.qty_decimals)

    def affordable_buy(self, qty: int, limit: int, budget: float) -> int:
        """How many of qty units a buyer with budget can take from the asks up to limit."""
        total = 0
        if budget <= 0:
            return 0
        for price, queue in self.book.levels(SELL):
            if price > limit or total >= qty:
                break
            unit = self.to_price(price) * self.qty_step  # cost of one unit
            take = min(qty - total, sum(o.qty for o in queue), int(budget // unit))
            total += take
            budget -= take * unit
            if take < sum(o.qty for o in queue):
                break
        return total

    def drain_player_fills(self) -> list[tuple[int, str, float, int]]:
        fills, self.player_fills = self.player_fills, []
        return fills

    # --- simulation ---

    def step(self, tick: int, sentiment: float, excited: bool) -> None:
        """One tick: expire stale orders, re-quote, let a random subset of traders act."""
        while self._expiries and self._expiries[0][0] <= tick:
            _, oid = heapq.heappop(self._expiries)
            self.book.cancel(oid)
        if tick % MM_REFRESH_TICKS == 0:
            self.market_maker.act(tick, sentiment)
        scale = self.profile.activity * (NEWS_ACTIVITY if excited else 1.0)
        acting = [a for a in self.traders if self.rng.random() < a.rate * scale]
        self.rng.shuffle(acting)
        for agent in acting:
            agent.act(tick, sentiment)

        mid = self.mid()
        ret = math.log(mid / self.smoothed)
        self.variance = 0.97 * self.variance + 0.03 * ret * ret
        self.smoothed += 0.1 * (mid - self.smoothed)
        self.price_memory.append(self.smoothed)

    # --- views ---

    def depth(self, side: str) -> list[list]:
        """[price, total size, player's size] per level, best first, in shares/coins."""
        return [
            [self.to_price(price), self.qty(sum(o.qty for o in queue)),
             self.qty(sum(o.qty for o in queue if o.owner is PLAYER))]
            for price, queue in self.book.levels(side, BOOK_LEVELS)
        ]
