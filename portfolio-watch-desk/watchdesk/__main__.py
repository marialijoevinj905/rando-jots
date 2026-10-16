"""Command line: ``python -m watchdesk [serve|scan|analyze] ...``"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import threading

from .config import load_config
from .engine import Watcher
from .server import serve


def _watcher(args) -> Watcher:
    cfg, _ = load_config(args.config)
    if args.demo:  # simulated prices, no news fetching, and a separate portfolio file
        cfg["provider"] = "simulated"
        cfg["state_dir"] = os.path.join(cfg["state_dir"], "demo")
        cfg["portfolio_file"] = os.path.join(cfg["state_dir"], "portfolio.json")
        cfg["poll_seconds"] = {k: 5 for k in ("open", "pre", "post", "closed", "crypto")}
    w = Watcher(cfg)
    if args.demo:
        w.news = None
        if not w.portfolio["holdings"]:
            from .config import parse_portfolio
            w.portfolio = parse_portfolio({"cash": 5000, "watchlist": ["GOOGL", "AMZN", "TSLA"], "holdings": [
                {"symbol": "NVDA", "shares": 40, "cost": 152.4, "target": 260, "stop": 195},
                {"symbol": "AAPL", "shares": 30, "cost": 214.1},
                {"symbol": "MSFT", "shares": 16, "cost": 431.0},
                {"symbol": "TSM", "shares": 22, "cost": 206.5},
            ]})
    return w


def cmd_serve(args) -> int:
    w = _watcher(args)
    cfg = w.cfg
    host = args.host or os.environ.get("WATCHDESK_HOST") or cfg["server"]["host"]
    port = int(args.port or os.environ.get("WATCHDESK_PORT") or cfg["server"]["port"])
    token = os.environ.get("WATCHDESK_TOKEN") or None
    if host not in ("127.0.0.1", "localhost", "::1") and not token:
        logging.warning("Listening on %s without WATCHDESK_TOKEN: anyone who can reach this port can see and edit "
                        "your portfolio. Set WATCHDESK_TOKEN to require a token.", host)
    httpd = serve(w, host, port, token)
    w.start()
    url = f"http://{'localhost' if host in ('0.0.0.0', '127.0.0.1') else host}:{port}/" + (f"?token={token}" if token else "")
    logging.info("Dashboard: %s", url)

    def stop(*_):
        logging.info("shutting down")
        w.stop()
        # shutdown() waits for serve_forever() to return, so it must run off the serving thread
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        stop()
    return 0


def cmd_scan(args) -> int:
    w = _watcher(args)
    if args.quiet:
        w.channels = [c for c in w.channels if c.name != "console"]
    res = w.scan_once()
    snap = res["snapshot"]
    p = snap["portfolio"]
    fired = [a for a in snap["alerts"] if a["time"] >= snap["status"]["last_tick"] - 5]
    if args.quiet:  # for public CI logs: no amounts, symbols or alert text
        print(f"Scanned {len(p['rows'])} holdings and {len(snap['watchlist'])} watchlist symbols; "
              f"{len(fired)} new alerts; {len(snap['status']['errors'])} data errors.")
        for e in res["alert_errors"]:
            print("alert delivery failed:", e.split(":")[0], file=sys.stderr)
        w.stop()
        return 1 if res["alert_errors"] else 0
    print(f"Portfolio ${p['total']:,.2f}  day {p['day_change']:+,.2f} ({p['day_change_pct']:+.2f}%)  session {snap['status']['session']}")
    for r in p["rows"]:
        price = f"${r['price']:,.2f}" if r["price"] is not None else "—"
        print(f"  {r['symbol']:<8} {price:>12}  {r['label'] or '—':<10} {format(r['score'], '+.0f') if r['score'] is not None else '':>5}  {r['pattern'] or ''}")
    print(f"{len(fired)} new alerts this run")
    for e in res["alert_errors"]:
        print("alert delivery failed:", e, file=sys.stderr)
    if snap["status"]["errors"]:
        print("data errors:", json.dumps(snap["status"]["errors"]), file=sys.stderr)
    w.stop()
    return 1 if res["alert_errors"] else 0


def cmd_analyze(args) -> int:
    w = _watcher(args)
    sym = args.symbol.upper()
    if sym not in w.portfolio["watchlist"] and sym not in w.holdings():
        w.portfolio["watchlist"].append(sym)
    w.tick()
    a = w.analyses.get(sym)
    w.stop()
    if not a or not a.get("ok"):
        print(f"Couldn't analyze {sym}: {w.errors.get(sym) or (a or {}).get('error') or 'no data'}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(a, indent=2, default=str))
        return 0
    print(f"{sym}  ${a['latest']['price']:,.2f}   {a['label']} ({a['score']:+.0f}, {a['confidence']:.0f}% agreement)")
    for c in a["components"]:
        print(f"  {c['points']:+6.1f}  {c['group']:<9} {c['reason']}")
    if a["patterns"]:
        print("Patterns:", ", ".join(f"{p['name']} ({p['direction']})" for p in a["patterns"]))
    lv = a["levels"]
    fmt = lambda x: f"${x:,.2f}" if x else "—"  # noqa: E731
    print(f"Stops: ATR {fmt(lv['atr_stop'])}  chandelier {fmt(lv['chandelier_stop'])}   take-profit {fmt(lv['take_profit'])}"
          + (f"  reward/risk {lv['reward_risk']:.2f}" if lv["reward_risk"] else ""))
    print("Suggestions:")
    for s in a["suggestions"]:
        print(f"  • [{s['action']}] {s['text']}")
    print("\nGeneral technical analysis, not personal financial advice.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="watchdesk", description="Watches your portfolio and the market, around the clock.")
    ap.add_argument("--config", default=os.environ.get("WATCHDESK_CONFIG"), help="path to config.json")
    ap.add_argument("--demo", action="store_true", help="use simulated prices (no network, no API keys)")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("serve", help="run the watcher and dashboard (default)")
    s.add_argument("--host")
    s.add_argument("--port", type=int)
    sc = sub.add_parser("scan", help="one pass: fetch, analyze, send alerts, exit (for cron / GitHub Actions)")
    sc.add_argument("--quiet", action="store_true", help="print counts only (keeps amounts out of shared logs)")
    a = sub.add_parser("analyze", help="print the technical read for one symbol")
    a.add_argument("symbol")
    a.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.cmd in (None, "serve"):
        if args.cmd is None:
            args.host = args.port = None
        return cmd_serve(args)
    if args.cmd == "scan":
        return cmd_scan(args)
    return cmd_analyze(args)


if __name__ == "__main__":
    sys.exit(main())
