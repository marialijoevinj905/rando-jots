"""Turns candles into a scored technical read and position-aware suggestions.

The score runs from -100 (strongly bearish) to +100 (strongly bullish) and is
the sum of named components, so every suggestion can show its working.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from . import indicators as ind
from .models import Candle, Holding
from .patterns import Pattern, detect, detect_at, scan_history, strongest

LABELS = [(50, "Strong buy"), (20, "Buy"), (-20, "Hold"), (-50, "Reduce")]


def label_for(score: float) -> str:
    for threshold, name in LABELS:
        if score >= threshold:
            return name
    return "Sell"


@dataclass
class Settings:
    risk_per_trade_pct: float = 1.0  # % of portfolio risked between entry and stop
    max_position_pct: float = 20.0  # concentration limit per holding
    atr_stop_mult: float = 2.0
    chandelier_mult: float = 3.0
    risk_free_rate: float = 0.04

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "Settings":
        s = cls()
        for k, v in (d or {}).items():
            if hasattr(s, k):
                setattr(s, k, float(v))
        return s


class Series:
    """All indicator series for one candle list, computed once."""

    def __init__(self, candles: Sequence[Candle]):
        self.candles = list(candles)
        c = [x.c for x in self.candles]
        self.closes = c
        self.sma20 = ind.sma(c, 20)
        self.sma50 = ind.sma(c, 50)
        self.sma200 = ind.sma(c, 200)
        self.ema9 = ind.ema(c, 9)
        self.rsi = ind.rsi(c, 14)
        self.macd, self.macd_sig, self.macd_hist = ind.macd(c)
        self.bb_mid, self.bb_up, self.bb_lo, self.bb_pb, self.bb_bw = ind.bollinger(c)
        self.atr = ind.atr(self.candles, 14)
        self.stoch_k, self.stoch_d = ind.stochastic(self.candles)
        self.adx, self.pdi, self.mdi = ind.adx(self.candles)
        self.obv = ind.obv(self.candles)
        self.vol_avg = ind.sma([x.v for x in self.candles], 20)


def _crossed(a: List[Optional[float]], b: List[Optional[float]], i: int, within: int) -> int:
    """+1 if a crossed above b in the last `within` bars up to i, -1 if below, else 0."""
    for j in range(i, max(i - within, 0), -1):
        a0, b0, a1, b1 = a[j - 1], b[j - 1], a[j], b[j]
        if None in (a0, b0, a1, b1):
            continue
        if a0 <= b0 and a1 > b1:
            return 1
        if a0 >= b0 and a1 < b1:
            return -1
    return 0


def score_at(s: Series, i: int, patterns: Optional[List[Pattern]] = None):
    """Score bar i. Returns (score, components)."""
    comps: List[dict] = []
    price = s.closes[i]

    def add(group, name, pts, reason):
        if pts:
            comps.append({"group": group, "name": name, "points": round(pts, 1), "reason": reason})

    # --- trend
    if s.sma50[i] is not None:
        d = (price / s.sma50[i] - 1) * 100
        add("Trend", "Price vs 50-day average", 8 if d > 0 else -8,
            f"Price is {abs(d):.1f}% {'above' if d > 0 else 'below'} its 50-day average.")
    if s.sma200[i] is not None:
        d = (price / s.sma200[i] - 1) * 100
        add("Trend", "Price vs 200-day average", 10 if d > 0 else -10,
            f"Price is {abs(d):.1f}% {'above' if d > 0 else 'below'} its 200-day average "
            f"({'long-term uptrend' if d > 0 else 'long-term downtrend'}).")
    if s.sma50[i] is not None and s.sma200[i] is not None:
        cross = _crossed(s.sma50, s.sma200, i, 10)
        if cross:
            add("Trend", "Golden cross" if cross > 0 else "Death cross", 7 * cross,
                "The 50-day average just crossed " + ("above" if cross > 0 else "below") + " the 200-day.")
        else:
            up = s.sma50[i] > s.sma200[i]
            add("Trend", "50 vs 200-day alignment", 4 if up else -4,
                f"50-day average is {'above' if up else 'below'} the 200-day.")
    if s.adx[i] is not None and s.pdi[i] is not None and s.adx[i] >= 25:
        bull = s.pdi[i] > s.mdi[i]
        add("Trend", "ADX trend strength", 5 if bull else -5,
            f"ADX {s.adx[i]:.0f} shows a strong trend, with {'buyers (+DI)' if bull else 'sellers (−DI)'} in control.")

    # --- momentum
    if s.macd_hist[i] is not None:
        cross = _crossed(s.macd, s.macd_sig, i, 3)
        if cross:
            add("Momentum", "MACD cross", 10 * cross,
                f"MACD just crossed {'above' if cross > 0 else 'below'} its signal line.")
        else:
            pos = s.macd_hist[i] > 0
            rising = s.macd_hist[i - 1] is not None and s.macd_hist[i] > s.macd_hist[i - 1]
            add("Momentum", "MACD histogram", (5 if pos else -5) + (1 if rising else -1),
                f"MACD histogram is {'positive' if pos else 'negative'} and {'rising' if rising else 'falling'}.")
    r = s.rsi[i]
    if r is not None:
        if r >= 70:
            add("Momentum", "RSI overbought", -8, f"RSI {r:.0f} is overbought (above 70); pullback risk is higher.")
        elif r <= 30:
            add("Momentum", "RSI oversold", 8, f"RSI {r:.0f} is oversold (below 30); bounce odds are higher.")
        elif r >= 50:
            add("Momentum", "RSI", 4, f"RSI {r:.0f} is above 50: momentum favors buyers.")
        else:
            add("Momentum", "RSI", -4, f"RSI {r:.0f} is below 50: momentum favors sellers.")
    k, dd = s.stoch_k[i], s.stoch_d[i]
    if k is not None and dd is not None:
        cross = _crossed(s.stoch_k, s.stoch_d, i, 2)
        if k < 25 and cross > 0:
            add("Momentum", "Stochastic", 5, f"Stochastic turned up from oversold ({k:.0f}).")
        elif k > 75 and cross < 0:
            add("Momentum", "Stochastic", -5, f"Stochastic turned down from overbought ({k:.0f}).")

    # --- mean reversion
    pb = s.bb_pb[i]
    if pb is not None:
        if pb > 1:
            add("Stretch", "Above upper Bollinger Band", -6, "Price closed above the upper Bollinger Band: stretched.")
        elif pb < 0:
            add("Stretch", "Below lower Bollinger Band", 6, "Price closed below the lower Bollinger Band: stretched to the downside.")
    if i >= 19:
        z = ind.zscore(s.closes[:i + 1], 20)
        if z is not None and abs(z) >= 2:
            add("Stretch", "20-day z-score", -4 if z > 0 else 4,
                f"Price is {abs(z):.1f} standard deviations {'above' if z > 0 else 'below'} its 20-day mean.")

    # --- volume
    if i >= 20:
        obv_slope, _, _ = ind.linreg(s.obv[i - 19:i + 1])
        px_slope, _, _ = ind.linreg(s.closes[i - 19:i + 1])
        if obv_slope > 0 and px_slope > 0:
            add("Volume", "On-balance volume", 5, "Volume is confirming the rise (OBV trending up).")
        elif obv_slope < 0 and px_slope < 0:
            add("Volume", "On-balance volume", -5, "Volume is confirming the decline (OBV trending down).")
        elif obv_slope > 0 > px_slope:
            add("Volume", "OBV divergence", 4, "Bullish divergence: OBV rising while price falls (accumulation).")
        elif obv_slope < 0 < px_slope:
            add("Volume", "OBV divergence", -4, "Bearish divergence: OBV falling while price rises (distribution).")
    va = s.vol_avg[i - 1] if i >= 1 else None
    bar = s.candles[i]
    if va and bar.v > 2 * va:
        up = bar.c >= bar.o
        add("Volume", "Volume spike", 5 if up else -5,
            f"Volume is {bar.v / va:.1f}× its 20-day average on a {'rising' if up else 'falling'} bar.")

    # --- candlesticks
    pats = patterns if patterns is not None else [p for j in range(max(0, i - 2), i + 1) for p in detect_at(s.candles, j)]
    best = strongest(pats)
    if best:
        age = i - best.index
        decay = {0: 1.0, 1: 0.75, 2: 0.5}.get(age, 0.0)
        sign = 1 if best.direction == "bullish" else -1
        add("Pattern", best.name, sign * best.strength * 6 * decay,
            f"{best.name} ({'today' if age == 0 else f'{age} bar' + ('s' if age > 1 else '') + ' ago'}): {best.meaning}")

    total = max(-100.0, min(100.0, sum(c["points"] for c in comps)))
    return total, comps


def backtest(s: Series, horizons=(5, 20), start: int = 200) -> dict:
    """How this stock moved after past signals of each kind (same rules, no look-ahead)."""
    n = len(s.closes)
    h_max = max(horizons)
    out = {"bars_tested": 0, "horizons": {}}
    if n < start + h_max + 10:
        start = max(60, n - h_max - 120)
    if n < start + h_max + 5:
        return out
    scores = []
    for i in range(start, n - min(horizons)):
        sc, _ = score_at(s, i)
        scores.append((i, sc))
    out["bars_tested"] = len(scores)
    for h in horizons:
        buy, sell, base = [], [], []
        for i, sc in scores:
            if i + h >= n:
                continue
            fwd = (s.closes[i + h] / s.closes[i] - 1) * 100
            base.append(fwd)
            if sc >= 20:
                buy.append(fwd)
            elif sc <= -20:
                sell.append(fwd)

        def stats(xs, want_up=True):
            if not xs:
                return {"count": 0}
            hits = sum(1 for x in xs if (x > 0) == want_up)
            return {"count": len(xs), "hit_rate": hits / len(xs) * 100, "avg_return": sum(xs) / len(xs)}

        out["horizons"][str(h)] = {"buy": stats(buy, True), "sell": stats(sell, False), "all": stats(base, True)}
    return out


def pattern_track_record(s: Series, names: Sequence[str], horizon: int = 5) -> Dict[str, dict]:
    """For each named pattern, how often price moved its way `horizon` bars later in this stock's history."""
    res: Dict[str, dict] = {}
    if not names:
        return res
    hist = scan_history(s.candles[:-horizon] if len(s.candles) > horizon else [], start=10)
    for name in set(names):
        hits = rets = 0
        count = 0
        for p in hist:
            if p.name != name:
                continue
            i = p.index
            if i + horizon >= len(s.closes):
                continue
            fwd = (s.closes[i + horizon] / s.closes[i] - 1) * 100
            count += 1
            rets += fwd
            if (fwd > 0) == (p.direction == "bullish"):
                hits += 1
        res[name] = {"count": count, "hit_rate": hits / count * 100 if count else None,
                     "avg_return": rets / count if count else None, "horizon": horizon}
    return res


