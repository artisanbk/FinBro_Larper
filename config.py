"""Game constants and static data shared by the engine modules."""

from dataclasses import dataclass

FEE_PER_ORDER = 5.00        # charged once per order, on its first fill
STARTING_CASH = 10_000.00
PORTFOLIO_ID = 1

TICK_SECONDS = 0.1          # 1 tick = 100 ms of real time
TICKS_PER_HOUR = 25         # 1 in-game hour = 2.5 s, one candle per hour
TICKS_PER_DAY = 600         # 1 in-game day = 1 real minute
GAME_DAYS = 28              # a month: 4 weeks, 28 real minutes at normal speed
DAYS_PER_WEEK = 7
GAME_TICKS = TICKS_PER_DAY * GAME_DAYS
TICKS_PER_WEEK = TICKS_PER_DAY * DAYS_PER_WEEK
FF_TICKS_PER_FRAME = 120    # Skip week / Skip month: 120 ticks per 100 ms frame = 2 in-game days per real second
FF_FRAME_BUDGET = 0.07      # seconds of each frame a skip may spend simulating, so the server stays responsive
EVENT_STUDY_HOURS = (-6, 24)  # the report's window around each headline, in in-game hours
HISTORY_CANDLES = 50        # pre-generated hourly candles before the game starts

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
    weekly_drift: float  # expected change of the true value per week
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

# News. Each game picks one storyline at random (from its seed) and plays its beats in order, plus
# a few wildcard headlines from outside the story. To keep the news surprising from game to game:
#   - a beat may have a chance of not happening at all ("chance", default 1),
#   - a beat may resolve one of several ways ("variants", picked by "weight", default 1),
#   - every event's moves are scaled by a random factor in MOVE_JITTER,
#   - wildcards are drawn from WILDCARDS, and some are rumors that excite traders without
#     changing anything's true value.
#
# An event has:
#   headline, body
#   impact:  BOOM or CRASH, the headline's tone (colors it on the page).
#   effects: target -> how far the event shifts the true value, where a target is GLOBAL, an asset
#            type or a symbol. An asset's shift is the sum of every effect that matches it, so
#            {"STOCK": -0.05, "TCHN": 0.08} moves TCHN +3% and GLOB -5%.
#   rumor:   optional; if true, only the signs of effects matter: traders lean that way while the
#            news is live, but the true value doesn't move, so prices drift back.
# A storyline beat adds:
#   window:  when it can break, as a fraction of the game (0 = start, 1 = end), so a story stretches
#            with the game's length. Windows are in order and never overlap.
MOVE_JITTER = (0.6, 1.4)
WILDCARDS_PER_GAME = (1, 2)
WILDCARD_WINDOW = (0.05, 0.95)

