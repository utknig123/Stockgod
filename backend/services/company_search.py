"""
Company search: curated Indian stocks + Yahoo Finance live search.
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

import httpx

from data.indian_stocks import INDIAN_STOCKS

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
)


def normalize_nse_symbol(symbol: str) -> str:
    symbol = (symbol or "").strip().upper()
    if not symbol:
        return symbol
    if symbol.endswith(".BO"):
        return symbol
    if not symbol.endswith(".NS"):
        symbol = f"{symbol.split('.')[0]}.NS"
    return symbol


def build_keywords(symbol: str, name: str) -> List[str]:
    """Keywords used to filter scraped text for relevance."""
    base = symbol.split(".")[0].lower()
    name_clean = re.sub(r"\([^)]*\)", "", name or "").strip()
    parts = [p for p in re.split(r"[\s,&]+", name_clean) if len(p) > 2]
    keywords = {base, name_clean.lower()}
    if parts:
        keywords.add(parts[0].lower())
    if len(parts) >= 2:
        keywords.add(f"{parts[0]} {parts[1]}".lower())
    # common aliases
    aliases = {
        "PAYTM": ["paytm", "one97"],
        "ZOMATO": ["zomato", "eternal"],
        "ETERNAL": ["eternal", "zomato"],
        "NYKAA": ["nykaa", "fsn"],
        "POLICYBZR": ["policybazaar", "pb fintech"],
        "RELIANCE": ["reliance", "ril"],
        "TCS": ["tcs", "tata consultancy"],
        "INFY": ["infosys", "infy"],
        "HDFCBANK": ["hdfc bank", "hdfc"],
        "SBIN": ["sbi", "state bank"],
        "BHARTIARTL": ["airtel", "bharti"],
        "TATAMOTORS": ["tata motors", "jaguar land rover"],
        "ADANIENT": ["adani"],
        "IDEA": ["vodafone idea", "vi"],
        "SWIGGY": ["swiggy"],
        "DMART": ["dmart", "avenue supermarts"],
        "JIOFIN": ["jio financial", "jiofin"],
    }
    for a in aliases.get(base, []):
        keywords.add(a)
    return [k for k in keywords if k and len(k) >= 2]


def _curated_matches(query: str, limit: int = 15) -> List[Dict]:
    q = query.strip().lower()
    if not q:
        return [
            {**s, "keywords": build_keywords(s["symbol"], s["name"]), "source": "curated"}
            for s in INDIAN_STOCKS[:limit]
        ]

    scored = []
    for s in INDIAN_STOCKS:
        symbol = s["symbol"].lower()
        name = s["name"].lower()
        bare = symbol.split(".")[0]
        score = 0
        if q == bare or q == symbol:
            score = 100
        elif symbol.startswith(q) or bare.startswith(q):
            score = 80
        elif q in name:
            score = 60
        elif any(q in w for w in name.split()):
            score = 40
        elif bare.startswith(q[:3]) and len(q) >= 3:
            score = 20
        if score:
            scored.append((score, s))
    scored.sort(key=lambda x: (-x[0], x[1]["name"]))
    out = []
    for _, s in scored[:limit]:
        out.append({
            **s,
            "keywords": build_keywords(s["symbol"], s["name"]),
            "source": "curated",
            "exchange": "NSE",
        })
    return out


async def yahoo_search_indian(query: str, limit: int = 10) -> List[Dict]:
    if not query or len(query.strip()) < 1:
        return []
    url = "https://query1.finance.yahoo.com/v1/finance/search"
    params = {
        "q": query.strip(),
        "quotesCount": 20,
        "newsCount": 0,
        "listsCount": 0,
    }
    try:
        async with httpx.AsyncClient(timeout=8.0, headers={"User-Agent": USER_AGENT}) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            quotes = resp.json().get("quotes") or []
    except Exception as e:
        logger.warning(f"Yahoo search failed: {e}")
        return []

    results = []
    for q in quotes:
        exchange = (q.get("exchange") or "").upper()
        symbol = (q.get("symbol") or "").upper()
        quote_type = (q.get("quoteType") or "").upper()
        if quote_type and quote_type not in ("EQUITY", "ETF"):
            continue
        # Prefer NSE / BSE India
        is_india = (
            exchange in ("NSI", "BSE", "BOM")
            or symbol.endswith(".NS")
            or symbol.endswith(".BO")
        )
        if not is_india:
            continue
        name = q.get("longname") or q.get("shortname") or symbol
        results.append({
            "symbol": symbol if ("." in symbol) else f"{symbol}.NS",
            "name": name,
            "exchange": "NSE" if symbol.endswith(".NS") or exchange == "NSI" else "BSE",
            "sector": q.get("sector") or q.get("sectorDisp"),
            "keywords": build_keywords(symbol, name),
            "source": "yahoo",
        })
        if len(results) >= limit:
            break
    return results


async def search_companies(query: str, limit: int = 15) -> List[Dict]:
    """Merge curated + Yahoo results; curated first for popular names."""
    curated = _curated_matches(query, limit=limit)
    yahoo = await yahoo_search_indian(query, limit=limit) if query.strip() else []

    seen = set()
    merged = []
    for item in curated + yahoo:
        sym = normalize_nse_symbol(item["symbol"])
        if sym in seen:
            continue
        seen.add(sym)
        item = {**item, "symbol": sym}
        merged.append(item)
        if len(merged) >= limit:
            break
    return merged


def resolve_company(symbol: str, name: Optional[str] = None) -> Dict:
    """Resolve a symbol into a full company dict with keywords."""
    symbol = normalize_nse_symbol(symbol)
    for s in INDIAN_STOCKS:
        if normalize_nse_symbol(s["symbol"]) == symbol:
            return {
                **s,
                "symbol": symbol,
                "keywords": build_keywords(s["symbol"], s["name"]),
                "source": "curated",
            }
    display_name = name or symbol.split(".")[0]
    return {
        "symbol": symbol,
        "name": display_name,
        "keywords": build_keywords(symbol, display_name),
        "source": "manual",
    }
