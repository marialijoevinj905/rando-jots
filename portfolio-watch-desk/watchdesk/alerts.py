"""Alert rules and delivery channels."""
from __future__ import annotations

import json
import logging
import os
import smtplib
import time
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Callable, Dict, List, Optional

from .models import Alert, Holding, Quote

log = logging.getLogger("watchdesk.alerts")
SEVERITY = {"info": 0, "warn": 1, "critical": 2}


def _day(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


class AlertRules:
    """Turns successive analyses into alerts. Keys carry the day or bar, so each event fires once."""

    def __init__(self, cfg: Optional[dict] = None):
        cfg = cfg or {}
        self.move_pct = float(cfg.get("move_pct", 3.0))
        self.sigma_move = float(cfg.get("sigma_move", 2.5))
        self.near_stop_pct = float(cfg.get("near_stop_pct", 3.0))
        self.min_pattern_strength = int(cfg.get("min_pattern_strength", 2))
        self.news_sentiment = int(cfg.get("news_sentiment", 3))
        self.signal_changes = bool(cfg.get("signal_changes", True))
        self._last_label: Dict[str, str] = {}
        self._last_rsi: Dict[str, float] = {}

    def evaluate(self, symbol: str, quote: Optional[Quote], analysis: Optional[dict],
                 holding: Optional[Holding], now: Optional[float] = None, live_bar: bool = True) -> List[Alert]:
        now = now or time.time()
        day = _day(now)
        out: List[Alert] = []
        held = holding is not None
        tag = "your holding " if held else ""

        def add(key, sev, title, body, kind="signal", **data):
            out.append(Alert(key=f"{symbol}:{key}", symbol=symbol, severity=sev, title=title, body=body,
                             time=int(now), kind=kind, data=data))

        price = quote.price if quote else (analysis or {}).get("latest", {}).get("price")
        if price is None:
            return out

        # --- your own levels
        if holding and holding.stop:
            if price <= holding.stop:
                add(f"stop:{day}", "critical", f"{symbol} hit your stop",
                    f"{symbol} is at ${price:,.2f}, at or below your stop of ${holding.stop:,.2f}.", "price", price=price)
            elif price <= holding.stop * (1 + self.near_stop_pct / 100):
                add(f"nearstop:{day}", "warn", f"{symbol} is near your stop",
                    f"{symbol} at ${price:,.2f} is within {self.near_stop_pct:.0f}% of your stop ${holding.stop:,.2f}.", "price")
        if holding and holding.target and price >= holding.target:
            add(f"target:{day}", "warn", f"{symbol} reached your target",
                f"{symbol} is at ${price:,.2f}, at or above your target of ${holding.target:,.2f}.", "price", price=price)

        # --- big moves
        chg = quote.change_pct if quote else None
        if chg is not None and abs(chg) >= self.move_pct:
            bucket = int(abs(chg) // self.move_pct)
            sigma = (analysis or {}).get("stats", {}).get("move_today_sigma")
            extra = f" That's a {abs(sigma):.1f}σ move for this stock." if sigma else ""
            add(f"move:{day}:{'up' if chg > 0 else 'down'}:{bucket}", "warn" if held else "info",
                f"{symbol} {'up' if chg > 0 else 'down'} {abs(chg):.1f}% today",
                f"{tag.capitalize() or ''}{symbol} is at ${price:,.2f} ({chg:+.2f}%).{extra}", "price", change_pct=chg)

        if not analysis or not analysis.get("ok"):
            return out

        # --- candlestick patterns on completed bars only (today's bar is still forming while the market is open)
        for p in analysis.get("patterns", []):
            if p["direction"] == "neutral" or p["strength"] < self.min_pattern_strength:
                continue
            completed = not live_bar or p["index"] < analysis.get("last_index", 0)
            if not completed:
                continue
            tr = p.get("track_record") or {}
            hist = (f" Historically on {symbol}: right {tr['hit_rate']:.0f}% of {tr['count']} times over {tr['horizon']} days."
                    if tr.get("count") else "")
            add(f"pattern:{p['name']}:{p.get('t', p['index'])}", "warn" if held else "info",
                f"{symbol}: {p['name']} ({p['direction']})", p["meaning"] + hist, "pattern", pattern=p["name"])

        # --- intraday 5-minute reversal patterns, for holdings
        intr = analysis.get("intraday") or {}
        if held:
            for p in intr.get("patterns_5m", []):
                if p["strength"] >= 3 and p["direction"] != "neutral":
                    add(f"pattern5m:{p['name']}:{day}", "info", f"{symbol}: {p['name']} on the 5-minute chart",
                        p["meaning"], "pattern", timeframe="5m")

        # --- signal changes
        label = analysis["label"]
        prev = self._last_label.get(symbol)
        self._last_label[symbol] = label
        if self.signal_changes and prev and prev != label:
            sev = "warn" if held and label in ("Sell", "Reduce", "Strong buy") else "info"
            top = sorted(analysis["components"], key=lambda c: -abs(c["points"]))[:3]
            add(f"label:{label}:{day}", sev, f"{symbol} signal: {prev} → {label} ({analysis['score']:+.0f})",
                " ".join(c["reason"] for c in top), "signal", score=analysis["score"])

        for c in analysis["components"]:
            if c["name"] in ("Golden cross", "Death cross"):
                add(f"cross:{c['name']}:{day}", "warn" if held else "info", f"{symbol}: {c['name']}", c["reason"], "signal")
            if c["name"] == "Volume spike":
                add(f"volume:{day}", "info", f"{symbol}: unusual volume", c["reason"], "signal")

        rsi = analysis["latest"].get("rsi14")
        prev_rsi = self._last_rsi.get(symbol)
        if rsi is not None:
            if prev_rsi is not None and prev_rsi < 70 <= rsi:
                add(f"rsi70:{day}", "info", f"{symbol} is overbought (RSI {rsi:.0f})", "RSI crossed above 70.", "signal")
            if prev_rsi is not None and prev_rsi > 30 >= rsi:
                add(f"rsi30:{day}", "info", f"{symbol} is oversold (RSI {rsi:.0f})", "RSI crossed below 30.", "signal")
            self._last_rsi[symbol] = rsi

        ch = analysis["levels"].get("chandelier_stop")
        if holding and ch and price < ch and price > holding.cost:
            add(f"chandelier:{day}", "warn", f"{symbol} broke its trailing stop",
                f"{symbol} at ${price:,.2f} fell below the chandelier stop ${ch:,.2f} while still in profit.", "price")
        return out

    def news_alerts(self, items: List[dict], holdings: Dict[str, Holding], now: Optional[float] = None) -> List[Alert]:
        out = []
        for n in items:
            hit = [s for s in n.get("symbols", []) if s in holdings]
            if hit and abs(n.get("sentiment", 0)) >= self.news_sentiment:
                good = n["sentiment"] > 0
                out.append(Alert(key=f"news:{n['id']}", symbol=hit[0], severity="warn",
                                 title=f"{'Positive' if good else 'Negative'} news for {', '.join(hit)}",
                                 body=n["title"], time=int(now or time.time()), kind="news",
                                 data={"link": n.get("link", ""), "sentiment": n["sentiment"]}))
        return out


# ---------------------------------------------------------------- dedupe

class AlertLog:
    """Remembers which alert keys already fired (persisted to JSON) and keeps recent history."""

    def __init__(self, path: Optional[str] = None, cooldown: float = 6 * 3600, history: int = 300):
        self.path = path
        self.cooldown = cooldown
        self.sent: Dict[str, float] = {}
        self.history: List[dict] = []
        self.max_history = history
        self._load()

    def _load(self):
        if self.path and os.path.exists(self.path):
            try:
                with open(self.path) as f:
                    d = json.load(f)
                self.sent = {k: float(v) for k, v in d.get("sent", {}).items()}
                self.history = d.get("history", [])[-self.max_history:]
            except (OSError, ValueError):
                log.warning("could not read alert log %s; starting fresh", self.path)

    def save(self):
        if not self.path:
            return
        cutoff = time.time() - 7 * 86400
        self.sent = {k: v for k, v in self.sent.items() if v > cutoff}
        tmp = self.path + ".tmp"
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with open(tmp, "w") as f:
            json.dump({"sent": self.sent, "history": self.history[-self.max_history:]}, f)
        os.replace(tmp, self.path)

    def fresh(self, alerts: List[Alert]) -> List[Alert]:
        out = []
        now = time.time()
        for a in alerts:
            last = self.sent.get(a.key)
            if last is not None and now - last < self.cooldown:
                continue
            self.sent[a.key] = now
            self.history.append(a.to_dict())
            out.append(a)
        if out:
            self.history = self.history[-self.max_history:]
            self.save()
        return out


# ---------------------------------------------------------------- channels

class Channel:
    name = "channel"

    def __init__(self, min_severity: str = "info"):
        self.min = SEVERITY.get(min_severity, 0)

    def wants(self, a: Alert) -> bool:
        return SEVERITY.get(a.severity, 0) >= self.min

    def send(self, alerts: List[Alert]) -> None:
        raise NotImplementedError


def _post_json(url: str, body: dict, timeout: float = 10):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "watchdesk"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        r.read(1000)


ICON = {"info": "🔵", "warn": "🟠", "critical": "🔴"}


def _text(a: Alert) -> str:
    return f"{ICON.get(a.severity, '')} {a.title}\n{a.body}"


class ConsoleChannel(Channel):
    name = "console"

    def send(self, alerts):
        for a in alerts:
            if self.wants(a):
                log.info("ALERT [%s] %s — %s", a.severity, a.title, a.body)


class WebhookChannel(Channel):
    """Discord, Slack or any JSON webhook."""
    name = "webhook"

    def __init__(self, url: str, style: str = "discord", min_severity: str = "warn"):
        super().__init__(min_severity)
        self.url, self.style = url, style

    def send(self, alerts):
        for a in [x for x in alerts if self.wants(x)]:
            if self.style == "discord":
                body = {"content": _text(a)[:1900]}
            elif self.style == "slack":
                body = {"text": _text(a)}
            else:
                body = a.to_dict()
            _post_json(self.url, body)


class TelegramChannel(Channel):
    name = "telegram"

    def __init__(self, token: str, chat_id: str, min_severity: str = "warn"):
        super().__init__(min_severity)
        self.token, self.chat_id = token, chat_id

    def send(self, alerts):
        for a in [x for x in alerts if self.wants(x)]:
            _post_json(f"https://api.telegram.org/bot{self.token}/sendMessage",
                       {"chat_id": self.chat_id, "text": _text(a)[:4000], "disable_web_page_preview": True})


class EmailChannel(Channel):
    name = "email"

    def __init__(self, host: str, port: int, user: str, password: str, sender: str, to: str,
                 starttls: bool = True, min_severity: str = "critical"):
        super().__init__(min_severity)
        self.host, self.port, self.user, self.password = host, int(port), user, password
        self.sender, self.to, self.starttls = sender, to, starttls

    def send(self, alerts):
        picked = [x for x in alerts if self.wants(x)]
        if not picked:
            return
        msg = EmailMessage()
        msg["Subject"] = picked[0].title if len(picked) == 1 else f"{len(picked)} portfolio alerts"
        msg["From"], msg["To"] = self.sender, self.to
        msg.set_content("\n\n".join(f"[{a.severity.upper()}] {a.title}\n{a.body}" for a in picked))
        with smtplib.SMTP(self.host, self.port, timeout=15) as s:
            if self.starttls:
                s.starttls()
            if self.user:
                s.login(self.user, self.password)
            s.send_message(msg)


class CallbackChannel(Channel):
    name = "callback"

    def __init__(self, fn: Callable[[List[Alert]], None]):
        super().__init__("info")
        self.fn = fn

    def send(self, alerts):
        self.fn(alerts)


def build_channels(cfg: dict) -> List[Channel]:
    """Channels from config, with secrets taken from environment variables."""
    a = cfg.get("alerts", {})
    chans: List[Channel] = [ConsoleChannel()]
    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN") or a.get("telegram", {}).get("bot_token")
    tg_chat = os.environ.get("TELEGRAM_CHAT_ID") or a.get("telegram", {}).get("chat_id")
    if tg_token and tg_chat:
        chans.append(TelegramChannel(tg_token, str(tg_chat), a.get("telegram", {}).get("min_severity", "warn")))
    for env, style in (("DISCORD_WEBHOOK_URL", "discord"), ("SLACK_WEBHOOK_URL", "slack")):
        url = os.environ.get(env) or a.get(style, {}).get("webhook_url")
        if url:
            chans.append(WebhookChannel(url, style, a.get(style, {}).get("min_severity", "warn")))
    em = a.get("email", {})
    host = os.environ.get("SMTP_HOST") or em.get("host")
    to = os.environ.get("ALERT_EMAIL_TO") or em.get("to")
    if host and to:
        chans.append(EmailChannel(host, int(os.environ.get("SMTP_PORT") or em.get("port", 587)),
                                  os.environ.get("SMTP_USER") or em.get("user", ""),
                                  os.environ.get("SMTP_PASSWORD") or em.get("password", ""),
                                  os.environ.get("ALERT_EMAIL_FROM") or em.get("from", to), to,
                                  bool(em.get("starttls", True)), em.get("min_severity", "critical")))
    return chans


def dispatch(channels: List[Channel], alerts: List[Alert]) -> List[str]:
    errors = []
    if not alerts:
        return errors
    for ch in channels:
        try:
            ch.send(alerts)
        except Exception as e:  # one broken channel must not stop the others
            errors.append(f"{ch.name}: {e}")
            log.warning("alert channel %s failed: %s", ch.name, e)
    return errors
