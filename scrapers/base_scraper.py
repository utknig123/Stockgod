"""
Base scraper class with common functionality
"""
import json
import logging
import os
from abc import ABC, abstractmethod
from datetime import datetime
from kafka import KafkaProducer
from typing import Dict, List, Optional
import time

from utils.rate_limiter import RateLimiter
from utils.proxy_rotator import ProxyRotator
from utils.text_cleaner import TextCleaner
from utils.http_scraper import HttpScraper

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class BaseScraper(ABC):
    def __init__(self, platform: str):
        self.platform = platform
        self.kafka_broker = os.getenv('KAFKA_BROKER', 'localhost:9092')
        self.redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
        
        # Initialize components
        self.rate_limiter = RateLimiter(self.redis_url)
        self.proxy_rotator = ProxyRotator()
        self.text_cleaner = TextCleaner()
        
        # Kafka producer (retry so the container doesn't crash-loop while Kafka boots)
        self.producer = self._connect_kafka()
        
        # IPO companies to track (config.py mounted at /app in Docker)
        self.companies = self._load_companies()
        self.http = HttpScraper()

    def _connect_kafka(self, attempts: int = 10, delay: int = 6) -> KafkaProducer:
        last_error = None
        for attempt in range(1, attempts + 1):
            try:
                return KafkaProducer(
                    bootstrap_servers=[self.kafka_broker],
                    value_serializer=lambda v: json.dumps(v).encode('utf-8'),
                    key_serializer=lambda k: k.encode('utf-8') if k else None,
                    acks='all',
                    retries=3
                )
            except Exception as e:
                last_error = e
                logger.warning(
                    f"Kafka not ready ({self.kafka_broker}), attempt {attempt}/{attempts}: {e}"
                )
                time.sleep(delay)
        raise RuntimeError(f"Could not connect to Kafka at {self.kafka_broker}: {last_error}")

    def _load_companies(self):
        try:
            from config import COMPANIES
            return COMPANIES
        except ImportError:
            # Fallback if config not found
            return [
                {'symbol': 'PAYTM.NS', 'name': 'Paytm', 'keywords': ['paytm', 'one97']},
                {'symbol': 'ZOMATO.NS', 'name': 'Zomato', 'keywords': ['zomato']},
                {'symbol': 'NYKAA.NS', 'name': 'Nykaa', 'keywords': ['nykaa']},
                {'symbol': 'POLICYBZR.NS', 'name': 'PolicyBazaar', 'keywords': ['policybazaar', 'pb fintech']},
                {'symbol': 'CARTRADE.NS', 'name': 'CarTrade', 'keywords': ['cartrade']},
            ]
    
    def _is_relevant_post(self, text: str) -> Optional[Dict]:
        """Check if post is relevant to any IPO company"""
        text_lower = text.lower()
        for company in self.companies:
            for keyword in company['keywords']:
                if keyword.lower() in text_lower:
                    return company
        return None
    
    def _send_to_kafka(self, data: Dict):
        """Send data to Kafka topic"""
        try:
            future = self.producer.send('raw_social_data', value=data, key=data.get('post_id'))
            future.get(timeout=10)
            logger.info(f"Sent {self.platform} post {data.get('post_id')} to Kafka")
        except Exception as e:
            logger.error(f"Failed to send to Kafka: {e}")
    
    def _create_post_data(self, post_id: str, content: str, author: str,
                         timestamp: datetime, url: Optional[str] = None,
                         engagement: int = 0, company: Optional[Dict] = None) -> Dict:
        """Create standardized post data structure"""
        cleaned_content = self.text_cleaner.clean_text(content)
        if company is None:
            company = self._is_relevant_post(cleaned_content)

        if not company:
            return None
        
        return {
            'post_id': f"{self.platform}_{post_id}",
            'platform': self.platform,
            'company_symbol': company['symbol'],
            'company_name': company['name'],
            'content': cleaned_content,
            'original_content': content,
            'author': author,
            'timestamp': timestamp.isoformat(),
            'url': url,
            'engagement_count': engagement,
            'hashtags': self.text_cleaner.extract_hashtags(content),
            'mentions': self.text_cleaner.extract_mentions(content),
            'scraped_at': datetime.utcnow().isoformat()
        }
    
    @abstractmethod
    async def scrape(self):
        """Main scraping method - must be implemented by subclasses"""
        pass
    
    def run(self):
        """Run the scraper"""
        logger.info(f"Starting {self.platform} scraper...")
        import asyncio
        try:
            asyncio.run(self.scrape())
        except KeyboardInterrupt:
            logger.info(f"Stopping {self.platform} scraper...")
        finally:
            self.producer.close()

