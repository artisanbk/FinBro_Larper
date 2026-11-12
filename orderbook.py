"""Limit order book with price-time priority.

Prices are integer ticks (multiples of the asset's tick size) so price levels compare exactly.
An incoming order trades against the best opposite prices first, oldest order first within a
price; any unfilled remainder of a limit order then rests in the book.
"""

import itertools
from bisect import bisect_left, insort
from collections import deque
from dataclasses import dataclass

BUY = "BUY"
SELL = "SELL"
NO_LIMIT = {BUY: 1 << 62, SELL: 0}  # limit that accepts any price


@dataclass(eq=False)  # identity equality: deque.remove must find this exact order
class BookOrder:
    oid: int
    owner: object
    side: str
    price: int        # ticks
    qty: int          # remaining quantity
    ref: int | None = None  # caller's reference (the player's DB order id)


@dataclass
class Fill:
    maker: BookOrder  # the resting order that was hit
    taker_owner: object
    taker_side: str
    price: int        # always the maker's price
    qty: int


class OrderBook:
    def __init__(self) -> None:
        self._levels: dict[str, dict[int, deque[BookOrder]]] = {BUY: {}, SELL: {}}
        self._prices: dict[str, list[int]] = {BUY: [], SELL: []}  # ascending
        self.orders: dict[int, BookOrder] = {}
        self._ids = itertools.count(1)

    def best(self, side: str) -> int | None:
        prices = self._prices[side]
        if not prices:
            return None
        return prices[-1] if side == BUY else prices[0]

    def submit(self, owner: object, side: str, qty: int, limit: int, rest: bool,
               ref: int | None = None) -> tuple[list[Fill], BookOrder | None]:
        """Match an order up to its limit price. If rest, the remainder joins the book."""
        fills: list[Fill] = []
        opposite = SELL if side == BUY else BUY
        levels, prices = self._levels[opposite], self._prices[opposite]
        while qty > 0 and prices:
            price = prices[0] if side == BUY else prices[-1]
            if (price > limit) if side == BUY else (price < limit):
                break
            queue = levels[price]
            while qty > 0 and queue:
                maker = queue[0]
                traded = min(qty, maker.qty)
                maker.qty -= traded
                qty -= traded
                fills.append(Fill(maker, owner, side, price, traded))
                if maker.qty == 0:
                    queue.popleft()
                    del self.orders[maker.oid]
            if not queue:
                del levels[price]
                prices.pop(0 if side == BUY else -1)

        resting = None
        if rest and qty > 0:
            resting = BookOrder(next(self._ids), owner, side, limit, qty, ref)
            queue = self._levels[side].get(limit)
            if queue is None:
                queue = self._levels[side][limit] = deque()
                insort(self._prices[side], limit)
            queue.append(resting)
            self.orders[resting.oid] = resting
        return fills, resting

    def cancel(self, oid: int) -> BookOrder | None:
        order = self.orders.pop(oid, None)
        if order is None:
            return None
        levels = self._levels[order.side]
        queue = levels[order.price]
        queue.remove(order)
        if not queue:
            del levels[order.price]
            prices = self._prices[order.side]
            prices.pop(bisect_left(prices, order.price))
        return order

    def levels(self, side: str, n: int | None = None) -> list[tuple[int, deque[BookOrder]]]:
        """Price levels on one side, best first."""
        prices = self._prices[side]
        if side == BUY:
            chosen = prices[::-1] if n is None else prices[: -n - 1 : -1]
        else:
            chosen = prices if n is None else prices[:n]
        return [(p, self._levels[side][p]) for p in chosen]
