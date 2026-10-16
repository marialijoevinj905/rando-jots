import json
import os
import tempfile
import unittest
from datetime import datetime, timezone

from watchdesk import market_hours as mh
from watchdesk.alerts import AlertLog, AlertRules, CallbackChannel, Channel, dispatch
from watchdesk.config import parse_portfolio
from watchdesk.engine import merge_live
from watchdesk.models import Alert, Candle, Holding, Quote
from watchdesk.news import NewsFeed, parse_rss, sentiment, tags
from watchdesk.providers import ProviderError, SimulatedProvider, parse_yahoo_chart, quote_from_meta

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc).timestamp()


def analysis(**over):
    a = {"ok": True, "label": "Hold", "score": 0, "components": [], "patterns": [], "last_index": 100,
         "latest": {"price": 100, "rsi14": 50}, "levels": {"chandelier_stop": None}, "stats": {}, "intraday": None}
    a.update(over)
    return a


class MarketHours(unittest.TestCase):
    def test_sessions(self):
        self.assertEqual(mh.session(utc(2026, 10, 15, 14, 0)), "open")   # Thu 10:00 EDT
        self.assertEqual(mh.session(utc(2026, 10, 15, 12, 0)), "pre")    # 08:00 EDT
        self.assertEqual(mh.session(utc(2026, 10, 15, 21, 0)), "post")   # 17:00 EDT
        self.assertEqual(mh.session(utc(2026, 10, 16, 2, 0)), "closed")  # 22:00 EDT
        self.assertEqual(mh.session(utc(2026, 10, 17, 15, 0)), "closed")  # Saturday

    def test_holiday_and_early_close(self):
        self.assertEqual(mh.session(utc(2026, 11, 26, 15, 0)), "closed")  # Thanksgiving
        self.assertEqual(mh.session(utc(2026, 11, 27, 17, 30)), "open")   # 12:30 EST
        self.assertEqual(mh.session(utc(2026, 11, 27, 18, 30)), "post")   # 13:30 EST, after the early close

    def test_winter_time(self):
        self.assertEqual(mh.session(utc(2026, 12, 1, 14, 45)), "open")  # 09:45 EST
        self.assertEqual(mh.session(utc(2026, 12, 1, 14, 15)), "pre")   # 09:15 EST

    def test_dst_fallback_rule(self):
        self.assertTrue(mh._us_dst(datetime(2026, 7, 1, tzinfo=timezone.utc)))
        self.assertFalse(mh._us_dst(datetime(2026, 12, 1, tzinfo=timezone.utc)))
        self.assertFalse(mh._us_dst(datetime(2026, 3, 8, 6, 59, tzinfo=timezone.utc)))
        self.assertTrue(mh._us_dst(datetime(2026, 3, 8, 7, 0, tzinfo=timezone.utc)))

    def test_poll_interval(self):
        iv = {"open": 15, "closed": 300, "crypto": 30}
        self.assertEqual(mh.poll_interval(iv, utc(2026, 10, 15, 14, 0)), 15)
        self.assertEqual(mh.poll_interval(iv, utc(2026, 10, 17, 15, 0)), 300)
        self.assertEqual(mh.poll_interval(iv, utc(2026, 10, 17, 15, 0), has_crypto=True), 30)

    def test_next_open_skips_weekend(self):
        n = mh.next_open(utc(2026, 10, 16, 21, 0))  # Friday evening
        self.assertEqual((n.month, n.day, n.hour, n.minute), (10, 19, 9, 30))


