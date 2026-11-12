# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```sh
python3 -m venv venv                            # venv/ is gitignored, so create it on a fresh clone (system python3 is 3.14)
venv/bin/pip install -r requirements.txt        # install deps
venv/bin/uvicorn main:app --reload              # dev server at http://127.0.0.1:8000
venv/bin/python run.py [--port N] [--no-browser] # launcher: free port, opens the browser (the packaged entry point)

venv/bin/pip install -r requirements-build.txt  # PyInstaller (pinned)
venv/bin/pyinstaller --noconfirm --clean finbro_larper.spec   # -> dist/FinBro_Larper, single file, 20–40 MB
```

Every server start begins a fresh 7-day game: `lifespan` drops and recreates all tables. Model changes therefore never need a migration, and with `--reload` every saved edit restarts the game.

**Packaging (PyInstaller, one file).**
- `finbro_larper.spec` bundles `static/` and collects uvicorn's submodules.
- `run.py` names uvicorn's `http`/`ws`/`loop`/`lifespan` explicitly. Auto-detection imports modules by name at runtime, which a frozen build can't find.
- In a frozen build, `main.BUNDLE_DIR` is `sys._MEIPASS` and `database.DB_PATH` is a per-process file in the temp dir, which `run.py` deletes on exit. From source it's `simulator.db` next to the code.
- `finbro_larper.spec` must stay tracked. `.gitignore` ignores `*.spec` (PyInstaller's generated ones) and re-includes it with `!finbro_larper.spec`.
- PyInstaller can't cross-compile, so `.github/workflows/build.yml` builds on GitHub Actions (remote: `github.com/artisanbk/FinBro_Larper`, public). Its matrix is Linux on `ubuntu-22.04` and Windows; there's no macOS build. Linux stays on 22.04 because a binary needs its build machine's glibc or newer. This machine runs Arch (glibc 2.44), so a local Linux build won't run on most distros and isn't a release artifact.
- `build.yml` uploads `FinBro_Larper-Windows.exe` and `FinBro_Larper-Linux.tar.gz` (the executable plus `LICENSE`, as a tarball because artifact uploads drop the executable bit). README and CHANGELOG use those names. A `v*` tag push adds a job that creates a **draft** release with both files, `SHA256SUMS.txt` and the tag's `## vX.Y.Z` section of `CHANGELOG.md`; the job fails if that section is missing.
- To verify a build: `venv/bin/python tests/smoke_executable.py dist/FinBro_Larper`. It runs the build from a temp directory, fetches the page and its vendored scripts, places a trade over `/ws`, and checks that Ctrl+C deletes the temp DB (POSIX only). CI runs it on each OS.

### Tests

```sh
venv/bin/pip install -r requirements-dev.txt       # pytest
venv/bin/pytest                                    # full suite, about 35 s
venv/bin/pytest tests/test_engine.py -k fractional # one file / matching tests
```

The tests are pytest and live in `tests/`; `pytest.ini` puts the project root and `tests/` on the path. `conftest.py` sets `FINBRO_LARPER_DB` to a temp file *before* app modules are imported, so tests never touch `simulator.db`. The test files:

- `test_orderbook.py`: matching rules (pure).
- `test_engine.py`: `Game` in-process, covering orders, reservations, fractional crypto, news, clock and seeds.
- `test_market_behaviour.py`: three fixed-seed weeks asserting price tracks true value, books never empty, spreads are sane, and big news moves prices (guards calibration).
- `test_protocol.py` and `test_frozen_client.py`: a real uvicorn subprocess per module (`server` fixture) or per test (`server_factory`), driven over `/ws` with `wsutil.py` helpers. Every wait has a timeout. Reset shared-server state with `wsutil.fresh_game()`, which sends `NEW_GAME` with `running: false` so the week is exactly reproducible.
- `test_page.py`: runs `tests/page_harness.js` in Node 22+. It executes the real inline script of `static/index.html` with stubbed DOM and chart libraries against a fresh server, and drives clicks and shortcuts. It's skipped without Node. When the page gains UI behavior, extend this harness.

CI: `.github/workflows/tests.yml` runs on every push and PR (Ubuntu, Python 3.14, Node 22); `build.yml` runs the suite on each OS before building.

For calibration work beyond the bounds in `test_market_behaviour.py`, run full weeks headlessly and compare price vs. `market.true_value`, realized volatility vs. `Profile.daily_vol`, spreads, and book depth. A tick costs well under 1 ms of the 100 ms budget.

## Architecture

A single-player, 7-day trading game. The server is authoritative; the browser renders what it receives.

