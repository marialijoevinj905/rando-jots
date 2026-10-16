"""Market data providers.

- ``yahoo``: no API key. Uses Yahoo Finance's public chart endpoint for live
  quotes (regular and extended hours), 1-minute intraday bars and daily history.
  It is unofficial and can change or rate-limit without notice.
- ``finnhub``: real-time quotes from Finnhub (free API key), with candles from Yahoo.
- ``simulated``: a random-walk market for demos and tests; needs no network.
"""
from __future__ import annotations

import json
import math
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from .market_hours import session, to_ny
from .models import Candle, Quote

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


class ProviderError(Exception):
    pass


class RateLimited(ProviderError):
    pass


def http_get_json(url: str, timeout: float = 10.0, retries: int = 2, headers: Optional[dict] = None) -> dict:
    hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    hdrs.update(headers or {})
    last_err: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read(5_000_000).decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                raise RateLimited(f"rate limited by {urllib.parse.urlsplit(url).netloc}") from e
            if e.code == 404:
                raise ProviderError("symbol not found") from e
            last_err = e
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
            last_err = e
        if attempt < retries:
            time.sleep(0.5 * (2 ** attempt))
    raise ProviderError(f"request failed: {last_err}")


def http_get_text(url: str, timeout: float = 10.0, limit: int = 2_000_000) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(limit).decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ProviderError(f"request failed: {e}") from e


class Provider:
    name = "base"

    def live(self, symbol: str) -> Tuple[Quote, List[Candle]]:
        """Latest quote plus today's 1-minute bars (may be empty outside trading hours)."""
        raise NotImplementedError

    def daily(self, symbol: str, years: int = 2) -> List[Candle]:
        raise NotImplementedError


# ---------------------------------------------------------------- Yahoo

def parse_yahoo_chart(payload: dict) -> Tuple[dict, List[Candle]]:
    chart = (payload or {}).get("chart") or {}
    if chart.get("error"):
        raise ProviderError(str(chart["error"].get("description") or chart["error"]))
    results = chart.get("result") or []
    if not results:
        raise ProviderError("empty chart response")
    res = results[0]
    meta = res.get("meta") or {}
    ts = res.get("timestamp") or []
    q = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    o, h, l, c, v = (q.get(k) or [] for k in ("open", "high", "low", "close", "volume"))
    candles = []
    for idx, t in enumerate(ts):
        try:
            vals = (o[idx], h[idx], l[idx], c[idx])
        except IndexError:
            break
        if any(x is None for x in vals):
            continue
        vol = v[idx] if idx < len(v) and v[idx] is not None else 0
        candles.append(Candle(int(t), float(vals[0]), float(vals[1]), float(vals[2]), float(vals[3]), float(vol)))
    return meta, candles


class YahooProvider(Provider):
    name = "yahoo"
    BASE = "https://query1.finance.yahoo.com/v8/finance/chart/"

    def _chart(self, symbol: str, **params) -> Tuple[dict, List[Candle]]:
        url = self.BASE + urllib.parse.quote(symbol) + "?" + urllib.parse.urlencode(params)
        return parse_yahoo_chart(http_get_json(url))

    def live(self, symbol: str) -> Tuple[Quote, List[Candle]]:
        meta, bars = self._chart(symbol, interval="1m", range="1d", includePrePost="true")
        return quote_from_meta(symbol, meta, bars, self.name), bars

    def daily(self, symbol: str, years: int = 2) -> List[Candle]:
        _, bars = self._chart(symbol, interval="1d", range=f"{years}y")
        return bars


def quote_from_meta(symbol: str, meta: dict, bars: List[Candle], source: str) -> Quote:
    price = meta.get("regularMarketPrice")
    if price is None:
        if not bars:
            raise ProviderError("no price in response")
        price = bars[-1].c
    reg_time = int(meta.get("regularMarketTime") or 0)
    ext = None
    if bars and bars[-1].t > reg_time + 60 and abs(bars[-1].c - price) > 1e-9:
        ext = bars[-1].c
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    return Quote(
        symbol=symbol, price=float(price), prev_close=float(prev) if prev else None,
        time=max(reg_time, bars[-1].t if bars else 0), volume=meta.get("regularMarketVolume"),
        name=meta.get("longName") or meta.get("shortName") or "", currency=meta.get("currency") or "USD",
        exchange=meta.get("fullExchangeName") or meta.get("exchangeName") or "", ext_price=ext, source=source,
    )


# ---------------------------------------------------------------- Finnhub

class FinnhubProvider(YahooProvider):
    """Finnhub real-time quotes; Yahoo for candles (Finnhub candles need a paid plan)."""
    name = "finnhub"

    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("Finnhub needs an API key (set FINNHUB_API_KEY)")
        self.key = api_key

    def live(self, symbol: str) -> Tuple[Quote, List[Candle]]:
        url = "https://finnhub.io/api/v1/quote?" + urllib.parse.urlencode({"symbol": symbol, "token": self.key})
        d = http_get_json(url)
        if not d or not d.get("c"):
            raise ProviderError("no quote returned")
        try:
            _, bars = self._chart(symbol, interval="1m", range="1d", includePrePost="true")
        except ProviderError:
            bars = []
        return Quote(symbol=symbol, price=float(d["c"]), prev_close=float(d.get("pc") or 0) or None,
                     time=int(d.get("t") or time.time()), source=self.name), bars


