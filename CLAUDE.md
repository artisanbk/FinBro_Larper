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

Every server start begins a fresh 28-day game (a month of 4 weeks): `lifespan` drops and recreates all tables. Model changes therefore never need a migration, and with `--reload` every saved edit restarts the game.

**Packaging (PyInstaller, one file).**
- `finbro_larper.spec` bundles `static/` and collects uvicorn's submodules.
- `run.py` names uvicorn's `http`/`ws`/`loop`/`lifespan` explicitly. Auto-detection imports modules by name at runtime, which a frozen build can't find.
- In a frozen build, `main.BUNDLE_DIR` is `sys._MEIPASS` and `database.DB_PATH` is a per-process file in the temp dir, which `run.py` deletes on exit. From source it's `simulator.db` next to the code.
- `finbro_larper.spec` must stay tracked. `.gitignore` ignores `*.spec` (PyInstaller's generated ones) and re-includes it with `!finbro_larper.spec`.
- PyInstaller can't cross-compile, so `.github/workflows/build.yml` builds on GitHub Actions (remote: `github.com/artisanbk/FinBro_Larper`, public). Its matrix is Linux on `ubuntu-22.04` and Windows; there's no macOS build. Linux stays on 22.04 because a binary needs its build machine's glibc or newer. This machine runs Arch (glibc 2.44), so a local Linux build won't run on most distros and isn't a release artifact.
- `build.yml` uploads `FinBro_Larper-Windows.exe` and `FinBro_Larper-Linux.tar.gz` (the executable plus `LICENSE`, as a tarball because artifact uploads drop the executable bit). README and CHANGELOG use those names. A `v*` tag push adds a job that creates a **draft** release with both files, `SHA256SUMS.txt` and the tag's `## vX.Y.Z` section of `CHANGELOG.md`; the job fails if that section is missing. Push the tag on its own: when `main` and the tag went out in one `git push`, the tag build never started. `gh workflow run build.yml --ref vX.Y.Z` runs the same jobs, the release included.
- To verify a build: `venv/bin/python tests/smoke_executable.py dist/FinBro_Larper`. It runs the build from a temp directory, fetches the page and its vendored scripts, places a trade over `/ws`, and checks that Ctrl+C deletes the temp DB (POSIX only). CI runs it on each OS.

### Tests

```sh
venv/bin/pip install -r requirements-dev.txt       # pytest
venv/bin/pytest                                    # full suite, about 55 s
venv/bin/pytest tests/test_engine.py -k fractional # one file / matching tests
```

The tests are pytest and live in `tests/`; `pytest.ini` puts the project root and `tests/` on the path. `conftest.py` sets `FINBRO_LARPER_DB` to a temp file *before* app modules are imported, so tests never touch `simulator.db`. The test files:

- `test_orderbook.py`: matching rules (pure).
- `test_engine.py`: `Game` in-process, covering orders, reservations, fractional crypto, news, clock and seeds.
- `test_market_behaviour.py`: three fixed (seed, storyline) week-long games (`days=7`, for speed; the story scales to fit) asserting price tracks true value, books never empty, spreads are sane, and big news moves prices (guards calibration).
- `test_protocol.py` and `test_frozen_client.py`: a real uvicorn subprocess per module (`server` fixture) or per test (`server_factory`), driven over `/ws` with `wsutil.py` helpers. Every wait has a timeout. Reset shared-server state with `wsutil.fresh_game()`, which sends `NEW_GAME` with `running: false` so the game is exactly reproducible. Tests that skip to the end start a short game (`NEW_GAME` `days`), so the skip takes about a second.
- `test_page.py`: runs `tests/page_harness.js` in Node 22+ and requires its `ALL PASSED` line. The harness reports a crash (e.g. a syntax error in the page script) as a failure; it once exited 0 silently and hid a broken page. It executes the real inline script of `static/index.html` with stubbed DOM and chart libraries against a fresh server, and drives clicks and shortcuts. It's skipped without Node. When the page gains UI behavior, extend this harness.

CI: `.github/workflows/tests.yml` runs on every push and PR (Ubuntu, Python 3.14, Node 22); `build.yml` runs the suite on each OS before building.

For calibration work beyond the bounds in `test_market_behaviour.py`, run full games headlessly (`tests/test_market_behaviour.simulate(seed, storyline, days=28)`) and compare price vs. `market.true_value`, realized volatility vs. `Profile.daily_vol`, spreads, and book depth. A tick costs about 0.25 ms, so a skip's 120-tick frame uses about 30 ms of the 100 ms budget.

`tests/smoke_executable.py <exe>` smoke-tests a build. It plays a one-day game through Skip month and checks the report; CI runs it on each OS.

## Architecture

A single-player trading game lasting one month: 28 in-game days in 4 weeks, 28 real minutes at normal speed. The server is authoritative; the browser renders what it receives.

- `config.py` — constants and static data: timing (1 tick = 100 ms, 25 ticks = 1 in-game hour = 1 candle, 600 ticks = 1 day, 4200 = a week, 16,800 = the month as `GAME_TICKS`; plus the skip speed `FF_TICKS_PER_FRAME` / `FF_FRAME_BUDGET` and the report's `EVENT_STUDY_HOURS`), assets with their price `tick` and quantity `qty_step` (1 for shares; 0.0001 BTC, 0.001 ETH), per-asset-class `Profile`s, and the news: `STORYLINES`, `WILDCARDS` and the knobs that vary them (`MOVE_JITTER`, `WILDCARDS_PER_GAME`). The comment above `STORYLINES` documents the event format.
- `orderbook.py` — a limit order book with price-time priority. Prices are integer ticks. A fill is always at the resting (maker) order's price.
- `market.py` — one `Market` per asset: its book, its agents, and its candles. **Prices are not generated; they emerge from agents' orders matching in the book.** The agents:
  - `MarketMaker`: always quotes both sides around a reference price. The reference follows trades and shifts with aggressive flow on the tape, and inventory skews the quotes. This is what lets informed flow move the price. It refreshes every `MM_REFRESH_TICKS`, and immediately whenever a sweep empties a side of the book.
  - `NoiseTrader`: random limit and market orders, position-limited.
  - `ValueTrader`: trades around a noisy, lagged estimate of the true value.
  - `MomentumTrader`: follows the smoothed mid over its lookback window.
- `game.py` — `Game` orchestrates one game (`days`, default 28): the clock, the news (`plan_news`), stepping every market each tick (`advance`), skips (`fast_forward` / `frame`), the player's account and orders, and the report (`_holdings`, `_event_study`).
- `main.py` — the FastAPI app. `market_simulation_loop` calls `game.frame()` every 100 ms (one tick, or a batch while skipping) and broadcasts the result, then pushes each client the `BOOK` of the asset it watches.
- `static/index.html` — rendering only. Its JS libraries are vendored in `static/vendor/` (see `LICENSES.md` there), so the page needs no internet.

**Exogenous vs. simulated.** At the start of a game, the seed picks a storyline and `plan_news` turns it into the game's news, and the seed also generates each asset's true-value path, with news baked in as a shift over `NEWS_DIFFUSION_TICKS`.

**News stays surprising from game to game** (a user requirement), so the same storyline never plays the same way twice:
- **Chance:** a beat may be skipped.
- **Variants:** a beat resolves to one of several outcomes, e.g. the ETF is approved or rejected.
- **Size:** every event's moves are scaled by a random factor in `MOVE_JITTER`.
- **Wildcards:** 1–2 headlines from outside the story are mixed in. Some are rumors, which tilt traders' sentiment but leave true values alone.

An asset's move from an event is the sum of the effects that match it (GLOBAL + its type + its symbol), via `game.asset_move`. The storyline, the magnitudes and the rumor flag never reach the page until the report reveals the storyline. Don't add predictability back, e.g. by always running the same sequence or showing which headlines are rumors.

Everything else is simulated live, because the player's orders sit in the same books the agents trade against. A pre-generated price path would be invalidated by the first player order. Every RNG is derived from `Game.seed` (`random.Random(f"{seed}:{symbol}:...")`), so the same seed with no player input replays identically. Never use the global `random` module inside the simulation.

Key invariants:

- **Quantities are integer units of the asset's `qty_step` inside the engine and the DB** (`Position.qty`, `Order.qty`/`filled_qty`, book orders, agent lots), so matching is exact. They are converted to shares/coins only at the edges: `Market.qty(units)`, `Market.units(qty)` and `Market.fmt_qty(units)`. The protocol, `ACCOUNT`, `BOOK` and candle `volume` all carry shares/coins as numbers.
- **Account state lives in SQLite.** That covers `Portfolio` (always `id=1`), `Position`, `Order`, `Execution` and `Candle`. `Execution` is one row per order per settlement (`_apply_fills`), holding units, the average price and the game tick; the chart's trade marks come from it. `Order` tracks status (`PENDING` while resting, then `FILLED`/`CANCELLED`), `qty`, `filled_qty`, `avg_fill_price` and `fees`; `Candle` holds completed hourly candles with volume. `Game` keeps an in-memory copy that `_load_account()` refreshes after every DB write: cash, positions, pending orders and reservations. Keep that pairing when adding mutations.
- **Player fills flow through `Market.player_fills`.** Any trade involving the `PLAYER` owner is queued there with the DB order id. `place_order` settles the order's own fills immediately; `_settle_resting_fills()` settles fills agents make against resting player orders each tick. `Game.player_orders` maps DB order id to the book order.
- **Order rules.**
  - The fee is $5 per order, charged on its first fill.
  - Market orders sweep the book but never fill more than `MARKET_ORDER_BAND` (5%) from the last price; buys are also capped by available cash. Any remainder is cancelled.
  - Limit orders fill at the book's prices up to the limit, and the rest stays resting.
  - Resting orders reserve cash (buys: remaining × limit + fee if unpaid) or holdings (sells), so any fill can settle. `available_cash = cash − reserved`.
  - Self-trade prevention rejects an order that would cross the player's own resting order.
  - The month's end cancels all resting player orders.
- **Skips run the real simulation, never a jump.**
  - `fast_forward(until)` sets `Game.ff`, and `frame()` then runs up to `FF_TICKS_PER_FRAME` ticks per frame through `advance()`: 2 in-game days per real second.
  - News breaks, agents trade and resting orders fill as usual, so the final prices are organic. A seeded game plays the same skipped or not; `test_a_skip_plays_exactly_like_normal_ticks` guards that.
  - Skip week (`WEEK`) pauses at the next week's start; in the last week it becomes END. Pausing (`set_running(False)`) cancels a skip.
  - `_coalesce` merges a frame into one TICK. Each symbol's update carries `completed`, every candle finished since the last update, taken from `Market.unreported`, so the chart has no gaps. Only the last ACCOUNT of a frame is kept.
- **Game methods are synchronous and return message dicts; `main.py` does the sending.** Since they run on the event-loop thread with no `await`, each call is atomic relative to ticks and other clients. Don't introduce awaits inside the engine.
- **The market loop must never await the network.** Each connection is a `Client` with its own bounded send queue and sender task; `broadcast()`/`push()` only enqueue. A client whose queue fills (it stopped reading) is closed with 1013, and the page reconnects and resyncs from `SNAPSHOT`. Previously the loop awaited each send, so one background tab that stopped reading (and timed out its keepalive ping) froze the market for everyone. Ticks are paced on `loop.time()`, so the game clock doesn't drift.
- **UI lists the user clicks (market watch, pending orders, news, portfolio cards) are rebuilt only when their data changes.** Ticks update text in place (e.g. `updatePortfolioValues()`), because re-rendering clickable rows at tick rate swallows clicks. The chart overlays work the same way: `renderChartOverlays()` redraws the blue buy-entry markers (`createSeriesMarkers`, `atPriceBottom`), the blue avg-entry line and the faint gray dashed pending-order lines (`createPriceLine`) only on `ACCOUNT` or an asset switch.
- **Keyboard shortcuts** live in one document-level `keydown` dispatcher:
  - Keys: Space play/pause, `1`–`5` asset tabs, Tab focuses quantity (cycling with limit price for limit orders, value selected), Esc leaves a trade field (vim-style "normal mode" so digits switch tabs again), `` ` `` buy/sell, `\` market/limit (moving focus to quantity if the hidden limit field had it), Shift+Enter executes (ignores key repeat), N toggles the news popup, W skips to next week, M skips to the month's end (after a confirm).
  - Digits type normally in the quantity/limit fields, but Space, Tab, Esc, `` ` ``, `\`, Shift+Enter, N, W and M still work there, since number fields can't use them. Other text fields, the `<select>` (for Space) and Ctrl/Alt/Meta combos are left alone.
  - While the news popup is open only N works; on the month-end report nothing does.
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
- `FAST_FORWARD` with optional `{until: WEEK|END}` (default END): skip ahead by running the simulation fast (see Skips above)
- `NEW_GAME` with optional `{seed: int, running: bool, storyline: id, days: 1-28}`; `running: false` starts paused, so a seeded game replays exactly; `storyline` overrides the seed's pick; `days` makes a shorter game (for tests). Invalid values get `ERROR`

**Server → client** (keyed by `type`):

| Type | When it's sent |
|---|---|
| `SNAPSHOT` | On connect and on `NEW_GAME`. Carries `seed`, `config` (`game_days`, `days_per_week`, …), `day`, `fast_forward`, each asset's `qty_step` and candle history (in-progress candle last, with `volume`), `account`, `news`/`news_log`, and `report` if the game has ended. The page re-subscribes after it. About 0.6 MB by the month's end. |
| `TICK` | Every frame while running (one per frame while skipping), and right after a player trade even while paused. Carries `clock`, `day`, `net_worth`, and `updates` (`{symbol: {price, candle, completed?}}`) for only the assets that traded, where `completed` lists candles finished since that asset's last update. |
| `BOOK` | To subscribers of that symbol, every tick and after orders. Carries `bids`/`asks` as `[price, size, player's size]` (best first, `BOOK_LEVELS` deep) and the `trades` since that client's last `BOOK` as `[price, qty, aggressor side, involves player]`. |
| `ACCOUNT` | After any order, cancel or fill. Includes `available_cash`, `positions` (`{ticker, qty, avg_cost}`), pending `orders` (`{id, ticker, side, qty, filled, limit_price}`) and `executions` (`{ticker, side, qty, price, time}`, where `time` is the start of the candle the fill landed in). |
| `STATUS` | Play/pause and skip changes. Carries `running`, `ended` and `fast_forward` (`{until, target_day}` or `null`). |
| `NEWS` | A news event starts or ends. Carries `news` (the active log entry, or `null`) and `news_log`. Entries have `headline`, `body`, `impact`, `clock`, `active` and `targets` (`[{target, direction: UP|DOWN}]`, where a target is GLOBAL, an asset type or a symbol). |
| `FILL` | Agents traded against a resting player order. Carries `message` and `fill` (`{side, ticker, qty, avg, remaining}`), which the page turns into a toast and chime. |
| `GAME_OVER` | The month ended; followed by `ACCOUNT`. The report (also in `SNAPSHOT.report`) has `net_worth`, `profit`, `fees_paid`, hourly `net_worth_history`, and `storyline` (`{id, title, summary}`), the only place the storyline is revealed. It also has `cash` and `holdings` (`{ticker, name, qty, avg_cost, price, value, pl, pl_pct}`). `events` gives one event study per headline: `{id, headline, clock, impact, rumor, assets: [{symbol, expected, path: [[hour, pct]], at_2h, at_6h, at_24h, peak, volume_x}]}`, with `path` running from −6 h to +24 h. |
| `ORDER_RESULT` | Sent to the requesting client only: `{ok, message, fill}`. `fill` is set only if part of the order executed immediately. |
| `ERROR` | Malformed message, unknown action or unknown symbol; the connection stays open. |

## Gotchas

- The page builds HTML in single-quoted JS strings, so an apostrophe ("This month's") must be escaped (`\'`) or the whole script fails to parse and the page is dead. The page harness catches this now.

- JS libraries are vendored, pinned files in `static/vendor/`; upgrade by replacing the file and its `<script>` tag. Lightweight Charts is 5.3.0 and the code uses the v5 API (`chart.addSeries(LightweightCharts.CandlestickSeries | HistogramSeries, ...)`). An unpinned CDN URL once pulled v5 under v4 code; the resulting error stopped the page before the WebSocket connected, so Play silently did nothing.
- The venv runs Python 3.14, so pinned deps must support it. SQLAlchemy 2.0.20 failed at import (`AssertionError: ... directly inherits TypingOnly but has additional attributes {'__firstlineno__', '__static_attributes__'}`); 2.0.57 works.
- `PROJECT_MEMORY.md` is the handoff summary for Claude sessions outside Claude Code: decisions and why, history, user preferences, open items. When features change, update it along with `README.md` and `implemented_features.md`.
- This repo is the only working copy. The project's earlier home, `~/Downloads/StockMarketSim/` (with `stock_simulator/`, `ideas.md`, `chat_memory.md` and the original draft `stock_market_simulator.html`), is no longer in use. Don't read from it or sync with it. Mentions of those files in `PROJECT_MEMORY.md` and `implemented_features.md` are stale.
- The game is named FinBro_Larper everywhere: page title and header, launcher, executable (`FinBro_Larper`), spec, env var (`FINBRO_LARPER_DB`), temp files and logger. Until 2026-11-12 it was "Pro Trader Sim" (`ProTraderSim`, `PRO_TRADER_SIM_DB`), so any of those names still around are leftovers.