def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def touch_probability(price: float, level: float, sigma_daily: float, days: int) -> Optional[float]:
    """Chance price touches `level` within `days` under a driftless random walk (reflection principle)."""
    if not level or sigma_daily <= 0 or price <= 0:
        return None
    d = abs(math.log(level / price)) / (sigma_daily * math.sqrt(days))
    return min(1.0, 2 * (1 - _norm_cdf(d))) * 100


def resample(candles: Sequence[Candle], seconds: int) -> List[Candle]:
    out: List[Candle] = []
    for c in candles:
        t = c.t - c.t % seconds
        if out and out[-1].t == t:
            b = out[-1]
            b.h, b.l, b.c, b.v = max(b.h, c.h), min(b.l, c.l), c.c, b.v + c.v
        else:
            out.append(Candle(t, c.o, c.h, c.l, c.c, c.v))
    return out


def analyze(symbol: str, daily: Sequence[Candle], intraday: Optional[Sequence[Candle]] = None,
            holding: Optional[Holding] = None, bench: Optional[Sequence[Candle]] = None,
            portfolio_value: Optional[float] = None, settings: Optional[Settings] = None,
            with_backtest: bool = True, backtest_result: Optional[dict] = None) -> dict:
    """Full technical read for one symbol. Pass ``backtest_result`` to reuse a cached backtest."""
    settings = settings or Settings()
    if len(daily) < 30:
        return {"symbol": symbol, "ok": False, "error": "Not enough price history to analyze (need 30+ daily bars)."}
    s = Series(daily)
    i = len(s.closes) - 1
    price = s.closes[i]
    pats = detect(s.candles, recent=3)
    score, comps = score_at(s, i, pats)

    atr = s.atr[i] or 0.0
    rets = ind.log_returns(s.closes[-61:])
    sigma_d = ind.stdev(rets) if len(rets) >= 10 else 0.0
    vol = sigma_d * math.sqrt(252)
    year = s.closes[-252:]
    hi52, lo52 = max(c.h for c in s.candles[-252:]), min(c.l for c in s.candles[-252:])
    day_ret = math.log(price / s.closes[i - 1]) if i >= 1 and s.closes[i - 1] > 0 else 0.0

    levels = ind.swing_levels(s.candles)
    prev = s.candles[-2] if len(s.candles) >= 2 else s.candles[-1]
    pivots = ind.pivot_points(prev)
    fib = ind.fibonacci(s.candles)
    atr_stop = price - settings.atr_stop_mult * atr if atr else None
    hh22 = max(c.h for c in s.candles[-22:])
    chandelier = hh22 - settings.chandelier_mult * atr if atr else None
    first_res = levels["resistance"][0]["level"] if levels["resistance"] else None
    take_profit = first_res if first_res and first_res > price * 1.01 else (price + 3 * atr if atr else None)
    rr = None
    if atr_stop and take_profit and price > atr_stop:
        rr = (take_profit - price) / (price - atr_stop)

    stats = {
        "volatility_annual_pct": vol * 100,
        "sigma_daily_pct": sigma_d * 100,
        "move_today_sigma": (day_ret / sigma_d) if sigma_d else None,
        "range_1d_68": [price * math.exp(-sigma_d), price * math.exp(sigma_d)] if sigma_d else None,
        "range_5d_95": [price * math.exp(-1.96 * sigma_d * math.sqrt(5)), price * math.exp(1.96 * sigma_d * math.sqrt(5))] if sigma_d else None,
        "max_drawdown_1y_pct": ind.max_drawdown(year),
        "sharpe_1y": ind.sharpe(s.closes, settings.risk_free_rate),
        "beta": ind.beta(s.closes, [c.c for c in bench]) if bench else None,
        "high_52w": hi52, "low_52w": lo52,
        "from_high_pct": (price / hi52 - 1) * 100 if hi52 else None,
        "from_low_pct": (price / lo52 - 1) * 100 if lo52 else None,
        "trend_slope_20d_pct": None, "trend_r2_20d": None,
    }
    if i >= 20:
        b, _, r2 = ind.linreg(s.closes[-20:])
        stats["trend_slope_20d_pct"] = b / price * 100
        stats["trend_r2_20d"] = r2

    latest = {
        "price": price, "sma20": s.sma20[i], "sma50": s.sma50[i], "sma200": s.sma200[i],
        "rsi14": s.rsi[i], "macd": s.macd[i], "macd_signal": s.macd_sig[i], "macd_hist": s.macd_hist[i],
        "bb_upper": s.bb_up[i], "bb_lower": s.bb_lo[i], "bb_pctb": s.bb_pb[i], "bb_width_pct": s.bb_bw[i],
        "atr14": atr, "atr_pct": atr / price * 100 if price else None,
        "stoch_k": s.stoch_k[i], "stoch_d": s.stoch_d[i], "adx": s.adx[i], "plus_di": s.pdi[i], "minus_di": s.mdi[i],
        "volume": s.candles[i].v, "volume_avg20": s.vol_avg[i - 1] if i >= 1 else None,
    }

    intraday_read = None
    if intraday:
        five = resample(intraday, 300)
        vw = ind.vwap(intraday)
        iv = ind.last(vw)
        ip = intraday[-1].c
        ir = ind.last(ind.rsi([c.c for c in five], 14)) if len(five) > 15 else None
        intraday_read = {
            "vwap": iv, "above_vwap": (ip > iv) if iv else None, "rsi14_5m": ir,
            "patterns_5m": [p.to_dict() for p in detect(five, recent=2)] if len(five) > 8 else [],
            "high": max(c.h for c in intraday), "low": min(c.l for c in intraday),
        }

    record = pattern_track_record(s, [p.name for p in pats if p.direction != "neutral"])
    result = {
        "symbol": symbol, "ok": True, "time": s.candles[i].t, "last_index": i,
        "score": round(score, 1), "label": label_for(score), "components": comps,
        "confidence": _agreement(comps),
        "patterns": [dict(p.to_dict(), t=s.candles[p.index].t, track_record=record.get(p.name)) for p in pats],
        "latest": latest, "stats": stats,
        "levels": {
            "support": levels["support"], "resistance": levels["resistance"], "pivots": pivots, "fibonacci": fib,
            "atr_stop": atr_stop, "chandelier_stop": chandelier, "take_profit": take_profit, "reward_risk": rr,
        },
        "intraday": intraday_read,
        "probabilities": {},
    }
    if sigma_d:
        probs = {}
        if take_profit:
            probs["touch_take_profit_20d"] = touch_probability(price, take_profit, sigma_d, 20)
        if atr_stop:
            probs["touch_atr_stop_20d"] = touch_probability(price, atr_stop, sigma_d, 20)
        if holding and holding.target:
            probs["touch_your_target_20d"] = touch_probability(price, holding.target, sigma_d, 20)
        if holding and holding.stop:
            probs["touch_your_stop_20d"] = touch_probability(price, holding.stop, sigma_d, 20)
        result["probabilities"] = probs
    if backtest_result is not None:
        result["backtest"] = backtest_result
    elif with_backtest:
        result["backtest"] = backtest(s)
    result["suggestions"] = suggest(result, holding, portfolio_value, settings)
    return result


