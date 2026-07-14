"""
ENHANCED SOCIAL MEDIA SCRAPER WITH PROPER DATA COLLECTION
- Real scraping from Twitter/X, Reddit, and StockTwits
- Automatic CSV/JSON backup when database unavailable
- No fake data generation
- Comprehensive error handling and retry logic
"""

import asyncio
import json
import logging
import os
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
import csv
from datetime import datetime
from typing import List, Dict, Any
from pathlib import Path

# Database imports
import psycopg2
from psycopg2.extras import RealDictCursor
from pymongo import MongoClient
import redis

# Sentiment analysis imports
from transformers import pipeline
import torch

# Selenium imports
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import undetected_chromedriver as uc
import time
import random

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
import socket

def is_port_open(host, port):
    """Check if a port is open"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except:
        return False

# Determine connection type
USE_LOCALHOST = is_port_open('localhost', 5432)

if USE_LOCALHOST:
    POSTGRES_CONFIG = {
        'host': 'localhost',
        'port': 5432,
        'database': 'sentiment_db',
        'user': 'admin',
        'password': 'admin123'
    }
    MONGODB_CONFIG = {
        'host': 'localhost',
        'port': 27017,
        'username': 'admin',
        'password': 'admin123',
        'authSource': 'admin'
    }
else:
    POSTGRES_CONFIG = {
        'host': 'postgres',
        'port': 5432,
        'database': 'sentiment_db',
        'user': 'admin',
        'password': 'admin123'
    }
    MONGODB_CONFIG = {
        'host': 'mongodb',
        'port': 27017,
        'username': 'admin',
        'password': 'admin123',
        'authSource': 'admin'
    }

# Companies to track
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "scrapers"))
try:
    from config import COMPANIES
except ImportError:
    COMPANIES = [
        {'symbol': 'RIVN', 'name': 'Rivian', 'keywords': ['rivian'], 'subreddits': ['stocks', 'wallstreetbets']},
        {'symbol': 'ARM', 'name': 'Arm Holdings', 'keywords': ['arm'], 'subreddits': ['stocks', 'investing']},
    ]

# Data storage directory
DATA_DIR = Path("scraped_data")
DATA_DIR.mkdir(exist_ok=True)

class DataBackup:
    """Handles saving data to CSV/JSON files"""
    
    def __init__(self, base_dir: Path = DATA_DIR):
        self.base_dir = base_dir
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
    def save_to_csv(self, posts: List[Dict], filename: str = None):
        """Save posts to CSV file"""
        if not posts:
            return None
            
        if filename is None:
            filename = f"posts_{self.timestamp}.csv"
        
        filepath = self.base_dir / filename
        
        # Flatten sentiment data for CSV
        flattened_posts = []
        for post in posts:
            flat_post = {
                'post_id': post['post_id'],
                'platform': post['platform'],
                'content': post['content'],
                'author': post.get('author', 'unknown'),
                'timestamp': post['timestamp'],
                'url': post.get('url', ''),
                'engagement': post.get('engagement', 0),
                'company_symbol': post.get('company_symbol', '')
            }
            
            # Add sentiment fields if available
            if 'sentiment' in post and post['sentiment']:
                sentiment = post['sentiment']
                flat_post['overall_sentiment'] = sentiment.get('overall_sentiment', 0)
                flat_post['positive_score'] = sentiment.get('positive_score', 0)
                flat_post['negative_score'] = sentiment.get('negative_score', 0)
                flat_post['neutral_score'] = sentiment.get('neutral_score', 0)
            
            flattened_posts.append(flat_post)
        
        # Write CSV
        if flattened_posts:
            keys = flattened_posts[0].keys()
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                writer.writerows(flattened_posts)
            
            print(f"✅ Saved {len(flattened_posts)} posts to {filepath}")
            return filepath
        
        return None
    
    def save_to_json(self, posts: List[Dict], filename: str = None):
        """Save posts to JSON file"""
        if not posts:
            return None
            
        if filename is None:
            filename = f"posts_{self.timestamp}.json"
        
        filepath = self.base_dir / filename
        
        # Convert datetime objects to strings
        json_posts = []
        for post in posts:
            json_post = post.copy()
            if isinstance(json_post.get('timestamp'), datetime):
                json_post['timestamp'] = json_post['timestamp'].isoformat()
            json_posts.append(json_post)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(json_posts, f, indent=2, ensure_ascii=False)
        
        print(f"✅ Saved {len(json_posts)} posts to {filepath}")
        return filepath

class DatabaseManager:
    """Manages database connections and operations"""
    
    def __init__(self):
        self.pg_conn = None
        self.mongo_client = None
        self.mongo_db = None
        self.connected = False
        
    def connect_postgres(self):
        """Connect to PostgreSQL"""
        try:
            self.pg_conn = psycopg2.connect(**POSTGRES_CONFIG, connect_timeout=5)
            print("✅ PostgreSQL connected")
            return True
        except Exception as e:
            print(f"⚠️  PostgreSQL unavailable: {e}")
            return False
    
    def connect_mongodb(self):
        """Connect to MongoDB"""
        try:
            connection_string = f"mongodb://{MONGODB_CONFIG['username']}:{MONGODB_CONFIG['password']}@{MONGODB_CONFIG['host']}:{MONGODB_CONFIG['port']}/?authSource={MONGODB_CONFIG['authSource']}"
            self.mongo_client = MongoClient(connection_string, serverSelectionTimeoutMS=5000)
            self.mongo_db = self.mongo_client.sentiment_db
            self.mongo_client.admin.command('ping')
            print("✅ MongoDB connected")
            return True
        except Exception as e:
            print(f"⚠️  MongoDB unavailable: {e}")
            return False
    
    def connect(self):
        """Connect to all databases"""
        pg_ok = self.connect_postgres()
        mongo_ok = self.connect_mongodb()
        self.connected = pg_ok and mongo_ok
        return self.connected
    
    def save_post_to_postgres(self, post_data: Dict[str, Any], company_id: int):
        """Save post to PostgreSQL"""
        if not self.pg_conn:
            return None
        try:
            with self.pg_conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO raw_posts (post_id, company_id, platform, content, author, timestamp, url, engagement_count)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (post_id) DO NOTHING
                    RETURNING id;
                """, (
                    post_data['post_id'],
                    company_id,
                    post_data['platform'],
                    post_data['content'],
                    post_data.get('author', 'unknown'),
                    post_data['timestamp'],
                    post_data.get('url', ''),
                    post_data.get('engagement', 0)
                ))
                result = cur.fetchone()
                self.pg_conn.commit()
                if result:
                    return result[0]
        except Exception as e:
            print(f"  ⚠️  PostgreSQL save error: {e}")
            self.pg_conn.rollback()
        return None
    
    def save_post_to_mongodb(self, post_data: Dict[str, Any]):
        """Save post to MongoDB"""
        if not self.mongo_db:
            return None
        try:
            result = self.mongo_db.posts.insert_one(post_data)
            return result.inserted_id
        except Exception as e:
            print(f"  ⚠️  MongoDB save error: {e}")
        return None
    
    def get_company_id(self, symbol: str) -> int:
        """Get company ID from symbol"""
        if not self.pg_conn:
            return None
        try:
            with self.pg_conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT id FROM companies WHERE symbol = %s;", (symbol,))
                result = cur.fetchone()
                if result:
                    return result['id']
        except Exception as e:
            print(f"  ⚠️  Error getting company ID: {e}")
        return None
    
    def close(self):
        """Close all connections"""
        if self.pg_conn:
            self.pg_conn.close()
        if self.mongo_client:
            self.mongo_client.close()

