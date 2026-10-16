"""Plain data types shared across the watcher."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass
class Candle:
    t: int  # bar open time, unix seconds (UTC)
    o: float
    h: float
    l: float  # noqa: E741 - OHLC convention
    c: float
    v: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Quote:
    symbol: str
    price: float
    prev_close: Optional[float] = None
    time: int = 0  # unix seconds of the last trade
    volume: Optional[float] = None
    name: str = ""
    currency: str = "USD"
    exchange: str = ""
    ext_price: Optional[float] = None  # latest pre/post-market trade, when newer than the regular close
    source: str = ""

    @property
    def change(self) -> Optional[float]:
        if self.prev_close in (None, 0):
            return None
        return self.price - self.prev_close

    @property
    def change_pct(self) -> Optional[float]:
        if self.prev_close in (None, 0):
            return None
        return (self.price / self.prev_close - 1.0) * 100.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["change"] = self.change
        d["change_pct"] = self.change_pct
        d["ext_change_pct"] = ((self.ext_price / self.price - 1) * 100) if self.ext_price and self.price else None
        return d


@dataclass
class Holding:
    symbol: str
    shares: float
    cost: float  # average cost per share
    target: Optional[float] = None
    stop: Optional[float] = None
    note: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "Holding":
        sym = str(d.get("symbol", "")).strip().upper()
        if not sym:
            raise ValueError("holding needs a symbol")
        shares = float(d.get("shares", 0))
        cost = float(d.get("cost", 0))
        if shares <= 0:
            raise ValueError(f"{sym}: shares must be more than zero")
        if cost < 0:
            raise ValueError(f"{sym}: cost can't be negative")

        def opt(k):
            v = d.get(k)
            return float(v) if v not in (None, "") and float(v) > 0 else None

        return cls(sym, shares, cost, opt("target"), opt("stop"), str(d.get("note", ""))[:200])

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v not in (None, "")}


@dataclass
class Alert:
    key: str  # dedupe key, e.g. "NVDA:pattern:Bullish Engulfing:2026-10-15"
    symbol: str
    severity: str  # info | warn | critical
    title: str
    body: str
    time: int
    kind: str = "signal"
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)