STORYLINES = [
    {
        "id": "crypto_winter",
        "title": "Crypto Winter",
        "summary": "A hack sets off a chain reaction in crypto. Whether it thaws depends on the regulators.",
        "events": [
            {"window": (0.10, 0.20), "impact": "CRASH", "effects": {"CRYPTO": -0.18},
             "headline": "Major Crypto Exchange Hacked",
             "body": "Billions are drained overnight and withdrawals are frozen across the sector."},
            {"window": (0.28, 0.38), "chance": 0.7, "impact": "CRASH", "effects": {"CRYPTO": -0.08},
             "headline": "Regulators Open Probe Into Crypto Exchanges",
             "body": "Subpoenas fly as watchdogs ask how customer funds were held."},
            {"window": (0.46, 0.56), "variants": [
                {"impact": "CRASH", "effects": {"CRYPTO": -0.10, "STOCK": -0.01, "ETF": -0.01},
                 "headline": "Top Stablecoin Loses Its Peg",
                 "body": "A 'safe' token slips to 92 cents, and the panic spills into stocks."},
                {"impact": "BOOM", "effects": {"CRYPTO": 0.07},
                 "headline": "Hacked Exchange Repays Customers in Full",
                 "body": "A surprise rescue deal makes every account whole."},
            ]},
            {"window": (0.64, 0.74), "variants": [
                {"impact": "BOOM", "effects": {"CRYPTO": 0.12, "BTC": 0.04},
                 "headline": "Spot Bitcoin ETF Approved",
                 "body": "Regulators approve the first spot Bitcoin ETF, and institutional money floods in."},
                {"impact": "CRASH", "effects": {"CRYPTO": -0.10, "BTC": -0.03},
                 "headline": "Regulators Reject Bitcoin ETF",
                 "body": "'The market is not ready,' the commission says, citing the recent hack."},
            ]},
            {"window": (0.82, 0.92), "variants": [
                {"impact": "BOOM", "effects": {"CRYPTO": 0.07},
                 "headline": "Pension Funds Add Crypto Allocations",
                 "body": "Some of the world's largest funds say they are buying the dip."},
                {"impact": "CRASH", "effects": {"CRYPTO": -0.09},
                 "headline": "Crypto Lender Files for Bankruptcy",
                 "body": "Another casualty of the hack freezes customer withdrawals."},
            ]},
        ],
    },
    {
        "id": "fed_pivot",
        "title": "Pivot at the Fed",
        "summary": "Cooling inflation puts rate cuts on the table, and every data point moves the odds.",
        "events": [
            {"window": (0.10, 0.20), "impact": "BOOM",
             "effects": {"STOCK": 0.015, "ETF": 0.012, "REIT": 0.015, "BOND": 0.006},
             "headline": "Inflation Cools More Than Expected",
             "body": "Consumer prices rise at their slowest pace in two years."},
            {"window": (0.28, 0.38), "variants": [
                {"impact": "BOOM", "effects": {"STOCK": 0.02, "ETF": 0.015, "REIT": 0.03, "BOND": 0.008, "CRYPTO": 0.03},
                 "headline": "Fed Chair Signals Rate Cuts Ahead",
                 "body": "'The time has come to adjust policy,' the chair tells lawmakers."},
                {"impact": "CRASH", "effects": {"STOCK": -0.015, "ETF": -0.01, "REIT": -0.02, "BOND": -0.005, "CRYPTO": -0.02},
                 "headline": "Fed Minutes Show Officials Split on Cuts",
                 "body": "Several officials want more proof that inflation is beaten."},
            ]},
            {"window": (0.46, 0.56), "chance": 0.75, "impact": "CRASH",
             "effects": {"STOCK": -0.03, "ETF": -0.02, "REIT": -0.035, "BOND": -0.01, "CRYPTO": -0.05},
             "headline": "Hot Jobs Report Rattles Rate-Cut Hopes",
             "body": "Hiring blows past forecasts, and traders wonder if the Fed will blink."},
            {"window": (0.64, 0.74), "variants": [
                {"weight": 2, "impact": "BOOM",
                 "effects": {"STOCK": 0.04, "ETF": 0.03, "REIT": 0.05, "BOND": 0.012, "CRYPTO": 0.08},
                 "headline": "Fed Slashes Rates by 50 bps",
                 "body": "A bigger-than-expected cut sends markets soaring."},
                {"impact": "CRASH",
                 "effects": {"STOCK": -0.025, "ETF": -0.02, "REIT": -0.03, "BOND": -0.008, "CRYPTO": -0.04},
                 "headline": "Fed Holds Rates Steady",
                 "body": "The cut markets were betting on doesn't come."},
            ]},
            {"window": (0.82, 0.92), "variants": [
                {"impact": "BOOM", "effects": {"STOCK": 0.01, "ETF": 0.01, "BOND": 0.004},
                 "headline": "Markets Price In More Cuts",
                 "body": "Futures now point to two more cuts before year end."},
                {"impact": "CRASH", "effects": {"STOCK": -0.02, "ETF": -0.015, "REIT": -0.02, "BOND": -0.006},
                 "headline": "Inflation Ticks Back Up",
                 "body": "Prices rise faster than expected, and rate-cut bets are pared back."},
            ]},
        ],
    },
    {
        "id": "chip_war",
        "title": "Chip War",
        "summary": "A chip shortage turns into a trade fight, and TechNet and Global Industries look for opposite ways out.",
        "events": [
            {"window": (0.10, 0.20), "impact": "CRASH", "effects": {"STOCK": -0.07, "QQQ": -0.02},
             "headline": "Tech Sector Faces Chip Shortage",
             "body": "Factories idle as chip deliveries slip by months."},
            {"window": (0.28, 0.38), "impact": "BOOM", "effects": {"TCHN": 0.09},
             "headline": "TechNet Locks In Exclusive Chip Supply",
             "body": "A multi-year deal guarantees TechNet first call on next year's output."},
            {"window": (0.46, 0.56), "variants": [
                {"impact": "CRASH", "effects": {"STOCK": -0.05, "QQQ": -0.02, "SPY": -0.01},
                 "headline": "New Export Ban on Advanced Chips",
                 "body": "Retaliatory curbs threaten supply chains across the industry."},
                {"impact": "BOOM", "effects": {"STOCK": 0.03, "QQQ": 0.01},
                 "headline": "Trade Talks Avert Chip Export Ban",
                 "body": "Negotiators strike a last-minute deal to keep chips flowing."},
            ]},
            {"window": (0.64, 0.74), "chance": 0.8, "variants": [
                {"impact": "BOOM", "effects": {"GLOB": 0.12},
                 "headline": "Global Industries Opens Domestic Chip Fab",
                 "body": "Its new plant comes online months early."},
                {"impact": "CRASH", "effects": {"GLOB": -0.08},
                 "headline": "Global Industries Chip Fab Delayed a Year",
                 "body": "Equipment shortages push back the plant it was counting on."},
            ]},
            {"window": (0.82, 0.92), "variants": [
                {"impact": "BOOM", "effects": {"STOCK": 0.05, "ETF": 0.015},
                 "headline": "Chip Shortage Eases as Fabs Ramp Up",
                 "body": "Lead times fall for the first time in a year."},
                {"impact": "CRASH", "effects": {"STOCK": -0.04, "ETF": -0.01},
                 "headline": "Chip Shortage to Drag Into Next Year",
                 "body": "Suppliers warn that relief is still months away."},
            ]},
        ],
    },
    {
        "id": "housing_squeeze",
        "title": "Housing Squeeze",
        "summary": "Rising mortgage rates crack real estate, and the question is whether the stress spreads.",
        "events": [
            {"window": (0.10, 0.20), "impact": "CRASH", "effects": {"REIT": -0.05, "BOND": -0.008},
             "headline": "Mortgage Rates Hit 20-Year High",
             "body": "Thirty-year rates jump again, and home buyers walk away."},
            {"window": (0.28, 0.38), "chance": 0.8, "impact": "CRASH", "effects": {"REIT": -0.06, "STOCK": -0.01, "ETF": -0.01},
             "headline": "Commercial Real Estate Defaults Surge",
             "body": "Office landlords hand back the keys as loans come due."},
            {"window": (0.46, 0.56), "variants": [
                {"impact": "CRASH", "effects": {"STOCK": -0.03, "ETF": -0.02, "REIT": -0.03, "CRYPTO": -0.04, "BOND": 0.008},
                 "headline": "Bank Stocks Tumble on Property Losses",
                 "body": "Lenders' write-downs spook markets, and investors run to Treasuries."},
                {"impact": "BOOM", "effects": {"STOCK": 0.02, "ETF": 0.015, "REIT": 0.02},
                 "headline": "Banks Shrug Off Property Losses",
                 "body": "Earnings show lenders well cushioned against bad property loans."},
            ]},
            {"window": (0.64, 0.74), "variants": [
                {"impact": "BOOM", "effects": {"REIT": 0.06, "STOCK": 0.02, "ETF": 0.015},
                 "headline": "Government Unveils Property Backstop",
                 "body": "A rescue fund will buy distressed property loans."},
                {"impact": "CRASH", "effects": {"REIT": -0.06, "STOCK": -0.015, "ETF": -0.01},
                 "headline": "Lawmakers Vote Down Property Rescue",
                 "body": "The bailout fails by three votes."},
            ]},
            {"window": (0.82, 0.92), "variants": [
                {"impact": "BOOM", "effects": {"REIT": 0.03},
                 "headline": "Home Sales Rebound",
                 "body": "Buyers return as mortgage rates ease from their peak."},
                {"impact": "CRASH", "effects": {"REIT": -0.04},
                 "headline": "Home Prices Post Biggest Drop Since 2008",
                 "body": "Sellers slash asking prices as listings pile up."},
            ]},
        ],
    },
    {
        "id": "ai_gold_rush",
        "title": "AI Gold Rush",
        "summary": "An AI breakthrough sends tech soaring, and everyone argues about whether it's a bubble.",
        "events": [
            {"window": (0.10, 0.20), "impact": "BOOM", "effects": {"TCHN": 0.12, "QQQ": 0.015},
             "headline": "TechNet Unveils Breakthrough AI Model",
             "body": "Its new model tops every benchmark, and orders pour in."},
            {"window": (0.28, 0.38), "chance": 0.75, "impact": "BOOM", "effects": {"STOCK": 0.03, "ETF": 0.025},
             "headline": "Nasdaq Hits Record on AI Frenzy",
             "body": "Investors pile into anything with AI in its pitch."},
            {"window": (0.46, 0.56), "variants": [
                {"impact": "BOOM", "effects": {"CRYPTO": 0.08},
                 "headline": "Crypto Miners Pivot to AI Data Centers",
                 "body": "Miners rent their machines to AI labs, and coins rally with them."},
                {"impact": "CRASH", "effects": {"STOCK": -0.03, "TCHN": 0.05},
                 "headline": "AI Chip Rationing Hits Smaller Rivals",
                 "body": "TechNet gets its chips; everyone else waits in line."},
            ]},
            {"window": (0.64, 0.74), "variants": [
                {"impact": "CRASH", "effects": {"STOCK": -0.06, "ETF": -0.03, "TCHN": -0.03},
                 "headline": "Analysts Warn of an AI Bubble",
                 "body": "Valuations look like 1999, top strategists warn."},
                {"impact": "BOOM", "effects": {"STOCK": 0.04, "ETF": 0.02},
                 "headline": "Big Tech Doubles AI Spending",
                 "body": "Budgets for AI data centers are raised again."},
            ]},
            {"window": (0.82, 0.92), "variants": [
                {"impact": "BOOM", "effects": {"TCHN": 0.08},
                 "headline": "TechNet Earnings Crush Estimates",
                 "body": "AI revenue triples, and TechNet raises its outlook."},
                {"impact": "CRASH", "effects": {"TCHN": -0.09},
                 "headline": "TechNet Misses on Soaring AI Costs",
                 "body": "Spending on chips eats the profits from its new model."},
            ]},
        ],
    },
]

