"""
Sentiment analysis API endpoints
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from datetime import datetime, timedelta
from typing import List, Optional
from database import get_db, mongodb_db
from models import Company, SentimentScore
from schemas import SentimentResponse, AggregatedSentiment, OverviewStats, CompanyStats, PlatformStats, SourceStats
from services.ml_service import MLService

router = APIRouter(prefix="/api/sentiment", tags=["sentiment"])

SOURCE_LABELS = {
    "google_news": "Google News RSS",
    "yahoo_finance": "Yahoo Finance",
    "bing_news": "Bing News",
    "stocktwits_user": "StockTwits",
    "finviz_news": "Finviz News",
    "reddit": "Reddit",
    "unknown": "Unknown",
}


def _time_threshold(hours: int) -> datetime:
    return datetime.utcnow() - timedelta(hours=hours)


def _platform_stats_from_groups(groups: list) -> List[PlatformStats]:
    stats = []
    for group in groups:
        platform = group.get("_id") or "unknown"
        count = group.get("count", 0)
        avg = float(group.get("avg_sentiment") or 0)
        pos = float(group.get("avg_positive") or 0)
        neg = float(group.get("avg_negative") or 0)
        neu = float(group.get("avg_neutral") or 0)
        stats.append(PlatformStats(
            platform=platform,
            post_count=count,
            avg_sentiment=avg,
            positive_pct=pos,
            negative_pct=neg,
            neutral_pct=neu,
        ))
    return sorted(stats, key=lambda s: s.post_count, reverse=True)


async def _mongo_post_groups(match_filter: dict, group_id, limit: int = None):
    collection = mongodb_db.posts
    pipeline = [
        {"$match": match_filter},
        {"$group": {
            "_id": group_id,
            "count": {"$sum": 1},
            "avg_sentiment": {"$avg": "$sentiment.overall"},
            "avg_positive": {"$avg": "$sentiment.positive"},
            "avg_negative": {"$avg": "$sentiment.negative"},
            "avg_neutral": {"$avg": "$sentiment.neutral"},
            "latest": {"$max": "$timestamp"},
        }},
        {"$sort": {"count": -1}},
    ]
    if limit:
        pipeline.append({"$limit": limit})
    return await collection.aggregate(pipeline).to_list(length=limit or 100)

@router.get("/company/{symbol}", response_model=List[SentimentResponse])
async def get_company_sentiment(
    symbol: str,
    platform: Optional[str] = Query(None, description="Filter by platform"),
    hours: int = Query(24, description="Hours of history"),
    db: AsyncSession = Depends(get_db)
):
    """Get sentiment scores for a company"""
    # Get company
    result = await db.execute(select(Company).where(Company.symbol == symbol.upper()))
    company = result.scalar_one_or_none()
    
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    
    # Calculate time threshold
    time_threshold = datetime.utcnow() - timedelta(hours=hours)
    
    # Build query
    query = select(SentimentScore).where(
        and_(
            SentimentScore.company_id == company.id,
            SentimentScore.time >= time_threshold
        )
    )
    
    if platform:
        query = query.where(SentimentScore.platform == platform)
    
    query = query.order_by(SentimentScore.time.desc())
    
    result = await db.execute(query)
    scores = result.scalars().all()
    
    return [
        SentimentResponse(
            company_symbol=company.symbol,
            company_name=company.name,
            platform=score.platform,
            time=score.time,
            positive_score=score.positive_score,
            negative_score=score.negative_score,
            neutral_score=score.neutral_score,
            overall_sentiment=score.overall_sentiment,
            post_count=score.post_count
        )
        for score in scores
    ]

@router.get("/aggregated", response_model=List[AggregatedSentiment])
async def get_aggregated_sentiment(
    hours: int = Query(24, description="Hours of history"),
    db: AsyncSession = Depends(get_db)
):
    """Get aggregated sentiment for all companies"""
    time_threshold = datetime.utcnow() - timedelta(hours=hours)
    
    # Get all companies with recent sentiment
    query = select(
        Company,
        func.avg(SentimentScore.overall_sentiment).label('avg_sentiment'),
        func.sum(SentimentScore.post_count).label('total_posts'),
        func.array_agg(SentimentScore.platform).label('platforms'),
        func.max(SentimentScore.time).label('latest_update')
    ).join(
        SentimentScore, Company.id == SentimentScore.company_id
    ).where(
        SentimentScore.time >= time_threshold
    ).group_by(
        Company.id
    )
    
    result = await db.execute(query)
    rows = result.all()
    
    aggregated = []
    for row in rows:
        company, avg_sentiment, total_posts, platforms, latest_update = row
        aggregated.append(
            AggregatedSentiment(
                company_symbol=company.symbol,
                company_name=company.name,
                total_posts=int(total_posts or 0),
                avg_sentiment=float(avg_sentiment or 0),
                platforms=sorted(set(filter(None, platforms or []))),
                latest_update=latest_update or datetime.utcnow()
            )
        )
    
    return aggregated

@router.get("/platform/{platform}", response_model=List[SentimentResponse])
async def get_platform_sentiment(
    platform: str,
    hours: int = Query(24, description="Hours of history"),
    db: AsyncSession = Depends(get_db)
):
    """Get sentiment scores for a platform"""
    time_threshold = datetime.utcnow() - timedelta(hours=hours)
    
    query = select(SentimentScore, Company).join(
        Company, SentimentScore.company_id == Company.id
    ).where(
        and_(
            SentimentScore.platform == platform.lower(),
            SentimentScore.time >= time_threshold
        )
    ).order_by(SentimentScore.time.desc())
    
    result = await db.execute(query)
    rows = result.all()
    
    return [
        SentimentResponse(
            company_symbol=company.symbol,
            company_name=company.name,
            platform=score.platform,
            time=score.time,
            positive_score=score.positive_score,
            negative_score=score.negative_score,
            neutral_score=score.neutral_score,
            overall_sentiment=score.overall_sentiment,
            post_count=score.post_count
        )
        for score, company in rows
    ]

@router.get("/posts/{company_symbol}")
async def get_recent_posts(
    company_symbol: str,
    limit: int = Query(50, le=200),
    platform: Optional[str] = None
):
    """Get recent posts for a company from MongoDB"""
    collection = mongodb_db.posts
    
    query = {'company_symbol': company_symbol.upper()}
    if platform:
        query['platform'] = platform.lower()
    
    cursor = collection.find(query).sort('timestamp', -1).limit(limit)
    posts = await cursor.to_list(length=limit)
    
    # Convert ObjectId to string
    for post in posts:
        post['_id'] = str(post['_id'])
    
    return posts


@router.get("/stats/overview", response_model=OverviewStats)
async def get_overview_stats(
    hours: int = Query(24, description="Hours of history"),
):
    """Scrape + sentiment overview across all companies."""
    threshold = _time_threshold(hours)
    match = {"processed_at": {"$gte": threshold.isoformat()}}

    collection = mongodb_db.posts
    total_posts = await collection.count_documents(match)

    platform_groups = await _mongo_post_groups(match, "$platform")
    company_groups = await _mongo_post_groups(
        match,
        {"symbol": "$company_symbol", "name": "$company_name"},
    )

    by_company = []
    for group in company_groups:
        gid = group.get("_id") or {}
        symbol = gid.get("symbol") or "UNKNOWN"
        name = gid.get("name") or symbol
        by_company.append(AggregatedSentiment(
            company_symbol=symbol,
            company_name=name,
            total_posts=group.get("count", 0),
            avg_sentiment=float(group.get("avg_sentiment") or 0),
            platforms=[],
            latest_update=group.get("latest") or datetime.utcnow(),
        ))

    return OverviewStats(
        total_posts=total_posts,
        total_companies=len(by_company),
        by_platform=_platform_stats_from_groups(platform_groups),
        by_company=sorted(by_company, key=lambda c: c.total_posts, reverse=True),
        hours=hours,
    )


@router.get("/stats/company/{symbol}", response_model=CompanyStats)
async def get_company_stats(
    symbol: str,
    hours: int = Query(24, description="Hours of history"),
):
    """Per-company scrape breakdown by platform and data source."""
    threshold = _time_threshold(hours)
    match = {
        "company_symbol": symbol.upper(),
        "processed_at": {"$gte": threshold.isoformat()},
    }

    collection = mongodb_db.posts
    total_posts = await collection.count_documents(match)
    if total_posts == 0:
        raise HTTPException(status_code=404, detail="No scraped data for this company in the selected window")

    platform_groups = await _mongo_post_groups(match, "$platform")
    source_groups = await _mongo_post_groups(
        match,
        {"source": "$author", "platform": "$platform"},
        limit=20,
    )

    sample = await collection.find_one(match, {"company_name": 1})
    company_name = (sample or {}).get("company_name", symbol.upper())

    overall = await collection.aggregate([
        {"$match": match},
        {"$group": {
            "_id": None,
            "avg_sentiment": {"$avg": "$sentiment.overall"},
            "latest": {"$max": "$timestamp"},
        }},
    ]).to_list(length=1)

    avg_sentiment = float((overall[0] if overall else {}).get("avg_sentiment") or 0)
    latest_post = (overall[0] if overall else {}).get("latest")

    by_source = []
    for group in source_groups:
        gid = group.get("_id") or {}
        raw_source = gid.get("source") or "unknown"
        by_source.append(SourceStats(
            source=SOURCE_LABELS.get(raw_source, raw_source.replace("_", " ").title()),
            platform=gid.get("platform") or "unknown",
            post_count=group.get("count", 0),
            avg_sentiment=float(group.get("avg_sentiment") or 0),
        ))

    return CompanyStats(
        company_symbol=symbol.upper(),
        company_name=company_name,
        total_posts=total_posts,
        avg_sentiment=avg_sentiment,
        by_platform=_platform_stats_from_groups(platform_groups),
        by_source=by_source,
        latest_post=latest_post,
    )

