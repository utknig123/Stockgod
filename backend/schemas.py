"""
Pydantic schemas for API validation
"""
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List

class CompanyBase(BaseModel):
    symbol: str
    name: str
    ipo_date: Optional[datetime] = None

class CompanyCreate(CompanyBase):
    pass

class Company(CompanyBase):
    id: int
    created_at: datetime
    
    class Config:
        from_attributes = True

class SentimentScoreBase(BaseModel):
    time: datetime
    company_id: int
    platform: str
    positive_score: float = Field(ge=0, le=1)
    negative_score: float = Field(ge=0, le=1)
    neutral_score: float = Field(ge=0, le=1)
    overall_sentiment: float = Field(ge=-1, le=1)
    post_count: int = Field(ge=0)

class SentimentScore(SentimentScoreBase):
    created_at: datetime
    
    class Config:
        from_attributes = True

class SentimentResponse(BaseModel):
    company_symbol: str
    company_name: str
    platform: str
    time: datetime
    positive_score: float
    negative_score: float
    neutral_score: float
    overall_sentiment: float
    post_count: int

class AggregatedSentiment(BaseModel):
    company_symbol: str
    company_name: str
    total_posts: int
    avg_sentiment: float
    platforms: List[str]
    latest_update: datetime

class PlatformStats(BaseModel):
    platform: str
    post_count: int
    avg_sentiment: float
    positive_pct: float
    negative_pct: float
    neutral_pct: float

class SourceStats(BaseModel):
    source: str
    platform: str
    post_count: int
    avg_sentiment: float

class CompanyStats(BaseModel):
    company_symbol: str
    company_name: str
    total_posts: int
    avg_sentiment: float
    by_platform: List[PlatformStats]
    by_source: List[SourceStats]
    latest_post: Optional[datetime] = None

class OverviewStats(BaseModel):
    total_posts: int
    total_companies: int
    by_platform: List[PlatformStats]
    by_company: List[AggregatedSentiment]
    hours: int

class PostResponse(BaseModel):
    post_id: str
    platform: str
    company_symbol: str
    company_name: str
    content: str
    author: str
    timestamp: datetime
    url: Optional[str]
    engagement_count: int
    sentiment: dict