- `config.py` — constants and static data: timing (1 tick = 100 ms, 25 ticks = 1 in-game hour = 1 candle, 600 ticks = 1 day, 4200 ticks = the week), assets with their price `tick` and quantity `qty_step` (1 for shares; 0.0001 BTC, 0.001 ETH), per-asset-class `Profile`s, and `NEWS_DB`.
- `orderbook.py` — a limit order book with price-time priority. Prices are integer ticks. A fill is always at the resting (maker) order's price.
- `market.py` — one `Market` per asset: its book, its agents, and its candles. **Prices are not generated; they emerge from agents' orders matching in the book.** The agents:
  - `MarketMaker`: always quotes both sides around a reference price. The reference follows trades and shifts with aggressive flow on the tape, and inventory skews the quotes. This is what lets informed flow move the price.
  - `NoiseTrader`: random limit and market orders, position-limited.
  - `ValueTrader`: trades around a noisy, lagged estimate of the true value.
  - `MomentumTrader`: follows the smoothed mid over its lookback window.
- `game.py` — `Game` orchestrates one week: the clock, the news schedule, stepping every market each tick, and the player's account and orders.
- `main.py` — the FastAPI app. `market_simulation_loop` calls `game.advance()` every tick and broadcasts the result, then pushes each client the `BOOK` of the asset it watches.
- `static/index.html` — rendering only. Its JS libraries are vendored in `static/vendor/` (see `LICENSES.md` there), so the page needs no internet.

**Exogenous vs. simulated.** At the start of a week, the seed generates the news schedule and each asset's true-value path, with news baked in as a shift over `NEWS_DIFFUSION_TICKS`. Everything else is simulated live, because the player's orders sit in the same books the agents trade against. A pre-generated price path would be invalidated by the first player order. Every RNG is derived from `Game.seed` (`random.Random(f"{seed}:{symbol}:...")`), so the same seed with no player input replays identically. Never use the global `random` module inside the simulation.

Key invariants:

- **Quantities are integer units of the asset's `qty_step` inside the engine and the DB** (`Position.qty`, `Order.qty`/`filled_qty`, book orders, agent lots), so matching is exact. They are converted to shares/coins only at the edges: `Market.qty(units)`, `Market.units(qty)` and `Market.fmt_qty(units)`. The protocol, `ACCOUNT`, `BOOK` and candle `volume` all carry shares/coins as numbers.
- **Account state lives in SQLite.** That covers `Portfolio` (always `id=1`), `Position`, `Order` and `Candle`. `Order` tracks status (`PENDING` while resting, then `FILLED`/`CANCELLED`), `qty`, `filled_qty`, `avg_fill_price` and `fees`; `Candle` holds completed hourly candles with volume. `Game` keeps an in-memory copy that `_load_account()` refreshes after every DB write: cash, positions, pending orders and reservations. Keep that pairing when adding mutations.
- **Player fills flow through `Market.player_fills`.** Any trade involving the `PLAYER` owner is queued there with the DB order id. `place_order` settles the order's own fills immediately; `_settle_resting_fills()` settles fills agents make against resting player orders each tick. `Game.player_orders` maps DB order id to the book order.
- **Order rules.**
  - The fee is $5 per order, charged on its first fill.
  - Market orders sweep the book but never fill more than `MARKET_ORDER_BAND` (5%) from the last price; buys are also capped by available cash. Any remainder is cancelled.
  - Limit orders fill at the book's prices up to the limit, and the rest stays resting.
  - Resting orders reserve cash (buys: remaining × limit + fee if unpaid) or holdings (sells), so any fill can settle. `available_cash = cash − reserved`.
  - Self-trade prevention rejects an order that would cross the player's own resting order.
  - The week's end cancels all resting player orders.
