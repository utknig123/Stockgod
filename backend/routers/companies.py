"""
Company management API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from database import get_db
from models import Company
from schemas import Company as CompanySchema, CompanyCreate
from services.company_search import search_companies

router = APIRouter(prefix="/api/companies", tags=["companies"])


@router.get("/search")
async def search_companies_endpoint(
    q: str = Query("", description="Name or ticker e.g. Reliance, TCS, Swiggy"),
    limit: int = Query(15, ge=1, le=30),
):
    """Search any Indian company (curated + Yahoo NSE/BSE). Must be before /{symbol}."""
    return await search_companies(q, limit=limit)


@router.get("/", response_model=List[CompanySchema])
async def get_companies(
    indian_only: bool = Query(True, description="Only return .NS / .BO symbols"),
    db: AsyncSession = Depends(get_db),
):
    """Get tracked companies (those already analyzed / seeded)."""
    result = await db.execute(select(Company).order_by(Company.symbol))
    companies = result.scalars().all()
    if indian_only:
        companies = [
            c for c in companies
            if c.symbol.endswith(".NS") or c.symbol.endswith(".BO")
        ]
    return companies


@router.get("/{symbol}", response_model=CompanySchema)
async def get_company(symbol: str, db: AsyncSession = Depends(get_db)):
    """Get a company by symbol"""
    result = await db.execute(select(Company).where(Company.symbol == symbol.upper()))
    company = result.scalar_one_or_none()

    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    return company


@router.post("/", response_model=CompanySchema)
async def create_company(company: CompanyCreate, db: AsyncSession = Depends(get_db)):
    """Create / register a company for tracking"""
    result = await db.execute(select(Company).where(Company.symbol == company.symbol.upper()))
    existing = result.scalar_one_or_none()

    if existing:
        raise HTTPException(status_code=400, detail="Company already exists")

    new_company = Company(
        symbol=company.symbol.upper(),
        name=company.name,
        ipo_date=company.ipo_date,
    )

    db.add(new_company)
    await db.commit()
    await db.refresh(new_company)

    return new_company