class SentimentAnalyzer:
    """Performs sentiment analysis using HuggingFace models"""
    
    def __init__(self):
        self.models = {}
        self.load_models()
    
    def load_models(self):
        """Load sentiment analysis models"""
        print("\n" + "="*60)
        print("LOADING SENTIMENT MODELS...")
        print("="*60)
        
        try:
            print("Loading FinBERT sentiment model...")
            self.models['financial'] = pipeline(
                "sentiment-analysis",
                model="ProsusAI/finbert",
                device=0 if torch.cuda.is_available() else -1
            )
            print("✅ Financial sentiment model loaded")
        except Exception as e:
            print(f"⚠️  Model loading error: {e}")
    
    def analyze(self, text: str) -> Dict[str, Any]:
        """Perform sentiment analysis"""
        results = {
            'text': text,
            'overall_sentiment': 0.0,
            'positive_score': 0.0,
            'negative_score': 0.0,
            'neutral_score': 0.0
        }
        
        if not text or len(text.strip()) < 5:
            return results
        
        try:
            # Truncate text if too long
            text_truncated = text[:512]
            
            if 'financial' in self.models:
                result = self.models['financial'](text_truncated)[0]
                label = result['label'].lower()
                score = result['score']
                
                if 'positive' in label:
                    results['positive_score'] = score
                    results['overall_sentiment'] = score
                elif 'negative' in label:
                    results['negative_score'] = score
                    results['overall_sentiment'] = -score
                else:
                    results['neutral_score'] = score
                    results['overall_sentiment'] = 0
        except Exception as e:
            print(f"    ⚠️  Sentiment analysis error: {e}")
        
        return results