class Rules(unittest.TestCase):
    def test_stop_hit_is_critical(self):
        q = Quote("X", 94, prev_close=100, time=int(utc(2026, 10, 15, 15)))
        out = AlertRules().evaluate("X", q, analysis(), Holding("X", 1, 100, stop=95), now=q.time)
        sev = {a.title: a.severity for a in out}
        self.assertEqual(sev["X hit your stop"], "critical")
        self.assertIn("X down 6.0% today", sev)

    def test_target_and_near_stop(self):
        r = AlertRules({"near_stop_pct": 3})
        self.assertTrue(any("near your stop" in a.title for a in r.evaluate("X", Quote("X", 97), analysis(), Holding("X", 1, 100, stop=95))))
        self.assertTrue(any("reached your target" in a.title for a in r.evaluate("X", Quote("X", 131), analysis(), Holding("X", 1, 100, target=130))))

    def test_patterns_on_a_forming_bar_wait_for_the_close(self):
        pat = {"name": "Bullish Engulfing", "direction": "bullish", "strength": 3, "index": 100, "t": 1, "meaning": "m"}
        r = AlertRules()
        live = r.evaluate("X", Quote("X", 100), analysis(patterns=[pat]), None, live_bar=True)
        done = r.evaluate("X", Quote("X", 100), analysis(patterns=[pat]), None, live_bar=False)
        self.assertFalse([a for a in live if a.kind == "pattern"])
        self.assertTrue([a for a in done if a.kind == "pattern"])

    def test_signal_change_fires_once_per_change(self):
        r = AlertRules()
        r.evaluate("X", Quote("X", 100), analysis(label="Hold"), None)
        out = r.evaluate("X", Quote("X", 100), analysis(label="Buy", score=25), None)
        self.assertTrue(any("Hold → Buy" in a.title for a in out))
        again = r.evaluate("X", Quote("X", 100), analysis(label="Buy", score=26), None)
        self.assertFalse(any(a.kind == "signal" and "→" in a.title for a in again))

    def test_news_alert_only_for_holdings_with_strong_sentiment(self):
        r = AlertRules({"news_sentiment": 3})
        items = [{"id": "1", "title": "X plunges after it cuts guidance", "symbols": ["X"], "sentiment": -5},
                 {"id": "2", "title": "Y soars", "symbols": ["Y"], "sentiment": 4},
                 {"id": "3", "title": "X mentioned", "symbols": ["X"], "sentiment": 1}]
        out = r.news_alerts(items, {"X": Holding("X", 1, 1)})
        self.assertEqual([a.key for a in out], ["news:1"])


class Delivery(unittest.TestCase):
    def test_log_dedupes_and_persists(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "alerts.json")
            log = AlertLog(path)
            a = Alert("k1", "X", "warn", "t", "b", 1)
            self.assertEqual(len(log.fresh([a, Alert("k2", "X", "info", "t", "b", 1)])), 2)
            self.assertEqual(log.fresh([a]), [])
            self.assertEqual(AlertLog(path).fresh([a]), [])  # survives a restart

    def test_broken_channel_does_not_block_others(self):
        class Boom(Channel):
            name = "boom"

            def send(self, alerts):
                raise RuntimeError("down")
        got = []
        errs = dispatch([Boom(), CallbackChannel(got.extend)], [Alert("k", "X", "info", "t", "b", 1)])
        self.assertEqual(len(got), 1)
        self.assertEqual(errs, ["boom: down"])


class Providers(unittest.TestCase):
    def test_parse_yahoo_chart(self):
        with open(os.path.join(FIX, "yahoo_chart_1m.json")) as f:
            meta, bars = parse_yahoo_chart(json.load(f))
        self.assertEqual(len(bars), 4)  # the all-null bar is skipped
        q = quote_from_meta("NVDA", meta, bars, "yahoo")
        self.assertEqual(q.price, 217.23)
        self.assertEqual(q.prev_close, 221.3)
        self.assertAlmostEqual(q.change_pct, (217.23 / 221.3 - 1) * 100)
        self.assertEqual(q.ext_price, 217.8)  # after-hours bar newer than the regular close
        self.assertEqual(q.name, "NVIDIA Corporation")

    def test_yahoo_error(self):
        with open(os.path.join(FIX, "yahoo_error.json")) as f:
            with self.assertRaises(ProviderError):
                parse_yahoo_chart(json.load(f))

    def test_simulated_is_deterministic_and_dated_correctly(self):
        now = utc(2026, 10, 16, 2, 0)  # Thursday night in New York
        a = SimulatedProvider(seed=1, now=now).daily("NVDA")
        b = SimulatedProvider(seed=1, now=now).daily("NVDA")
        self.assertEqual([x.c for x in a], [x.c for x in b])
        self.assertEqual(datetime.fromtimestamp(a[-1].t, timezone.utc).date().isoformat(), "2026-10-15")
        self.assertAlmostEqual(a[-1].c, 217.23)
        self.assertTrue(all(datetime.fromtimestamp(x.t, timezone.utc).weekday() < 5 for x in a))

    def test_merge_live_updates_todays_bar(self):
        t = int(utc(2026, 10, 15, 14, 0))
        daily = [Candle(t - 86400, 10, 11, 9, 10), Candle(t - 1800, 10, 10.5, 9.8, 10.2)]
        intr = [Candle(t, 10.2, 12.0, 10.1, 11.9, 100)]
        merged = merge_live(daily, intr, Quote("X", 11.8, 10, time=t + 60, volume=5000))
        self.assertEqual(len(merged), 2)
        self.assertEqual((merged[-1].h, merged[-1].c, merged[-1].v), (12.0, 11.8, 5000))
        self.assertEqual(daily[-1].c, 10.2)  # input not mutated

    def test_merge_live_adds_a_new_session_bar(self):
        t = int(utc(2026, 10, 15, 14, 0))
        daily = [Candle(t - 86400, 10, 11, 9, 10)]
        merged = merge_live(daily, [Candle(t, 10.5, 10.9, 10.4, 10.8, 10)], Quote("X", 10.8, 10, time=t + 60))
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[-1].o, 10.5)


