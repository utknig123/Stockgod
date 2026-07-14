-- One-time migration for existing databases created before Jul 2026 schema fixes.
-- Safe to run multiple times.

ALTER TABLE companies ALTER COLUMN symbol TYPE VARCHAR(20);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'sentiment_scores_pkey'
    ) THEN
        ALTER TABLE sentiment_scores
            ADD CONSTRAINT sentiment_scores_pkey PRIMARY KEY (time, company_id, platform);
    END IF;
END $$;

INSERT INTO companies (symbol, name, ipo_date) VALUES
    ('PAYTM.NS', 'Paytm (One97 Communications)', '2021-11-18'),
    ('ZOMATO.NS', 'Zomato', '2021-07-23'),
    ('NYKAA.NS', 'Nykaa (FSN E-Commerce)', '2021-11-10'),
    ('POLICYBZR.NS', 'PolicyBazaar (PB Fintech)', '2021-11-15'),
    ('CARTRADE.NS', 'CarTrade Tech', '2021-08-20')
ON CONFLICT (symbol) DO NOTHING;
