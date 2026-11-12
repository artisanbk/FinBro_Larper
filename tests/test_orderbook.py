"""Matching rules of the limit order book (pure, no database)."""

from orderbook import BUY, NO_LIMIT, SELL, OrderBook


def sizes(book, side):
    return [(price, sum(o.qty for o in queue)) for price, queue in book.levels(side)]


def test_best_prices():
    book = OrderBook()
    assert book.best(BUY) is None and book.best(SELL) is None
    book.submit("a", SELL, 5, 101, rest=True)
    book.submit("b", SELL, 5, 100, rest=True)
    book.submit("c", BUY, 3, 98, rest=True)
    assert book.best(SELL) == 100
    assert book.best(BUY) == 98


def test_price_time_priority():
    book = OrderBook()
    book.submit("a", SELL, 5, 101, rest=True)
    book.submit("b", SELL, 5, 100, rest=True)
    book.submit("c", SELL, 5, 100, rest=True)  # same price as b, but later
    fills, resting = book.submit("taker", BUY, 12, 101, rest=False)
    assert [(f.maker.owner, f.price, f.qty) for f in fills] == [("b", 100, 5), ("c", 100, 5), ("a", 101, 2)]
    assert resting is None
    assert sizes(book, SELL) == [(101, 3)]  # a's remainder keeps its place


def test_fills_happen_at_the_resting_price():
    book = OrderBook()
    book.submit("maker", SELL, 5, 100, rest=True)
    fills, _ = book.submit("taker", BUY, 5, 105, rest=False)
    assert fills[0].price == 100


def test_limit_remainder_rests_at_its_price():
    book = OrderBook()
    book.submit("maker", SELL, 3, 101, rest=True)
    fills, resting = book.submit("taker", BUY, 10, 101, rest=True)
    assert sum(f.qty for f in fills) == 3
    assert resting is not None and resting.qty == 7 and resting.price == 101
    assert book.best(BUY) == 101 and book.best(SELL) is None


def test_immediate_or_cancel_never_rests():
    book = OrderBook()
    fills, resting = book.submit("taker", BUY, 10, 101, rest=False)
    assert fills == [] and resting is None and book.orders == {}


def test_cancel_removes_order_and_empty_level():
    book = OrderBook()
    book.submit("x", BUY, 3, 98, rest=True)
    _, order = book.submit("y", BUY, 5, 99, rest=True)
    assert book.cancel(order.oid) is order
    assert book.best(BUY) == 98
    assert book.cancel(order.oid) is None  # already gone


def test_market_order_hits_the_best_price():
    book = OrderBook()
    book.submit("x", BUY, 3, 98, rest=True)
    book.submit("y", BUY, 3, 97, rest=True)
    fills, _ = book.submit("taker", SELL, 4, NO_LIMIT[SELL], rest=False)
    assert [(f.price, f.qty) for f in fills] == [(98, 3), (97, 1)]
    assert sizes(book, BUY) == [(97, 2)]


def test_levels_are_best_first_and_limited():
    book = OrderBook()
    for price in (95, 99, 97):
        book.submit("b", BUY, 1, price, rest=True)
    for price in (104, 101, 102):
        book.submit("s", SELL, 1, price, rest=True)
    assert [p for p, _ in book.levels(BUY)] == [99, 97, 95]
    assert [p for p, _ in book.levels(SELL)] == [101, 102, 104]
    assert [p for p, _ in book.levels(BUY, 2)] == [99, 97]
    assert [p for p, _ in book.levels(SELL, 2)] == [101, 102]
