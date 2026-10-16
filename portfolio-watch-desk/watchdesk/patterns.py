"""Candlestick pattern recognition.

Shapes are judged relative to each bar's own range and to the recent
average range, and reversal patterns only count when they appear after
a move in the opposite direction (a hammer means nothing in an uptrend).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import List, Optional, Sequence

from .models import Candle


@dataclass
class Pattern:
    name: str
    direction: str  # bullish | bearish | neutral
    strength: int  # 1 weak .. 3 strong
    index: int  # index of the bar that completes the pattern
    bars: int
    meaning: str

    def to_dict(self) -> dict:
        return asdict(self)


def _body(c: Candle) -> float:
    return abs(c.c - c.o)


def _range(c: Candle) -> float:
    return max(c.h - c.l, 1e-12)


def _upper(c: Candle) -> float:
    return c.h - max(c.o, c.c)


def _lower(c: Candle) -> float:
    return min(c.o, c.c) - c.l


def _bull(c: Candle) -> bool:
    return c.c > c.o


def _bear(c: Candle) -> bool:
    return c.c < c.o


def _mid(c: Candle) -> float:
    return (c.o + c.c) / 2


def trend_before(candles: Sequence[Candle], i: int, lookback: int = 6) -> str:
    """'up', 'down' or 'flat' for the bars leading into index i (exclusive)."""
    start = i - lookback
    if start < 0:
        return "flat"
    first, last = candles[start].c, candles[i - 1].c
    avg_rng = sum(_range(c) for c in candles[start:i]) / lookback
    move = last - first
    if move > avg_rng * 1.0:
        return "up"
    if move < -avg_rng * 1.0:
        return "down"
    return "flat"


def _avg_body(candles: Sequence[Candle], i: int, n: int = 10) -> float:
    w = candles[max(0, i - n):i] or candles[i:i + 1]
    return max(sum(_body(c) for c in w) / len(w), 1e-12)


def detect_at(candles: Sequence[Candle], i: int) -> List[Pattern]:
    """All patterns completed by the bar at index i."""
    out: List[Pattern] = []
    c = candles[i]
    trend = trend_before(candles, i)
    body, rng, up, lo = _body(c), _range(c), _upper(c), _lower(c)
    avgb = _avg_body(candles, i)

    def add(name, direction, strength, bars, meaning):
        out.append(Pattern(name, direction, strength, i, bars, meaning))

    # ---- single-bar shapes
    is_doji = body <= rng * 0.1
    if is_doji:
        if lo >= rng * 0.6 and up <= rng * 0.1:
            add("Dragonfly Doji", "bullish" if trend == "down" else "neutral", 2 if trend == "down" else 1, 1,
                "Sellers pushed price down but buyers closed it at the high: possible bottom.")
        elif up >= rng * 0.6 and lo <= rng * 0.1:
            add("Gravestone Doji", "bearish" if trend == "up" else "neutral", 2 if trend == "up" else 1, 1,
                "Buyers pushed price up but sellers closed it at the low: possible top.")
        else:
            add("Doji", "neutral", 1, 1, "Open and close are almost equal: indecision, often before a turn.")
    else:
        small_body = body <= rng * 0.35
        if small_body and lo >= body * 2 and up <= body * 0.5 + rng * 0.05:
            if trend == "down":
                add("Hammer", "bullish", 2, 1, "Long lower shadow after a decline: buyers rejected lower prices.")
            elif trend == "up":
                add("Hanging Man", "bearish", 1, 1, "Hammer shape after a rally: selling pressure is appearing.")
        if small_body and up >= body * 2 and lo <= body * 0.5 + rng * 0.05:
            if trend == "up":
                add("Shooting Star", "bearish", 2, 1, "Long upper shadow after a rally: buyers were rejected at the highs.")
            elif trend == "down":
                add("Inverted Hammer", "bullish", 1, 1, "Long upper shadow after a decline: first sign of buying interest.")
        if body >= rng * 0.9 and body >= avgb * 1.3:
            if _bull(c):
                add("Bullish Marubozu", "bullish", 2, 1, "Full-bodied up bar with no shadows: buyers in control all session.")
            else:
                add("Bearish Marubozu", "bearish", 2, 1, "Full-bodied down bar with no shadows: sellers in control all session.")
        elif body <= rng * 0.3 and up >= rng * 0.25 and lo >= rng * 0.25:
            add("Spinning Top", "neutral", 1, 1, "Small body with shadows both ways: the trend is losing conviction.")

    # ---- two-bar patterns
    if i >= 1:
        p = candles[i - 1]
        pb = _body(p)
        t2 = trend_before(candles, i - 1)
        if _bear(p) and _bull(c) and c.o <= p.c and c.c >= p.o and body > pb and t2 != "up":
            add("Bullish Engulfing", "bullish", 3 if t2 == "down" else 2, 2,
                "An up bar fully swallows the prior down bar: buyers took over.")
        if _bull(p) and _bear(c) and c.o >= p.c and c.c <= p.o and body > pb and t2 != "down":
            add("Bearish Engulfing", "bearish", 3 if t2 == "up" else 2, 2,
                "A down bar fully swallows the prior up bar: sellers took over.")
        if _bear(p) and pb >= avgb and body <= pb * 0.5 and max(c.o, c.c) <= p.o and min(c.o, c.c) >= p.c and t2 == "down":
            add("Bullish Harami", "bullish", 1, 2, "A small bar inside a big down bar: selling is slowing.")
        if _bull(p) and pb >= avgb and body <= pb * 0.5 and max(c.o, c.c) <= p.c and min(c.o, c.c) >= p.o and t2 == "up":
            add("Bearish Harami", "bearish", 1, 2, "A small bar inside a big up bar: buying is slowing.")
        if _bear(p) and _bull(c) and t2 == "down" and pb >= avgb and c.o < p.c and _mid(p) < c.c < p.o:
            add("Piercing Line", "bullish", 2, 2, "Opens below the prior close and recovers past the midpoint of the down bar.")
        if _bull(p) and _bear(c) and t2 == "up" and pb >= avgb and c.o > p.c and p.o < c.c < _mid(p):
            add("Dark Cloud Cover", "bearish", 2, 2, "Opens above the prior close and falls below the midpoint of the up bar.")
        tol = _range(c) * 0.05 + _range(p) * 0.05
        if t2 == "up" and abs(c.h - p.h) <= tol and _bull(p) and _bear(c):
            add("Tweezer Top", "bearish", 1, 2, "Two bars fail at the same high: resistance.")
        if t2 == "down" and abs(c.l - p.l) <= tol and _bear(p) and _bull(c):
            add("Tweezer Bottom", "bullish", 1, 2, "Two bars hold the same low: support.")

    # ---- three-bar patterns
    if i >= 2:
        a, b = candles[i - 2], candles[i - 1]
        t3 = trend_before(candles, i - 2)
        ab, bb = _body(a), _body(b)
        if (_bear(a) and ab >= avgb and bb <= ab * 0.5 and max(b.o, b.c) <= a.c + _range(a) * 0.1
                and _bull(c) and c.c > _mid(a) and t3 != "up"):
            add("Morning Star", "bullish", 3, 3, "Big down bar, small pause, strong up bar: a classic bottom reversal.")
        if (_bull(a) and ab >= avgb and bb <= ab * 0.5 and min(b.o, b.c) >= a.c - _range(a) * 0.1
                and _bear(c) and c.c < _mid(a) and t3 != "down"):
            add("Evening Star", "bearish", 3, 3, "Big up bar, small pause, strong down bar: a classic top reversal.")
        three = (a, b, c)
        if (all(_bull(x) for x in three) and a.c < b.c < c.c and a.o < b.o <= a.c and b.o < c.o <= b.c
                and all(_body(x) >= _range(x) * 0.5 for x in three)):
            add("Three White Soldiers", "bullish", 3, 3, "Three strong up bars, each closing higher: sustained buying.")
        if (all(_bear(x) for x in three) and a.c > b.c > c.c and a.c <= b.o < a.o and b.c <= c.o < b.o
                and all(_body(x) >= _range(x) * 0.5 for x in three)):
            add("Three Black Crows", "bearish", 3, 3, "Three strong down bars, each closing lower: sustained selling.")
        if (_bear(a) and ab >= avgb and bb <= ab * 0.5 and _bull(b) and max(b.o, b.c) <= a.o
                and min(b.o, b.c) >= a.c and _bull(c) and c.c > a.o):
            add("Three Inside Up", "bullish", 2, 3, "A bullish harami confirmed by a close above the first bar.")
        if (_bull(a) and ab >= avgb and bb <= ab * 0.5 and _bear(b) and max(b.o, b.c) <= a.c
                and min(b.o, b.c) >= a.o and _bear(c) and c.c < a.o):
            add("Three Inside Down", "bearish", 2, 3, "A bearish harami confirmed by a close below the first bar.")
    return out


def detect(candles: Sequence[Candle], recent: int = 3) -> List[Pattern]:
    """Patterns completed in the last ``recent`` bars, newest first."""
    out: List[Pattern] = []
    for i in range(max(0, len(candles) - recent), len(candles)):
        out.extend(detect_at(candles, i))
    out.sort(key=lambda p: (-p.index, -p.strength))
    return out


def scan_history(candles: Sequence[Candle], start: int = 0) -> List[Pattern]:
    """Every directional pattern in the series, for chart markers and backtests."""
    out: List[Pattern] = []
    for i in range(max(start, 0), len(candles)):
        out.extend(p for p in detect_at(candles, i) if p.direction != "neutral")
    return out


def strongest(patterns: Sequence[Pattern]) -> Optional[Pattern]:
    directional = [p for p in patterns if p.direction != "neutral"]
    return max(directional, key=lambda p: (p.strength, p.index)) if directional else None
