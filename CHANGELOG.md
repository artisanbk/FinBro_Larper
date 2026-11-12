# Changelog

Each `## vX.Y.Z` section becomes the notes of that version's GitHub release (see `.github/workflows/build.yml`).

## v1.0.0 (2026-11-12)

The first release of FinBro_Larper: a 7-day stock market trading game. You start with $10,000 and trade stocks, ETFs, crypto, REITs and bonds against a market full of simulated traders.

**Downloads.** Each one is a single file with no install, and it needs no Python or internet connection.

| System | File |
|---|---|
| Windows | `FinBro_Larper-Windows.exe` |
| Linux (glibc 2.35+: Ubuntu 22.04, Debian 12, Fedora 36 or newer) | `FinBro_Larper-Linux.tar.gz` |

`SHA256SUMS.txt` lists the checksums. On Linux, run `tar -xzf FinBro_Larper-Linux.tar.gz && ./FinBro_Larper`. On Windows, double-click the `.exe`. The game opens in your browser.

**What's in it:**
- 8 assets in 5 classes, each with a real limit order book. Prices come from about 37 simulated traders per asset, not a random walk.
- Market and limit orders, with slippage, partial fills, reserved cash and holdings, a $5 fee per order, and fractional crypto.
- Two news events per week that move their markets, an always-visible news bar, and a Market News panel.
- A live chart with volume, an order book panel, a trade tape, a Portfolio panel, fill notifications, and an end-of-week report.
- Keyboard shortcuts for everything (hover the keyboard icon in the header).

**Known issues:**
- The executables aren't signed. Windows SmartScreen may warn about an unknown app (choose **More info → Run anyway**), and some antivirus tools flag single-file Python apps as a false positive.
- There's no macOS download. On a Mac, build it from source (see the README).
