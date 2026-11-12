# Chat Memory: Implemented Features

This document tracks the functionality built into FinBro_Larper. Everything from the original client-only draft (`stock_market_simulator.html`) has been ported to a server-authoritative design: the game runs on the server, and the browser renders what it receives over the `/ws` WebSocket. Prices come from an agent-based market rather than a random walk.

## Backend (FastAPI & Python)

* **Assets:** 8 across 5 classes: Stocks (TCHN, GLOB), ETFs (SPY, QQQ), Crypto (BTC, ETH), REITs (VNQ) and Bonds (US10Y). Each class has its own volatility, drift, spread and activity level.
  * Crypto trades in fractions (0.0001 BTC, 0.001 ETH); everything else in whole shares.
* **Order books (`orderbook.py`):** Every asset has a limit order book with price-time priority; all trading, the player's included, goes through it.
* **Agent-based market (`market.py`):** Prices emerge from about 37 agents per asset trading in its book:
  * A market maker that quotes both sides and reprices on order flow.
  * Random traders.
  * Value traders that track the asset's true value.
  * Trend followers.
  * Calibrated so prices track the true value within about 1% on average, react to news by roughly the intended amount, and show fat tails and volatility clustering.
* **Seeded weeks:** The news schedule and each asset's true-value path are generated from a seed at the start of the week. The same seed with no player input replays identically, and `NEW_GAME` accepts a seed.
* **Server-side candles:** Real trades are aggregated into hourly OHLCV candles (1 in-game hour = 2.5 s), seeded with 50 hours of generated history.
  * Completed candles, with volume, are saved to the `Candle` table.
* **Loop:** Ticks every 100 ms on the server clock. Slow or frozen browsers can't stall it; they're disconnected and resync when they return.
* **In-game clock and 7-day week:** 1 in-game day = 1 real minute, starting Day 1 at 09:00 AM.
  * The week ends automatically after 7 days, or on demand via "End Day 7".
* **News engine:** 2 random, non-overlapping events per week fire between days 2 and 6.
  * Each event shifts the true value of the markets it targets (e.g. crypto hack -20%, chip shortage -8% for stocks). It also makes random traders more active and tilts them toward buying or selling for 6 in-game hours (15 real seconds).
  * The week's headlines are kept in a news log that reconnecting clients receive.
* **Trading:**
  * Market orders sweep the book with real slippage, never more than 5% from the last price, and are capped by available cash.
  * Limit orders fill at the book's prices up to the limit; any remainder rests in the book until agents trade against it, with partial fills.
  * The fee is $5 per order, charged on its first fill.
  * Resting orders reserve cash or shares; your own orders can't trade against each other.
  * Pending orders can be cancelled, and the end of the week cancels them.
* **Persistence:** Cash, fees, positions (with average cost) and all orders (pending, filled, cancelled) are stored in SQLite.
  * Each server start or "Play Again" begins a new week.
* **Fill details:** Order results and fills carry a structured summary (side, quantity, average price, remaining) for notifications.
* **Controls over WebSocket:** `PLAY`, `PAUSE`, `SUBSCRIBE`, `ORDER`, `CANCEL`, `FAST_FORWARD`, `NEW_GAME`.
  * Malformed messages get an error reply instead of dropping the connection.
* **End-of-week report:** Final net worth, P/L, fees and an hourly net-worth history.

## Packaging

* **Single-file executable (PyInstaller):** `FinBro_Larper` / `FinBro_Larper.exe` needs no Python or internet.
  * It starts the server on port 8000 (or any free port) and opens the browser.
  * It uses a temporary database that's deleted on exit.
* **Offline page:** Tailwind, Chart.js and Lightweight Charts are bundled in `static/vendor/` instead of loaded from CDNs.
* **Cross-platform builds:** a GitHub Actions workflow builds and smoke-tests the Linux (Ubuntu 22.04, for glibc 2.35+) and Windows executables.
  * A version tag also creates a draft GitHub release with both files, SHA256 checksums and that version's `CHANGELOG.md` notes.

## Tests

* **pytest suite (`tests/`, 55 tests, about 35 s):**
  * Order-book matching rules.
  * Engine and account rules.
  * Market behaviour over fixed-seed weeks.
  * The `/ws` protocol against a live server.
  * A frozen-browser regression test.
  * The page's real JavaScript driven in Node.
* **CI:** runs on every push and before every build.

## Frontend (HTML/JS/Tailwind)

* **Asset tabs and Market Watch:** Browse by class; click an asset to chart and trade it.
* **Live candlestick chart:** Lightweight Charts v5 with volume bars, fed by server candles, with full history when switching assets.
* **Order book panel:** The selected asset's best 8 price levels per side, with depth bars, the spread, and your own resting orders highlighted.
* **Trade panel:**
  * Buy/sell toggle and market/limit order types (the limit price is prefilled with the current price).
  * Quantity input that follows the asset's step (Shares vs. Quantity in BTC/ETH), with a sensible default and a Max button.
  * Available cash (buying) or available-to-sell quantity (selling), with warnings for over-cash, over-holdings or off-step quantities.
  * Live preview that walks the order book to estimate a market order's average price and slippage; limit orders show worst-case totals (Max Total Cost, Min Proceeds).
  * Inline confirmation and error messages from the server.
* **Portfolio:**
  * Net worth, available cash (with any cash reserved by orders) and fees in the header.
  * A Portfolio panel under Market Watch / Pending Orders / Market News that fills the rest of the column. It shows a value, cost and unrealized P/L summary, plus a card per position (quantity, value, average cost, P/L in $ and %); click a card to open that asset.
  * Pending limit orders with partial-fill progress and cancel buttons.
* **News:**
  * An always-visible news bar: quiet by default, it pulses red (crash) or green (boom) with a scrolling headline while an event is live.
  * A Market News panel lists the week's headlines with their time, the markets affected, and a LIVE marker.
  * Clicking the bar or a headline opens a modal that pauses the market; closing it resumes only if the market was running.
* **Live tape:** Every real trade in the selected asset, colored by the side that crossed the spread, with your own trades tagged.
* **End-of-week modal:** Summary stats, a Chart.js net-worth chart and a "Play Again" button.
* **Fill notifications:** A small toast in the bottom-right corner ("▲ Bought 0.05 BTC @ $42,010.00") with a short chime, whenever an order executes. It fades after 3 seconds and never blocks clicks; the bell in the header mutes the chime (remembered per browser).
* **Keyboard shortcuts** (listed under the keyboard icon in the header):
  * Space: play / pause.
  * 1–5: Stocks, ETFs, Crypto, REITs, Bonds.
  * Tab: jump to the quantity with its value selected; for limit orders, Tab / Shift+Tab cycle between quantity and limit price.
  * Esc: leave the quantity / limit field (vim-style), so 1–5 switch tabs again.
  * `: switch buy / sell.
  * `\`: switch market / limit order.
  * Shift+Enter: execute the order (works from the quantity / limit fields; holding the keys never sends a second order).
  * N (either case): open / close the news popup, showing the live headline or else the latest one this week.
  * Digits type normally in the trade fields, and only N works while the news is open.
* **Resilience:** Status indicator (Live / Paused / Week over / Offline).
  * The page reconnects automatically and resyncs its full state from the server.