# ---------------------------------------------------------------- Simulated

class SimulatedProvider(Provider):
    """Deterministic random-walk market, for demos and tests."""
    name = "simulated"

    # Demo price anchors (Oct 15, 2026 closes) so the simulated market looks familiar.
    ANCHORS = {"NVDA": 217.23, "AAPL": 342.00, "MSFT": 539.44, "TSM": 430.00, "GOOGL": 349.22, "AMZN": 254.76,
               "META": 736.72, "TSLA": 362.44, "SPY": 772.0, "QQQ": 650.0, "BTC-USD": 82300.0, "GC=F": 4170.0}

    def __init__(self, seed: int = 7, now: Optional[float] = None, anchors: Optional[Dict[str, float]] = None):
        self.seed = seed
        self.anchors = self.ANCHORS if anchors is None else anchors
        self._fixed_now = now
        self._state: Dict[str, dict] = {}

    def _now(self) -> float:
        return self._fixed_now if self._fixed_now is not None else time.time()

    def _params(self, symbol: str):
        rnd = random.Random(f"{self.seed}:{symbol}")
        start = rnd.uniform(40, 600)
        drift = rnd.uniform(-0.0004, 0.0012)
        vol = rnd.uniform(0.012, 0.03)
        return rnd, start, drift, vol

    def daily(self, symbol: str, years: int = 2) -> List[Candle]:
        rnd, price, drift, vol = self._params(symbol)
        n = 252 * years
        day = 86400
        ny = to_ny(self._now())
        today = int(datetime(ny.year, ny.month, ny.day, tzinfo=timezone.utc).timestamp())
        if session(self._now()) in ("closed", "pre") and ny.hour < 9:
            today -= day  # today's session hasn't opened yet, so no bar for it
        bars: List[Candle] = []
        t = today - (n * 7 // 5 + 7) * day
        while t <= today:
            if time.gmtime(t).tm_wday < 5:
                o = price * math.exp(rnd.gauss(0, vol * 0.3))
                c = o * math.exp(drift + rnd.gauss(0, vol))
                h = max(o, c) * math.exp(abs(rnd.gauss(0, vol * 0.5)))
                lo = min(o, c) * math.exp(-abs(rnd.gauss(0, vol * 0.5)))
                bars.append(Candle(t + 13 * 3600 + 1800, o, h, lo, c, rnd.uniform(5e6, 4e7)))
                price = c
            t += day
        bars = bars[-n:]
        anchor = self.anchors.get(symbol)
        if anchor and bars:
            k = anchor / bars[-1].c
            bars = [Candle(b.t, b.o * k, b.h * k, b.l * k, b.c * k, b.v) for b in bars]
        st = self._state.setdefault(symbol, {})
        st.setdefault("price", bars[-1].c)
        st.setdefault("prev", bars[-2].c if len(bars) > 1 else bars[-1].c)
        return bars

    def live(self, symbol: str) -> Tuple[Quote, List[Candle]]:
        st = self._state.get(symbol)
        if st is None:
            self.daily(symbol)
            st = self._state[symbol]
        rnd, _, _, vol = self._params(symbol)
        now = int(self._now())
        bars: List[Candle] = st.setdefault("bars", [])
        if not bars:
            p = st["prev"]
            for k in range(120, 0, -1):
                o = p
                p = p * math.exp(rnd.gauss(0, vol / 20))
                bars.append(Candle(now - now % 60 - k * 60, o, max(o, p) * 1.0005, min(o, p) * 0.9995, p, rnd.uniform(1e4, 1e5)))
            st["price"] = p
        step_rnd = random.Random(f"{self.seed}:{symbol}:{now // 5}")
        st["price"] *= math.exp(step_rnd.gauss(0, vol / 40))
        minute = now - now % 60
        if bars[-1].t == minute:
            b = bars[-1]
            b.h, b.l, b.c = max(b.h, st["price"]), min(b.l, st["price"]), st["price"]
            b.v += step_rnd.uniform(1e3, 1e4)
        else:
            bars.append(Candle(minute, bars[-1].c, max(bars[-1].c, st["price"]), min(bars[-1].c, st["price"]), st["price"], 1e4))
            del bars[:-390]
        q = Quote(symbol=symbol, price=st["price"], prev_close=st["prev"], time=now, volume=sum(b.v for b in bars),
                  name=f"{symbol} (simulated)", source=self.name)
        return q, [Candle(**b.to_dict()) for b in bars]


def make_provider(cfg: dict) -> Provider:
    name = (cfg.get("provider") or "yahoo").lower()
    if name == "yahoo":
        return YahooProvider()
    if name == "finnhub":
        return FinnhubProvider(cfg.get("finnhub_api_key") or "")
    if name in ("simulated", "demo"):
        return SimulatedProvider(seed=int(cfg.get("seed", 7)))
    raise ValueError(f"unknown provider '{name}' (use yahoo, finnhub or simulated)")
