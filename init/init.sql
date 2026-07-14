-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Create companies table
CREATE TABLE IF NOT EXISTS companies (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    ipo_date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create sentiment_scores table (TimescaleDB hypertable)
CREATE TABLE IF NOT EXISTS sentiment_scores (
    time TIMESTAMPTZ NOT NULL,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    platform VARCHAR(50) NOT NULL,
    positive_score FLOAT DEFAULT 0.0,
    negative_score FLOAT DEFAULT 0.0,
    neutral_score FLOAT DEFAULT 0.0,
    overall_sentiment FLOAT DEFAULT 0.0, -- -1 to 1 scale
    post_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (time, company_id, platform)
);

-- Convert to hypertable for time-series optimization
SELECT create_hypertable('sentiment_scores', 'time', if_not_exists => TRUE);

-- Create raw_posts table for storing individual posts
CREATE TABLE IF NOT EXISTS raw_posts (
    id SERIAL PRIMARY KEY,
    post_id VARCHAR(255) UNIQUE NOT NULL,
    company_id INTEGER REFERENCES companies(id),
    platform VARCHAR(50) NOT NULL,
    content TEXT NOT NULL,
    author VARCHAR(255),
    timestamp TIMESTAMPTZ NOT NULL,
    url TEXT,
    engagement_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_sentiment_scores_company_time ON sentiment_scores(company_id, time DESC);
CREATE INDEX IF NOT EXISTS idx_sentiment_scores_platform ON sentiment_scores(platform);
CREATE INDEX IF NOT EXISTS idx_raw_posts_company ON raw_posts(company_id);
CREATE INDEX IF NOT EXISTS idx_raw_posts_timestamp ON raw_posts(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_raw_posts_platform ON raw_posts(platform);

-- Insert Indian IPO companies
INSERT INTO companies (symbol, name, ipo_date) VALUES
    ('PAYTM.NS', 'Paytm (One97 Communications)', '2021-11-18'),
    ('ZOMATO.NS', 'Zomato', '2021-07-23'),
    ('NYKAA.NS', 'Nykaa (FSN E-Commerce)', '2021-11-10'),
    ('POLICYBZR.NS', 'PolicyBazaar (PB Fintech)', '2021-11-15'),
    ('CARTRADE.NS', 'CarTrade Tech', '2021-08-20')
ON CONFLICT (symbol) DO NOTHING;

