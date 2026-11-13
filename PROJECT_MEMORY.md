# Project Memory: FinBro_Larper

Handoff notes for future Claude sessions (Claude Code, desktop or web). Last updated 2026-11-12.
Detailed architecture and invariants are in `CLAUDE.md`. The feature list is in `implemented_features.md`, and running, testing and building are in `README.md`.

## What it is

A single-player, month-long (28 in-game days) stock market trading game.
- **Server and page:** a FastAPI server runs an agent-based market with one limit order book per asset. A browser page renders it over a single WebSocket (`/ws`).
- **Packaging:** a single executable per OS (PyInstaller), with no Python or internet needed to play.
- **Stack:** Python 3.14 venv, SQLite via SQLAlchemy, pytest. The page test needs Node 22+.

## Current state

- **Built and working:**
  - Everything from the original client-only draft (`stock_market_simulator.html`): 8 assets in 5 classes, the 7-day clock, news, the end-of-week report and Play Again.
  - The agent market with real order books. Orders support market/limit, partial fills, reserved cash and holdings, self-trade prevention, a $5 per-order fee, and fractional crypto.
  - **Page:** order book panel, live tape of real trades, volume bars, Portfolio panel, fill toasts with a chime, and keyboard shortcuts.
  - **Packaging and tests:** offline vendored JS, the PyInstaller build, a 55-test pytest suite, a build smoke test (`tests/smoke_executable.py`), and GitHub workflows for tests, builds and draft releases.
- **Git:** public repo at `github.com/artisanbk/FinBro_Larper`. Both workflows pass on GitHub, and the Linux and Windows builds pass the smoke test there.
- **Release:** v1.0.0 was published on 2026-11-12 as the latest GitHub release (tag on `a4846dc`), with both executables and `SHA256SUMS.txt`.
- **Never checked in a real browser by Claude:** the development environment had none. UI behaviour is verified by `tests/page_harness.js`, which runs the page's real script in Node with stubbed DOM and charts. Layout and visuals are unverified.

## Key decisions and why

- **Server-authoritative state:** the browser only renders. Reconnecting tabs resync from `SNAPSHOT`, and the market runs regardless of the page.
- **Agent-based market instead of a random walk or a pre-generated price path:** the user wanted realism. A pre-generated path is invalidated by the first player order, because the player's orders sit in the same books the agents trade against. So only exogenous inputs (the news schedule and each asset's true-value path) are generated from the seed. Everything else is simulated live, and the same seed with no player input replays exactly.
- **The market loop never awaits the network:** each client has its own bounded send queue. This fixed "the market stops when I tab out", where a background tab's stalled socket froze the loop.
- **Quantities are integer units of each asset's `qty_step`** (1 share, 0.0001 BTC, 0.001 ETH), so matching is exact with fractional crypto.
- **Fresh game on every start:** the DB is dropped and recreated, so there are no migrations. The packaged app uses a per-process temp DB.
- **Order rules:** fees are charged per order, not per fill. Limit orders fill at the book's price; the draft filled at the limit price, which was a bug.
- **Vendored, pinned JS libraries:** for offline play, and because an unpinned CDN once broke Play.

## History of major changes

1. **Launch crash:** SQLAlchemy 2.0.20 doesn't support Python 3.14. Fixed by upgrading to 2.0.57.
2. **Play did nothing:** an unpinned Lightweight Charts CDN URL served v5 under v4 code. Fixed by pinning the version and moving to the v5 API.
3. **Port:** moved the draft's game logic to the server (`game.py`) and rebuilt the UI from the draft.
4. **"News is missing":** events were rare, lasted 15 s and were hidden otherwise. Fixed with an always-visible news bar, a Market News panel and non-overlapping scheduling.
5. **Market stalled with a backgrounded tab:** fixed with non-blocking per-client send queues.
6. **Agent market and order books:** replaced the random walk. The two key tuning lessons:
   - Price impact must scale with volatility, not spread.
   - Uncapped passive noise liquidity pins prices.
