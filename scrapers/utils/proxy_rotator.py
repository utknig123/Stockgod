"""
Proxy rotation utility for scrapers
"""
import requests
from fake_useragent import UserAgent
import random
import time
from typing import Optional, List
import logging

logger = logging.getLogger(__name__)

class ProxyRotator:
    def __init__(self, rotation_interval: int = 50):
        self.rotation_interval = rotation_interval
        self.request_count = 0
        self.current_proxy: Optional[str] = None
        self.proxies: List[str] = []
        self.ua = UserAgent()
        self._fetch_proxies()
    
    def _fetch_proxies(self):
        """Fetch free proxies from free-proxy-list.net"""
        try:
            url = "https://www.proxy-list.download/api/v1/get?type=http"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                proxies = response.text.strip().split('\n')
                self.proxies = [p.strip() for p in proxies if p.strip()]
                logger.info(f"Fetched {len(self.proxies)} proxies")
        except Exception as e:
            logger.warning(f"Failed to fetch proxies: {e}")
            self.proxies = []
    
    def get_proxy(self) -> Optional[dict]:
        """Get a random proxy"""
        if not self.proxies:
            return None
        
        proxy_str = random.choice(self.proxies)
        return {
            'http': f'http://{proxy_str}',
            'https': f'http://{proxy_str}'
        }
    
    def get_headers(self) -> dict:
        """Get random user agent headers"""
        return {
            'User-Agent': self.ua.random,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        }
    
    def should_rotate(self) -> bool:
        """Check if proxy should be rotated"""
        self.request_count += 1
        if self.request_count >= self.rotation_interval:
            self.request_count = 0
            return True
        return False
    
    def rotate(self):
        """Rotate to a new proxy"""
        self.current_proxy = self.get_proxy()
        if self.should_rotate():
            self._fetch_proxies()

