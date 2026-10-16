# Portfolio Watch Desk

A market watcher that runs around the clock on your own machine, server or GitHub Actions. It tracks your portfolio on live prices, runs technical analysis on every holding (candlestick patterns, indicators, statistics, probabilities and a backtest), turns that into position-aware suggestions, and alerts you when something happens. It needs Python 3.10+ and no third-party packages.

```bash
cd portfolio-watch-desk
python3 -m watchdesk --demo serve          # simulated market, no network or setup: open http://localhost:8765
```

## Run it on your portfolio

```bash
cp config.example.json config.json
cp portfolio.example.json portfolio.json    # or add holdings from the dashboard's "Edit portfolio" button
python3 -m watchdesk --config config.json serve
```

Open http://localhost:8765. Prices update every 15 seconds while US markets are open, every minute pre- and post-market, and every 5 minutes overnight and at weekends (60 seconds if you track crypto). The page updates itself over a live stream. Choose **Turn on desktop alerts** to get browser notifications.

Other commands:

```bash
python3 -m watchdesk --config config.json analyze NVDA   # full technical read in the terminal (--json for raw)
python3 -m watchdesk --config config.json scan           # one pass + alerts, then exit (cron friendly)
```

## Keep it running 24/7

Pick one:

| Option | How | Notes |
| --- | --- | --- |
| **Docker** | `docker compose up -d` | Restarts after crashes and reboots. Your config, portfolio and alert history live in `./data`. |
| **Linux server / Raspberry Pi** | `deploy/watchdesk.service` (systemd) | Instructions are in the file. |
| **GitHub Actions** (no machine needed) | `.github/workflows/watchdesk-scan.yml` | Scans every 15 minutes in market hours and every 3 hours otherwise, then sends alerts to your phone. It's off until you set the repo variable `WATCHDESK_SCAN_ENABLED=true` and add your portfolio as the `WATCHDESK_PORTFOLIO_JSON` secret. GitHub can start scheduled runs late, and on a private repo each run uses Actions minutes. |

If the dashboard can be reached from other machines, set `WATCHDESK_TOKEN` to a long random string and open `http://host:8765/?token=...`. Without a token, anyone who can reach the port can see and edit your portfolio.

## Live prices

| `provider` | Key | Notes |
| --- | --- | --- |
| `yahoo` (default) | none | Live regular and extended-hours prices, 1-minute bars and 2 years of daily history from Yahoo Finance's public chart endpoint. It's unofficial: it can rate-limit or change without notice, and it isn't licensed for redistribution. |
| `finnhub` | `FINNHUB_API_KEY` (free) | Real-time quotes from Finnhub; candles still come from Yahoo. |
| `simulated` | none | A random-walk market for demos and tests. |

Symbols use Yahoo's format: `AAPL`, `BRK-B`, `^VIX`, `CL=F` (crude), `GC=F` (gold), `BTC-USD`, and `RELIANCE.NS` or `VOD.L` for other exchanges. Market-hours pacing follows the US session.

## What the analysis does

Each update rebuilds today's candle from live data, then recomputes:

