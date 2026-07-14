# StockGod — Indian Stock Sentiment Analysis

Real-time + on-demand sentiment analysis for **any NSE/BSE Indian stock**.

Scrapes multi-source news & social → scores with **FinBERT** → stores in Kafka / PostgreSQL / MongoDB → serves via **FastAPI** + **Streamlit** dashboard with BUY / HOLD / AVOID suggestions.

---

## Features

- **Search any Indian company** (curated list + Yahoo Finance NSE/BSE)
- **Deep scrape** ~100–200 posts (targets ~50 from major sources when available)
- Sources: Moneycontrol, Economic Times, Business Standard, LiveMint, Reuters, ZeeBiz, The Hindu, Google News, Bing, Yahoo, Reddit, StockTwits
- **FinBERT** financial sentiment scoring
- Live **price chart** (Yahoo Finance) + news vs price alignment
- Source coverage charts, themes, bullish/bearish headlines
- Background pipeline: Kafka scrapers → PySpark streaming → TimescaleDB / MongoDB

---

## Quick start (Docker)

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop) with **≥ 8GB RAM** allocated
- Ports free: `8501`, `8000`, `5432`, `27017`, `6379`, `9092`, `8080`, `3000`, `9090`

### Run

```bash
cd Stockgod
docker compose up -d --build
```

Wait ~1–2 minutes, then open:

| Service | URL |
|---------|-----|
| **Dashboard** | http://localhost:8501 |
| **API docs** | http://localhost:8000/docs |
| **Kafka UI** | http://localhost:8080 |
| **Grafana** | http://localhost:3000 (admin / admin) |

### Use the dashboard

1. Search a company (e.g. `Reliance`, `TCS`, `Swiggy`)
2. Select it (or type a ticker like `INFY.NS`)
3. Click **Deep scrape + analytics**
4. Review scores, sources, price chart, and suggestion

First analyze after API start may take **2–4 minutes** (FinBERT download / warm-up). Later runs are faster.

### Stop

```bash
docker compose down
```

Reset databases (fresh start):

```bash
docker compose down -v
docker compose up -d --build
```

---

## Architecture

```
News / Social sources
        │
        ▼
┌───────────────────┐     Kafka      ┌─────────────────────┐
│ Docker scrapers   │───────────────►│ Spark + FinBERT     │
│ (twitter/reddit/  │  raw_social_   │ streaming pipeline  │
│  instagram)       │     data       └──────────┬──────────┘
└───────────────────┘                           │
                                                ▼
┌───────────────────┐                 PostgreSQL + MongoDB
│ On-demand analyze │◄── FastAPI ───► Redis
│ (search any stock)│                    │
└─────────┬─────────┘                    ▼
          └──────────────────────► Streamlit dashboard
```

---

## Useful API endpoints

```
GET  /health
GET  /api/companies/search?q=swiggy
POST /api/analyze          {"symbol":"SWIGGY.NS","name":"Swiggy"}
GET  /api/analyze/RELIANCE.NS
GET  /api/sentiment/stats/overview?hours=24
GET  /api/sentiment/posts/NYKAA.NS?limit=20
```

---

## Project structure

```
Stockgod/
├── docker-compose.yml          # Full stack
├── config.py                   # Default tracked IPO companies
├── backend/                    # FastAPI (search, analyze, REST)
├── frontend/                   # Streamlit dashboard
├── scrapers/                   # Background Kafka scrapers
├── spark-processor/            # Streaming FinBERT pipeline
├── init/                       # Postgres schema + migration
├── monitoring/                 # Prometheus / Grafana
├── _source_check.py            # Quick HTTP source health check
└── test_scraping_and_sentiment.py
```

---

## Optional local checks (no full stack)

```bash
pip install -r test_requirements.txt
python _source_check.py
python check_system.py          # needs Docker infra running
```

---

## Notes

- Suggestions are **sentiment-based signals only — not financial advice**.
- Reddit may return `429` under rate limits; other sources still fill the scrape.
- If the DB has old non-Indian symbols, run migration SQL in `init/migrate_existing.sql` or `docker compose down -v` and recreate.

---

## License

MIT — see [LICENSE](LICENSE)