# Headlines from outside any storyline. Rumors only tilt traders; true values don't move.
WILDCARDS = [
    {"impact": "CRASH", "effects": {"STOCK": -0.02, "ETF": -0.015, "REIT": -0.01, "BOND": -0.004},
     "headline": "Oil Prices Spike on Supply Fears",
     "body": "A pipeline outage sends crude up 8% in a day."},
    {"impact": "BOOM", "effects": {"STOCK": 0.025, "ETF": 0.02},
     "headline": "Surprise Tax-Cut Plan Lifts Stocks",
     "body": "The proposal would cut corporate taxes next year."},
    {"impact": "BOOM", "effects": {"GLOB": 0.06},
     "headline": "Global Industries Wins Defense Contract",
     "body": "The ten-year deal is its largest ever."},
    {"impact": "CRASH", "effects": {"BOND": -0.008, "REIT": -0.01},
     "headline": "Treasury Auction Draws Weak Demand",
     "body": "Buyers demand higher yields to take on new debt."},
    {"impact": "BOOM", "effects": {"TCHN": 1}, "rumor": True,
     "headline": "Reports Say TechNet Is Exploring a Sale",
     "body": "Unnamed sources say bankers have been hired. TechNet declined to comment."},
    {"impact": "CRASH", "effects": {"CRYPTO": -1, "STOCK": -1}, "rumor": True,
     "headline": "Rumor: Major Bank Hit by Crypto Losses",
     "body": "Screenshots of an internal memo circulate online. The bank hasn't responded."},
    {"impact": "CRASH", "effects": {"BTC": -1}, "rumor": True,
     "headline": "Whale Alert: Huge Bitcoin Transfer to Exchanges",
     "body": "A wallet untouched for years moves 20,000 BTC. Traders brace for a sale."},
    {"impact": "CRASH", "effects": {"ETH": -1}, "rumor": True,
     "headline": "Viral Post Claims Ethereum Upgrade Delayed",
     "body": "Developers haven't confirmed the claim."},
]