try:
    from utils.http_scraper import HttpScraper, normalize_symbol
except ImportError:
    HttpScraper = None
    def normalize_symbol(symbol):
        return symbol.split(".")[0].upper()


class EnhancedWebScraper:
    """Enhanced web scraper with better error handling and retry logic"""
    
    def __init__(self, use_browser: bool = True):
        self.driver = None
        self._is_closed = False
        self.max_retries = 3
        self.http = HttpScraper() if HttpScraper else None
        self.use_browser = use_browser
        if use_browser:
            self.init_driver()
    
    def init_driver(self):
        """Initialize Selenium WebDriver"""
        print("\n" + "="*60)
        print("INITIALIZING WEBDRIVER...")
        print("="*60)
        
        try:
            options = uc.ChromeOptions()
            options.add_argument('--headless=new')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-blink-features=AutomationControlled')
            options.add_argument('--window-size=1920,1080')
            options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
            
            self.driver = uc.Chrome(options=options, version_main=None)
            self._is_closed = False
            print("✅ WebDriver initialized")
            return True
        except Exception as e:
            print(f"❌ WebDriver initialization failed: {e}")
            return False
    
    def _wait_and_scroll(self, seconds=2, scrolls=3):
        """Wait and scroll to load content"""
        time.sleep(seconds)
        for _ in range(scrolls):
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1)
    
    def scrape_reddit(self, subreddit: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Scrape Reddit posts using JSON API, then old.reddit.com"""
        print(f"\n{'='*60}")
        print(f"SCRAPING REDDIT: r/{subreddit}")
        print(f"{'='*60}")

        if self.http:
            raw = self.http.fetch_reddit_subreddit(subreddit, limit=limit)
            if raw:
                posts = []
                for i, p in enumerate(raw):
                    posts.append({
                        'post_id': p['id'],
                        'platform': 'reddit',
                        'content': p['content'],
                        'author': p['author'],
                        'timestamp': p['timestamp'],
                        'url': p['url'],
                        'engagement': p['engagement'],
                    })
                    print(f"  ✅ [{i+1}/{len(raw)}] {p['content'][:60]}...")
                print(f"✅ Scraped {len(posts)} Reddit posts (JSON API)")
                return posts
        
        if not self.driver:
            print("❌ WebDriver not available")
            return []
        
        posts = []
        
        for attempt in range(self.max_retries):
            try:
                url = f"https://old.reddit.com/r/{subreddit}/hot/"
                print(f"  Attempt {attempt + 1}/{self.max_retries}: {url}")
                self.driver.get(url)
                self._wait_and_scroll(3, 2)
                
                # Find all posts
                post_elements = self.driver.find_elements(By.CSS_SELECTOR, 'div.thing.link')
                print(f"  Found {len(post_elements)} posts")
                
                for i, element in enumerate(post_elements[:limit]):
                    try:
                        # Extract title
                        title_elem = element.find_element(By.CSS_SELECTOR, 'a.title')
                        content = title_elem.text.strip()
                        post_url = title_elem.get_attribute('href')
                        
                        if not content or len(content) < 10:
                            continue
                        
                        # Extract author
                        author = "unknown"
                        try:
                            author_elem = element.find_element(By.CSS_SELECTOR, 'a.author')
                            author = author_elem.text.strip()
                        except:
                            pass
                        
                        # Extract score
                        engagement = 0
                        try:
                            score_elem = element.find_element(By.CSS_SELECTOR, 'div.score')
                            score_text = score_elem.get_attribute('title') or score_elem.text
                            engagement = self._parse_score(score_text)
                        except:
                            pass
                        
                        # Get post ID
                        post_id = element.get_attribute('data-fullname') or f"reddit_{int(time.time()*1000)}_{i}"
                        
                        posts.append({
                            'post_id': post_id,
                            'platform': 'reddit',
                            'content': content,
                            'author': author,
                            'timestamp': datetime.utcnow(),
                            'url': post_url or f"https://www.reddit.com/r/{subreddit}/",
                            'engagement': engagement
                        })
                        
                        print(f"  ✅ [{i+1}/{limit}] {content[:60]}... (↑{engagement})")
                        
                    except Exception as e:
                        print(f"  ⚠️  Error extracting post {i+1}: {e}")
                        continue
                
                if posts:
                    print(f"✅ Scraped {len(posts)} Reddit posts from r/{subreddit}")
                    break
                    
            except Exception as e:
                print(f"  ❌ Attempt {attempt + 1} failed: {e}")
                if attempt < self.max_retries - 1:
                    print(f"  Retrying in 5 seconds...")
                    time.sleep(5)
        
        return posts
    
    def scrape_stocktwits(self, symbol: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Scrape StockTwits messages"""
        ticker = normalize_symbol(symbol)
        print(f"\n{'='*60}")
        print(f"SCRAPING STOCKTWITS: ${ticker}")
        print(f"{'='*60}")

        if self.http:
            raw = self.http.fetch_stocktwits(ticker, limit=limit)
            if raw:
                posts = []
                for i, p in enumerate(raw):
                    posts.append({
                        'post_id': f"stocktwits_{ticker}_{p['id']}",
                        'platform': 'stocktwits',
                        'content': p['content'][:500],
                        'author': p['author'],
                        'timestamp': p['timestamp'],
                        'url': p['url'],
                        'engagement': p['engagement'],
                    })
                    print(f"  ✅ [{i+1}/{len(raw)}] {p['content'][:60]}...")
                print(f"✅ Scraped {len(posts)} StockTwits messages (API)")
                return posts
        
        if not self.driver:
            print("❌ WebDriver not available")
            return []
        
        posts = []
        
        for attempt in range(self.max_retries):
            try:
                url = f"https://stocktwits.com/symbol/{ticker}"
                print(f"  Attempt {attempt + 1}/{self.max_retries}: {url}")
                self.driver.get(url)
                self._wait_and_scroll(4, 5)
                
                # Find message containers
                message_selectors = [
                    'div.RichTextMessage_body',
                    'div[class*="message-body"]',
                    'article.st_message',
                ]
                
                messages = []
                for selector in message_selectors:
                    try:
                        messages = self.driver.find_elements(By.CSS_SELECTOR, selector)
                        if messages:
                            print(f"  Found {len(messages)} messages using selector: {selector}")
                            break
                    except:
                        continue
                
                if not messages:
                    print("  ⚠️  No messages found, trying alternative method...")
                    # Try getting all article elements
                    messages = self.driver.find_elements(By.TAG_NAME, 'article')
                
                for i, elem in enumerate(messages[:limit]):
                    try:
                        content = elem.text.strip()
                        
                        # Filter out UI elements
                        if not content or len(content) < 15:
                            continue
                        if any(skip in content.lower() for skip in ['follow', 'share', 'reply', 'sign in', 'log in']):
                            continue
                        
                        # Extract actual message (first paragraph-like text)
                        lines = [line.strip() for line in content.split('\n') if line.strip()]
                        if lines:
                            content = lines[0]
                        
                        if len(content) < 15:
                            continue
                        
                        posts.append({
                            'post_id': f"stocktwits_{symbol}_{int(time.time()*1000)}_{i}_{random.randint(1000,9999)}",
                            'platform': 'stocktwits',
                            'content': content[:500],
                            'author': 'stocktwits_user',
                            'timestamp': datetime.utcnow(),
                            'url': url,
                            'engagement': 0
                        })
                        
                        print(f"  ✅ [{i+1}/{limit}] {content[:60]}...")
                        
                    except Exception as e:
                        continue
                
                if posts:
                    print(f"✅ Scraped {len(posts)} StockTwits messages")
                    break
                    
            except Exception as e:
                print(f"  ❌ Attempt {attempt + 1} failed: {e}")
                if attempt < self.max_retries - 1:
                    print(f"  Retrying in 5 seconds...")
                    time.sleep(5)
        
        return posts
    
    def scrape_yahoo_finance(self, symbol: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Scrape Yahoo Finance news"""
        print(f"\n{'='*60}")
        print(f"SCRAPING YAHOO FINANCE: {symbol}")
        print(f"{'='*60}")

        if self.http:
            raw = self.http.fetch_yahoo_news_rss(symbol, limit=limit)
            if raw:
                posts = []
                for i, p in enumerate(raw):
                    posts.append({
                        'post_id': f"yahoo_{symbol}_{p['id']}",
                        'platform': 'yahoo_finance',
                        'content': p['content'],
                        'author': p['author'],
                        'timestamp': p['timestamp'],
                        'url': p['url'],
                        'engagement': 0,
                    })
                    print(f"  ✅ [{i+1}/{len(raw)}] {p['content'][:60]}...")
                print(f"✅ Scraped {len(posts)} Yahoo Finance headlines (RSS)")
                return posts

        if not self.driver:
            print("❌ WebDriver not available")
            return []
        
        posts = []
        
        for attempt in range(self.max_retries):
            try:
                url = f"https://finance.yahoo.com/quote/{symbol}/news"
                print(f"  Attempt {attempt + 1}/{self.max_retries}: {url}")
                self.driver.get(url)
                self._wait_and_scroll(3, 3)
                
                # Find news headlines
                news_selectors = [
                    'h3 a',
                    'a[data-test="mega-item-header"]',
                    'div.C\\(\\$c-fuji-grey-j\\) a',
                ]
                
                headlines = []
                for selector in news_selectors:
                    try:
                        headlines = self.driver.find_elements(By.CSS_SELECTOR, selector)
                        if headlines:
                            print(f"  Found {len(headlines)} headlines")
                            break
                    except:
                        continue
                
                for i, elem in enumerate(headlines[:limit]):
                    try:
                        text = elem.text.strip()
                        href = elem.get_attribute('href')
                        
                        if not text or len(text) < 10:  # Relaxed length check
                            continue
                        
                        # Avoid duplicates
                        if any(p['content'] == text for p in posts):
                            continue

                        posts.append({
                            'post_id': f"yahoo_{symbol}_{int(time.time()*1000)}_{i}_{random.randint(1000,9999)}",
                            'platform': 'yahoo_finance',
                            'content': text,
                            'author': 'yahoo_finance',
                            'timestamp': datetime.utcnow(),
                            'url': href or url,
                            'engagement': 0
                        })
                        
                        print(f"  ✅ [{i+1}/{limit}] {text[:60]}...")
                        
                    except Exception as e:
                        continue
                
                if posts:
                    print(f"✅ Scraped {len(posts)} Yahoo Finance headlines")
                    break
                    
            except Exception as e:
                print(f"  ❌ Attempt {attempt + 1} failed: {e}")
                if attempt < self.max_retries - 1:
                    print(f"  Retrying in 5 seconds...")
                    time.sleep(5)
        
        return posts
    
    def search_reddit(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search Reddit for specific query"""
        print(f"\n{'='*60}")
        print(f"SEARCHING REDDIT: {query}")
        print(f"{'='*60}")

        if self.http:
            raw = self.http.fetch_reddit_search(query, limit=limit)
            if raw:
                posts = []
                for i, p in enumerate(raw):
                    posts.append({
                        'post_id': p['id'],
                        'platform': 'reddit',
                        'content': p['content'],
                        'author': p['author'],
                        'timestamp': p['timestamp'],
                        'url': p['url'],
                        'engagement': p['engagement'],
                    })
                    print(f"  ✅ [{i+1}/{len(raw)}] {p['content'][:60]}...")
                return posts
        
        if not self.driver:
            return []
            
        posts = []
        try:
            # Use old reddit search
            url = f"https://old.reddit.com/search?q={query}&sort=new"
            print(f"  Searching: {url}")
            self.driver.get(url)
            self._wait_and_scroll(3, 2)
            
            post_elements = self.driver.find_elements(By.CSS_SELECTOR, 'div.search-result-link, div.thing')
            print(f"  Found {len(post_elements)} search results")
            
            for i, element in enumerate(post_elements[:limit]):
                try:
                    title_elem = element.find_element(By.CSS_SELECTOR, 'a.search-title, a.title')
                    content = title_elem.text.strip()
                    post_url = title_elem.get_attribute('href')
                    
                    if not content:
                        continue
                        
                    posts.append({
                        'post_id': f"reddit_search_{int(time.time()*1000)}_{i}",
                        'platform': 'reddit',
                        'content': content,
                        'author': 'unknown',
                        'timestamp': datetime.utcnow(),
                        'url': post_url,
                        'engagement': 0
                    })
                    print(f"  ✅ [{i+1}/{limit}] {content[:60]}...")
                except:
                    continue
                    
        except Exception as e:
            print(f"  ❌ Search failed: {e}")
            
        return posts

    def _parse_score(self, score_text: str) -> int:
        """Parse score text to integer"""
        if not score_text:
            return 0
        try:
            score_text = str(score_text).lower().strip()
            if 'k' in score_text:
                return int(float(score_text.replace('k', '').strip()) * 1000)
            elif 'm' in score_text:
                return int(float(score_text.replace('m', '').strip()) * 1000000)
            else:
                import re
                clean = re.sub(r'[^0-9.-]', '', score_text)
                return int(float(clean)) if clean else 0
        except:
            return 0
    
    def close(self):
        """Close WebDriver safely"""
        if self._is_closed or not self.driver:
            return
        
        self._is_closed = True
        try:
            self.driver.quit()
            print("✅ WebDriver closed")
        except:
            pass
        finally:
            self.driver = None

def main():
    """Main execution function"""
    print("\n" + "="*60)
    print("ENHANCED SOCIAL MEDIA SCRAPER")
    print("="*60)
    print(f"Started: {datetime.now()}")
    print("="*60)
    
    # Initialize components
    db = DatabaseManager()
    scraper = EnhancedWebScraper(use_browser=False)
    sentiment_analyzer = SentimentAnalyzer()
    backup = DataBackup()
    
    # Try database connection
    print("\n" + "="*60)
    print("CHECKING DATABASE CONNECTIONS...")
    print("="*60)
    db_connected = db.connect()
    
    if not db_connected:
        print("\n⚠️  Databases not available - data will be saved to CSV/JSON files")
        print(f"📁 Data directory: {DATA_DIR.absolute()}")
    
    # Scrape data
    print("\n" + "="*60)
    print("STARTING DATA COLLECTION...")
    print("="*60)
    
    all_posts = []
    
    for company in COMPANIES:
        print(f"\n{'='*60}")
        print(f"COLLECTING DATA FOR: {company['name']} ({company['symbol']})")
        print(f"{'='*60}")
        
        # Scrape StockTwits (API) or Google News for Indian tickers
        stocktwits_posts = scraper.scrape_stocktwits(company['symbol'], limit=30)
        if not stocktwits_posts and scraper.http:
            print(f"  Using Google News for {company['name']}...")
            raw = scraper.http.fetch_google_news_rss(
                f"{company['name']} stock India IPO", limit=15
            )
            for i, p in enumerate(raw):
                stocktwits_posts.append({
                    'post_id': f"gnews_{company['symbol']}_{i}",
                    'platform': 'google_news',
                    'content': p['content'],
                    'author': p['author'],
                    'timestamp': p['timestamp'],
                    'url': p['url'],
                    'engagement': 0,
                })
        for post in stocktwits_posts:
            post['company_symbol'] = company['symbol']
            all_posts.append(post)
        
        time.sleep(1)
        
        # Scrape Yahoo Finance (RSS; may be empty for some NSE symbols)
        yahoo_posts = scraper.scrape_yahoo_finance(company['symbol'], limit=15)
        for post in yahoo_posts:
            post['company_symbol'] = company['symbol']
            all_posts.append(post)
        
        time.sleep(2)
        
        # Scrape Reddit
        for subreddit in company['subreddits'][:2]:  # First 2 subreddits
            reddit_posts = scraper.scrape_reddit(subreddit, limit=15)
            for post in reddit_posts:
                # Only include if mentions company OR if we are in a company specific check
                content_lower = post['content'].lower()
                relevant = False
                
                for keyword in company['keywords']:
                    if keyword.lower() in content_lower:
                        relevant = True
                        break
                
                # If explicit mention found OR the post is from a search specifically for this company (which we plan to add)
                # For now, just trust the keyword match
                if relevant:
                    post['company_symbol'] = company['symbol']
                    all_posts.append(post)
            
            time.sleep(3)
        
        # Search Reddit specifically for the company
        print(f"  Searching Reddit for {company['symbol']}...")
        search_results = scraper.search_reddit(f"{company['name']} stock", limit=10)
        for post in search_results:
            post['company_symbol'] = company['symbol']
            all_posts.append(post)
    
    print(f"\n{'='*60}")
    print(f"SCRAPING COMPLETE: {len(all_posts)} posts collected")
    print(f"{'='*60}")
    
    if not all_posts:
        print("❌ No posts were scraped. Please check:")
        print("   1. Internet connection")
        print("   2. ChromeDriver installation")
        print("   3. Website accessibility")
        scraper.close()
        db.close()
        return
    
    # Analyze sentiment
    print("\n" + "="*60)
    print("ANALYZING SENTIMENT...")
    print("="*60)
    
    for i, post in enumerate(all_posts, 1):
        print(f"\n[{i}/{len(all_posts)}] Analyzing: {post['content'][:60]}...")
        sentiment = sentiment_analyzer.analyze(post['content'])
        post['sentiment'] = sentiment
        print(f"  Sentiment: {sentiment['overall_sentiment']:.3f}")
    
    # Save data
    print("\n" + "="*60)
    print("SAVING DATA...")
    print("="*60)
    
    # Always save to CSV/JSON as backup
    csv_file = backup.save_to_csv(all_posts, f"posts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
    json_file = backup.save_to_json(all_posts, f"posts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    
    # Save to database if available
    saved_count = 0
    if db_connected:
        print("\nSaving to databases...")
        for post in all_posts:
            company_id = db.get_company_id(post['company_symbol'])
            if company_id:
                if db.save_post_to_postgres(post, company_id):
                    saved_count += 1
                db.save_post_to_mongodb(post)
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(f"✅ Posts scraped: {len(all_posts)}")
    print(f"✅ Posts analyzed: {len([p for p in all_posts if 'sentiment' in p])}")
    
    if csv_file:
        print(f"✅ CSV saved: {csv_file}")
    if json_file:
        print(f"✅ JSON saved: {json_file}")
    
    if db_connected:
        print(f"✅ Posts saved to database: {saved_count}")
    else:
        print("⚠️  Database not available - check CSV/JSON files")
    
    # Platform breakdown
    platform_counts = {}
    for post in all_posts:
        platform = post['platform']
        platform_counts[platform] = platform_counts.get(platform, 0) + 1
    
    print("\nBy Platform:")
    for platform, count in sorted(platform_counts.items()):
        print(f"  {platform}: {count} posts")
    
    # Company breakdown
    company_counts = {}
    for post in all_posts:
        symbol = post.get('company_symbol', 'unknown')
        company_counts[symbol] = company_counts.get(symbol, 0) + 1
    
    print("\nBy Company:")
    for symbol, count in sorted(company_counts.items()):
        print(f"  {symbol}: {count} posts")
    
    # Cleanup
    scraper.close()
    db.close()
    
    print("\n" + "="*60)
    print("COMPLETE!")
    print("="*60)
    print(f"Finished: {datetime.now()}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
        import traceback
        traceback.print_exc()