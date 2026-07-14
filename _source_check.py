"""Quick health check of all HTTP scraping sources (run from repo root)."""
import sys
sys.path.insert(0, "scrapers")
import logging
logging.basicConfig(level=logging.INFO, format="%(message)s")

from utils.http_scraper import HttpScraper

h = HttpScraper()

checks = {
    "reddit_subreddit": lambda: h.fetch_reddit_subreddit("IndianStockMarket", limit=5),
    "reddit_search": lambda: h.fetch_reddit_search("paytm stock", limit=5),
    "stocktwits_paytm": lambda: h.fetch_stocktwits("PAYTM.NS", limit=5),
    "google_news": lambda: h.fetch_google_news_rss("zomato stock", limit=5),
    "bing_news": lambda: h.fetch_bing_news_rss("nykaa stock NSE", limit=5),
    "yahoo_or_bing": lambda: h.fetch_yahoo_news_rss("PAYTM.NS", limit=5),
}

results = {}
for name, fn in checks.items():
    try:
        posts = fn()
        results[name] = len(posts)
        sample = posts[0]["content"][:80].replace("\n", " ") if posts else ""
        print(f"[{name}] {len(posts)} posts | {sample}")
    except Exception as e:
        results[name] = f"ERROR: {e}"
        print(f"[{name}] ERROR: {e}")

print("\nSUMMARY:", results)
