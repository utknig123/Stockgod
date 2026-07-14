"""
HTTP-based scraping (no browser) — Reddit RSS/JSON, StockTwits API, news RSS.

Source health (verified Jul 2026):
- Reddit .rss feeds: working, fresh data (JSON endpoints return 403)
- PullPush: stale archive (~1 year old) — last-resort fallback only
- StockTwits: needs .NSE suffix for Indian tickers (e.g. PAYTM.NSE)
- Google News RSS + Bing News RSS: working
- Yahoo Finance RSS: returns empty feeds for .NS tickers — Bing used instead
"""
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Dict, List
from urllib.parse import quote_plus

import requests

logger = logging.getLogger(__name__)

ATOM_NS = "{http://www.w3.org/2005/Atom}"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
)
DEFAULT_TIMEOUT = 20


def _stable_id(text: str) -> str:
    """Deterministic hash so re-scraped headlines dedupe across runs
    (built-in hash() is salted per-process)."""
    import hashlib
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:12]


def normalize_symbol(symbol: str) -> str:
    """PAYTM.NS -> PAYTM for APIs that use bare tickers."""
    return symbol.split(".")[0].upper().strip()


def yahoo_ticker(symbol: str) -> str:
    """Keep NSE suffix when present (e.g. PAYTM.NS)."""
    symbol = symbol.strip().upper()
    if "." in symbol:
        return symbol
    return f"{normalize_symbol(symbol)}.NS"