class News(unittest.TestCase):
    def test_parse_rss(self):
        with open(os.path.join(FIX, "feed.xml")) as f:
            items = parse_rss(f.read(), "Yahoo Finance")
        self.assertEqual(len(items), 3)  # blank title skipped
        self.assertEqual(items[1]["summary"], "Semiconductor shares fall.")
        self.assertEqual(items[2]["link"], "")  # javascript: link dropped
        self.assertGreater(items[0]["time"], 0)

    def test_refuses_entity_payloads(self):
        with self.assertRaises(ProviderError):
            parse_rss('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><rss><channel></channel></rss>')

    def test_sentiment_and_tags(self):
        self.assertGreater(sentiment("Nvidia beats estimates and raises guidance"), 2)
        self.assertLess(sentiment("Chip stocks tumble as Fed rate hike fears grow"), -2)
        self.assertEqual(sentiment("Analyst day scheduled"), 0)
        self.assertIn("Fed & rates", tags("Fed signals another rate hike"))
        self.assertIn("Energy & oil", tags("Crude oil jumps on OPEC cut"))

    def test_feed_dedupes_across_symbols(self):
        with open(os.path.join(FIX, "feed.xml")) as f:
            xml = f.read()
        feed = NewsFeed(macro_queries=[], fetch=lambda url: xml)
        new = feed.refresh(["NVDA", "AMD"])
        self.assertEqual(len(new), 3)
        self.assertEqual(sorted(feed.latest()[0]["symbols"]), ["AMD", "NVDA"])
        self.assertEqual(feed.refresh(["NVDA"]), [])


class PortfolioValidation(unittest.TestCase):
    def test_valid(self):
        p = parse_portfolio({"cash": 10, "holdings": [{"symbol": "nvda", "shares": 2, "cost": 100, "stop": ""}],
                             "watchlist": ["amd", "AMD", "bad symbol!", "BTC-USD"]})
        self.assertEqual(p["holdings"][0].symbol, "NVDA")
        self.assertIsNone(p["holdings"][0].stop)
        self.assertEqual(p["watchlist"], ["AMD", "BTC-USD"])

    def test_invalid(self):
        for bad in ({"holdings": [{"symbol": "X", "shares": 0, "cost": 1}]},
                    {"holdings": [{"symbol": "", "shares": 1, "cost": 1}]},
                    {"holdings": [{"symbol": "X", "shares": 1, "cost": 1}, {"symbol": "x", "shares": 1, "cost": 1}]},
                    {"cash": -5}, []):
            with self.assertRaises((ValueError, TypeError)):
                parse_portfolio(bad)


if __name__ == "__main__":
    unittest.main()


class YahooOverHttp(unittest.TestCase):
    """Runs the real HTTP code path against a local stand-in for Yahoo."""

    @classmethod
    def setUpClass(cls):
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        with open(os.path.join(FIX, "yahoo_chart_1m.json"), "rb") as f:
            body = f.read()
        cls.paths = []

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                cls.paths.append(self.path)
                if "LIMIT" in self.path:
                    self.send_response(429)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def provider(self):
        from watchdesk.providers import YahooProvider
        p = YahooProvider()
        p.BASE = f"http://127.0.0.1:{self.httpd.server_address[1]}/v8/finance/chart/"
        return p

    def test_live_quote(self):
        q, bars = self.provider().live("NVDA")
        self.assertEqual(q.price, 217.23)
        self.assertEqual(len(bars), 4)
        self.assertIn("interval=1m", self.paths[-1])
        self.assertIn("includePrePost=true", self.paths[-1])

    def test_symbols_are_url_encoded(self):
        self.provider().daily("^VIX")
        self.assertTrue(self.paths[-1].startswith("/v8/finance/chart/%5EVIX?"))
        self.assertIn("range=2y", self.paths[-1])

    def test_rate_limit(self):
        from watchdesk.providers import RateLimited
        with self.assertRaises(RateLimited):
            self.provider().live("LIMIT")