- **Candlestick patterns (20):** doji (standard, dragonfly, gravestone), hammer, hanging man, inverted hammer, shooting star, marubozu, spinning top, bullish/bearish engulfing, harami, piercing line, dark cloud cover, tweezer top/bottom, morning/evening star, three white soldiers, three black crows, three inside up/down. A reversal pattern only counts after a move in the opposite direction. Each pattern shows its **track record on that stock**: how often price moved its way over the next 5 days in the past two years.
- **Indicators:** SMA 20/50/200, golden/death crosses, EMA, MACD, RSI (Wilder), stochastic, ADX with +DI/−DI, Bollinger Bands (%B, width), ATR, on-balance volume (trend and divergence), volume spikes, VWAP and 5-minute RSI and patterns for today's session.
- **Statistics:** annualized volatility, today's move in standard deviations, the 68% one-day and 95% five-day price ranges, beta vs the S&P 500, 1-year Sharpe ratio, maximum drawdown, distance from the 52-week high and low, and 20-day regression slope with R².
- **Price levels:** support and resistance from clustered swing highs and lows, floor-trader pivots, Fibonacci retracements, a 2×ATR stop, a chandelier trailing stop, a take-profit level and the reward/risk ratio.
- **Probabilities:** the chance of touching the take-profit, the stop, or your own target and stop within 20 trading days. This uses the reflection principle on a driftless random walk at the stock's own volatility.
- **Score:** −100 to +100 from named components (trend, momentum, stretch, volume, pattern), labelled Strong buy / Buy / Hold / Reduce / Sell, with the share of evidence that agrees. Every point traces back to a one-line reason.
- **Backtest:** the same scoring rules replayed over the past year of that stock with no look-ahead. It shows how often buy and sell readings were right after 5 and 20 days, compared with the baseline of any day. A signal only has an edge if it beats that baseline. Often it doesn't, and the dashboard says so.

**Suggestions** take your position into account:

- Exit or review when price hits your stop
- Take partial profit at your target
- Trim back to your concentration limit, with a share count
- Protect gains or cut risk when signals turn negative
- Add on a pullback to support when they're positive
- Trail a chandelier stop on big winners
- Set a stop if you have none
- Size new buys so a stop-out costs 1% of the portfolio

All limits are in `config.json` under `settings`.

## Alerts

Alerts fire for:

- Your stop hit, or price near your stop
- Your target reached
- Moves of 3% or more, with the σ size
- New candlestick patterns, once the bar closes
- Strong 5-minute reversal patterns on holdings
- Signal changes such as Hold → Buy
- Golden and death crosses
- Volume spikes
- RSI crossing 70 or 30
- A broken trailing stop
- Strongly positive or negative headlines about your holdings

Each event fires once, and alert history survives restarts.

Delivery goes to the dashboard (live feed, toast, desktop notification) plus any channels you configure with environment variables (see `.env.example`):

- **Telegram:** `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. Create a bot with @BotFather, message it once, then read your chat id from `https://api.telegram.org/bot<token>/getUpdates`.
- **Discord / Slack:** `DISCORD_WEBHOOK_URL` / `SLACK_WEBHOOK_URL`
- **Email:** `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `ALERT_EMAIL_FROM`, `ALERT_EMAIL_TO`

Set the minimum severity per channel in `config.json` under `alerts`.

## News

Every 10 minutes the watcher reads Yahoo Finance headlines for each holding and watchlist symbol, plus Google News searches for macro themes (Fed, inflation, oil, geopolitics, earnings). It scores each headline with a finance word list and tags its theme. The word list is a simple heuristic: it can't read sarcasm or context, so read the headline itself.

## Tests

```bash
python3 -m unittest discover -s tests -t .
```

The tests cover:

- Indicator math against known values
- Every candlestick pattern
- The scoring, including a no-look-ahead check on the backtest
- Alert rules and dedupe
- US market hours, including holidays, early closes and daylight saving
- Yahoo response parsing over HTTP
- RSS parsing
- The HTTP API, live stream, token auth and cross-site protections

GitHub Actions runs them on Python 3.10, 3.12 and 3.13.

## Layout

```
watchdesk/   indicators · patterns · signals (scoring, backtest, suggestions) · providers · news · alerts · market_hours · engine · server
web/         the dashboard (Lightweight Charts by TradingView is vendored in web/vendor, Apache-2.0)
tests/       unit and integration tests
deploy/      systemd unit
artifact/    the earlier claude.ai Artifact version, which uses snapshot data and no live feed
```

## Not financial advice

This is general technical analysis, not a recommendation for your situation. Candlestick patterns and indicators are wrong often; the track-record figures show how often. Free data feeds can be delayed, incomplete or briefly wrong, so confirm prices with your broker before you trade.
