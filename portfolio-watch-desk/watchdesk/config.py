"""Configuration and portfolio files."""
from __future__ import annotations

import copy
import json
import os
from typing import List, Tuple

from .models import Holding

DEFAULTS = {
    "provider": "yahoo",
    "finnhub_api_key": "",
    "portfolio_file": "portfolio.json",
    "state_dir": "state",
    "benchmark": "SPY",
    "tape": ["SPY", "QQQ", "DIA", "IWM", "^VIX", "^TNX", "CL=F", "GC=F", "BTC-USD"],
    "tape_labels": {"SPY": "S&P 500", "QQQ": "Nasdaq 100", "DIA": "Dow", "IWM": "Russell 2000", "^VIX": "VIX",
                    "^TNX": "US 10Y yield", "CL=F": "Crude oil", "GC=F": "Gold", "BTC-USD": "Bitcoin"},
    "poll_seconds": {"open": 15, "pre": 60, "post": 60, "closed": 300, "crypto": 60},
    "daily_refresh_seconds": 1800,
    "news_refresh_seconds": 600,
    "news_queries": ["stock market", "Federal Reserve interest rates", "inflation CPI", "oil prices OPEC",
                     "geopolitics markets", "earnings guidance"],
    "settings": {"risk_per_trade_pct": 1.0, "max_position_pct": 20.0, "atr_stop_mult": 2.0,
                 "chandelier_mult": 3.0, "risk_free_rate": 0.04},
    "alert_rules": {"move_pct": 3.0, "sigma_move": 2.5, "near_stop_pct": 3.0, "min_pattern_strength": 2,
                    "news_sentiment": 3, "signal_changes": True},
    "alerts": {"telegram": {"min_severity": "warn"}, "discord": {"min_severity": "warn"},
               "slack": {"min_severity": "warn"}, "email": {"min_severity": "critical"}},
    "alert_cooldown_seconds": 21600,
    "server": {"host": "127.0.0.1", "port": 8765},
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str = None) -> Tuple[dict, str]:
    """Returns (config, base_dir). Relative paths in the config resolve against base_dir."""
    user = {}
    base = os.getcwd()
    if path:
        with open(path) as f:
            user = json.load(f)
        base = os.path.dirname(os.path.abspath(path))
    cfg = _merge(DEFAULTS, user)
    if os.environ.get("WATCHDESK_PROVIDER"):
        cfg["provider"] = os.environ["WATCHDESK_PROVIDER"]
    if os.environ.get("FINNHUB_API_KEY"):
        cfg["finnhub_api_key"] = os.environ["FINNHUB_API_KEY"]
    for key in ("portfolio_file", "state_dir"):
        if not os.path.isabs(cfg[key]):
            cfg[key] = os.path.join(base, cfg[key])
    return cfg, base


def normalize_symbols(items) -> List[str]:
    seen, out = set(), []
    for s in items or []:
        s = str(s).strip().upper()
        if s and len(s) <= 15 and all(ch.isalnum() or ch in ".-^=" for ch in s) and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def parse_portfolio(d: dict) -> dict:
    """Validate a portfolio dict. Raises ValueError with a readable message."""
    if not isinstance(d, dict):
        raise ValueError("portfolio must be a JSON object")
    holdings = [Holding.from_dict(h) for h in d.get("holdings", [])]
    seen = set()
    for h in holdings:
        if h.symbol in seen:
            raise ValueError(f"{h.symbol} is listed twice")
        seen.add(h.symbol)
    cash = float(d.get("cash", 0) or 0)
    if cash < 0:
        raise ValueError("cash can't be negative")
    return {"cash": cash, "holdings": holdings, "watchlist": normalize_symbols(d.get("watchlist", []))}


def load_portfolio(path: str) -> dict:
    env = os.environ.get("WATCHDESK_PORTFOLIO_JSON")
    if env:
        return parse_portfolio(json.loads(env))
    if not os.path.exists(path):
        return {"cash": 0.0, "holdings": [], "watchlist": []}
    with open(path) as f:
        return parse_portfolio(json.load(f))


def save_portfolio(path: str, p: dict) -> None:
    data = {"cash": p["cash"], "holdings": [h.to_dict() for h in p["holdings"]], "watchlist": p["watchlist"]}
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)
