"""
On-demand analyze endpoints (scrape + FinBERT + suggestion)
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from pydantic import BaseModel, Field

from database import get_db
from services.company_search import resolve_company, normalize_nse_symbol
from services.on_demand import analyze_company

router = APIRouter(prefix="/api", tags=["analyze"])


class AnalyzeRequest(BaseModel):
    symbol: str = Field(..., description="NSE/BSE symbol e.g. RELIANCE.NS or RELIANCE")
    name: Optional[str] = Field(None, description="Optional company display name")


@router.post("/analyze")
async def analyze_any_company(
    body: AnalyzeRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Scrape news/social for the selected Indian company, score with FinBERT,
    persist results, and return scores + suggestion.
    """
    symbol = normalize_nse_symbol(body.symbol)
    if not symbol or len(symbol) < 3:
        raise HTTPException(status_code=400, detail="Invalid symbol")

    try:
        result = await analyze_company(db, symbol=symbol, name=body.name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {e}") from e

    return result


@router.get("/analyze/{symbol}")
async def analyze_company_get(
    symbol: str,
    name: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """GET variant of on-demand scrape + score + suggest."""
    symbol = normalize_nse_symbol(symbol)
    try:
        return await analyze_company(db, symbol=symbol, name=name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {e}") from e


@router.get("/resolve/{symbol}")
async def resolve_symbol(symbol: str, name: Optional[str] = None):
    """Resolve symbol to name + keywords without scraping."""
    return resolve_company(symbol, name)