7. **UI:** Portfolio panel, fill toasts with a chime, fractional crypto, and trade-panel accuracy (worst-case labels for limit orders, availability and Max).
8. **Keyboard shortcuts:** Space, 1–5, Tab, Esc, `` ` ``, `\`, Shift+Enter, N.
9. **Packaging:** vendored libs, the `run.py` launcher, the PyInstaller spec and the cross-platform build workflow.
10. **pytest suite and CI:** `NEW_GAME` accepts `running: false`, so seeded weeks replay exactly.
11. **Renamed to FinBro_Larper (2026-11-12):** previously "Pro Trader Sim". This covers the page, launcher, executable, spec file (`finbro_larper.spec`), the DB env var (`FINBRO_LARPER_DB`) and the docs.
12. **Release prep (2026-11-12):** `.gitignore` re-includes the spec and ignores `simulator.db`. The build workflow targets Linux (Ubuntu 22.04) and Windows only and ends with a draft release. Added `CHANGELOG.md` and the build smoke test.

## User preferences and working style

- **Keyboard-first, vim-like design:** a focused trade field is "insert mode" and Esc returns to "normal mode". New interactive features should get shortcuts and be listed in the header's keyboard tooltip and the README table.
- **Ideas before code:** the user often proposes an idea and asks for input before building it. Give an honest assessment (will it work, the trade-offs, a recommendation) first; they then say "go ahead".
- **Docs kept current:** keep `README.md` (Players vs. Developers sections), `implemented_features.md` and `CLAUDE.md` up to date with changes, and this file for major ones.
- **Concise answers.**

## Open items and ideas

- **v1.1.0 in progress (started 2026-11-12), one feature at a time:**
  1. Done (2026-11-12): chart trade marks (blue buy arrows and avg-entry line, gray dashed pending-order lines), backed by a new `Execution` table.
  2. Done (2026-11-13): storylines replace `NEWS_DB`. The seed picks one of 5; events target GLOBAL, an asset type or a symbol, and their effects add up. At the user's request the news stays surprising: beats branch, some are optional, moves are scaled 0.6–1.4×, and 1–2 wildcards (some rumors) mix in. The market maker now refills an emptied book side at once, which removed rare one-tick empty books that storyline weeks exposed.
  3. The report lists final holdings.
  4. The report shows how prices reacted to each event. Agreed metric: % change from the pre-event price over −6h…+24h hourly, plus the move at +2h/+6h/+24h, the peak, and the volume multiple vs. the prior 24h.
  3. Done (2026-11-13): the report lists holdings at final prices, plus cash.
  4. Done (2026-11-13): the report has one event study per headline (the metric above); the page charts it per headline, and rumors are revealed there.
  5. Done (2026-11-13): a 28-day month (4 weeks). Skip week pauses at the next week; Skip month plays to the end. Both run the real simulation at 2 in-game days per second (`Game.frame` batches ticks through `advance`), so news and fills still happen and a seeded game plays the same skipped or not. Shortcuts: W and M. `NEW_GAME` takes `days` for short test games.
  - Found along the way: the page harness exited 0 when it crashed, so a page syntax error (an unescaped apostrophe, from feature 2) passed the suite. The harness now reports crashes and `test_page` requires `ALL PASSED`.
  - Published as v1.1.0 on 2026-11-13, the latest GitHub release. Before release, Windows skips crawled because every SQLite commit synced to disk; disabling the sync fixed it. `TODO.md` (untracked) is the user's progress list.

- **Volatility:** quiet-period volatility is about 65–80% of target. Raising `config.PROFILES[...].daily_vol` would close the gap.
- **Builds:** There's no macOS build (the user asked for Linux and Windows). The executables are unsigned, so Windows SmartScreen warns on first launch.
- **One game per server:** everyone who connects shares the same game. That only matters if it's ever hosted for multiple players.
- **Unread ideas file:** `../ideas.md`, outside the project folder, holds the user's original ideas. Claude Code couldn't read it because reads outside the working directory are blocked; `/add-dir ..` allows it.
- **Historical files:** `chat_memory.md` holds notes from an early debugging chat and `stock_market_simulator.html` is the original draft. Neither describes the current code.

## Verify quickly

```sh
venv/bin/pytest            # 80 tests, about 55 s
venv/bin/python run.py     # play from source
```
