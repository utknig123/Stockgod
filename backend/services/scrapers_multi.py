"""
High-volume multi-source scrapers for Indian stocks.
Targets ~50+ items per source when available and 100–200+ unique posts overall.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote_plus

import httpx

from services.company_search import normalize_nse_symbol

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
)
ATOM_NS = "{http://www.w3.org/2005/Atom}"

SOURCE_TARGET = 50
TOTAL_TARGET_MIN = 100
TOTAL_TARGET_MAX = 200


def _stable_id(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:12]


def _post(
    content: str,
    source: str,
    platform: str,
    url: str = "",
    author: Optional[str] = None,
    engagement: int = 0,
    prefix: Optional[str] = None,
) -> Dict:
    content = (content or "").strip()
    return {
        "id": f"{prefix or source}_{_stable_id(content)}",
        "content": content[:2500],
        "author": author or source,
        "url": url,
        "platform": platform,
        "source": source,
        "engagement": engagement or 0,
    }


async def _http_get(client: httpx.AsyncClient, url: str, params: dict = None) -> Optional[httpx.Response]:
    try:
        resp = await client.get(url, params=params)
        if resp.status_code == 200:
            return resp
        logger.warning(f"HTTP {resp.status_code} for {url[:120]}")
    except Exception as e:
        logger.warning(f"HTTP failed {url[:120]}: {e}")
    return None


def _parse_rss_items(content: bytes) -> List[Tuple[str, str, str]]:
    out = []
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return out

    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = (item.findtext("description") or "").strip()
        desc = re.sub(r"<[^>]+>", " ", desc)
        desc = desc.replace("&nbsp;", " ").replace("&amp;", "&").replace("&quot;", '"')
        desc = re.sub(r"&\w+;", " ", desc)
        desc = re.sub(r"\s+", " ", desc).strip()
        if title and len(title) >= 8:
            out.append((title, link, desc))

    if not out:
        for entry in root.findall(f".//{ATOM_NS}entry"):
            title = (entry.findtext(f"{ATOM_NS}title") or "").strip()
            link_el = entry.find(f"{ATOM_NS}link")
            link = link_el.get("href", "") if link_el is not None else ""
            summary = (
                entry.findtext(f"{ATOM_NS}summary")
                or entry.findtext(f"{ATOM_NS}content")
                or ""
            ).strip()
            summary = re.sub(r"<[^>]+>", " ", summary)
            summary = re.sub(r"\s+", " ", summary).strip()
            if title and len(title) >= 5:
                out.append((title, link, summary))
    return out


async def scrape_google_news_query(
    client: httpx.AsyncClient, query: str, source: str = "google_news", limit: int = 100
) -> List[Dict]:
    url = (
        "https://news.google.com/rss/search"
        f"?q={quote_plus(query)}&hl=en-IN&gl=IN&ceid=IN:en&num={min(limit, 100)}"
    )
    resp = await _http_get(client, url)
    posts = []
    if not resp:
        return posts
    for title, link, desc in _parse_rss_items(resp.content)[:limit]:
        body = f"{title}. {desc}" if desc and desc.lower() not in title.lower() else title
        posts.append(_post(body, source, "news", link or url, author=source, prefix=source))
    return posts


async def scrape_bing_news_queries(
    client: httpx.AsyncClient, queries: List[str], limit_each: int = 20
) -> List[Dict]:
    posts = []
    seen = set()
    for q in queries:
        url = f"https://www.bing.com/news/search?q={quote_plus(q)}&format=rss"
        resp = await _http_get(client, url)
        if not resp:
            continue
        for title, link, desc in _parse_rss_items(resp.content)[:limit_each]:
            key = title[:90].lower()
            if key in seen:
                continue
            seen.add(key)
            body = f"{title}. {desc}" if desc else title
            posts.append(_post(body, "bing_news", "news", link or url, author="bing_news"))
    return posts


async def scrape_yahoo_rss(client: httpx.AsyncClient, symbol: str, limit: int = 50) -> List[Dict]:
    ticker = normalize_nse_symbol(symbol)
    url = f"https://finance.yahoo.com/rss/headline?s={quote_plus(ticker)}"
    resp = await _http_get(client, url)
    posts = []
    if not resp:
        return posts
    for title, link, desc in _parse_rss_items(resp.content)[:limit]:
        body = f"{title}. {desc}" if desc else title
        posts.append(_post(
            body, "yahoo_finance", "news",
            link or f"https://finance.yahoo.com/quote/{ticker}",
            author="yahoo_finance",
        ))
    return posts


async def scrape_generic_rss(
    client: httpx.AsyncClient,
    feed_url: str,
    source: str,
    keywords: List[str],
    limit: int = 80,
    require_keyword: bool = True,
) -> List[Dict]:
    resp = await _http_get(client, feed_url)
    posts = []
    if not resp:
        return posts
    for title, link, desc in _parse_rss_items(resp.content):
        body = f"{title}. {desc}" if desc else title
        lower = body.lower()
        if require_keyword and keywords:
            if not any(k.lower() in lower for k in keywords if len(k) >= 3):
                continue
        posts.append(_post(body, source, "news", link or feed_url, author=source))
        if len(posts) >= limit:
            break
    return posts


async def scrape_reddit_multi(
    client: httpx.AsyncClient, queries: List[str], keywords: List[str], limit_each: int = 30
) -> List[Dict]:
    posts = []
    seen = set()
    hit_429 = False

    for q in queries[:2]:
        if hit_429:
            break
        for sort in ("new", "top"):
            url = (
                f"https://www.reddit.com/search.rss?q={quote_plus(q)}"
                f"&sort={sort}&t=month&limit={min(limit_each, 100)}"
            )
            try:
                resp = await client.get(url)
            except Exception as e:
                logger.warning(f"Reddit error: {e}")
                continue
            if resp.status_code == 429:
                hit_429 = True
                logger.warning("Reddit rate-limited — skipping remaining Reddit fetches")
                break
            if resp.status_code != 200:
                continue
            for title, link, desc in _parse_rss_items(resp.content)[:limit_each]:
                key = title[:90].lower()
                if key in seen:
                    continue
                seen.add(key)
                body = f"{title}. {desc}" if desc else title
                posts.append(_post(body, "reddit", "reddit", link, author="reddit"))
            if len(posts) >= SOURCE_TARGET:
                return posts

    if not hit_429:
        for sub in ("IndianStockMarket", "IndianStreetBets"):
            if hit_429 or len(posts) >= SOURCE_TARGET:
                break
            url = f"https://www.reddit.com/r/{sub}/hot.rss?limit=100"
            try:
                resp = await client.get(url)
            except Exception:
                continue
            if resp.status_code == 429:
                break
            if resp.status_code != 200:
                continue
            for title, link, desc in _parse_rss_items(resp.content):
                body = f"{title}. {desc}" if desc else title
                if keywords and not any(k.lower() in body.lower() for k in keywords if len(k) >= 3):
                    continue
                key = title[:90].lower()
                if key in seen:
                    continue
                seen.add(key)
                posts.append(_post(body, "reddit", "reddit", link, author=f"r/{sub}"))
    return posts


async def scrape_stocktwits(client: httpx.AsyncClient, symbol: str, limit: int = 50) -> List[Dict]:
    bare = symbol.split(".")[0].upper()
    aliases = {"ZOMATO": "ETERNAL"}
    bare = aliases.get(bare, bare)
    posts = []
    for ticker in [f"{bare}.NSE", bare]:
        url = f"https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"
        resp = await _http_get(client, url)
        if not resp:
            continue
        try:
            messages = resp.json().get("messages") or []
        except Exception:
            continue
        for msg in messages[:limit]:
            body = (msg.get("body") or "").strip()
            if len(body) < 5:
                continue
            user = (msg.get("user") or {}).get("username") or "stocktwits"
            likes = msg.get("likes")
            engagement = int(likes.get("total", 0)) if isinstance(likes, dict) else 0
            posts.append(_post(
                body, "stocktwits", "social",
                f"https://stocktwits.com/symbol/{ticker}",
                author=user, engagement=engagement,
                prefix=f"stw_{msg.get('id', _stable_id(body))}",
            ))
        if posts:
            break
    return posts


async def fetch_yahoo_quote(symbol: str) -> Dict:
    ticker = normalize_nse_symbol(symbol)
    out = {
        "symbol": ticker,
        "price": None,
        "previous_close": None,
        "change": None,
        "change_pct": None,
        "currency": "INR",
        "volume": None,
        "day_high": None,
        "day_low": None,
        "fifty_two_week_high": None,
        "fifty_two_week_low": None,
        "month_change_pct": None,
        "chart": [],
    }
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote_plus(ticker)}"
    async with httpx.AsyncClient(timeout=18.0, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
        resp = await _http_get(client, url, params={"range": "1mo", "interval": "1d"})
    if not resp:
        return out
    try:
        result = (resp.json().get("chart") or {}).get("result") or []
        if not result:
            return out
        r0 = result[0]
        meta = r0.get("meta") or {}
        ts = r0.get("timestamp") or []
        quote = ((r0.get("indicators") or {}).get("quote") or [{}])[0]
        closes = quote.get("close") or []
        volumes = quote.get("volume") or []
        highs = quote.get("high") or []
        lows = quote.get("low") or []

        price = meta.get("regularMarketPrice")
        prev = meta.get("chartPreviousClose") or meta.get("previousClose")
        out.update({
            "price": price,
            "previous_close": prev,
            "currency": meta.get("currency") or "INR",
            "fifty_two_week_high": meta.get("fiftyTwoWeekHigh"),
            "fifty_two_week_low": meta.get("fiftyTwoWeekLow"),
            "exchange": meta.get("exchangeName"),
        })
        if price is not None and prev:
            out["change"] = round(price - prev, 2)
            out["change_pct"] = round(((price - prev) / prev) * 100, 2)

        from datetime import datetime, timezone
        chart = []
        for i, t in enumerate(ts):
            c = closes[i] if i < len(closes) else None
            if c is None:
                continue
            chart.append({
                "date": datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d"),
                "close": round(float(c), 2),
                "volume": int(volumes[i]) if i < len(volumes) and volumes[i] is not None else 0,
                "high": round(float(highs[i]), 2) if i < len(highs) and highs[i] is not None else None,
                "low": round(float(lows[i]), 2) if i < len(lows) and lows[i] is not None else None,
            })
        out["chart"] = chart
        if chart:
            out["day_high"] = chart[-1].get("high")
            out["day_low"] = chart[-1].get("low")
            out["volume"] = chart[-1].get("volume")
            if len(chart) >= 2 and chart[0]["close"]:
                out["month_change_pct"] = round(
                    ((chart[-1]["close"] - chart[0]["close"]) / chart[0]["close"]) * 100, 2
                )
    except Exception as e:
        logger.warning(f"Yahoo quote parse error: {e}")
    return out


def _build_queries(symbol: str, name: str, bare: str) -> List[str]:
    short = re.sub(r"\([^)]*\)", "", name).strip()
    return [
        f"{short} stock NSE India",
        f"{bare} share price",
        f"{short} results OR earnings OR revenue",
        f"{short} stock news",
        f"{bare} NSE",
        f"{short} buy OR sell OR target OR brokerage",
    ]


def _dedupe_cap(items: List[Dict], keywords: List[str], cap: int) -> List[Dict]:
    seen = set()
    unique = []
    for p in items:
        key = p["content"][:100].lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)
    unique.sort(
        key=lambda p: (
            0 if any(k.lower() in p["content"].lower() for k in keywords if len(k) >= 3) else 1,
            -len(p["content"]),
        )
    )
    return unique[:cap]


async def scrape_company_high_volume(company: Dict) -> Tuple[List[Dict], Dict[str, int]]:
    symbol = company["symbol"]
    name = company["name"]
    keywords = company.get("keywords") or [symbol.split(".")[0].lower(), name.lower()]
    bare = symbol.split(".")[0]
    queries = _build_queries(symbol, name, bare)

    site_map = {
        "moneycontrol": "site:moneycontrol.com",
        "economic_times": "site:economictimes.indiatimes.com",
        "business_standard": "site:business-standard.com",
        "livemint": "site:livemint.com",
        "reuters": "site:reuters.com",
        "zeebiz": "site:zeebiz.com",
        "the_hindu": "site:thehindu.com OR site:thehindubusinessline.com",
    }

    async with httpx.AsyncClient(
        timeout=18.0, headers={"User-Agent": USER_AGENT}, follow_redirects=True
    ) as client:
        tasks = []

        for q in queries[:4]:
            tasks.append(("google_news", scrape_google_news_query(client, q, "google_news", 100)))

        for src, site in site_map.items():
            for q in [f"{bare} {site}", f"{name} stock {site}"]:
                tasks.append((src, scrape_google_news_query(client, q, src, 100)))

        tasks.append(("bing_news", scrape_bing_news_queries(client, queries, 20)))
        tasks.append(("yahoo_finance", scrape_yahoo_rss(client, symbol, 50)))
        tasks.append((
            "et_markets_rss",
            scrape_generic_rss(
                client,
                "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
                "et_markets_rss", keywords, 80, True,
            ),
        ))
        tasks.append((
            "livemint_rss",
            scrape_generic_rss(client, "https://www.livemint.com/rss/markets", "livemint_rss", keywords, 60, True),
        ))
        tasks.append((
            "ndtv_profit",
            scrape_generic_rss(
                client, "https://feeds.feedburner.com/ndtvprofit-latest", "ndtv_profit", keywords, 40, True
            ),
        ))
        tasks.append((
            "reddit",
            scrape_reddit_multi(client, [f"{bare} stock", name, f"{bare} NSE"], keywords, 30),
        ))
        tasks.append(("stocktwits", scrape_stocktwits(client, symbol, 50)))

        gathered = await asyncio.gather(*[t[1] for t in tasks], return_exceptions=True)

    buckets: Dict[str, List[Dict]] = {}
    for (src, _), result in zip(tasks, gathered):
        if isinstance(result, Exception):
            logger.warning(f"Source {src} failed: {result}")
            continue
        buckets.setdefault(src, []).extend(result)

    async with httpx.AsyncClient(
        timeout=18.0, headers={"User-Agent": USER_AGENT}, follow_redirects=True
    ) as client:
        if len(buckets.get("et_markets_rss") or []) < 20:
            more = await scrape_generic_rss(
                client,
                "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
                "et_markets_rss", keywords, 50, False,
            )
            buckets.setdefault("et_markets_rss", []).extend(more)
        if len(buckets.get("livemint_rss") or []) < 15:
            more = await scrape_generic_rss(
                client, "https://www.livemint.com/rss/markets", "livemint_rss", keywords, 40, False
            )
            buckets.setdefault("livemint_rss", []).extend(more)

    # Per-source unique pools (before cross-source merge)
    per_source_unique: Dict[str, List[Dict]] = {}
    for source, items in buckets.items():
        per_source_unique[source] = _dedupe_cap(items, keywords, 120)

    preferred_order = [
        "moneycontrol", "economic_times", "business_standard", "livemint",
        "reuters", "zeebiz", "the_hindu", "google_news", "yahoo_finance",
        "et_markets_rss", "livemint_rss", "ndtv_profit", "bing_news",
        "reddit", "stocktwits",
    ]
    ordered_sources = [s for s in preferred_order if s in per_source_unique]
    ordered_sources += [s for s in per_source_unique if s not in ordered_sources]

    # Take up to SOURCE_TARGET (50) from each source in priority order until
    # we fill TOTAL_TARGET_MAX (200). That typically yields 4×50 sources.
    merged: List[Dict] = []
    global_seen = set()
    source_counts: Dict[str, int] = {}

    for src in ordered_sources:
        if len(merged) >= TOTAL_TARGET_MAX:
            break
        taken = 0
        room = TOTAL_TARGET_MAX - len(merged)
        # Prefer full 50-packs while room remains for another full pack
        allowed = min(SOURCE_TARGET, room)
        for p in per_source_unique[src]:
            if taken >= allowed:
                break
            gkey = p["content"][:100].lower()
            if gkey in global_seen:
                continue
            global_seen.add(gkey)
            merged.append({**p, "author": src, "source": src})
            taken += 1
        if taken:
            source_counts[src] = taken

    if len(merged) < TOTAL_TARGET_MIN:
        async with httpx.AsyncClient(
            timeout=18.0, headers={"User-Agent": USER_AGENT}, follow_redirects=True
        ) as client:
            for q in queries + [f"{bare} India stock market", f"{name} analysts"]:
                for p in await scrape_google_news_query(client, q, "google_news", 100):
                    gkey = p["content"][:100].lower()
                    if gkey in global_seen:
                        continue
                    global_seen.add(gkey)
                    merged.append({**p, "author": "google_news", "source": "google_news"})
                    source_counts["google_news"] = source_counts.get("google_news", 0) + 1
                    if len(merged) >= TOTAL_TARGET_MIN:
                        break
                if len(merged) >= TOTAL_TARGET_MIN:
                    break

    source_counts = {k: v for k, v in source_counts.items() if v > 0}
    # Also attach raw pool sizes for analytics transparency
    for src, items in per_source_unique.items():
        source_counts.setdefault(src, 0)
    # Keep only sources that contributed scored posts
    source_counts = {k: v for k, v in source_counts.items() if v > 0}
    return merged[:TOTAL_TARGET_MAX], source_counts
