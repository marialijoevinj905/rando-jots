import http.client
import json
import os
import tempfile
import threading
import time
import unittest

from watchdesk.alerts import CallbackChannel
from watchdesk.config import DEFAULTS, _merge
from watchdesk.engine import Watcher
from watchdesk.providers import SimulatedProvider
from watchdesk.server import serve

PORTFOLIO = {"cash": 1000, "watchlist": ["AMZN"], "holdings": [
    {"symbol": "NVDA", "shares": 10, "cost": 150, "stop": 400},  # stop far above price: guaranteed alert
    {"symbol": "AAPL", "shares": 5, "cost": 200}]}


class Base(unittest.TestCase):
    token = None

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        pf = os.path.join(cls.tmp.name, "portfolio.json")
        with open(pf, "w") as f:
            json.dump(PORTFOLIO, f)
        cfg = _merge(DEFAULTS, {"portfolio_file": pf, "state_dir": os.path.join(cls.tmp.name, "state"),
                                "tape": ["SPY"], "benchmark": "SPY"})
        cls.sent = []
        cls.w = Watcher(cfg, provider=SimulatedProvider(seed=2), news=None,
                        channels=[CallbackChannel(cls.sent.extend)])
        cls.w.tick()
        cls.w.flush_alerts()  # the run loop does this after every tick
        cls.httpd = serve(cls.w, "127.0.0.1", 0, cls.token)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.w.stop()
        cls.tmp.cleanup()

    def req(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = dict(headers or {})
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            h.setdefault("Content-Type", "application/json")
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        raw = r.read()
        c.close()
        try:
            return r.status, json.loads(raw)
        except ValueError:
            return r.status, raw


class Api(Base):
    def test_state(self):
        code, d = self.req("GET", "/api/state")
        self.assertEqual(code, 200)
        rows = {r["symbol"]: r for r in d["portfolio"]["rows"]}
        self.assertEqual(set(rows), {"NVDA", "AAPL"})
        self.assertIsNotNone(rows["NVDA"]["price"])
        self.assertIn(rows["NVDA"]["label"], ("Strong buy", "Buy", "Hold", "Reduce", "Sell"))
        weights = sum(r["weight"] for r in rows.values())
        self.assertLess(weights, 100)  # cash takes the rest
        self.assertEqual(d["tape"][0]["symbol"], "SPY")

    def test_stop_alert_was_delivered(self):
        self.assertTrue(any(a.title == "NVDA hit your stop" for a in self.sent))

    def test_analysis_and_candles(self):
        code, d = self.req("GET", "/api/analysis?symbol=nvda")
        self.assertEqual(code, 200)
        self.assertTrue(d["analysis"]["ok"])
        code, c = self.req("GET", "/api/candles?symbol=NVDA&tf=1d")
        self.assertGreater(len(c["candles"]), 400)
        self.assertIsInstance(c["markers"], list)
        code, c = self.req("GET", "/api/candles?symbol=NVDA&tf=1m")
        self.assertGreater(len(c["candles"]), 10)
        code, _ = self.req("GET", "/api/analysis?symbol=ZZZZ")
        self.assertEqual(code, 404)

    def test_static_and_traversal(self):
        code, body = self.req("GET", "/")
        self.assertEqual(code, 200)
        self.assertIn(b"Portfolio Watch Desk", body)
        code, _ = self.req("GET", "/vendor/lightweight-charts.standalone.production.js")
        self.assertEqual(code, 200)
        for bad in ("/../watchdesk/server.py", "/%2e%2e/watchdesk/server.py", "/vendor/../../README.md"):
            code, _ = self.req("GET", bad)
            self.assertEqual(code, 404, bad)

    def test_save_portfolio(self):
        new = {"cash": 0, "watchlist": ["MSFT"], "holdings": [{"symbol": "TSM", "shares": 3, "cost": 300}]}
        code, _ = self.req("PUT", "/api/portfolio", new)
        self.assertEqual(code, 200)
        with open(self.w.cfg["portfolio_file"]) as f:
            self.assertEqual(json.load(f)["holdings"][0]["symbol"], "TSM")
        code, d = self.req("GET", "/api/portfolio")
        self.assertEqual(d["watchlist"], ["MSFT"])
        self.req("PUT", "/api/portfolio", PORTFOLIO)  # restore for other tests
        time.sleep(0.5)

    def test_rejects_bad_portfolio_and_cross_site_writes(self):
        code, d = self.req("PUT", "/api/portfolio", {"holdings": [{"symbol": "X", "shares": -1, "cost": 1}]})
        self.assertEqual(code, 400)
        self.assertIn("shares", d["error"])
        code, _ = self.req("PUT", "/api/portfolio", PORTFOLIO, {"Origin": "https://evil.example"})
        self.assertEqual(code, 403)
        code, _ = self.req("PUT", "/api/portfolio", PORTFOLIO, {"Content-Type": "text/plain"})
        self.assertEqual(code, 415)

    def test_event_stream_sends_state_immediately(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("GET", "/api/stream")
        r = c.getresponse()
        self.assertEqual(r.getheader("Content-Type"), "text/event-stream")
        first = r.fp.readline().decode()
        data = r.fp.readline().decode()
        c.close()
        self.assertEqual(first.strip(), "event: state")
        self.assertIn('"portfolio"', data)


class TokenAuth(Base):
    token = "s3cret-token"

    def test_requires_token(self):
        code, _ = self.req("GET", "/api/state")
        self.assertEqual(code, 401)
        code, _ = self.req("GET", "/api/state?token=wrong")
        self.assertEqual(code, 401)
        code, _ = self.req("GET", "/api/state", headers={"Authorization": "Bearer s3cret-token"})
        self.assertEqual(code, 200)

    def test_token_link_sets_cookie(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("GET", "/?token=s3cret-token")
        r = c.getresponse()
        r.read()
        cookie = r.getheader("Set-Cookie")
        c.close()
        self.assertIn("wd_token=s3cret-token", cookie)
        self.assertIn("HttpOnly", cookie)
        code, _ = self.req("GET", "/api/state", headers={"Cookie": "wd_token=s3cret-token"})
        self.assertEqual(code, 200)


class ScanOnce(unittest.TestCase):
    def test_scan_once_delivers_alerts_once(self):
        with tempfile.TemporaryDirectory() as d:
            pf = os.path.join(d, "p.json")
            with open(pf, "w") as f:
                json.dump(PORTFOLIO, f)
            cfg = _merge(DEFAULTS, {"portfolio_file": pf, "state_dir": d, "tape": []})
            got = []
            w = Watcher(cfg, provider=SimulatedProvider(seed=4), news=None, channels=[CallbackChannel(got.extend)])
            res = w.scan_once()
            w.stop()
            self.assertEqual(res["alert_errors"], [])
            self.assertTrue(any(a.title == "NVDA hit your stop" for a in got))
            # a second run (e.g. the next cron job) must not repeat the same alert
            got2 = []
            w2 = Watcher(cfg, provider=SimulatedProvider(seed=4), news=None, channels=[CallbackChannel(got2.extend)])
            w2.scan_once()
            w2.stop()
            self.assertFalse(any(a.title == "NVDA hit your stop" for a in got2))


if __name__ == "__main__":
    unittest.main()
