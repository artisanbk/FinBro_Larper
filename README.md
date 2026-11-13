# FinBro_Larper

A month-long stock market trading game. You start with $10,000 and trade stocks, ETFs, crypto, REITs and bonds in a market full of simulated traders, then see how you did when the month ends.

## Playing

### Get the game

The game is a single file per operating system. You don't need Python or an internet connection.

| System | File |
|---|---|
| Windows | `FinBro_Larper-Windows.exe` |
| Linux (glibc 2.35+: Ubuntu 22.04, Debian 12, Fedora 36 or newer) | `FinBro_Larper-Linux.tar.gz` |

Download it from the [Releases page](https://github.com/artisanbk/FinBro_Larper/releases). `SHA256SUMS.txt` there lists the files' checksums. On Linux, extract it first: `tar -xzf FinBro_Larper-Linux.tar.gz`. There's no macOS download; on a Mac, build it yourself (see [Build the executable](#build-the-executable)).

### Launch

- **Windows:** double-click `FinBro_Larper-Windows.exe`.
- **Linux (or a macOS build):** run `./FinBro_Larper` in a terminal (or double-click it).

A small window shows the game's address, and your browser opens the game. Press **Play** (▶) or Space to start the market. To quit, close that window or press `Ctrl+C` in it.

**The first time:**
- **Windows:** SmartScreen may warn about an unknown app; choose **More info → Run anyway**. Some antivirus tools flag single-file Python apps; that's a known false positive.

**Options:** the game uses port 8000, or any free port if that's taken. Run `FinBro_Larper --port 8001` to choose one, or `--no-browser` to skip opening the browser and open the shown address yourself.

### How to play

- **The month:** it lasts 28 in-game days (4 weeks), and one day is one real minute. Pause any time.
- **Skipping ahead:**
  - **Skip week** (W) fast-forwards to the start of next week and pauses there.
  - **Skip month** (M) fast-forwards to the end of the month.
  - The market really plays out, at 2 days a second, so news still breaks, prices move and your pending orders can fill on the way. Press Space to stop a skip.
- **The market:** prices come from simulated traders buying and selling in each asset's order book, shown on the right.
  - **Market orders** fill right away against the book. Large ones fill at several prices (slippage).
  - **Limit orders** wait in the book until someone trades at your price or better, and can fill in parts.
  - Pending orders set aside the cash or holdings they need.
- **Your trades on the chart:** each buy shows as a blue arrow at its entry price, with a blue line at your average entry while you hold. Pending limit orders are faint gray dashed lines at their prices.
- **The report:** at the month's end you see your net worth over time, what you still hold (value and P/L), and how the market reacted to each headline. Pick one to chart each affected asset's price from 6 hours before to 24 hours after, against how far the news should have moved it.
- **Fees and quantities:** every order that executes costs a $5 fee. Crypto can be traded in fractions (0.0001 BTC, 0.001 ETH).
- **News:** each month follows a hidden storyline: a chain of related events, like a crypto hack that leads to a regulator probe. It's revealed in your month-end report. The story plays out differently every game: events can go either way, some don't happen, and their size varies. A few unrelated headlines (some just rumors) mix in. The news bar and Market News panel show each headline and the markets it moves (▲/▼), and clicking a headline pauses the market while you read.

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
| W | Skip to next week |
| M | Skip to the end of the month |

While you're typing in the quantity or limit field, digits type as normal; the other shortcuts still work. Hover the keyboard icon in the header for this list.

## For developers

### Set up

Requires Python 3.10 or newer (the project is developed on 3.14). Run everything from the project folder (`FinBro_Larper`). The commands below are for Linux/macOS; on Windows use `py` instead of `python3` and `venv\Scripts\` instead of `venv/bin/`.

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

Every start (and every `--reload`) begins a fresh month. From source, the database is `simulator.db` next to the code; it's rebuilt on each start.

### Test

```sh
venv/bin/pytest                          # the whole suite, about 55 s
venv/bin/pytest tests/test_engine.py     # one file
venv/bin/pytest -k fractional            # tests whose name matches
```

| File | Covers |
|---|---|
| `test_orderbook.py` | Order matching rules |
| `test_engine.py` | Orders, account rules, fractional crypto, news, clock, seeds |
| `test_market_behaviour.py` | Simulated games: prices track value, books stay filled, news moves prices |
| `test_protocol.py`, `test_frozen_client.py` | The WebSocket protocol against a real server, including a frozen-tab regression |
| `test_page.py` | The page's JavaScript, driven in Node (needs Node 22+; skipped otherwise) |

The tests use their own temporary databases and never touch `simulator.db`. On GitHub, the suite runs on every push and pull request (`tests.yml`), and again on each OS before building (`build.yml`).

### Build the executable

PyInstaller can't cross-compile, so build on each OS you want to ship for:

```sh
venv/bin/pip install -r requirements-build.txt
venv/bin/pyinstaller --noconfirm --clean finbro_larper.spec
```

The result is `dist/FinBro_Larper` (`dist\FinBro_Larper.exe` on Windows), a single file of 20–40 MB (CI builds: about 22 MB on Windows, 40 MB on Linux). To check it, run `venv/bin/python tests/smoke_executable.py dist/FinBro_Larper`. That starts it from another folder, checks the bundled page, places a trade over the WebSocket, and quits it.

A Linux build only runs on systems with the same glibc as the build machine or newer. That's why release builds come from GitHub Actions' Ubuntu 22.04 runner and not from a rolling distro.

To build for Linux and Windows without a Windows machine, run **Build executables** (`.github/workflows/build.yml`) from the repository's Actions tab. It runs the tests, builds and smoke-tests on each OS, and attaches the files listed under [Get the game](#get-the-game) to the run. For macOS, add `macos-latest` (an Apple Silicon build) to its matrix.

### Release

1. Add a `## vX.Y.Z (date)` section to `CHANGELOG.md`. It becomes the release notes.
2. Commit and push it, then tag and push the tag on its own: `git push origin main && git tag -a v1.0.0 -m "FinBro_Larper v1.0.0" && git push origin v1.0.0`. If you push the branch and the tag in one command, GitHub may not start the tag's build. If that happens, run `gh workflow run build.yml --ref v1.0.0`.
3. The tag runs **Build executables**. It ends by creating a **draft** release with both files, `SHA256SUMS.txt` and that changelog section.
4. Check the draft on the Releases page and publish it.

### Project layout

| Path | What it is |
|---|---|
| `run.py` | Launcher: picks a port, starts the server, opens the browser |
| `main.py` | FastAPI app, WebSocket endpoint, market loop |
| `game.py` | One trading month: clock, news, skips, the player's orders and account, the report |
| `market.py`, `orderbook.py` | Agent traders and the order book that sets prices |
| `config.py` | Assets, fees, timing, news and market tuning |
| `models.py`, `database.py` | SQLite tables and connection |
| `static/` | The game page; its libraries are bundled in `static/vendor/` so it works offline |
| `finbro_larper.spec` | PyInstaller build recipe |
| `tests/smoke_executable.py` | Smoke test for a built executable |
| `.github/workflows/` | CI: `tests.yml` (every push) and `build.yml` (executables and draft releases) |
| `CHANGELOG.md` | Release notes, one section per version |
| `CLAUDE.md` | Architecture notes and invariants |
