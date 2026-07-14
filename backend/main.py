"""
FastAPI main application
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from routers import sentiment, companies, realtime, analyze
from database import engine, Base

app = FastAPI(
    title="IPO Sentiment Analysis API",
    description="Real-time sentiment analysis for any Indian stock — scrape, score, suggest",
    version="1.1.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers (analyze before companies/{symbol} paths where needed)
app.include_router(analyze.router)
app.include_router(sentiment.router)
app.include_router(companies.router)
app.include_router(realtime.router)

@app.on_event("startup")
async def startup():
    """Initialize database tables"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "IPO Sentiment Analysis API",
        "version": "1.0.0",
        "docs": "/docs"
    }

@app.get("/health")
async def health():
    """Health check endpoint"""
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

