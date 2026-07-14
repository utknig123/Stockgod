"""
On-demand scrape → score → store → suggest for any Indian company.
High-volume multi-source + richer analytics payload.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import mongodb_db
from models import Company, SentimentScore
from services.company_search import build_keywords, normalize_nse_symbol, resolve_company
from services.scrapers_multi import fetch_yahoo_quote, scrape_company_high_volume
from services.sentiment_local import analyze_text, analyze_batch

logger = logging.getLogger(__name__)

STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "at", "by",
    "from", "is", "are", "was", "were", "be", "been", "as", "that", "this", "it",
    "its", "into", "over", "after", "before", "about", "than", "then", "will", "can",
    "stock", "share", "shares", "price", "market", "india", "indian", "nse", "bse",
    "ltd", "limited", "rs", "crore", "lakh", "says", "amid", "near", "vs", "via",
    "nbsp", "quot", "amp", "http", "https", "www", "com", "html",
}


def build_suggestion(
    avg_sentiment: float,
    post_count: int,
    positive_pct: float,
    negative_pct: float,
    platform_count: int,
    quote: Optional[Dict] = None,
) -> Dict:
    confidence = "low"
    if post_count >= 80 and platform_count >= 3:
        confidence = "high"
    elif post_count >= 30:
        confidence = "medium"

    price_note = ""
    if quote and quote.get("change_pct") is not None:
        price_note = f" Price today {quote.get('change_pct'):+.2f}%."

    if post_count < 10:
        action, label, color = "INSUFFICIENT_DATA", "Not enough data", "gray"
        rationale = (
            f"Only {post_count} posts found across sources. "
            "Retry later or pick a more liquid name for stronger coverage."
        )
    elif avg_sentiment >= 0.35 and positive_pct >= 0.4:
        action, label, color = "BUY", "Bullish — lean BUY", "green"
        rationale = (
            f"Strong positive news/social tone ({avg_sentiment:+.2f}) across {post_count} items "
            f"from {platform_count} channels.{price_note} Treat as one signal — check fundamentals."
        )
    elif avg_sentiment >= 0.15:
        action, label, color = "HOLD_POSITIVE", "Mildly bullish — HOLD / watch", "green"
        rationale = (
            f"Moderately positive sentiment ({avg_sentiment:+.2f}) on {post_count} posts."
            f"{price_note} Upside bias without extreme conviction."
        )
    elif avg_sentiment <= -0.35 and negative_pct >= 0.35:
        action, label, color = "SELL_AVOID", "Bearish — AVOID / reduce", "red"
        rationale = (
            f"Strong negative tone ({avg_sentiment:+.2f}) in {post_count} posts."
            f"{price_note} Prefer caution until headlines improve."
        )
    elif avg_sentiment <= -0.15:
        action, label, color = "HOLD_CAUTION", "Mildly bearish — HOLD with caution", "orange"
        rationale = (
            f"Negative tilt ({avg_sentiment:+.2f}).{price_note} Watch catalysts and risk."
        )
    else:
        action, label, color = "HOLD", "Neutral — HOLD / wait", "yellow"
        rationale = (
            f"Sentiment near neutral ({avg_sentiment:+.2f}) across {post_count} posts."
            f"{price_note} No strong edge from news flow alone."
        )

    return {
        "action": action,
        "label": label,
        "rationale": rationale,
        "confidence": confidence,
        "color": color,
        "disclaimer": (
            "Sentiment + news-flow signal only — NOT financial advice. "
            "Always do your own research."
        ),
    }


def _themes(posts: List[Dict], top_n: int = 15) -> List[Dict]:
    words = []
    for p in posts:
        tokens = re.findall(r"[A-Za-z]{4,}", (p.get("content") or "").lower())
        words.extend(t for t in tokens if t not in STOPWORDS)
    return [{"term": w, "count": c} for w, c in Counter(words).most_common(top_n)]


def _bucket_distribution(scores: List[float]) -> List[Dict]:
    edges = [
        (-1.0, -0.5, "Very bearish"),
        (-0.5, -0.15, "Bearish"),
        (-0.15, 0.15, "Neutral"),
        (0.15, 0.5, "Bullish"),
        (0.5, 1.01, "Very bullish"),
    ]
    out = []
    for lo, hi, label in edges:
        n = sum(1 for s in scores if lo <= s < hi)
        out.append({"bucket": label, "count": n})
    return out


def _build_analytics(scored: List[Dict], quote: Dict, source_counts: Dict[str, int]) -> Dict:
    scores = [p["sentiment"]["overall"] for p in scored]
    bullish = sorted(scored, key=lambda p: p["sentiment"]["overall"], reverse=True)[:8]
    bearish = sorted(scored, key=lambda p: p["sentiment"]["overall"])[:8]

    by_source_sent = {}
    for p in scored:
        src = p.get("source") or p.get("author") or "unknown"
        by_source_sent.setdefault(src, []).append(p["sentiment"]["overall"])

    source_sentiment = [
        {
            "source": src,
            "post_count": len(vals),
            "avg_sentiment": round(sum(vals) / len(vals), 4),
            "bullish_share": round(sum(1 for v in vals if v > 0.15) / len(vals), 3),
            "bearish_share": round(sum(1 for v in vals if v < -0.15) / len(vals), 3),
        }
        for src, vals in sorted(by_source_sent.items(), key=lambda x: -len(x[1]))
    ]

    # Coverage vs target
    coverage = [
        {
            "source": src,
            "scraped": source_counts.get(src, 0),
            "target": 50,
            "hit_target": source_counts.get(src, 0) >= 50,
        }
        for src, _ in sorted(source_counts.items(), key=lambda x: -x[1])
    ]

    return {
        "sentiment_histogram": _bucket_distribution(scores),
        "themes": _themes(scored),
        "top_bullish": [
            {"content": p["content"][:220], "score": p["sentiment"]["overall"], "source": p.get("source"), "url": p.get("url")}
            for p in bullish if p["sentiment"]["overall"] > 0
        ],
        "top_bearish": [
            {"content": p["content"][:220], "score": p["sentiment"]["overall"], "source": p.get("source"), "url": p.get("url")}
            for p in bearish if p["sentiment"]["overall"] < 0
        ],
        "source_sentiment": source_sentiment,
        "source_coverage": coverage,
        "quote": quote,
        "news_vs_price": {
            "avg_sentiment": round(sum(scores) / len(scores), 4) if scores else 0,
            "price_change_pct": quote.get("change_pct"),
            "month_change_pct": quote.get("month_change_pct"),
            "alignment": (
                "aligned_positive"
                if scores and quote.get("change_pct") is not None
                and sum(scores) / len(scores) > 0.1 and quote["change_pct"] > 0
                else "aligned_negative"
                if scores and quote.get("change_pct") is not None
                and sum(scores) / len(scores) < -0.1 and quote["change_pct"] < 0
                else "diverging"
                if scores and quote.get("change_pct") is not None
                else "unknown"
            ),
        },
    }


async def ensure_company_in_db(db: AsyncSession, company: Dict) -> Company:
    symbol = normalize_nse_symbol(company["symbol"])
    result = await db.execute(select(Company).where(Company.symbol == symbol))
    row = result.scalar_one_or_none()
    if row:
        return row
    row = Company(symbol=symbol, name=company.get("name") or symbol, ipo_date=None)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def store_results(
    db: AsyncSession,
    company_row: Company,
    company: Dict,
    scored_posts: List[Dict],
) -> None:
    now = datetime.utcnow()
    collection = mongodb_db.posts

    by_platform: Dict[str, List[Dict]] = {}
    for p in scored_posts:
        by_platform.setdefault(p["platform"], []).append(p)

    for platform, items in by_platform.items():
        avg_pos = sum(i["sentiment"]["positive"] for i in items) / len(items)
        avg_neg = sum(i["sentiment"]["negative"] for i in items) / len(items)
        avg_neu = sum(i["sentiment"]["neutral"] for i in items) / len(items)
        avg_overall = sum(i["sentiment"]["overall"] for i in items) / len(items)
        try:
            db.add(SentimentScore(
                time=datetime.utcnow(),
                company_id=company_row.id,
                platform=platform,
                positive_score=avg_pos,
                negative_score=avg_neg,
                neutral_score=avg_neu,
                overall_sentiment=avg_overall,
                post_count=len(items),
            ))
            await db.commit()
        except Exception as e:
            await db.rollback()
            logger.warning(f"Could not store sentiment_scores row: {e}")

    for p in scored_posts:
        post_id = f"{p['platform']}_{p['id']}"
        doc = {
            "post_id": post_id,
            "company_symbol": company["symbol"],
            "company_name": company["name"],
            "platform": p["platform"],
            "content": p["content"],
            "original_content": p["content"],
            "author": p.get("source") or p.get("author") or "unknown",
            "timestamp": now.isoformat(),
            "url": p.get("url") or "",
            "engagement_count": p.get("engagement") or 0,
            "sentiment": {
                "positive": p["sentiment"]["positive"],
                "negative": p["sentiment"]["negative"],
                "neutral": p["sentiment"]["neutral"],
                "overall": p["sentiment"]["overall"],
            },
            "hashtags": [],
            "mentions": [],
            "processed_at": now.isoformat(),
            "source_type": "on_demand",
            "source": p.get("source"),
        }
        await collection.update_one({"post_id": post_id}, {"$set": doc}, upsert=True)


async def analyze_company(
    db: AsyncSession,
    symbol: str,
    name: Optional[str] = None,
) -> Dict:
    company = resolve_company(symbol, name)
    if not company.get("keywords"):
        company["keywords"] = build_keywords(company["symbol"], company["name"])
    company_row = await ensure_company_in_db(db, company)

    quote = await fetch_yahoo_quote(company["symbol"])
    raw_posts, source_counts = await scrape_company_high_volume(company)

    # Batch FinBERT scoring for speed
    texts = [p["content"] for p in raw_posts]
    try:
        sentiments = analyze_batch(texts)
    except Exception as e:
        logger.warning(f"Batch sentiment failed, falling back: {e}")
        sentiments = [analyze_text(t) for t in texts]

    scored = []
    source_used: Dict[str, int] = {}
    platform_counts: Dict[str, int] = {}

    for post, sent in zip(raw_posts, sentiments):
        post["sentiment"] = {
            "positive": sent["positive"],
            "negative": sent["negative"],
            "neutral": sent["neutral"],
            "overall": sent["overall_sentiment"],
        }
        scored.append(post)
        src = post.get("source") or post.get("author") or "unknown"
        source_used[src] = source_used.get(src, 0) + 1
        platform_counts[post["platform"]] = platform_counts.get(post["platform"], 0) + 1

    if scored:
        await store_results(db, company_row, company, scored)

    post_count = len(scored)
    if post_count:
        avg_sentiment = sum(p["sentiment"]["overall"] for p in scored) / post_count
        avg_pos = sum(p["sentiment"]["positive"] for p in scored) / post_count
        avg_neg = sum(p["sentiment"]["negative"] for p in scored) / post_count
        avg_neu = sum(p["sentiment"]["neutral"] for p in scored) / post_count
    else:
        avg_sentiment = avg_pos = avg_neg = 0.0
        avg_neu = 1.0

    suggestion = build_suggestion(
        avg_sentiment=avg_sentiment,
        post_count=post_count,
        positive_pct=avg_pos,
        negative_pct=avg_neg,
        platform_count=len(platform_counts),
        quote=quote,
    )

    analytics = _build_analytics(scored, quote, source_used)

    by_source = [
        {"source": k, "post_count": v, "avg_sentiment": next(
            (s["avg_sentiment"] for s in analytics["source_sentiment"] if s["source"] == k), 0
        )}
        for k, v in sorted(source_used.items(), key=lambda x: -x[1])
    ]
    by_platform = [
        {
            "platform": k,
            "post_count": v,
            "avg_sentiment": round(
                sum(p["sentiment"]["overall"] for p in scored if p["platform"] == k) / v, 4
            ),
        }
        for k, v in sorted(platform_counts.items(), key=lambda x: -x[1])
    ]

    return {
        "company_symbol": company["symbol"],
        "company_name": company["name"],
        "keywords": company.get("keywords") or [],
        "total_posts": post_count,
        "avg_sentiment": round(avg_sentiment, 4),
        "positive_pct": round(avg_pos, 4),
        "negative_pct": round(avg_neg, 4),
        "neutral_pct": round(avg_neu, 4),
        "by_platform": by_platform,
        "by_source": by_source,
        "source_targets": {
            "per_source_target": 50,
            "total_target_range": [100, 200],
            "sources_hitting_50": sum(1 for v in source_used.values() if v >= 50),
            "total_sources_used": len(source_used),
        },
        "suggestion": suggestion,
        "analytics": analytics,
        "quote": quote,
        "posts": [
            {
                "post_id": f"{p['platform']}_{p['id']}",
                "platform": p["platform"],
                "source": p.get("source"),
                "content": p["content"],
                "author": p.get("author"),
                "url": p.get("url"),
                "sentiment": p["sentiment"],
            }
            for p in scored[:80]
        ],
        "analyzed_at": datetime.utcnow().isoformat(),
    }
