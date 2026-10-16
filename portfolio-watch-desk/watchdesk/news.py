"""Headline news from public RSS feeds, scored with a small finance lexicon."""
from __future__ import annotations

import hashlib
import html
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from typing import Dict, Iterable, List, Optional

from .providers import ProviderError, http_get_text

POSITIVE = {
    "beat": 2, "beats": 2, "tops": 2, "surge": 2, "surges": 2, "soar": 2, "soars": 2, "jump": 1, "jumps": 1,
    "rally": 1, "rallies": 1, "record": 1, "upgrade": 2, "upgraded": 2, "raises guidance": 3, "raises outlook": 3,
    "raises forecast": 3, "buyback": 1, "outperform": 2, "strong demand": 2, "approval": 2, "approved": 2,
    "partnership": 1, "wins": 1, "profit rises": 2, "growth": 1, "rebound": 1, "gains": 1, "rate cut": 2,
    "cools": 1, "eases": 1, "ceasefire": 1, "deal": 1,
}
NEGATIVE = {
    "miss": 2, "misses": 2, "plunge": 2, "plunges": 2, "tumble": 2, "tumbles": 2, "sink": 2, "sinks": 2,
    "fall": 1, "falls": 1, "drop": 1, "drops": 1, "slump": 2, "downgrade": 2, "downgraded": 2,
    "cuts guidance": 3, "lowers guidance": 3, "cuts outlook": 3, "warns": 2, "warning": 2, "lawsuit": 2,
    "probe": 2, "investigation": 2, "recall": 2, "layoffs": 1, "fraud": 3, "bankruptcy": 3, "default": 2,
    "rate hike": 2, "hot inflation": 2, "tariff": 1, "tariffs": 1, "sanctions": 1, "war": 2, "attack": 2,
    "selloff": 2, "sell-off": 2, "recession": 2, "halt": 1, "antitrust": 2, "fine": 1, "shortfall": 2,
}
MACRO_TAGS = {
    "Fed & rates": ["fed ", "federal reserve", "powell", "warsh", "fomc", "rate hike", "rate cut", "interest rate", "treasury yield", "bond yield"],
    "Inflation": ["inflation", "cpi", "ppi", "pce", "prices rose"],
    "Jobs": ["payrolls", "jobless", "unemployment", "jobs report", "labor market"],
    "Energy & oil": ["oil", "crude", "opec", "brent", "natural gas", "gasoline"],
    "Geopolitics": ["war", "missile", "sanction", "tariff", "ceasefire", "iran", "israel", "russia", "ukraine", "taiwan", "houthi"],
    "China": ["china", "beijing", "yuan", "xi "],
    "Earnings": ["earnings", "quarterly", "guidance", "revenue", "eps", "results"],
    "AI & chips": ["ai ", "artificial intelligence", "chip", "semiconductor", "nvidia", "gpu", "data center"],
    "Crypto": ["bitcoin", "crypto", "ether"],
}


def sentiment(text: str) -> int:
    """Lexicon score: positive is good news for the stock, negative is bad."""
    t = " " + text.lower() + " "
    score = 0
    for lex, sign in ((POSITIVE, 1), (NEGATIVE, -1)):
        for phrase, w in lex.items():
            if " " in phrase:
                if phrase in t:
                    score += sign * w
            elif re.search(r"\b" + re.escape(phrase) + r"\b", t):
                score += sign * w
    # "beat ... but cuts guidance" style headlines lean on the guidance part
    return max(-5, min(5, score))


def tags(text: str) -> List[str]:
    t = " " + text.lower() + " "
    return [name for name, keys in MACRO_TAGS.items() if any(k in t for k in keys)]


def _clean(s: Optional[str]) -> str:
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", s).strip()


def parse_rss(xml_text: str, source: str = "") -> List[dict]:
    if "<!ENTITY" in xml_text[:5000]:  # refuse entity definitions (billion-laughs style payloads)
        raise ProviderError("feed declares XML entities; refusing to parse")
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise ProviderError(f"bad feed: {e}") from e
    items = []
    for it in root.iter("item"):
        title = _clean(it.findtext("title"))
        if not title:
            continue
        link = (it.findtext("link") or "").strip()
        desc = _clean(it.findtext("description"))[:400]
        pub = it.findtext("pubDate")
        ts = 0
        if pub:
            try:
                ts = int(parsedate_to_datetime(pub).timestamp())
            except (TypeError, ValueError):
                ts = 0
        src = _clean(it.findtext("source")) or source
        items.append({"title": title, "link": link if link.startswith(("http://", "https://")) else "",
                      "summary": desc if desc != title else "", "time": ts, "source": src})
    return items


def _id(item: dict) -> str:
    return hashlib.sha1((item["title"].lower()[:120]).encode()).hexdigest()[:16]


class NewsFeed:
    """Collects symbol and macro headlines, deduplicated and scored."""

    def __init__(self, macro_queries: Optional[Iterable[str]] = None, max_items: int = 150,
                 fetch=http_get_text):
        self.macro_queries = list(macro_queries or [
            "stock market", "Federal Reserve interest rates", "inflation CPI", "oil prices OPEC", "geopolitics markets",
        ])
        self.max_items = max_items
        self._fetch = fetch
        self.items: Dict[str, dict] = {}
        self.errors: List[str] = []

    @staticmethod
    def symbol_feed(symbol: str) -> str:
        return ("https://feeds.finance.yahoo.com/rss/2.0/headline?" +
                urllib.parse.urlencode({"s": symbol, "region": "US", "lang": "en-US"}))

    @staticmethod
    def query_feed(q: str) -> str:
        return "https://news.google.com/rss/search?" + urllib.parse.urlencode(
            {"q": q + " when:2d", "hl": "en-US", "gl": "US", "ceid": "US:en"})

    def refresh(self, symbols: Iterable[str]) -> List[dict]:
        """Fetch all feeds. Returns the items that are new since the last refresh."""
        self.errors = []
        jobs = [(self.symbol_feed(s), "Yahoo Finance", s) for s in symbols]
        jobs += [(self.query_feed(q), "Google News", None) for q in self.macro_queries]
        new = []
        for url, src, sym in jobs:
            try:
                parsed = parse_rss(self._fetch(url), src)
            except ProviderError as e:
                self.errors.append(f"{sym or 'macro'}: {e}")
                continue
            for item in parsed[:25]:
                text = item["title"] + " " + item["summary"]
                key = _id(item)
                existing = self.items.get(key)
                if existing:
                    if sym and sym not in existing["symbols"]:
                        existing["symbols"].append(sym)
                    continue
                item.update(id=key, symbols=[sym] if sym else [], sentiment=sentiment(text), tags=tags(text),
                            seen=int(time.time()))
                self.items[key] = item
                new.append(item)
        self._trim()
        return new

    def _trim(self):
        cutoff = time.time() - 4 * 86400
        for k in [k for k, v in self.items.items() if v["time"] and v["time"] < cutoff]:
            del self.items[k]
        if len(self.items) > self.max_items:
            keep = sorted(self.items.values(), key=lambda x: x["time"] or x["seen"], reverse=True)[:self.max_items]
            self.items = {x["id"]: x for x in keep}

    def latest(self, limit: int = 80) -> List[dict]:
        return sorted(self.items.values(), key=lambda x: x["time"] or x["seen"], reverse=True)[:limit]

    def for_symbol(self, symbol: str, limit: int = 10) -> List[dict]:
        return [x for x in self.latest(self.max_items) if symbol in x["symbols"]][:limit]
