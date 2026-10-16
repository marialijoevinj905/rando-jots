"""The watcher: polls prices, re-runs the analysis, fires alerts and publishes state."""
from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

from . import market_hours as mh
from .alerts import AlertLog, AlertRules, CallbackChannel, build_channels, dispatch
from .config import load_portfolio, save_portfolio
from .models import Alert, Candle, Holding, Quote
from .news import NewsFeed
from .providers import Provider, ProviderError, RateLimited, make_provider
from .signals import Series, Settings, analyze, backtest

log = logging.getLogger("watchdesk.engine")


class Hub:
    """Fan-out of server-sent events to connected browsers."""

    def __init__(self):
        self._subs: List[queue.Queue] = []
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=50)
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q: queue.Queue):
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def publish(self, event: str, data) -> None:
        msg = (event, json.dumps(data, default=str))
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(msg)
            except queue.Full:  # slow client: drop its oldest message
                try:
                    q.get_nowait()
                    q.put_nowait(msg)
                except queue.Empty:
                    pass

    @property
    def clients(self) -> int:
        with self._lock:
            return len(self._subs)


def _ny_date(ts: int) -> str:
    return mh.to_ny(ts).strftime("%Y-%m-%d")


def merge_live(daily: List[Candle], intraday: List[Candle], quote: Optional[Quote]) -> List[Candle]:
    """Daily bars with today's bar rebuilt from live data, so indicators move intraday."""
    out = [Candle(**c.to_dict()) for c in daily]
    if not quote:
        return out
    today = _ny_date(quote.time or int(time.time()))
    regular = [b for b in intraday if _ny_date(b.t) == today and mh.session(b.t) == "open"]
    price = quote.price
    if out and _ny_date(out[-1].t) == today:
        bar = out[-1]
        if regular:
            bar.h = max(bar.h, max(b.h for b in regular))
            bar.l = min(bar.l, min(b.l for b in regular))
        bar.h, bar.l, bar.c = max(bar.h, price), min(bar.l, price), price
        if quote.volume:
            bar.v = max(bar.v, float(quote.volume))
    elif regular:
        o = regular[0].o
        out.append(Candle(regular[0].t, o, max(max(b.h for b in regular), price), min(min(b.l for b in regular), price),
                          price, float(quote.volume or sum(b.v for b in regular))))
    return out


