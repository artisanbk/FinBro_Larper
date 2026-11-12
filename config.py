"""Game constants and static data shared by the engine modules."""

from dataclasses import dataclass

FEE_PER_ORDER = 5.00        # charged once per order, on its first fill
STARTING_CASH = 10_000.00
PORTFOLIO_ID = 1

TICK_SECONDS = 0.1          # 1 tick = 100 ms of real time
TICKS_PER_HOUR = 25         # 1 in-game hour = 2.5 s, one candle per hour
TICKS_PER_DAY = 600         # 1 in-game day = 1 real minute
GAME_DAYS = 7
GAME_TICKS = TICKS_PER_DAY * GAME_DAYS
HISTORY_CANDLES = 50        # pre-generated hourly candles before the game starts

NEWS_PER_GAME = 2
NEWS_DURATION_TICKS = 150   # 6 in-game hours of excited trading
NEWS_DIFFUSION_TICKS = 50   # the true value absorbs the news over the first 2 in-game hours
NEWS_SENTIMENT = 0.12       # how far news tilts random traders toward buying or selling

MARKET_ORDER_BAND = 0.05    # market orders never fill more than 5% away from the last price
BOOK_LEVELS = 8             # price levels per side sent to the page
LOT_NOTIONAL = 4_000.0      # typical agent order size in dollars


@dataclass(frozen=True)
class Profile:
    """How an asset class behaves. Agents scale their behaviour from these."""
    daily_vol: float     # volatility of the true value per in-game day
    weekly_drift: float  # expected change of the true value over the week
    spread_bps: float    # market maker's base quoted spread, in basis points
    activity: float      # how often traders act, relative to 1.0


PROFILES = {
    "CRYPTO": Profile(daily_vol=0.04, weekly_drift=0.0, spread_bps=8.0, activity=1.0),
    "STOCK": Profile(daily_vol=0.02, weekly_drift=0.03, spread_bps=6.0, activity=0.8),
    "ETF": Profile(daily_vol=0.012, weekly_drift=0.02, spread_bps=3.0, activity=0.8),
    "REIT": Profile(daily_vol=0.015, weekly_drift=0.015, spread_bps=10.0, activity=0.5),
    "BOND": Profile(daily_vol=0.003, weekly_drift=0.005, spread_bps=4.0, activity=0.25),
}

# tick: the smallest price increment. qty_step: the smallest tradable quantity (crypto is fractional).
INITIAL_ASSETS = [
    {"symbol": "TCHN", "name": "TechNet Systems", "type": "STOCK", "price": 150.00, "tick": 0.01, "qty_step": 1},
    {"symbol": "GLOB", "name": "Global Industries", "type": "STOCK", "price": 45.20, "tick": 0.01, "qty_step": 1},
    {"symbol": "SPY", "name": "S&P 500 ETF", "type": "ETF", "price": 420.50, "tick": 0.01, "qty_step": 1},
    {"symbol": "QQQ", "name": "Nasdaq 100 ETF", "type": "ETF", "price": 350.10, "tick": 0.01, "qty_step": 1},
    {"symbol": "BTC", "name": "Bitcoin", "type": "CRYPTO", "price": 42000.00, "tick": 1.0, "qty_step": 0.0001},
    {"symbol": "ETH", "name": "Ethereum", "type": "CRYPTO", "price": 2200.00, "tick": 0.1, "qty_step": 0.001},
    {"symbol": "VNQ", "name": "Vanguard Real Estate", "type": "REIT", "price": 80.00, "tick": 0.01, "qty_step": 1},
    {"symbol": "US10Y", "name": "US 10-Year Treasury", "type": "BOND", "price": 95.00, "tick": 0.01, "qty_step": 1},
]

# target: an asset type or GLOBAL. move: how far the event shifts the true value of what it targets.
NEWS_DB = [
    {"headline": "Fed Slashes Rates by 50 bps", "body": "Surprise rate cut sends markets soaring.", "target": "GLOBAL", "impact": "BOOM", "move": 0.03},
    {"headline": "Major Crypto Exchange Hacked", "body": "Billions drained, crypto plummets.", "target": "CRYPTO", "impact": "CRASH", "move": -0.20},
    {"headline": "Tech Sector Faces Chip Shortage", "body": "Manufacturing grinds to a halt.", "target": "STOCK", "impact": "CRASH", "move": -0.08},
    {"headline": "Bitcoin ETF Approved", "body": "Institutional money floods crypto.", "target": "CRYPTO", "impact": "BOOM", "move": 0.15},
]