- **Game methods are synchronous and return message dicts; `main.py` does the sending.** Since they run on the event-loop thread with no `await`, each call is atomic relative to ticks and other clients. Don't introduce awaits inside the engine.
- **The market loop must never await the network.** Each connection is a `Client` with its own bounded send queue and sender task; `broadcast()`/`push()` only enqueue. A client whose queue fills (it stopped reading) is closed with 1013, and the page reconnects and resyncs from `SNAPSHOT`. Previously the loop awaited each send, so one background tab that stopped reading (and timed out its keepalive ping) froze the market for everyone. Ticks are paced on `loop.time()`, so the game clock doesn't drift.
- **UI lists the user clicks (market watch, pending orders, news, portfolio cards) are rebuilt only when their data changes.** Ticks update text in place (e.g. `updatePortfolioValues()`), because re-rendering clickable rows at tick rate swallows clicks.
- **Keyboard shortcuts** live in one document-level `keydown` dispatcher:
  - Keys: Space play/pause, `1`–`5` asset tabs, Tab focuses quantity (cycling with limit price for limit orders, value selected), Esc leaves a trade field (vim-style "normal mode" so digits switch tabs again), `` ` `` buy/sell, `\` market/limit (moving focus to quantity if the hidden limit field had it), Shift+Enter executes (ignores key repeat), N toggles the news popup.
  - Digits type normally in the quantity/limit fields, but Space, Tab, Esc, `` ` ``, `\`, Shift+Enter and N still work there, since number fields can't use them. Other text fields, the `<select>` (for Space) and Ctrl/Alt/Meta combos are left alone.
  - While the news popup is open only N works; on the end-of-week report nothing does.
  - Space cancels both keydown and keyup so it never "clicks" a focused button such as Execute.

**Calibration knobs** live at the top of `market.py` (`FLOW_IMPACT`, `INVENTORY_SKEW`, `VALUE_THRESHOLD`, `NOISE_MAX_LOTS`, agent counts and rates) and in `config.PROFILES`. Two lessons from tuning:

- Passive liquidity with unlimited capacity, such as uncapped noise bids, absorbs informed flow and pins the price.
- Price impact must scale with an asset's volatility, not its spread, or high-volatility assets can't follow their value.

### WebSocket protocol (`/ws`)

All messages are JSON objects.

**Client → server** (keyed by `action`):

- `PLAY`, `PAUSE`
- `SUBSCRIBE` with `{symbol}`: choose which asset's book and trades to stream
- `ORDER` with `{ticker, side: BUY|SELL, type: MARKET|LIMIT, quantity, limit_price}`; `quantity` must be a positive multiple of the asset's `qty_step`
- `CANCEL` with `{order_id}`
- `FAST_FORWARD`
- `NEW_GAME` with optional `{seed: int, running: bool}`; `running: false` starts paused, so a seeded week replays exactly

**Server → client** (keyed by `type`):

| Type | When it's sent |
|---|---|
| `SNAPSHOT` | On connect and on `NEW_GAME`. Carries `seed`, `config`, each asset's `qty_step` and candle history (in-progress candle last, with `volume`), `account`, `news`/`news_log`, and `report` if the week has ended. The page re-subscribes after it. |
| `TICK` | Every tick while running, and right after a player trade even while paused. Carries `clock`, `net_worth`, and `updates` (`{symbol: {price, candle}}`) for only the assets that traded. |
| `BOOK` | To subscribers of that symbol, every tick and after orders. Carries `bids`/`asks` as `[price, size, player's size]` (best first, `BOOK_LEVELS` deep) and the `trades` since that client's last `BOOK` as `[price, qty, aggressor side, involves player]`. |
| `ACCOUNT` | After any order, cancel or fill. Includes `available_cash`, `positions` (`{ticker, qty, avg_cost}`) and pending `orders` (`{id, ticker, side, qty, filled, limit_price}`). |
| `STATUS` | Play/pause changes. |
| `NEWS` | A news event starts or ends. Carries `news` (the active log entry, or `null`) and `news_log`. |
| `FILL` | Agents traded against a resting player order. Carries `message` and `fill` (`{side, ticker, qty, avg, remaining}`), which the page turns into a toast and chime. |
| `GAME_OVER` | The week ended; followed by `ACCOUNT`. |
| `ORDER_RESULT` | Sent to the requesting client only: `{ok, message, fill}`. `fill` is set only if part of the order executed immediately. |
| `ERROR` | Malformed message, unknown action or unknown symbol; the connection stays open. |

## Gotchas

- JS libraries are vendored, pinned files in `static/vendor/`; upgrade by replacing the file and its `<script>` tag. Lightweight Charts is 5.3.0 and the code uses the v5 API (`chart.addSeries(LightweightCharts.CandlestickSeries | HistogramSeries, ...)`). An unpinned CDN URL once pulled v5 under v4 code; the resulting error stopped the page before the WebSocket connected, so Play silently did nothing.
- The venv runs Python 3.14, so pinned deps must support it. SQLAlchemy 2.0.20 failed at import (`AssertionError: ... directly inherits TypingOnly but has additional attributes {'__firstlineno__', '__static_attributes__'}`); 2.0.57 works.
- `PROJECT_MEMORY.md` is the handoff summary for Claude sessions outside Claude Code: decisions and why, history, user preferences, open items. When features change, update it along with `README.md` and `implemented_features.md`.
- This repo is the only working copy. The project's earlier home, `~/Downloads/StockMarketSim/` (with `stock_simulator/`, `ideas.md`, `chat_memory.md` and the original draft `stock_market_simulator.html`), is no longer in use. Don't read from it or sync with it. Mentions of those files in `PROJECT_MEMORY.md` and `implemented_features.md` are stale.
- The game is named FinBro_Larper everywhere: page title and header, launcher, executable (`FinBro_Larper`), spec, env var (`FINBRO_LARPER_DB`), temp files and logger. Until 2026-11-12 it was "Pro Trader Sim" (`ProTraderSim`, `PRO_TRADER_SIM_DB`), so any of those names still around are leftovers.
