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
* **Seeded games:** The storyline, the news schedule and each asset's true-value path are generated from a seed at the start of the game. The same seed with no player input replays identically, and `NEW_GAME` accepts a seed.
* **Server-side candles:** Real trades are aggregated into hourly OHLCV candles (1 in-game hour = 2.5 s), seeded with 50 hours of generated history.
  * Completed candles, with volume, are saved to the `Candle` table.
* **Loop:** Ticks every 100 ms on the server clock. Slow or frozen browsers can't stall it; they're disconnected and resync when they return.
* **In-game clock and 28-day month:** 4 weeks; 1 in-game day = 1 real minute, starting Day 1 at 09:00 AM. The page shows the week and day.
  * The month ends automatically after 28 days.
* **Skip week / Skip month:** fast-forward by running the real simulation at 2 in-game days per real second (120 ticks per 100 ms frame). Skip week takes about 3.5 s and Skip month at most 14 s.
  * News breaks, prices move and resting orders fill along the way, so the final prices that decide the result come out of the market.
  * Skip week pauses at the start of the next week (in the last week it skips to the end), and Pause cancels a skip.
  * Each frame is sent as one TICK with every candle finished in between, so the chart animates without gaps.
* **Storylines:** each game the seed picks one of 5 storylines (Crypto Winter, Pivot at the Fed, Chip War, Housing Squeeze, AI Gold Rush). Its 5 beats break in order through the month, never overlapping.
  * Events can move all markets, an asset class or a single stock or coin. An asset's move is the sum of what targets it, so one headline can lift TechNet while it sinks other stocks.
  * The same story never plays the same way twice. Beats can resolve different ways (the ETF is approved or rejected), some don't always happen, and every move is scaled by a random 0.6–1.4×. 1–2 wildcard headlines from outside the story mix in; some are rumors that excite traders without changing true value.
  * Each event shifts the true value of what it targets, and for 6 in-game hours (15 real seconds) it makes the affected traders more active and tilts them its way.
  * The storyline is hidden while you play and revealed in the month-end report. The month's headlines are kept in a news log that reconnecting clients receive.
* **Market maker refill:** when a big sweep empties one side of a book, the market maker re-quotes at once instead of waiting for its next refresh.
* **Trading:**
  * Market orders sweep the book with real slippage, never more than 5% from the last price, and are capped by available cash.
  * Limit orders fill at the book's prices up to the limit; any remainder rests in the book until agents trade against it, with partial fills.
  * The fee is $5 per order, charged on its first fill.
  * Resting orders reserve cash or shares; your own orders can't trade against each other.
  * Pending orders can be cancelled, and the end of the month cancels them.
* **Persistence:** Cash, fees, positions (with average cost) and all orders (pending, filled, cancelled) are stored in SQLite.
  * Each server start or "Play Again" begins a new month.
* **Fill details:** Order results and fills carry a structured summary (side, quantity, average price, remaining) for notifications.
* **Controls over WebSocket:** `PLAY`, `PAUSE`, `SUBSCRIBE`, `ORDER`, `CANCEL`, `FAST_FORWARD`, `NEW_GAME`.
  * Malformed messages get an error reply instead of dropping the connection.
* **Month-end report:** Final net worth, P/L, fees, an hourly net-worth history, and the storyline.
  * **Holdings:** what you still hold at final prices (quantity, average cost, final price, value, P/L in $ and %), plus cash and net worth.
  * **Event studies:** for each headline and each asset it moved:
    * the price path from 6 hours before to 24 hours after, as % change from the last price before it;
    * the move at +2 h (the news is fully priced in), +6 h (the excited trading ends) and +24 h (did it stick);
    * the peak move, the volume multiple vs. the prior 24 h, and the intended move for comparison;
    * rumors are flagged here, and only here.

## Packaging

* **Single-file executable (PyInstaller):** `FinBro_Larper` / `FinBro_Larper.exe` needs no Python or internet.
  * It starts the server on port 8000 (or any free port) and opens the browser.
  * It uses a temporary database that's deleted on exit.
* **Offline page:** Tailwind, Chart.js and Lightweight Charts are bundled in `static/vendor/` instead of loaded from CDNs.
* **Cross-platform builds:** a GitHub Actions workflow builds and smoke-tests the Linux (Ubuntu 22.04, for glibc 2.35+) and Windows executables.
  * A version tag also creates a draft GitHub release with both files, SHA256 checksums and that version's `CHANGELOG.md` notes.

## Tests

* **pytest suite (`tests/`, 80 tests, about 55 s):**
  * Order-book matching rules.
  * Engine and account rules.
  * Market behaviour over fixed (seed, storyline) games.
  * Skips: they pause at the week, deliver gap-free candles, and play exactly like normal ticks.
  * The `/ws` protocol against a live server.
  * A frozen-browser regression test.
  * The page's real JavaScript driven in Node.
* **CI:** runs on every push and before every build.

## Frontend (HTML/JS/Tailwind)

* **Asset tabs and Market Watch:** Browse by class; click an asset to chart and trade it.
* **Live candlestick chart:** Lightweight Charts v5 with volume bars, fed by server candles, with full history when switching assets.
* **Chart trade marks:** blue arrows at each buy's entry price on the candle it filled in, plus a blue line at the position's average entry. Pending limit orders show as faint gray dashed lines with their side and remaining quantity. They come from the server's `Execution` records, so they survive reloads.
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
  * A Market News panel lists the month's headlines with their time, the markets each one moves (▲/▼), and a LIVE marker.
  * Clicking the bar or a headline opens a modal that pauses the market; closing it resumes only if the market was running.
* **Live tape:** Every real trade in the selected asset, colored by the side that crossed the spread, with your own trades tagged.
* **Month-end modal (scrolls):**
  * the month's storyline, summary stats and a Chart.js net-worth chart;
  * a holdings table;
  * "How the market reacted": one button per headline, a chart of each affected asset's % move (−6 h to +24 h) with dashed lines at the intended moves and a marker at the headline, and a table of +2 h / +6 h / +24 h / peak / volume ×;
  * a "Play Again" button.
* **Fill notifications:** A small toast in the bottom-right corner ("▲ Bought 0.05 BTC @ $42,010.00") with a short chime, whenever an order executes. It fades after 3 seconds and never blocks clicks; the bell in the header mutes the chime (remembered per browser).
* **Keyboard shortcuts** (listed under the keyboard icon in the header):
  * Space: play / pause.
  * 1–5: Stocks, ETFs, Crypto, REITs, Bonds.
  * Tab: jump to the quantity with its value selected; for limit orders, Tab / Shift+Tab cycle between quantity and limit price.
  * Esc: leave the quantity / limit field (vim-style), so 1–5 switch tabs again.
  * `: switch buy / sell.
  * `\`: switch market / limit order.
  * Shift+Enter: execute the order (works from the quantity / limit fields; holding the keys never sends a second order).
  * N (either case): open / close the news popup, showing the live headline or else the latest one this month.
  * W: skip to next week. M: skip to the end of the month (asks first).
  * Digits type normally in the trade fields, and only N works while the news is open.
* **Resilience:** Status indicator (Live / Paused / Skipping → Day N / Month over / Offline).
  * The page reconnects automatically and resyncs its full state from the server.
