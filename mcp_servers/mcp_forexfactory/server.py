"""
MCP Server: mcp-forexfactory
ForexFactory calendar scraper + NewsAPI macro news filter.
Run standalone: python mcp_servers/mcp_forexfactory/server.py
"""

import os
import requests
from datetime import datetime, timedelta
from typing import Optional
from bs4 import BeautifulSoup
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("mcp-forexfactory")

NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "")
FF_BASE_URL = "https://www.forexfactory.com"
FF_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

_events_cache: dict = {}
_cache_time: Optional[datetime] = None
_CACHE_TTL_MIN = 5


def _refresh_cache_if_needed():
    global _cache_time
    now = datetime.utcnow()
    if _cache_time and (now - _cache_time).seconds < _CACHE_TTL_MIN * 60:
        return
    try:
        _fetch_ff_calendar()
        _cache_time = now
    except Exception as e:
        print(f"[mcp-forexfactory] Calendar fetch error: {e}")


def _fetch_ff_calendar() -> list:
    """Scrape ForexFactory calendar for today's events."""
    global _events_cache
    try:
        resp = requests.get(f"{FF_BASE_URL}/calendar", headers=FF_HEADERS, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        rows = soup.select("tr.calendar__row")
        events = []
        current_time = ""
        for row in rows:
            time_cell = row.select_one(".calendar__time")
            if time_cell and time_cell.text.strip():
                current_time = time_cell.text.strip()
            currency_cell = row.select_one(".calendar__currency")
            impact_cell = row.select_one(".calendar__impact")
            event_cell = row.select_one(".calendar__event")
            forecast_cell = row.select_one(".calendar__forecast")
            previous_cell = row.select_one(".calendar__previous")
            if not currency_cell or not impact_cell or not event_cell:
                continue
            impact_span = impact_cell.select_one("span")
            impact_class = impact_span.get("class", []) if impact_span else []
            if "icon--ff-impact-red" in " ".join(impact_class):
                impact = "HIGH"
            elif "icon--ff-impact-ora" in " ".join(impact_class):
                impact = "MEDIUM"
            else:
                impact = "LOW"
            events.append({
                "time": current_time,
                "currency": currency_cell.text.strip(),
                "impact": impact,
                "name": event_cell.text.strip(),
                "forecast": forecast_cell.text.strip() if forecast_cell else "",
                "previous": previous_cell.text.strip() if previous_cell else "",
            })
        _events_cache = {"date": datetime.utcnow().strftime("%Y-%m-%d"), "events": events}
        return events
    except Exception as e:
        print(f"[mcp-forexfactory] Parse error: {e}")
        return _events_cache.get("events", [])


# ── Tools ──────────────────────────────────────────────────────────────────────

@mcp.tool()
def get_events_today() -> list:
    """Return all economic events for today with time, currency, and impact."""
    _refresh_cache_if_needed()
    return _events_cache.get("events", [])


@mcp.tool()
def is_news_window(currency: str, buffer_min: int = 30) -> bool:
    """
    Return True if a HIGH-impact event for the currency is within buffer_min
    minutes (before or after). Used to block trades.
    """
    events = get_events_today()
    now_utc = datetime.utcnow()
    for event in events:
        if event["currency"] != currency or event["impact"] != "HIGH":
            continue
        try:
            event_time = datetime.strptime(
                f"{now_utc.strftime('%Y-%m-%d')} {event['time']}", "%Y-%m-%d %I:%M%p"
            )
            delta = abs((event_time - now_utc).total_seconds() / 60)
            if delta <= buffer_min:
                return True
        except ValueError:
            continue
    return False


@mcp.tool()
def get_next_high_impact(currency: str) -> Optional[dict]:
    """Return the next HIGH-impact event for a currency, or None."""
    events = get_events_today()
    now_utc = datetime.utcnow()
    for event in events:
        if event["currency"] != currency or event["impact"] != "HIGH":
            continue
        try:
            event_time = datetime.strptime(
                f"{now_utc.strftime('%Y-%m-%d')} {event['time']}", "%Y-%m-%d %I:%M%p"
            )
            if event_time > now_utc:
                return {**event, "minutes_away": int((event_time - now_utc).total_seconds() / 60)}
        except ValueError:
            continue
    return None


@mcp.tool()
def get_live_news(keywords: list) -> list:
    """Fetch breaking news articles matching keywords via NewsAPI."""
    if not NEWSAPI_KEY:
        return []
    try:
        query = " OR ".join(keywords[:5])
        resp = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": query,
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": 5,
                "apiKey": NEWSAPI_KEY,
            },
            timeout=8,
        )
        data = resp.json()
        articles = data.get("articles", [])
        return [
            {
                "title": a["title"],
                "description": a.get("description", ""),
                "published": a["publishedAt"],
                "source": a["source"]["name"],
            }
            for a in articles
        ]
    except Exception as e:
        print(f"[mcp-forexfactory] NewsAPI error: {e}")
        return []


@mcp.tool()
def score_sentiment(currency: str) -> str:
    """
    Rough sentiment score based on recent news headlines.
    Returns BULLISH | BEARISH | NEUTRAL
    """
    currency_map = {
        "USD": ["dollar", "fed", "fomc", "us economy", "usd"],
        "EUR": ["euro", "ecb", "european", "eur"],
        "GBP": ["pound", "sterling", "boe", "bank of england", "gbp"],
        "JPY": ["yen", "boj", "bank of japan", "jpy"],
    }
    keywords = currency_map.get(currency.upper(), [currency.lower()])
    articles = get_live_news(keywords)
    if not articles:
        return "NEUTRAL"

    bullish_words = ["rise", "gain", "strong", "beat", "better", "surge", "positive", "growth"]
    bearish_words = ["fall", "drop", "weak", "miss", "worse", "decline", "negative", "recession"]

    score = 0
    for a in articles:
        text = (a["title"] + " " + a.get("description", "")).lower()
        for w in bullish_words:
            if w in text:
                score += 1
        for w in bearish_words:
            if w in text:
                score -= 1

    if score > 1:
        return "BULLISH"
    if score < -1:
        return "BEARISH"
    return "NEUTRAL"


@mcp.tool()
def get_blocked_currencies() -> list:
    """Return list of currencies currently in a news block window (30min buffer)."""
    currencies = ["USD", "EUR", "GBP", "JPY", "CHF", "AUD", "CAD"]
    return [c for c in currencies if is_news_window(c, buffer_min=30)]


if __name__ == "__main__":
    mcp.run()
