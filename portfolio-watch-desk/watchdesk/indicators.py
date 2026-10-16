"""Technical indicators and statistics.

Every series function returns a list the same length as its input, with
``None`` where the indicator hasn't warmed up yet, so index ``i`` always
lines up with candle ``i``.
"""
from __future__ import annotations

import math
from typing import List, Optional, Sequence

from .models import Candle

Series = List[Optional[float]]


# ---------------------------------------------------------------- averages

def sma(values: Sequence[float], n: int) -> Series:
    out: Series = [None] * len(values)
    s = 0.0
    for i, v in enumerate(values):
        s += v
        if i >= n:
            s -= values[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def ema(values: Sequence[float], n: int) -> Series:
    """Exponential moving average seeded with the SMA of the first n values."""
    out: Series = [None] * len(values)
    if len(values) < n:
        return out
    k = 2.0 / (n + 1)
    prev = sum(values[:n]) / n
    out[n - 1] = prev
    for i in range(n, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def _wilder(values: Sequence[float], n: int, start: int = 0) -> Series:
    """Wilder's smoothing (RMA) starting at index ``start``."""
    out: Series = [None] * len(values)
    if len(values) - start < n:
        return out
    prev = sum(values[start:start + n]) / n
    out[start + n - 1] = prev
    for i in range(start + n, len(values)):
        prev = (prev * (n - 1) + values[i]) / n
        out[i] = prev
    return out


# ---------------------------------------------------------------- momentum

def rsi(closes: Sequence[float], n: int = 14) -> Series:
    out: Series = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains = [0.0] + [max(closes[i] - closes[i - 1], 0.0) for i in range(1, len(closes))]
    losses = [0.0] + [max(closes[i - 1] - closes[i], 0.0) for i in range(1, len(closes))]
    ag = _wilder(gains, n, start=1)
    al = _wilder(losses, n, start=1)
    for i in range(len(closes)):
        if ag[i] is None:
            continue
        if al[i] == 0:
            out[i] = 100.0 if ag[i] > 0 else 50.0
        else:
            out[i] = 100.0 - 100.0 / (1.0 + ag[i] / al[i])
    return out


def macd(closes: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9):
    ef, es = ema(closes, fast), ema(closes, slow)
    line: Series = [None if a is None or b is None else a - b for a, b in zip(ef, es)]
    start = next((i for i, v in enumerate(line) if v is not None), len(line))
    sig_part = ema([v for v in line[start:]], signal) if start < len(line) else []
    sig: Series = [None] * start + sig_part
    hist: Series = [None if a is None or b is None else a - b for a, b in zip(line, sig)]
    return line, sig, hist


def roc(closes: Sequence[float], n: int = 10) -> Series:
    return [None if i < n or closes[i - n] == 0 else (closes[i] / closes[i - n] - 1) * 100
            for i in range(len(closes))]


def stochastic(candles: Sequence[Candle], n: int = 14, d: int = 3):
    k: Series = [None] * len(candles)
    for i in range(n - 1, len(candles)):
        window = candles[i - n + 1:i + 1]
        hh = max(c.h for c in window)
        ll = min(c.l for c in window)
        k[i] = 50.0 if hh == ll else (candles[i].c - ll) / (hh - ll) * 100
    start = n - 1
    dd: Series = [None] * len(candles)
    if len(candles) >= start + d:
        part = sma([v for v in k[start:]], d)
        dd = [None] * start + part
    return k, dd


# ---------------------------------------------------------------- volatility

def true_range(candles: Sequence[Candle]) -> List[float]:
    out = []
    for i, c in enumerate(candles):
        if i == 0:
            out.append(c.h - c.l)
        else:
            pc = candles[i - 1].c
            out.append(max(c.h - c.l, abs(c.h - pc), abs(c.l - pc)))
    return out


def atr(candles: Sequence[Candle], n: int = 14) -> Series:
    return _wilder(true_range(candles), n)


def bollinger(closes: Sequence[float], n: int = 20, k: float = 2.0):
    mid = sma(closes, n)
    up: Series = [None] * len(closes)
    lo: Series = [None] * len(closes)
    pb: Series = [None] * len(closes)
    bw: Series = [None] * len(closes)
    for i in range(n - 1, len(closes)):
        w = closes[i - n + 1:i + 1]
        m = mid[i]
        sd = math.sqrt(sum((x - m) ** 2 for x in w) / n)
        up[i], lo[i] = m + k * sd, m - k * sd
        width = up[i] - lo[i]
        pb[i] = 0.5 if width == 0 else (closes[i] - lo[i]) / width
        bw[i] = 0.0 if m == 0 else width / m * 100
    return mid, up, lo, pb, bw


def adx(candles: Sequence[Candle], n: int = 14):
    """Average Directional Index with +DI / -DI."""
    size = len(candles)
    plus_dm, minus_dm = [0.0] * size, [0.0] * size
    for i in range(1, size):
        upm = candles[i].h - candles[i - 1].h
        dnm = candles[i - 1].l - candles[i].l
        plus_dm[i] = upm if upm > dnm and upm > 0 else 0.0
        minus_dm[i] = dnm if dnm > upm and dnm > 0 else 0.0
    tr = true_range(candles)
    atr_ = _wilder(tr, n, start=1)
    pdm = _wilder(plus_dm, n, start=1)
    mdm = _wilder(minus_dm, n, start=1)
    pdi: Series = [None] * size
    mdi: Series = [None] * size
    dx = [0.0] * size
    first = None
    for i in range(size):
        if atr_[i] is None or atr_[i] == 0:
            continue
        pdi[i] = 100 * pdm[i] / atr_[i]
        mdi[i] = 100 * mdm[i] / atr_[i]
        s = pdi[i] + mdi[i]
        dx[i] = 0.0 if s == 0 else 100 * abs(pdi[i] - mdi[i]) / s
        if first is None:
            first = i
    adx_: Series = [None] * size
    if first is not None:
        adx_ = _wilder(dx, n, start=first)
    return adx_, pdi, mdi


# ---------------------------------------------------------------- volume

def obv(candles: Sequence[Candle]) -> List[float]:
    out, total = [], 0.0
    for i, c in enumerate(candles):
        if i > 0:
            if c.c > candles[i - 1].c:
                total += c.v
            elif c.c < candles[i - 1].c:
                total -= c.v
        out.append(total)
    return out


def vwap(candles: Sequence[Candle]) -> Series:
    """Cumulative VWAP over the given (intraday) candles."""
    out: Series = []
    pv = vol = 0.0
    for c in candles:
        tp = (c.h + c.l + c.c) / 3
        pv += tp * c.v
        vol += c.v
        out.append(pv / vol if vol else None)
    return out


# ---------------------------------------------------------------- statistics

def log_returns(closes: Sequence[float]) -> List[float]:
    return [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))
            if closes[i - 1] > 0 and closes[i] > 0]


