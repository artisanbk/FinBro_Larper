# Pro Trader Sim

A 7-day stock market trading game. You start with $10,000 and trade stocks, ETFs, crypto, REITs and bonds in a market full of simulated traders, then see how you did when the week ends.

## Playing

### Get the game

The game is a single file per operating system. You don't need Python or an internet connection.

| System | File |
|---|---|
| Windows | `ProTraderSim-Windows.exe` |
| macOS (Apple Silicon) | `ProTraderSim-macOS.tar.gz` |
| Linux | `ProTraderSim-Linux.tar.gz` |

Download it from the latest **Build executables** run in the repository's Actions tab (under *Artifacts*), or build it yourself (see [Build the executable](#build-the-executable)). On macOS and Linux, extract it first: `tar -xzf ProTraderSim-macOS.tar.gz`.

### Launch

- **Windows:** double-click `ProTraderSim-Windows.exe`.
- **macOS / Linux:** run `./ProTraderSim` in a terminal (or double-click it).

A small window shows the game's address, and your browser opens the game. Press **Play** (▶) or Space to start the market. To quit, close that window or press `Ctrl+C` in it.

**The first time:**
- **macOS:** the app isn't signed, so macOS blocks it. Right-click it and choose **Open**, or run `xattr -d com.apple.quarantine ProTraderSim`.
- **Windows:** SmartScreen may warn about an unknown app; choose **More info → Run anyway**. Some antivirus tools flag single-file Python apps; that's a known false positive.

**Options:** the game uses port 8000, or any free port if that's taken. Run `ProTraderSim --port 8001` to choose one, or `--no-browser` to skip opening the browser and open the shown address yourself.

### How to play

- **The week:** it lasts 7 in-game days, and one day is one real minute. Pause any time. "End Day 7" skips to your results.
- **The market:** prices come from simulated traders buying and selling in each asset's order book, shown on the right.
  - **Market orders** fill right away against the book. Large ones fill at several prices (slippage).
  - **Limit orders** wait in the book until someone trades at your price or better, and can fill in parts.
  - Pending orders set aside the cash or holdings they need.
- **Fees and quantities:** every order that executes costs a $5 fee. Crypto can be traded in fractions (0.0001 BTC, 0.001 ETH).
- **News:** two big events hit during the week. The news bar and Market News panel show them, and clicking a headline pauses the market while you read.

### Keyboard shortcuts

| Key | Action |
|---|---|
| Space | Play / pause |
| 1 – 5 | Stocks, ETFs, Crypto, REITs, Bonds |
| Tab | Jump to the quantity (value selected); for limit orders, Tab / Shift+Tab switch between quantity and limit price |
| Esc | Leave the quantity / limit field, so 1–5 switch tabs again |
| `` ` `` | Switch buy / sell |
| `\` | Switch market / limit order |
| Shift+Enter | Execute the order |
| N | Open / close the news |

While you're typing in the quantity or limit field, digits type as normal; the other shortcuts still work. Hover the keyboard icon in the header for this list.

## For developers

### Set up

Requires Python 3.10 or newer (the project is developed on 3.14). Run everything from the `stock_simulator` folder. The commands below are for Linux/macOS; on Windows use `py` instead of `python3` and `venv\Scripts\` instead of `venv/bin/`.

```sh
python3 -m venv venv
venv/bin/pip install -r requirements.txt -r requirements-dev.txt
```

Don't copy `venv/` between machines; recreate it.

### Run from source

```sh
venv/bin/python run.py                  # starts the server and opens the browser (same launcher as the executable)
venv/bin/uvicorn main:app --reload      # development: restarts on code changes; open http://127.0.0.1:8000
```

Every start (and every `--reload`) begins a fresh week. From source, the database is `simulator.db` next to the code; it's rebuilt on each start.

### Test

```sh
venv/bin/pytest                          # the whole suite, about 35 s
venv/bin/pytest tests/test_engine.py     # one file
venv/bin/pytest -k fractional            # tests whose name matches
```

| File | Covers |
|---|---|
| `test_orderbook.py` | Order matching rules |
| `test_engine.py` | Orders, account rules, fractional crypto, news, clock, seeds |
| `test_market_behaviour.py` | Simulated weeks: prices track value, books stay filled, news moves prices |
| `test_protocol.py`, `test_frozen_client.py` | The WebSocket protocol against a real server, including a frozen-tab regression |
| `test_page.py` | The page's JavaScript, driven in Node (needs Node 22+; skipped otherwise) |

The tests use their own temporary databases and never touch `simulator.db`. On GitHub, the suite runs on every push (`tests.yml`) and again on each OS before building (`build.yml`).

### Build the executable

PyInstaller can't cross-compile, so build on each OS you want to ship for:

```sh
venv/bin/pip install -r requirements-build.txt
venv/bin/pyinstaller --noconfirm --clean pro_trader_sim.spec
```

The result is `dist/ProTraderSim` (`dist\ProTraderSim.exe` on Windows), a single file of about 25 MB. Check it with `dist/ProTraderSim --no-browser`.

To build all three platforms without three machines, push the project to GitHub. Then run **Build executables** (`.github/workflows/build.yml`) from the Actions tab, or push a tag like `v1.0`. It runs the tests, builds and smoke-tests on Linux, Windows and macOS, and attaches the files listed under [Get the game](#get-the-game) to the run.

### Project layout

| Path | What it is |
|---|---|
| `run.py` | Launcher: picks a port, starts the server, opens the browser |
| `main.py` | FastAPI app, WebSocket endpoint, market loop |
| `game.py` | One trading week: clock, news, the player's orders and account |
| `market.py`, `orderbook.py` | Agent traders and the order book that sets prices |
| `config.py` | Assets, fees, timing, news and market tuning |
| `models.py`, `database.py` | SQLite tables and connection |
| `static/` | The game page; its libraries are bundled in `static/vendor/` so it works offline |
| `pro_trader_sim.spec` | PyInstaller build recipe |
| `CLAUDE.md` | Architecture notes and invariants |
