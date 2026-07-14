"""
SQLAlchemy models
"""
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Date
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from database import Base

class Company(Base):
    __tablename__ = "companies"
    
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(20), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    ipo_date = Column(Date)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    sentiment_scores = relationship("SentimentScore", back_populates="company")

class SentimentScore(Base):
    __tablename__ = "sentiment_scores"
    
    time = Column(DateTime(timezone=True), primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), primary_key=True)
    platform = Column(String(50), primary_key=True)
    positive_score = Column(Float, default=0.0)
    negative_score = Column(Float, default=0.0)
    neutral_score = Column(Float, default=0.0)
    overall_sentiment = Column(Float, default=0.0)
    post_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    company = relationship("Company", back_populates="sentiment_scores")