def stdev(xs: Sequence[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def annualized_vol(closes: Sequence[float], periods: int = 252, lookback: int = 60) -> Optional[float]:
    r = log_returns(closes[-(lookback + 1):])
    return stdev(r) * math.sqrt(periods) if len(r) >= 10 else None


def zscore(closes: Sequence[float], n: int = 20) -> Optional[float]:
    if len(closes) < n:
        return None
    w = closes[-n:]
    m = sum(w) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in w) / n)
    return 0.0 if sd == 0 else (closes[-1] - m) / sd


def linreg(values: Sequence[float]):
    """Least-squares fit y = a + b*x. Returns (slope, intercept, r_squared)."""
    n = len(values)
    if n < 3:
        return 0.0, values[-1] if values else 0.0, 0.0
    xs = range(n)
    mx = (n - 1) / 2
    my = sum(values) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, values))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in values)
    b = sxy / sxx if sxx else 0.0
    a = my - b * mx
    r2 = (sxy * sxy) / (sxx * syy) if sxx and syy else 0.0
    return b, a, r2


def max_drawdown(closes: Sequence[float]) -> float:
    """Largest peak-to-trough fall, as a negative percentage."""
    peak, worst = -math.inf, 0.0
    for c in closes:
        peak = max(peak, c)
        if peak > 0:
            worst = min(worst, (c / peak - 1) * 100)
    return worst


