"""
Centralized configuration for StockGod
"""
import os

# Companies to track - Indian IPO Stocks
COMPANIES = [
    {
        'symbol': 'PAYTM.NS', 
        'name': 'Paytm (One97 Communications)', 
        'keywords': ['paytm', 'one97', 'paytm ipo', 'vijay shekhar sharma'],
        'subreddits': ['IndianStockMarket', 'IndianStreetBets', 'investing']
    },
    {
        'symbol': 'ZOMATO.NS', 
        'name': 'Zomato', 
        'keywords': ['zomato', 'zomato ipo', 'eternal ltd'],
        'subreddits': ['IndianStockMarket', 'IndianStreetBets', 'india']
    },
    {
        'symbol': 'NYKAA.NS', 
        'name': 'Nykaa (FSN E-Commerce)', 
        'keywords': ['nykaa', 'fsn e-commerce', 'nykaa ipo'],
        'subreddits': ['IndianStockMarket', 'IndianStreetBets', 'investing']
    },
    {
        'symbol': 'POLICYBZR.NS', 
        'name': 'PolicyBazaar (PB Fintech)', 
        'keywords': ['policybazaar', 'policy bazaar', 'pb fintech'],
        'subreddits': ['IndianStockMarket', 'IndianStreetBets', 'investing']
    },
    {
        'symbol': 'CARTRADE.NS', 
        'name': 'CarTrade Tech', 
        'keywords': ['cartrade', 'car trade tech'],
        'subreddits': ['IndianStockMarket', 'IndianStreetBets', 'india']
    }
]

# Database Config
POSTGRES_DB = os.getenv('POSTGRES_DB', 'sentiment_db')
POSTGRES_USER = os.getenv('POSTGRES_USER', 'admin')
POSTGRES_PASSWORD = os.getenv('POSTGRES_PASSWORD', 'admin123')
POSTGRES_HOST = os.getenv('POSTGRES_HOST', 'localhost')
POSTGRES_PORT = int(os.getenv('POSTGRES_PORT', 5432))

MONGODB_URL = os.getenv(
    'MONGODB_URL',
    'mongodb://admin:admin123@localhost:27017/sentiment_db?authSource=admin'
)
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
KAFKA_BROKER = os.getenv('KAFKA_BROKER', 'localhost:9092')