class HttpScraper:
    # Reddit rate-limits unauthenticated clients aggressively; space requests out
    # (~10 req/min is the observed safe ceiling for anonymous RSS/JSON access)
    REDDIT_MIN_INTERVAL = 6.0
    # Ignore archive posts older than this — they'd pollute the real-time pipeline
    MAX_POST_AGE_DAYS = 90

    def __init__(self, timeout: int = DEFAULT_TIMEOUT):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self._last_reddit_request = 0.0

    def _reddit_get(self, url: str, **kwargs):
        """GET against reddit.com with spacing and one retry on 429."""
        wait = self.REDDIT_MIN_INTERVAL - (time.time() - self._last_reddit_request)
        if wait > 0:
            time.sleep(wait)
        self._last_reddit_request = time.time()
        resp = self.session.get(url, timeout=self.timeout, **kwargs)
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After") or 10)
            time.sleep(min(retry_after, 30))
            self._last_reddit_request = time.time()
            resp = self.session.get(url, timeout=self.timeout, **kwargs)
        return resp

    def fetch_reddit_subreddit(self, subreddit: str, limit: int = 25) -> List[Dict]:
        # RSS is the only Reddit endpoint that reliably works without OAuth.
        for feed in ("hot", "new"):
            url = f"https://www.reddit.com/r/{subreddit}/{feed}.rss?limit={min(limit, 100)}"
            posts = self._fetch_reddit_rss(url, f"r/{subreddit}/{feed}")
            if posts:
                return posts[:limit]

        posts = self._fetch_reddit_json(
            f"https://www.reddit.com/r/{subreddit}/hot.json?limit={min(limit, 100)}",
            f"r/{subreddit}", limit,
        )
        if posts:
            return posts

        # PullPush archive is stale (months old) — last resort only.
        return self._fetch_reddit_pullpush(subreddit=subreddit, limit=limit)

    def fetch_reddit_search(self, query: str, limit: int = 20) -> List[Dict]:
        url = f"https://www.reddit.com/search.rss?q={quote_plus(query)}&sort=new&limit={min(limit, 100)}"
        posts = self._fetch_reddit_rss(url, f"search '{query}'")
        if posts:
            return posts[:limit]

        posts = self._fetch_reddit_json(
            f"https://www.reddit.com/search.json?q={quote_plus(query)}&sort=new&limit={min(limit, 100)}",
            f"search '{query}'", limit,
        )
        if posts:
            return posts

        return self._fetch_reddit_pullpush(query=query, limit=limit)

    def _fetch_reddit_rss(self, url: str, label: str) -> List[Dict]:
        """Parse a Reddit Atom feed into standard post dicts."""
        posts = []
        try:
            resp = self._reddit_get(url)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            for entry in root.findall(f"{ATOM_NS}entry"):
                title = (entry.findtext(f"{ATOM_NS}title") or "").strip()
                if not title or len(title) < 5:
                    continue
                entry_id = (entry.findtext(f"{ATOM_NS}id") or "").strip()
                author = (entry.findtext(f"{ATOM_NS}author/{ATOM_NS}name") or "unknown").removeprefix("/u/")
                updated = (entry.findtext(f"{ATOM_NS}updated") or "").strip()
                try:
                    ts = datetime.fromisoformat(updated.replace("Z", "+00:00")).replace(tzinfo=None)
                except ValueError:
                    ts = datetime.utcnow()
                link_el = entry.find(f"{ATOM_NS}link")
                link = link_el.get("href", "") if link_el is not None else ""
                # Strip HTML from the content snippet to enrich the post body
                content_html = entry.findtext(f"{ATOM_NS}content") or ""
                snippet = re.sub(r"<[^>]+>", " ", content_html)
                snippet = re.sub(r"\s+", " ", snippet).strip()
                snippet = snippet.replace("[link]", "").replace("[comments]", "").strip()
                content = f"{title}\n\n{snippet}" if snippet and snippet != title else title
                posts.append({
                    "id": entry_id.split("/")[-1] or f"reddit_{len(posts)}",
                    "content": content[:2000],
                    "author": author,
                    "url": link,
                    "engagement": 0,
                    "timestamp": ts,
                })
            logger.info(f"Reddit RSS: {len(posts)} posts from {label}")
        except Exception as e:
            logger.warning(f"Reddit RSS failed for {label}: {e}")
        return posts

    def _fetch_reddit_json(self, url: str, label: str, limit: int) -> List[Dict]:
        posts = []
        try:
            resp = self._reddit_get(url)
            resp.raise_for_status()
            children = resp.json().get("data", {}).get("children", [])
            for child in children[:limit]:
                post = self._parse_reddit_child(child)
                if post:
                    posts.append(post)
            logger.info(f"Reddit JSON: {len(posts)} posts from {label}")
        except Exception as e:
            logger.warning(f"Reddit JSON failed for {label}: {e}")
        return posts

    def _fetch_reddit_pullpush(
        self,
        subreddit: str = None,
        query: str = None,
        limit: int = 25,
    ) -> List[Dict]:
        posts = []
        params = {"size": min(limit, 100), "sort": "desc", "sort_type": "created_utc"}
        if subreddit:
            params["subreddit"] = subreddit
        if query:
            params["q"] = query
        url = "https://api.pullpush.io/reddit/search/submission/"
        cutoff = datetime.utcnow() - timedelta(days=self.MAX_POST_AGE_DAYS)
        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
            resp.raise_for_status()
            for item in resp.json().get("data", [])[:limit]:
                title = (item.get("title") or "").strip()
                selftext = (item.get("selftext") or "").strip()
                content = f"{title}\n\n{selftext}".strip() if selftext else title
                if not content or len(content) < 5:
                    continue
                created = item.get("created_utc")
                ts = datetime.utcfromtimestamp(created) if created else datetime.utcnow()
                # PullPush archive lags by months; skip stale posts entirely
                if ts < cutoff:
                    continue
                permalink = item.get("permalink") or ""
                posts.append({
                    "id": str(item.get("id") or f"reddit_{len(posts)}"),
                    "content": content,
                    "author": item.get("author") or "unknown",
                    "url": f"https://www.reddit.com{permalink}" if permalink else "",
                    "engagement": int(item.get("score") or 0),
                    "timestamp": ts,
                })
            logger.info(f"PullPush Reddit: {len(posts)} posts")
        except Exception as e:
            logger.warning(f"PullPush Reddit failed: {e}")
        return posts

    def _parse_reddit_child(self, child: dict) -> Dict | None:
        try:
            data = child.get("data", {})
            title = (data.get("title") or "").strip()
            selftext = (data.get("selftext") or "").strip()
            content = f"{title}\n\n{selftext}".strip() if selftext else title
            if not content or len(content) < 5:
                return None
            created = data.get("created_utc")
            ts = datetime.utcfromtimestamp(created) if created else datetime.utcnow()
            return {
                "id": data.get("name") or data.get("id") or f"reddit_{int(ts.timestamp())}",
                "content": content,
                "author": data.get("author") or "unknown",
                "url": f"https://www.reddit.com{data.get('permalink', '')}",
                "engagement": int(data.get("score") or 0),
                "timestamp": ts,
            }
        except Exception as e:
            logger.debug(f"Reddit parse error: {e}")
            return None

    # Renamed/rebranded tickers (e.g. Zomato -> Eternal Ltd in 2025)
    STOCKTWITS_ALIASES = {"ZOMATO": "ETERNAL"}

    def fetch_stocktwits(self, symbol: str, limit: int = 20) -> List[Dict]:
        """Indian NSE stocks live under TICKER.NSE on StockTwits (e.g. PAYTM.NSE)."""
        base = normalize_symbol(symbol)
        base = self.STOCKTWITS_ALIASES.get(base, base)
        candidates = [f"{base}.NSE", base] if symbol.upper().endswith(".NS") else [base, f"{base}.NSE"]
        for ticker in candidates:
            posts = self._fetch_stocktwits_ticker(ticker, limit)
            if posts:
                return posts
        return []

    def _fetch_stocktwits_ticker(self, ticker: str, limit: int) -> List[Dict]:
        posts = []
        url = f"https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"
        try:
            resp = self.session.get(url, timeout=self.timeout)
            if resp.status_code == 404:
                logger.info(f"StockTwits has no stream for {ticker}")
                return posts
            resp.raise_for_status()
            messages = resp.json().get("messages", [])
            for msg in messages[:limit]:
                body = (msg.get("body") or "").strip()
                if not body or len(body) < 5:
                    continue
                user = (msg.get("user") or {}).get("username") or "stocktwits_user"
                created = msg.get("created_at")
                try:
                    ts = datetime.strptime(created, "%Y-%m-%dT%H:%M:%SZ") if created else datetime.utcnow()
                except ValueError:
                    ts = datetime.utcnow()
                likes = msg.get("likes")
                engagement = int(likes.get("total", 0)) if isinstance(likes, dict) else 0
                posts.append({
                    "id": str(msg.get("id") or f"stocktwits_{ticker}_{len(posts)}"),
                    "content": body,
                    "author": user,
                    "url": f"https://stocktwits.com/symbol/{ticker}",
                    "engagement": engagement,
                    "timestamp": ts,
                })
            logger.info(f"StockTwits API: {len(posts)} messages for {ticker}")
        except Exception as e:
            logger.warning(f"StockTwits API failed for {ticker}: {e}")
        return posts

    def fetch_google_news_rss(self, query: str, limit: int = 15) -> List[Dict]:
        posts = []
        url = (
            "https://news.google.com/rss/search"
            f"?q={quote_plus(query)}&hl=en-IN&gl=IN&ceid=IN:en"
        )
        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            for item in root.findall(".//item")[:limit]:
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                if not title or len(title) < 10:
                    continue
                posts.append({
                    "id": f"gnews_{_stable_id(title)}",
                    "content": title,
                    "author": "google_news",
                    "url": link or url,
                    "engagement": 0,
                    "timestamp": datetime.utcnow(),
                })
            logger.info(f"Google News RSS: {len(posts)} items for '{query}'")
        except Exception as e:
            logger.warning(f"Google News RSS failed: {e}")
        return posts

    def fetch_bing_news_rss(self, query: str, limit: int = 15) -> List[Dict]:
        posts = []
        url = f"https://www.bing.com/news/search?q={quote_plus(query)}&format=rss"
        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            for item in root.findall(".//item")[:limit]:
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                if not title or len(title) < 10:
                    continue
                posts.append({
                    "id": f"bing_{_stable_id(title)}",
                    "content": title,
                    "author": "bing_news",
                    "url": link or url,
                    "engagement": 0,
                    "timestamp": datetime.utcnow(),
                })
            logger.info(f"Bing News RSS: {len(posts)} items for '{query}'")
        except Exception as e:
            logger.warning(f"Bing News RSS failed: {e}")
        return posts

    def fetch_yahoo_news_rss(self, symbol: str, limit: int = 10) -> List[Dict]:
        """Yahoo per-ticker RSS is empty for NSE tickers; try it, then Bing News."""
        posts = []
        ticker = yahoo_ticker(symbol)
        url = f"https://finance.yahoo.com/rss/headline?s={quote_plus(ticker)}"
        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            for item in root.findall(".//item")[:limit]:
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                if not title or len(title) < 10:
                    continue
                posts.append({
                    "id": f"yahoo_{_stable_id(title)}",
                    "content": title,
                    "author": "yahoo_finance",
                    "url": link or f"https://finance.yahoo.com/quote/{ticker}",
                    "engagement": 0,
                    "timestamp": datetime.utcnow(),
                })
            logger.info(f"Yahoo RSS: {len(posts)} headlines for {ticker}")
        except Exception as e:
            logger.warning(f"Yahoo RSS failed for {ticker}: {e}")

        if not posts:
            posts = self.fetch_bing_news_rss(f"{normalize_symbol(symbol)} stock NSE", limit=limit)
        return posts