def beta(asset: Sequence[float], bench: Sequence[float], lookback: int = 252) -> Optional[float]:
    """Beta of asset closes vs benchmark closes (aligned, same length)."""
    n = min(len(asset), len(bench), lookback + 1)
    if n < 30:
        return None
    ra = log_returns(asset[-n:])
    rb = log_returns(bench[-n:])
    m = min(len(ra), len(rb))
    ra, rb = ra[-m:], rb[-m:]
    ma, mb = sum(ra) / m, sum(rb) / m
    cov = sum((a - ma) * (b - mb) for a, b in zip(ra, rb)) / (m - 1)
    var = sum((b - mb) ** 2 for b in rb) / (m - 1)
    return cov / var if var else None


def sharpe(closes: Sequence[float], rf_annual: float = 0.04, periods: int = 252,
           lookback: int = 252) -> Optional[float]:
    r = log_returns(closes[-(lookback + 1):])
    if len(r) < 30:
        return None
    rf = rf_annual / periods
    ex = [x - rf for x in r]
    sd = stdev(ex)
    return (sum(ex) / len(ex)) / sd * math.sqrt(periods) if sd else None


# ---------------------------------------------------------------- price levels

def pivot_points(prev: Candle) -> dict:
    """Classic floor-trader pivots from the previous completed bar."""
    p = (prev.h + prev.l + prev.c) / 3
    return {
        "P": p,
        "R1": 2 * p - prev.l, "S1": 2 * p - prev.h,
        "R2": p + (prev.h - prev.l), "S2": p - (prev.h - prev.l),
        "R3": prev.h + 2 * (p - prev.l), "S3": prev.l - 2 * (prev.h - p),
    }


def fibonacci(candles: Sequence[Candle], lookback: int = 120) -> dict:
    """Retracement levels between the swing high and low of the lookback window."""
    w = candles[-lookback:]
    hi_i = max(range(len(w)), key=lambda i: w[i].h)
    lo_i = min(range(len(w)), key=lambda i: w[i].l)
    hi, lo = w[hi_i].h, w[lo_i].l
    up = lo_i < hi_i  # swing went low -> high, so retracements are measured down from the high
    levels = {}
    for r in (0.236, 0.382, 0.5, 0.618, 0.786):
        levels[f"{r * 100:.1f}%"] = hi - (hi - lo) * r if up else lo + (hi - lo) * r
    return {"swing_high": hi, "swing_low": lo, "direction": "up" if up else "down", "levels": levels}


def swing_levels(candles: Sequence[Candle], width: int = 3, lookback: int = 180,
                 tolerance: float = 0.015) -> dict:
    """Support/resistance from fractal swing highs and lows, merged when within tolerance."""
    w = candles[-lookback:]
    highs, lows = [], []
    for i in range(width, len(w) - width):
        seg = w[i - width:i + width + 1]
        if w[i].h == max(c.h for c in seg):
            highs.append(w[i].h)
        if w[i].l == min(c.l for c in seg):
            lows.append(w[i].l)

    def cluster(levels):
        levels = sorted(levels)
        groups: List[List[float]] = []
        for lv in levels:
            if groups and abs(lv / groups[-1][-1] - 1) <= tolerance:
                groups[-1].append(lv)
            else:
                groups.append([lv])
        return [{"level": sum(g) / len(g), "touches": len(g)} for g in groups]

    price = candles[-1].c
    allv = cluster(highs + lows)
    support = sorted([x for x in allv if x["level"] < price], key=lambda x: -x["level"])[:3]
    resistance = sorted([x for x in allv if x["level"] > price], key=lambda x: x["level"])[:3]
    return {"support": support, "resistance": resistance}


def last(series: Sequence[Optional[float]], back: int = 0) -> Optional[float]:
    idx = len(series) - 1 - back
    return series[idx] if 0 <= idx < len(series) else None
