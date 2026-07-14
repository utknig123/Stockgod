"""
Instagram scraper using Selenium
Updated with alternative sources since Instagram requires login
"""
import asyncio
import logging
import os
from datetime import datetime
from base_scraper import BaseScraper
from utils.selenium_helper import SeleniumHelper
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import time
import random

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class InstagramScraper(BaseScraper):
    def __init__(self):
        super().__init__('instagram')
        self.selenium = SeleniumHelper(headless=True, use_undetected=True)
        
        # Alternative sources for financial social content
        self.alternative_sources = [
            {
                'name': 'StockTwits',
                'url': 'https://stocktwits.com/symbol/{symbol}',
                'type': 'social'
            },
            {
                'name': 'Seeking Alpha',
                'url': 'https://seekingalpha.com/symbol/{symbol}',
                'type': 'analysis'
            },
            {
                'name': 'Finviz',
                'url': 'https://finviz.com/quote.ashx?t={symbol}',
                'type': 'finance'
            }
        ]
    
    def scrape_hashtag(self, hashtag: str, limit: int = 20):
        """
        Try to scrape Instagram hashtag, fallback to StockTwits if blocked
        """
        posts = []
        driver = None
        
        try:
            driver = self.selenium.get_driver()
            
            # Clean hashtag
            hashtag_clean = hashtag.replace('#', '').replace(' ', '')
            url = f"https://www.instagram.com/explore/tags/{hashtag_clean}/"
            
            logger.info(f"Attempting Instagram: {url}")
            driver.get(url)
            self.selenium.random_delay(3, 5)
            
            # Check if login is required
            page_source = driver.page_source.lower()
            if 'log in' in page_source or 'sign up' in page_source or 'login' in page_source:
                logger.warning("Instagram requires login - switching to StockTwits")
                return self.scrape_stocktwits(hashtag_clean, limit)
            
            # Try to find posts
            self.selenium.scroll_page(scroll_pause_time=2, max_scrolls=3)
            
            post_selectors = [
                'article a[href*="/p/"]',
                'a[href*="/p/"]',
                'div[style*="flex"] a[href*="/p/"]',
            ]
            
            post_links = []
            for selector in post_selectors:
                try:
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    post_links = [elem.get_attribute('href') for elem in elements if elem.get_attribute('href')]
                    if post_links:
                        logger.info(f"Found {len(post_links)} Instagram post links")
                        break
                except:
                    continue
            
            if not post_links:
                logger.warning("No Instagram posts found - using StockTwits")
                return self.scrape_stocktwits(hashtag_clean, limit)
            
            # Visit each post
            for post_url in post_links[:limit]:
                try:
                    driver.get(post_url)
                    self.selenium.random_delay(2, 3)
                    
                    content = self._extract_instagram_content(driver)
                    
                    if not content:
                        continue
                    
                    post_id = post_url.split('/p/')[-1].split('/')[0]
                    
                    posts.append({
                        'id': post_id,
                        'content': content,
                        'author': self._get_instagram_author(driver),
                        'url': post_url,
                        'engagement': self._get_instagram_engagement(driver),
                        'timestamp': datetime.utcnow()
                    })
                    
                except Exception as e:
                    logger.debug(f"Error extracting Instagram post: {e}")
                    continue
            
            logger.info(f"Scraped {len(posts)} Instagram posts")
            
        except Exception as e:
            logger.error(f"Error scraping Instagram: {e}")
            return self.scrape_stocktwits(hashtag.replace('#', '').replace(' ', ''), limit)
        
        return posts
    
    def _extract_instagram_content(self, driver):
        """Extract post content from Instagram"""
        content_selectors = [
            'article h1',
            'h1 + div span',
            'article div span',
            'div[role="dialog"] span',
        ]
        
        for selector in content_selectors:
            try:
                element = driver.find_element(By.CSS_SELECTOR, selector)
                content = element.text.strip()
                if content and len(content) > 10:
                    return content
            except:
                continue
        
        return ""
    
    def _get_instagram_author(self, driver):
        """Get Instagram post author"""
        try:
            selectors = ['header a', 'h2 a', 'a[role="link"]']
            for selector in selectors:
                try:
                    elem = driver.find_element(By.CSS_SELECTOR, selector)
                    author = elem.text.strip() or elem.get_attribute('href').split('/')[-2]
                    if author:
                        return author
                except:
                    continue
        except:
            pass
        return "unknown"
    
    def _get_instagram_engagement(self, driver):
        """Get Instagram post engagement"""
        try:
            selectors = ['section span', 'button span']
            for selector in selectors:
                try:
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    for elem in elements:
                        text = elem.text.lower()
                        if 'like' in text or text.replace(',', '').isdigit():
                            num = text.replace('likes', '').replace('like', '').replace(',', '').strip()
                            if 'k' in num:
                                return int(float(num.replace('k', '')) * 1000)
                            elif 'm' in num:
                                return int(float(num.replace('m', '')) * 1000000)
                            elif num.isdigit():
                                return int(num)
                except:
                    continue
        except:
            pass
        return 0
    
    def scrape_stocktwits(self, symbol: str, limit: int = 20):
        """Scrape StockTwits as alternative to Instagram"""
        posts = self.http.fetch_stocktwits(symbol, limit=limit)
        if posts:
            return posts

        driver = self.selenium.get_driver()
        
        try:
            # Clean symbol
            symbol_clean = symbol.upper().replace(' ', '')
            if len(symbol_clean) > 5:
                # It's a company name, not symbol - try to extract
                symbol_clean = symbol_clean[:4]
            
            url = f"https://stocktwits.com/symbol/{symbol_clean}"
            logger.info(f"Scraping StockTwits: {url}")
            driver.get(url)
            
            self.selenium.random_delay(3, 5)
            self.selenium.scroll_page(scroll_pause_time=2, max_scrolls=3)
            
            # Find message elements
            message_selectors = [
                'div[class*="MessageBody"]',
                'article[class*="Message"]',
                'div[class*="message-body"]',
                'div[data-testid="message-body"]',
                '.st_message-body',
                'div.message',
            ]
            
            message_elements = []
            for selector in message_selectors:
                try:
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    if elements:
                        message_elements = elements
                        logger.info(f"Found {len(elements)} StockTwits messages")
                        break
                except:
                    continue
            
            # If no specific elements found, try to get all text from stream
            if not message_elements:
                try:
                    stream = driver.find_element(By.CSS_SELECTOR, 'div[class*="Stream"], main')
                    # Get all paragraph-like elements
                    message_elements = stream.find_elements(By.CSS_SELECTOR, 'p, div > span')
                except:
                    pass
            
            for elem in message_elements[:limit]:
                try:
                    content = elem.text.strip()
                    
                    if not content or len(content) < 10:
                        continue
                    
                    # Skip navigation/menu items
                    if any(skip in content.lower() for skip in ['follow', 'share', 'reply', 'sign in', 'sign up']):
                        continue
                    
                    posts.append({
                        'id': f"stocktwits_{int(time.time())}_{random.randint(1000,9999)}",
                        'content': content,
                        'author': 'stocktwits_user',
                        'url': url,
                        'engagement': 0,
                        'timestamp': datetime.utcnow()
                    })
                    
                except Exception as e:
                    logger.debug(f"Error extracting StockTwits message: {e}")
                    continue
            
            logger.info(f"Scraped {len(posts)} StockTwits posts for {symbol_clean}")
            
        except Exception as e:
            logger.error(f"Error scraping StockTwits: {e}")
        
        # If StockTwits failed, try Google News RSS then Finviz
        if not posts:
            posts = self.http.fetch_google_news_rss(f"{symbol} stock India", limit=limit)
        if not posts:
            posts = self.scrape_finviz_news(symbol, limit)

        return posts
    
    def scrape_finviz_news(self, symbol: str, limit: int = 20):
        """Scrape Finviz news as fallback"""
        posts = []
        driver = self.selenium.get_driver()
        
        try:
            # Clean symbol
            symbol_clean = symbol.upper().replace(' ', '')[:5]
            
            url = f"https://finviz.com/quote.ashx?t={symbol_clean}"
            logger.info(f"Scraping Finviz: {url}")
            driver.get(url)
            
            self.selenium.random_delay(2, 4)
            
            # Find news table
            news_selectors = [
                'table.fullview-news-outer tr',
                'td.news-link-container a',
                'a[href*="news"]',
            ]
            
            for selector in news_selectors:
                try:
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    for elem in elements[:limit]:
                        try:
                            text = elem.text.strip()
                            href = elem.get_attribute('href') if elem.tag_name == 'a' else ''
                            
                            if text and len(text) > 20:
                                posts.append({
                                    'id': f"finviz_{int(time.time())}_{random.randint(1000,9999)}",
                                    'content': text,
                                    'author': 'finviz_news',
                                    'url': href or url,
                                    'engagement': 0,
                                    'timestamp': datetime.utcnow()
                                })
                        except:
                            continue
                    
                    if posts:
                        break
                except:
                    continue
            
            logger.info(f"Scraped {len(posts)} Finviz news items")
            
        except Exception as e:
            logger.error(f"Error scraping Finviz: {e}")
        
        return posts
    
    async def scrape(self):
        """Scrape posts from Instagram or alternatives"""
        while True:
            try:
                for company in self.companies:
                    # Check rate limit
                    await self.rate_limiter.wait_if_needed(
                        'instagram', 'search', 20, 60
                    )
                    
                    # Search for posts with company keywords
                    for keyword in company['keywords']:
                        try:
                            # Clean keyword for hashtag/search
                            hashtag = keyword.replace(' ', '').replace('#', '')
                            
                            # Try Instagram first, fallback to alternatives
                            instagram_posts = self.scrape_hashtag(hashtag, limit=15)
                            
                            # Also try with company symbol
                            if not instagram_posts:
                                instagram_posts = self.scrape_stocktwits(company['symbol'], limit=15)
                            
                            for post in instagram_posts:
                                try:
                                    post_data = self._create_post_data(
                                        post_id=str(post['id']),
                                        content=post['content'],
                                        author=post['author'],
                                        timestamp=post['timestamp'],
                                        url=post['url'],
                                        engagement=post['engagement'],
                                        company=company,
                                    )
                                    
                                    if post_data:
                                        self._send_to_kafka(post_data)
                                        logger.info(f"Sent to Kafka: {post['id'][:30]}...")
                                    
                                    await asyncio.sleep(1)
                                    
                                except Exception as e:
                                    logger.error(f"Error processing post: {e}")
                                    continue
                            
                            # Random delay between searches
                            await asyncio.sleep(random.uniform(15, 25))
                            
                        except Exception as e:
                            logger.error(f"Error searching for {keyword}: {e}")
                            continue
                
                # Wait before next scraping cycle
                logger.info("Completed Instagram/StockTwits scraping cycle, waiting 10 minutes...")
                await asyncio.sleep(600)  # 10 minutes between cycles
                
            except Exception as e:
                logger.error(f"Instagram scraper error: {e}")
                await asyncio.sleep(60)
    
    def __del__(self):
        """Cleanup"""
        try:
            if hasattr(self, 'selenium'):
                self.selenium.close()
        except:
            pass


if __name__ == "__main__":
    scraper = InstagramScraper()
    scraper.run()
