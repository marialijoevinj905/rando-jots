"""HTTP server: the dashboard, a JSON API and a live event stream."""
from __future__ import annotations

import hmac
import json
import logging
import mimetypes
import os
import queue
import threading
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlsplit

from .config import parse_portfolio
from .engine import Watcher
from .models import Candle
from .patterns import scan_history

log = logging.getLogger("watchdesk.server")
WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
MAX_BODY = 200_000


def make_handler(watcher: Watcher, token: Optional[str] = None, web_dir: str = WEB_DIR):
    class Handler(BaseHTTPRequestHandler):
        server_version = "watchdesk"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):  # route through logging instead of stderr
            log.debug("%s - %s", self.address_string(), fmt % args)

        # ---------------------------------------------------- helpers
        def _authed(self, qs) -> bool:
            if not token:
                return True
            supplied = (qs.get("token") or [""])[0]
            auth = self.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                supplied = supplied or auth[7:]
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            if not supplied and "wd_token" in cookie:
                supplied = cookie["wd_token"].value
            return bool(supplied) and hmac.compare_digest(supplied, token)

        def _send(self, code: int, body: bytes, ctype: str, extra: Optional[dict] = None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if self.command in ("PUT", "POST") and code >= 400:
                # the body may be unread; close so it isn't parsed as the next request
                self.send_header("Connection", "close")
                self.close_connection = True
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, data, code: int = 200, extra: Optional[dict] = None):
            self._send(code, json.dumps(data, default=str).encode(), "application/json; charset=utf-8", extra)

        def _error(self, code: int, msg: str):
            self._json({"error": msg}, code)

        def _token_cookie(self, qs) -> Optional[dict]:
            if token and (qs.get("token") or [""])[0] == token:
                return {"Set-Cookie": f"wd_token={token}; HttpOnly; SameSite=Strict; Path=/"}
            return None

        # ---------------------------------------------------- routes
        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            url = urlsplit(self.path)
            qs = parse_qs(url.query)
            if not self._authed(qs):
                return self._error(HTTPStatus.UNAUTHORIZED, "Add ?token=YOUR_TOKEN to the address (set by WATCHDESK_TOKEN).")
            path = url.path
            if path == "/api/state":
                with watcher.lock:
                    return self._json(watcher.snapshot())
            if path == "/api/stream":
                return self._stream()
            if path == "/api/analysis":
                sym = (qs.get("symbol") or [""])[0].upper()
                with watcher.lock:
                    a = watcher.analyses.get(sym)
                    q = watcher.quotes.get(sym)
                if not a:
                    return self._error(404, f"No analysis for {sym or 'that symbol'} yet. Add it to holdings or the watchlist.")
                news = watcher.news.for_symbol(sym) if watcher.news else []
                return self._json({"analysis": a, "quote": q.to_dict() if q else None, "news": news})
            if path == "/api/candles":
                sym = (qs.get("symbol") or [""])[0].upper()
                tf = "1m" if (qs.get("tf") or ["1d"])[0] == "1m" else "1d"
                candles = watcher.candles(sym, tf)
                markers = []
                if tf == "1d" and candles:
                    bars = [Candle(**c) for c in candles]
                    markers = [{"t": bars[p.index].t, "name": p.name, "direction": p.direction, "strength": p.strength}
                               for p in scan_history(bars, start=max(0, len(bars) - 260)) if p.strength >= 2]
                return self._json({"symbol": sym, "tf": tf, "candles": candles, "markers": markers})
            if path == "/api/news":
                return self._json({"items": watcher.news.latest(80) if watcher.news else []})
            if path == "/api/portfolio":
                p = watcher.portfolio
                return self._json({"cash": p["cash"], "holdings": [h.to_dict() for h in p["holdings"]], "watchlist": p["watchlist"]})
            return self._static(path, self._token_cookie(qs))

        def do_PUT(self):
            url = urlsplit(self.path)
            if not self._authed(parse_qs(url.query)):
                return self._error(HTTPStatus.UNAUTHORIZED, "Not signed in.")
            if url.path != "/api/portfolio":
                return self._error(404, "Not found.")
            if not self._same_origin():
                return self._error(HTTPStatus.FORBIDDEN, "Cross-site request refused.")
            if "application/json" not in self.headers.get("Content-Type", ""):
                return self._error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Send JSON.")
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY:
                return self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Portfolio is empty or too large.")
            try:
                p = parse_portfolio(json.loads(self.rfile.read(length)))
            except (ValueError, TypeError) as e:
                return self._error(HTTPStatus.BAD_REQUEST, str(e))
            watcher.set_portfolio(p)
            return self._json({"ok": True})

        def do_POST(self):
            url = urlsplit(self.path)
            if not self._authed(parse_qs(url.query)):
                return self._error(HTTPStatus.UNAUTHORIZED, "Not signed in.")
            if url.path == "/api/refresh" and self._same_origin():
                threading.Thread(target=watcher.tick, daemon=True).start()
                return self._json({"ok": True})
            return self._error(404, "Not found.")

        def _same_origin(self) -> bool:
            origin = self.headers.get("Origin")
            if not origin:
                return True
            return urlsplit(origin).netloc == self.headers.get("Host", "")

        def _static(self, path: str, extra: Optional[dict]):
            if path in ("", "/"):
                path = "/index.html"
            full = os.path.realpath(os.path.join(web_dir, path.lstrip("/")))
            if not full.startswith(os.path.realpath(web_dir) + os.sep) or not os.path.isfile(full):
                return self._error(404, "Not found.")
            ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype.endswith("javascript"):
                ctype += "; charset=utf-8"
            with open(full, "rb") as f:
                self._send(200, f.read(), ctype, extra)

        def _stream(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            q = watcher.hub.subscribe()
            try:
                with watcher.lock:
                    first = json.dumps(watcher.snapshot(), default=str)
                self._event("state", first)
                if watcher.news:
                    self._event("news", json.dumps(watcher.news.latest(60), default=str))
                while True:
                    try:
                        ev, data = q.get(timeout=15)
                        self._event(ev, data)
                    except queue.Empty:
                        self.wfile.write(b": keep-alive\n\n")
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                watcher.hub.unsubscribe(q)
                self.close_connection = True

        def _event(self, ev: str, data: str):
            self.wfile.write(f"event: {ev}\ndata: {data}\n\n".encode())
            self.wfile.flush()

    return Handler


def serve(watcher: Watcher, host: str = "127.0.0.1", port: int = 8765, token: Optional[str] = None) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), make_handler(watcher, token))
    httpd.daemon_threads = True
    return httpd
