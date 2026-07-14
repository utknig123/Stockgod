"""
Twitter/X scraper using Selenium
Updated with better selectors and alternative methods
"""
import asyncio
import logging
import os
import random
import re
from datetime import datetime
from base_scraper import BaseScraper
from utils.selenium_helper import SeleniumHelper
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TwitterScraper(BaseScraper):
    def __init__(self):
        super().__init__('twitter')
        self.selenium = SeleniumHelper(headless=True, use_undetected=True)
        
        # Alternative financial news sources when Twitter is blocked
        self.news_sources = [
            {
                'name': 'Yahoo Finance',
                'url_template': 'https://finance.yahoo.com/quote/{symbol}/news',
                'type': 'finance'
            },
            {
                'name': 'Google News',
                'url_template': 'https://news.google.com/search?q={query}+stock+IPO&hl=en-US',
                'type': 'news'
            },
            {
                'name': 'MarketWatch',
                'url_template': 'https://www.marketwatch.com/search?q={query}&ts=0&ns=y',
                'type': 'finance'
            }
        ]
    
    def scrape_news_http(self, company: dict, limit: int = 20):
        """Scrape financial news via HTTP (no browser)."""
        posts = []
        symbol = company['symbol']
        name = company['name']
        for keyword in company['keywords'][:2]:
            posts.extend(
                self.http.fetch_google_news_rss(
                    f"{keyword} {name} stock India IPO", limit=limit // 2
                )
            )
        yahoo_posts = self.http.fetch_yahoo_news_rss(symbol, limit=limit // 2)
        if yahoo_posts:
            posts.extend(yahoo_posts)
        seen = set()
        unique = []
        for p in posts:
            key = p['content'][:80]
            if key not in seen:
                seen.add(key)
                unique.append(p)
        return unique[:limit]

    def scrape_tweets_selenium(self, query: str, limit: int = 20, company: dict = None):
        """Scrape news/social data — HTTP first, Selenium only if needed."""
        if company:
            http_posts = self.scrape_news_http(company, limit=limit)
            if http_posts:
                return http_posts

        tweets = []
        driver = None

        try:
            driver = self.selenium.get_driver()
            driver.set_page_load_timeout(45)

            # Twitter/X is often blocked; skip long waits when login wall appears quickly
            search_url = f"https://twitter.com/search?q={query.replace(' ', '%20')}&src=typed_query&f=live"
            logger.info(f"Opening Twitter search: {search_url}")
            driver.get(search_url)
            
            # Wait for page to load
            self.selenium.random_delay(3, 5)
            
            # Check if we hit a login wall
            page_source = driver.page_source.lower()
            if 'log in' in page_source and 'sign up' in page_source:
                logger.warning("Twitter requires login - switching to alternative sources")
                return self.scrape_alternative_sources(query, limit)
            
            # Multiple tweet selectors to try (Twitter changes these often)
            tweet_selectors = [
                'article[data-testid="tweet"]',
                '[data-testid="tweet"]',
                'article[role="article"]',
                'div[data-testid="cellInnerDiv"] article',
                'article',
            ]
            
            tweet_elements = []
            for selector in tweet_selectors:
                try:
                    self.selenium.random_delay(1, 2)
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    if elements:
                        tweet_elements = elements
                        logger.info(f"Found {len(elements)} elements with selector: {selector}")
                        break
                except Exception as e:
                    logger.debug(f"Selector {selector} failed: {e}")
                    continue
            
            if not tweet_elements:
                logger.warning(f"No tweets found for query: {query} - trying alternative sources")
                return self.scrape_alternative_sources(query, limit)
            
            # Scroll to load more tweets
            for _ in range(2):
                self.selenium.scroll_page(scroll_pause_time=2, max_scrolls=3)
                try:
                    tweet_elements = driver.find_elements(By.CSS_SELECTOR, tweet_selectors[0])
                except:
                    pass
                if len(tweet_elements) >= limit:
                    break
            
            # Extract tweet data
            for element in tweet_elements[:limit]:
                try:
                    tweet_data = self._extract_tweet_data(element, driver)
                    if tweet_data and tweet_data.get('content'):
                        tweets.append(tweet_data)
                except Exception as e:
                    logger.debug(f"Error extracting tweet: {e}")
                    continue
            
            logger.info(f"Successfully scraped {len(tweets)} tweets for query: {query}")
            
        except Exception as e:
            logger.error(f"Error scraping Twitter: {e}")
            # Fallback to alternative sources
            return self.scrape_alternative_sources(query, limit)
        
        return tweets
    
    def _extract_tweet_data(self, element, driver):
        """Extract data from a tweet element"""
        content = ""
        username = "unknown"
        tweet_id = f"tweet_{int(time.time())}_{random.randint(1000,9999)}"
        tweet_url = ""
        engagement = 0
        
        # Get tweet text - multiple selectors
        text_selectors = [
            'div[data-testid="tweetText"]',
            '[data-testid="tweetText"]',
            'div[lang]',
            '.css-1dbjc4n span',
        ]
        
        for selector in text_selectors:
            try:
                text_element = element.find_element(By.CSS_SELECTOR, selector)
                content = text_element.text.strip()
                if content:
                    break
            except:
                continue
        
        if not content:
            return None
        
        # Get username
        username_selectors = [
            'div[data-testid="User-Name"] a span',
            '[data-testid="User-Name"] a',
            'a[role="link"][href^="/"]',
        ]
        
        for selector in username_selectors:
            try:
                username_element = element.find_element(By.CSS_SELECTOR, selector)
                username = username_element.text.replace('@', '').strip()
                if username:
                    break
            except:
                continue
        
        # Get tweet URL/ID
        try:
            time_element = element.find_element(By.CSS_SELECTOR, 'a[href*="/status/"] time')
            parent = time_element.find_element(By.XPATH, '..')
            tweet_url = parent.get_attribute('href')
            if '/status/' in tweet_url:
                tweet_id = tweet_url.split('/status/')[-1].split('?')[0].split('/')[0]
        except:
            try:
                link = element.find_element(By.CSS_SELECTOR, 'a[href*="/status/"]')
                tweet_url = link.get_attribute('href')
                if '/status/' in tweet_url:
                    tweet_id = tweet_url.split('/status/')[-1].split('?')[0].split('/')[0]
            except:
                pass
        
        if not tweet_url:
            tweet_url = f"https://twitter.com/{username}/status/{tweet_id}"
        
        # Get engagement metrics
        try:
            metrics = element.find_elements(By.CSS_SELECTOR, '[data-testid$="-button"] span, [role="group"] span')
            for metric in metrics:
                text = metric.text.strip()
                if text and text[0].isdigit():
                    try:
                        if 'K' in text.upper():
                            engagement += int(float(text.upper().replace('K', '')) * 1000)
                        elif 'M' in text.upper():
                            engagement += int(float(text.upper().replace('M', '')) * 1000000)
                        else:
                            engagement += int(text.replace(',', ''))
                    except:
                        pass
        except:
            pass
        
        return {
            'id': tweet_id,
            'content': content,
            'username': username,
            'url': tweet_url,
            'engagement': engagement,
            'date': datetime.utcnow()
        }
    
    def scrape_alternative_sources(self, query: str, limit: int = 20):
        """Scrape from alternative news sources when Twitter is blocked"""
        posts = []
        driver = self.selenium.get_driver()
        
        logger.info(f"Scraping alternative sources for: {query}")
        
        # Try Yahoo Finance
        try:
            symbol = query.split()[0].upper()
            url = f"https://finance.yahoo.com/quote/{symbol}"
            driver.get(url)
            self.selenium.random_delay(2, 4)
            
            # Get news headlines
            news_selectors = [
                'li[class*="news"] a',
                'h3 a[href*="news"]',
                '[data-testid="news-list"] a',
                'a[href*="/news/"]',
            ]
            
            for selector in news_selectors:
                try:
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    for elem in elements[:limit//2]:
                        text = elem.text.strip()
                        href = elem.get_attribute('href')
                        if text and len(text) > 20:
                            posts.append({
                                'id': f"yahoo_{int(time.time())}_{random.randint(1000,9999)}",
                                'content': text,
                                'username': 'yahoo_finance',
                                'url': href or url,
                                'engagement': 0,
                                'date': datetime.utcnow()
                            })
                    if posts:
                        break
                except:
                    continue
            
            logger.info(f"Found {len(posts)} items from Yahoo Finance")
            
        except Exception as e:
            logger.debug(f"Yahoo Finance scraping failed: {e}")
        
        # Try Google News
        try:
            url = f"https://news.google.com/search?q={query.replace(' ', '%20')}+stock+IPO"
            driver.get(url)
            self.selenium.random_delay(2, 4)
            
            news_elements = driver.find_elements(By.CSS_SELECTOR, 'article h3 a, article h4 a, a[href*="./articles/"]')
            
            for elem in news_elements[:limit//2]:
                try:
                    text = elem.text.strip()
                    if text and len(text) > 20:
                        posts.append({
                            'id': f"gnews_{int(time.time())}_{random.randint(1000,9999)}",
                            'content': text,
                            'username': 'google_news',
                            'url': 'https://news.google.com' + elem.get_attribute('href').replace('./', '/'),
                            'engagement': 0,
                            'date': datetime.utcnow()
                        })
                except:
                    continue
            
            logger.info(f"Total posts from alternative sources: {len(posts)}")
            
        except Exception as e:
            logger.debug(f"Google News scraping failed: {e}")
        
        return posts[:limit]
    
    async def scrape(self):
        """Main scraping loop"""
        while True:
            try:
                for company in self.companies:
                    # Check rate limit
                    await self.rate_limiter.wait_if_needed(
                        'twitter', 'search', 20, 60
                    )
                    
                    # Search for posts with company keywords
                    for keyword in company['keywords']:
                        try:
                            # Build search query
                            query = f"{keyword} IPO OR {keyword} stock OR ${company['symbol']}"
                            
                            # Scrape news (HTTP) or tweets (Selenium fallback)
                            tweets = self.scrape_tweets_selenium(query, limit=20, company=company)

                            for tweet in tweets:
                                try:
                                    author = tweet.get('username') or tweet.get('author', 'unknown')
                                    ts = tweet.get('date') or tweet.get('timestamp', datetime.utcnow())
                                    post_data = self._create_post_data(
                                        post_id=str(tweet['id']),
                                        content=tweet['content'],
                                        author=author,
                                        timestamp=ts,
                                        url=tweet['url'],
                                        engagement=tweet.get('engagement', 0),
                                        company=company,
                                    )
                                    
                                    if post_data:
                                        self._send_to_kafka(post_data)
                                        logger.info(f"Sent to Kafka: {tweet['id'][:20]}...")
                                    
                                    await asyncio.sleep(0.5)
                                    
                                except Exception as e:
                                    logger.error(f"Error processing tweet: {e}")
                                    continue
                            
                            # Random delay between searches
                            await asyncio.sleep(random.uniform(10, 20))
                            
                        except Exception as e:
                            logger.error(f"Error searching for {keyword}: {e}")
                            continue
                
                # Wait before next scraping cycle
                logger.info("Completed scraping cycle, waiting 5 minutes...")
                await asyncio.sleep(300)  # 5 minutes between cycles
                
            except Exception as e:
                logger.error(f"Twitter scraper error: {e}")
                await asyncio.sleep(60)
    
    def __del__(self):
        """Cleanup"""
        try:
            if hasattr(self, 'selenium'):
                self.selenium.close()
        except:
            pass


if __name__ == "__main__":
    scraper = TwitterScraper()
    scraper.run()