def _agreement(comps: List[dict]) -> float:
    """Share of evidence (by points) pointing the same way as the total, 0-100."""
    pos = sum(c["points"] for c in comps if c["points"] > 0)
    neg = -sum(c["points"] for c in comps if c["points"] < 0)
    tot = pos + neg
    return round(max(pos, neg) / tot * 100, 0) if tot else 0.0


def _fmt(x: Optional[float]) -> str:
    return "—" if x is None else f"${x:,.2f}"


def suggest(a: dict, holding: Optional[Holding], portfolio_value: Optional[float], st: Settings) -> List[dict]:
    """Plain-language next steps from the analysis and, if held, the position itself."""
    out: List[dict] = []
    price = a["latest"]["price"]
    score, label = a["score"], a["label"]
    lv = a["levels"]
    stop = lv["atr_stop"]
    support = lv["support"][0]["level"] if lv["support"] else None
    res = lv["resistance"][0]["level"] if lv["resistance"] else None
    best = next((p for p in a["patterns"] if p["direction"] != "neutral"), None)

    def add(action, priority, text):
        out.append({"action": action, "priority": priority, "text": text})

    if best:
        tr = best.get("track_record") or {}
        hist = ""
        if tr.get("count"):
            hist = (f" In this stock's history it was followed by a move its way {tr['hit_rate']:.0f}% of the time "
                    f"over {tr['horizon']} days ({tr['count']} cases"
                    + ("; too few to rely on)." if tr["count"] < 10 else ").") )
        add("Pattern", 2, f"{best['name']} detected: {best['meaning']}{hist}")

    if holding:
        value = holding.shares * price
        pnl_pct = (price / holding.cost - 1) * 100 if holding.cost else 0.0
        weight = value / portfolio_value * 100 if portfolio_value else None
        if holding.stop and price <= holding.stop:
            add("Exit / review", 1, f"Price {_fmt(price)} is at or below your stop {_fmt(holding.stop)}. "
                "Your own plan says exit or re-justify the position now.")
        if holding.target and price >= holding.target:
            add("Take profit", 1, f"Price reached your target {_fmt(holding.target)}. Consider selling part and "
                f"trailing a stop at {_fmt(lv['chandelier_stop'])} on the rest.")
        if weight is not None and weight > st.max_position_pct + 2:  # small overshoots aren't worth a trade
            trim_value = value - portfolio_value * st.max_position_pct / 100
            add("Trim", 2, f"This position is {weight:.1f}% of the portfolio, above your {st.max_position_pct:.0f}% limit. "
                f"Selling about {trim_value / price:,.0f} shares ({_fmt(trim_value)}) brings it back to the limit.")
        if score <= -20:
            if pnl_pct > 0:
                raise_to = max((x for x in (stop, holding.stop) if x), default=None)
                add("Protect gains", 2, f"Signals are {label.lower()} ({score:+.0f}) while you're up {pnl_pct:.1f}%. "
                    f"Consider taking partial profits or raising your stop to {_fmt(raise_to)}.")
            else:
                add("Cut risk", 2, f"Signals are {label.lower()} ({score:+.0f}) and you're down {abs(pnl_pct):.1f}%. "
                    f"Decide your exit level now; the volatility-based stop is {_fmt(stop)}.")
        elif score >= 20:
            room = (st.max_position_pct - (weight or 0)) if weight is not None else None
            if room is None or room > 1:
                add("Add on pullback", 3, f"Signals are {label.lower()} ({score:+.0f}). If you want to add, a pullback toward "
                    f"support {_fmt(support)} gives a better entry than chasing; next resistance is {_fmt(res)}.")
            if pnl_pct > 15 and lv["chandelier_stop"]:
                add("Trail stop", 3, f"You're up {pnl_pct:.1f}%. A trailing (chandelier) stop at {_fmt(lv['chandelier_stop'])} "
                    "locks in most of the gain while letting the trend run.")
        else:
            add("Hold", 4, f"Signals are mixed ({score:+.0f}). Holding is reasonable; watch support {_fmt(support)} "
                f"and resistance {_fmt(res)} for the next move.")
        if not holding.stop and stop:
            add("Set a stop", 3, f"You have no stop set. A 2×ATR stop would sit at {_fmt(stop)} "
                f"({(1 - stop / price) * 100:.1f}% below the price).")
    else:
        if score >= 20 and stop and portfolio_value:
            risk_per_share = price - stop
            budget = portfolio_value * st.risk_per_trade_pct / 100
            shares = budget / risk_per_share if risk_per_share > 0 else 0
            cap = portfolio_value * st.max_position_pct / 100 / price
            shares = min(shares, cap)
            add("Buy candidate", 2, f"Signals are {label.lower()} ({score:+.0f}). Risking {st.risk_per_trade_pct:.0f}% of the "
                f"portfolio with a stop at {_fmt(stop)} sizes a position of about {shares:,.0f} shares ({_fmt(shares * price)}).")
        elif score <= -20:
            add("Avoid for now", 3, f"Signals are {label.lower()} ({score:+.0f}). Wait for a base or a bullish reversal pattern before buying.")
        else:
            add("Watch", 4, f"No clear edge ({score:+.0f}). Watch for a break above {_fmt(res)} or a hold at {_fmt(support)}.")

    bt = a.get("backtest", {}).get("horizons", {}).get("5")
    if bt:
        side = "buy" if score >= 20 else "sell" if score <= -20 else None
        if side and bt[side].get("count", 0) >= 5:
            x = bt[side]
            add("Evidence", 5, f"Over the past year on this stock, a {'buy' if side == 'buy' else 'sell'} reading like this was right "
                f"{x['hit_rate']:.0f}% of the time 5 days later ({x['count']} days, average move {x['avg_return']:+.2f}%). "
                f"Baseline: price rose on {bt['all']['hit_rate']:.0f}% of 5-day windows.")
    out.sort(key=lambda x: x["priority"])
    return out