class Watcher:
    def __init__(self, cfg: dict, provider: Optional[Provider] = None, news: Optional[NewsFeed] = None,
                 hub: Optional[Hub] = None, channels=None):
        self.cfg = cfg
        self.provider = provider or make_provider(cfg)
        self.hub = hub or Hub()
        self.news = news if news is not None else NewsFeed(cfg.get("news_queries"))
        self.settings = Settings.from_dict(cfg.get("settings"))
        self.rules = AlertRules(cfg.get("alert_rules"))
        os.makedirs(cfg["state_dir"], exist_ok=True)
        self.alert_log = AlertLog(os.path.join(cfg["state_dir"], "alerts.json"),
                                  cooldown=float(cfg.get("alert_cooldown_seconds", 21600)))
        self.channels = list(channels) if channels is not None else build_channels(cfg)
        self.channels.append(CallbackChannel(lambda alerts: self.hub.publish("alerts", [a.to_dict() for a in alerts])))
        self.portfolio = load_portfolio(cfg["portfolio_file"])
        self.lock = threading.RLock()
        self.quotes: Dict[str, Quote] = {}
        self.intraday: Dict[str, List[Candle]] = {}
        self.daily: Dict[str, List[Candle]] = {}
        self.daily_at: Dict[str, float] = {}
        self.analyses: Dict[str, dict] = {}
        self._bt_cache: Dict[str, tuple] = {}
        self.errors: Dict[str, str] = {}
        self.status = {"provider": self.provider.name, "session": mh.session(), "last_tick": None,
                       "tick_ms": None, "next_tick": None, "ticks": 0, "news_at": None, "news_errors": []}
        self._news_at = 0.0
        self._news_thread: Optional[threading.Thread] = None
        self._alert_q: "queue.Queue[List[Alert]]" = queue.Queue()
        self._stop = threading.Event()
        self._pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix="fetch")

    # ------------------------------------------------------------ portfolio
    def holdings(self) -> Dict[str, Holding]:
        return {h.symbol: h for h in self.portfolio["holdings"]}

    def tracked(self) -> List[str]:
        """Symbols that get the full analysis: holdings, then watchlist."""
        out = [h.symbol for h in self.portfolio["holdings"]]
        out += [s for s in self.portfolio["watchlist"] if s not in out]
        return out

    def all_symbols(self) -> List[str]:
        out = self.tracked()
        bench = self.cfg.get("benchmark")
        for s in ([bench] if bench else []) + list(self.cfg.get("tape", [])):
            if s not in out:
                out.append(s)
        return out

    def set_portfolio(self, p: dict, sync: bool = False) -> None:
        with self.lock:
            self.portfolio = p
            save_portfolio(self.cfg["portfolio_file"], p)
        if sync:
            self.tick()
        else:  # refresh in the background so the request that saved it returns at once
            threading.Thread(target=self.tick, name="tick-on-save", daemon=True).start()

    # ------------------------------------------------------------ fetching
    def _fetch_live(self, sym: str):
        try:
            q, bars = self.provider.live(sym)
            return sym, q, bars, None
        except RateLimited as e:
            return sym, None, None, f"rate limited ({e})"
        except (ProviderError, ValueError, KeyError, TypeError) as e:
            return sym, None, None, str(e)

    def _fetch_daily(self, sym: str):
        try:
            return sym, self.provider.daily(sym), None
        except (ProviderError, ValueError, KeyError, TypeError) as e:
            return sym, None, str(e)

    def tick(self) -> dict:
        started = time.time()
        syms = self.all_symbols()
        live = list(self._pool.map(self._fetch_live, syms))
        refresh = float(self.cfg.get("daily_refresh_seconds", 1800))
        need_daily = [s for s in syms if s not in self.daily or started - self.daily_at.get(s, 0) > refresh]
        daily = list(self._pool.map(self._fetch_daily, need_daily)) if need_daily else []
        with self.lock:
            for sym, q, bars, err in live:
                if err:
                    self.errors[sym] = err
                    continue
                self.errors.pop(sym, None)
                self.quotes[sym] = q
                self.intraday[sym] = bars or []
            for sym, bars, err in daily:
                if err:
                    self.errors[sym] = "history: " + err
                elif bars:
                    self.daily[sym] = bars
                    self.daily_at[sym] = started
            self._analyze_all()
            fired = self._alerts()
            self.status.update(session=mh.session(), last_tick=int(time.time()), tick_ms=int((time.time() - started) * 1000),
                               ticks=self.status["ticks"] + 1)
            snap = self.snapshot()
        if fired:
            self._alert_q.put(fired)
        self.hub.publish("state", snap)
        self._maybe_refresh_news()
        return snap

    def _analyze_all(self):
        holdings = self.holdings()
        bench_sym = self.cfg.get("benchmark")
        bench = merge_live(self.daily.get(bench_sym, []), self.intraday.get(bench_sym, []), self.quotes.get(bench_sym))
        pv = self.portfolio_value()
        for sym in self.tracked():
            d = self.daily.get(sym)
            if not d:
                continue
            q = self.quotes.get(sym)
            merged = merge_live(d, self.intraday.get(sym, []), q)
            today = _ny_date(int(time.time()))
            cached = self._bt_cache.get(sym)
            if not cached or cached[0] != today:
                cached = (today, backtest(Series(merged)))
                self._bt_cache[sym] = cached
            intr = [b for b in self.intraday.get(sym, []) if q and _ny_date(b.t) == _ny_date(q.time or b.t)]
            self.analyses[sym] = analyze(sym, merged, intr or None, holdings.get(sym), bench or None, pv,
                                         self.settings, backtest_result=cached[1])

    def _alerts(self) -> List[Alert]:
        holdings = self.holdings()
        live_bar = mh.session() in ("open", "pre")
        found: List[Alert] = []
        for sym in self.tracked():
            found += self.rules.evaluate(sym, self.quotes.get(sym), self.analyses.get(sym), holdings.get(sym),
                                         live_bar=live_bar)
        return self.alert_log.fresh(found)

    def _maybe_refresh_news(self, wait: bool = False):
        interval = float(self.cfg.get("news_refresh_seconds", 600))
        if self.news is None or time.time() - self._news_at < interval:
            return
        if self._news_thread and self._news_thread.is_alive():
            return
        self._news_at = time.time()

        def run():
            try:
                new = self.news.refresh(self.tracked())
                with self.lock:
                    self.status.update(news_at=int(time.time()), news_errors=self.news.errors[:10])
                fired = self.alert_log.fresh(self.rules.news_alerts(new, self.holdings()))
                if fired:
                    self._alert_q.put(fired)
                self.hub.publish("news", self.news.latest(60))
            except Exception as e:  # never let news break the price loop
                log.warning("news refresh failed: %s", e)

        self._news_thread = threading.Thread(target=run, name="news", daemon=True)
        self._news_thread.start()
        if wait:
            self._news_thread.join(timeout=120)

    def flush_alerts(self) -> List[str]:
        errors = []
        while True:
            try:
                batch = self._alert_q.get_nowait()
            except queue.Empty:
                return errors
            errors += dispatch(self.channels, batch)

    # ------------------------------------------------------------ views
    def portfolio_value(self) -> float:
        total = float(self.portfolio.get("cash", 0))
        for h in self.portfolio["holdings"]:
            q = self.quotes.get(h.symbol)
            total += h.shares * (q.price if q else h.cost)
        return total

    def portfolio_rows(self) -> dict:
        rows, total, day, basis = [], float(self.portfolio.get("cash", 0)), 0.0, 0.0
        for h in self.portfolio["holdings"]:
            q = self.quotes.get(h.symbol)
            price = q.price if q else None
            value = h.shares * price if price is not None else None
            dchg = h.shares * q.change if q and q.change is not None else None
            a = self.analyses.get(h.symbol) or {}
            pat = next((p for p in a.get("patterns", []) if p["direction"] != "neutral"), None)
            rows.append({
                "symbol": h.symbol, "name": q.name if q else "", "shares": h.shares, "cost": h.cost,
                "target": h.target, "stop": h.stop, "price": price, "change_pct": q.change_pct if q else None,
                "ext_price": q.ext_price if q else None, "value": value, "day_change": dchg,
                "pnl": value - h.shares * h.cost if value is not None else None,
                "pnl_pct": (price / h.cost - 1) * 100 if price and h.cost else None,
                "score": a.get("score"), "label": a.get("label"), "pattern": pat["name"] if pat else None,
                "pattern_dir": pat["direction"] if pat else None,
                "top_suggestion": (a.get("suggestions") or [{}])[0].get("text"), "error": self.errors.get(h.symbol),
            })
            if value is not None:
                total += value
                basis += h.shares * h.cost
            if dchg is not None:
                day += dchg
        for r in rows:
            r["weight"] = r["value"] / total * 100 if r["value"] is not None and total else None
        invested = total - float(self.portfolio.get("cash", 0))
        return {"rows": rows, "total": total, "cash": self.portfolio.get("cash", 0), "invested": invested,
                "basis": basis, "pnl": invested - basis if basis else 0.0, "day_change": day,
                "day_change_pct": day / (invested - day) * 100 if invested - day else 0.0}

    def snapshot(self) -> dict:
        labels = self.cfg.get("tape_labels", {})
        tape = []
        for s in self.cfg.get("tape", []):
            q = self.quotes.get(s)
            tape.append({"symbol": s, "label": labels.get(s, s), "price": q.price if q else None,
                         "change_pct": q.change_pct if q else None, "ext_price": q.ext_price if q else None})
        watch = []
        for s in self.portfolio["watchlist"]:
            q, a = self.quotes.get(s), self.analyses.get(s) or {}
            watch.append({"symbol": s, "name": q.name if q else "", "price": q.price if q else None,
                          "change_pct": q.change_pct if q else None, "score": a.get("score"), "label": a.get("label"),
                          "error": self.errors.get(s)})
        st = dict(self.status)
        st["clients"] = self.hub.clients
        st["errors"] = dict(self.errors)
        st["interval"] = self.interval()
        return {"status": st, "tape": tape, "portfolio": self.portfolio_rows(), "watchlist": watch,
                "settings": self.settings.__dict__, "alerts": self.alert_log.history[-50:][::-1]}

    def candles(self, sym: str, tf: str = "1d") -> List[dict]:
        with self.lock:
            if tf == "1m":
                return [c.to_dict() for c in self.intraday.get(sym, [])]
            return [c.to_dict() for c in merge_live(self.daily.get(sym, []), self.intraday.get(sym, []), self.quotes.get(sym))]

    def interval(self) -> float:
        has_crypto = any(mh.is_crypto(s) for s in self.tracked())
        return mh.poll_interval(self.cfg.get("poll_seconds", {}), has_crypto=has_crypto)

    # ------------------------------------------------------------ loop
    def run_forever(self):
        log.info("watching %d symbols with the %s provider", len(self.all_symbols()), self.provider.name)
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("tick failed; retrying next interval")
            self.flush_alerts()
            wait = self.interval()
            self.status["next_tick"] = int(time.time() + wait)
            self._stop.wait(wait)

    def start(self) -> threading.Thread:
        t = threading.Thread(target=self.run_forever, name="watcher", daemon=True)
        t.start()
        return t

    def stop(self):
        self._stop.set()
        self._pool.shutdown(wait=False, cancel_futures=True)

    def scan_once(self) -> dict:
        """One full pass with news, then deliver alerts. For cron jobs and GitHub Actions."""
        self._news_at = 0.0
        snap = self.tick()
        if self._news_thread:
            self._news_thread.join(timeout=120)
        errors = self.flush_alerts()
        return {"snapshot": snap, "alert_errors": errors}
