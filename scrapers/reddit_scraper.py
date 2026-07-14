"""
Reddit scraper using Selenium
Updated with better selectors for new Reddit UI (2024+)
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
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class RedditScraper(BaseScraper):
    def __init__(self):
        super().__init__('reddit')
        self.selenium = SeleniumHelper(headless=True, use_undetected=True)
        
        # Subreddits from config (Indian IPO focus) with sensible defaults
        self.subreddits = []
        for company in self.companies:
            self.subreddits.extend(company.get('subreddits', []))
        self.subreddits = list(dict.fromkeys(self.subreddits)) or [
            'IndianStockMarket', 'IndianStreetBets', 'investing', 'stocks', 'StockMarket'
        ]
    
    def scrape_subreddit(self, subreddit_name: str, limit: int = 25):
        """Scrape posts from a subreddit - JSON API first, Selenium fallback"""
        posts = self.http.fetch_reddit_subreddit(subreddit_name, limit=limit)
        if posts:
            return posts

        driver = None

        try:
            driver = self.selenium.get_driver()
            
            # Try old.reddit.com first (more stable for scraping)
            url = f"https://old.reddit.com/r/{subreddit_name}/hot/"
            logger.info(f"Opening Reddit: {url}")
            driver.get(url)
            
            # Wait for page to load
            self.selenium.random_delay(2, 4)
            
            # Try old Reddit selectors first
            post_elements = driver.find_elements(By.CSS_SELECTOR, 'div.thing.link')
            
            if post_elements:
                logger.info(f"Found {len(post_elements)} posts on old.reddit.com")
                posts = self._extract_old_reddit_posts(post_elements, subreddit_name, limit)
            else:
                # Fallback to new Reddit
                url = f"https://www.reddit.com/r/{subreddit_name}/hot/"
                driver.get(url)
                self.selenium.random_delay(3, 5)
                
                # Scroll to load more posts
                self.selenium.scroll_page(scroll_pause_time=2, max_scrolls=3)
                
                # New Reddit selectors (multiple options)
                new_reddit_selectors = [
                    'shreddit-post',  # Web component
                    'div[data-testid="post-container"]',
                    'article.Post',
                    'div[class*="_1oQyIsiPHYt6nx7VOmd1sz"]',  # Reddit's class names
                    'div[data-click-id="body"]',
                ]
                
                for selector in new_reddit_selectors:
                    try:
                        post_elements = driver.find_elements(By.CSS_SELECTOR, selector)
                        if post_elements:
                            logger.info(f"Found {len(post_elements)} posts with selector: {selector}")
                            break
                    except:
                        continue
                
                if post_elements:
                    posts = self._extract_new_reddit_posts(post_elements, subreddit_name, limit, driver)
            
            logger.info(f"Scraped {len(posts)} posts from r/{subreddit_name}")
            
        except Exception as e:
            logger.error(f"Error scraping r/{subreddit_name}: {e}")
        
        return posts
    
    def _extract_old_reddit_posts(self, elements, subreddit_name, limit):
        """Extract posts from old.reddit.com format"""
        posts = []
        
        for element in elements[:limit]:
            try:
                # Get post title
                try:
                    title_element = element.find_element(By.CSS_SELECTOR, 'a.title')
                    title = title_element.text.strip()
                    post_url = title_element.get_attribute('href')
                except:
                    continue
                
                if not title:
                    continue
                
                # Get post ID
                try:
                    post_id = element.get_attribute('data-fullname')
                    if not post_id:
                        post_id = element.get_attribute('id')
                    if not post_id:
                        post_id = f"reddit_{int(time.time())}_{random.randint(1000,9999)}"
                except:
                    post_id = f"reddit_{int(time.time())}_{random.randint(1000,9999)}"
                
                # Get author
                try:
                    author_element = element.find_element(By.CSS_SELECTOR, 'a.author')
                    author = author_element.text.strip()
                except:
                    author = "unknown"
                
                # Get score/engagement
                engagement = 0
                try:
                    score_element = element.find_element(By.CSS_SELECTOR, 'div.score.unvoted')
                    score_text = score_element.get_attribute('title') or score_element.text
                    engagement = self._parse_score(score_text)
                except:
                    try:
                        score_element = element.find_element(By.CSS_SELECTOR, 'div.score')
                        engagement = self._parse_score(score_element.text)
                    except:
                        pass
                
                # Get selftext if available
                content = title
                try:
                    text_element = element.find_element(By.CSS_SELECTOR, 'div.md')
                    selftext = text_element.text.strip()
                    if selftext:
                        content = f"{title}\n\n{selftext}"
                except:
                    pass
                
                posts.append({
                    'id': post_id,
                    'content': content,
                    'author': author,
                    'url': post_url,
                    'engagement': engagement,
                    'timestamp': datetime.utcnow()
                })
                
            except Exception as e:
                logger.debug(f"Error extracting old Reddit post: {e}")
                continue
        
        return posts
    
    def _extract_new_reddit_posts(self, elements, subreddit_name, limit, driver):
        """Extract posts from new Reddit format"""
        posts = []
        
        for element in elements[:limit]:
            try:
                content = ""
                post_url = ""
                post_id = ""
                author = "unknown"
                engagement = 0
                
                # Check if it's a shreddit-post web component
                tag_name = element.tag_name.lower()
                
                if tag_name == 'shreddit-post':
                    # Extract from shreddit-post attributes
                    try:
                        content = element.get_attribute('post-title') or ""
                        post_url = element.get_attribute('content-href') or element.get_attribute('permalink') or ""
                        post_id = element.get_attribute('id') or f"reddit_{int(time.time())}"
                        author = element.get_attribute('author') or "unknown"
                        
                        score = element.get_attribute('score')
                        if score:
                            engagement = self._parse_score(score)
                    except:
                        pass
                else:
                    # Try standard selectors
                    title_selectors = [
                        'h3',
                        'a[data-click-id="body"]',
                        'div[slot="title"]',
                        'a[data-testid="post-title"]',
                    ]
                    
                    for selector in title_selectors:
                        try:
                            title_element = element.find_element(By.CSS_SELECTOR, selector)
                            content = title_element.text.strip()
                            if content:
                                break
                        except:
                            continue
                    
                    # Get URL
                    try:
                        link = element.find_element(By.CSS_SELECTOR, 'a[data-click-id="body"], a[href*="/comments/"]')
                        post_url = link.get_attribute('href')
                        if '/comments/' in post_url:
                            post_id = post_url.split('/comments/')[-1].split('/')[0]
                    except:
                        post_id = f"reddit_{int(time.time())}_{random.randint(1000,9999)}"
                    
                    # Get author
                    try:
                        author_element = element.find_element(By.CSS_SELECTOR, 'a[href*="/user/"]')
                        author = author_element.text.replace('u/', '').strip()
                    except:
                        pass
                    
                    # Get score
                    try:
                        score_element = element.find_element(By.CSS_SELECTOR, 'faceplate-number, [id*="vote-score"]')
                        engagement = self._parse_score(score_element.text)
                    except:
                        pass
                
                if not content:
                    continue
                
                if not post_url:
                    post_url = f"https://www.reddit.com/r/{subreddit_name}/"
                
                posts.append({
                    'id': post_id or f"reddit_{int(time.time())}",
                    'content': content,
                    'author': author,
                    'url': post_url,
                    'engagement': engagement,
                    'timestamp': datetime.utcnow()
                })
                
            except Exception as e:
                logger.debug(f"Error extracting new Reddit post: {e}")
                continue
        
        return posts
    
    def _parse_score(self, score_text):
        """Parse Reddit score/karma text to integer"""
        if not score_text:
            return 0
        
        score_text = str(score_text).lower().strip()
        
        try:
            if 'k' in score_text:
                return int(float(score_text.replace('k', '').strip()) * 1000)
            elif 'm' in score_text:
                return int(float(score_text.replace('m', '').strip()) * 1000000)
            else:
                # Remove non-numeric characters
                clean = re.sub(r'[^0-9.-]', '', score_text)
                return int(float(clean)) if clean else 0
        except:
            return 0
    
    def search_reddit(self, query: str, limit: int = 20):
        """Search Reddit for a query"""
        posts = self.http.fetch_reddit_search(query, limit=limit)
        if posts:
            return posts

        driver = self.selenium.get_driver()
        
        try:
            # Use old Reddit for search (more reliable)
            url = f"https://old.reddit.com/search?q={query.replace(' ', '+')}&sort=new&t=week"
            logger.info(f"Searching Reddit: {url}")
            driver.get(url)
            
            self.selenium.random_delay(2, 4)
            
            # Find search results
            post_elements = driver.find_elements(By.CSS_SELECTOR, 'div.thing.link, div.search-result-link')
            
            if post_elements:
                posts = self._extract_old_reddit_posts(post_elements, 'search', limit)
            else:
                # Fallback to new Reddit search
                url = f"https://www.reddit.com/search/?q={query.replace(' ', '%20')}&sort=new"
                driver.get(url)
                self.selenium.random_delay(3, 5)
                self.selenium.scroll_page(scroll_pause_time=2, max_scrolls=2)
                
                post_elements = driver.find_elements(By.CSS_SELECTOR, 'shreddit-post, div[data-testid="post-container"]')
                posts = self._extract_new_reddit_posts(post_elements, 'search', limit, driver)
            
            logger.info(f"Found {len(posts)} search results for: {query}")
            
        except Exception as e:
            logger.error(f"Error searching Reddit: {e}")
        
        return posts
    
    async def scrape(self):
        """Scrape Reddit posts"""
        while True:
            try:
                # Scrape from subreddits
                for subreddit_name in self.subreddits:
                    try:
                        await self.rate_limiter.wait_if_needed(
                            'reddit', 'scrape', 30, 60
                        )
                        
                        posts = self.scrape_subreddit(subreddit_name, limit=25)
                        
                        for post in posts:
                            try:
                                post_data = self._create_post_data(
                                    post_id=post['id'],
                                    content=post['content'],
                                    author=post['author'],
                                    timestamp=post['timestamp'],
                                    url=post['url'],
                                    engagement=post['engagement'],
                                    company=self._is_relevant_post(post['content']),
                                )

                                if post_data:
                                    self._send_to_kafka(post_data)
                                    logger.info(f"Sent to Kafka: {post['id'][:30]}...")
                                
                                await asyncio.sleep(0.5)
                                
                            except Exception as e:
                                logger.error(f"Error processing Reddit post: {e}")
                                continue
                        
                        await asyncio.sleep(random.uniform(5, 10))
                        
                    except Exception as e:
                        logger.error(f"Error accessing subreddit {subreddit_name}: {e}")
                        continue
                
                # Also search for company-specific posts
                for company in self.companies:
                    for keyword in company['keywords']:
                        try:
                            await self.rate_limiter.wait_if_needed(
                                'reddit', 'search', 20, 60
                            )
                            
                            posts = self.search_reddit(f"{keyword} stock", limit=10)
                            
                            for post in posts:
                                try:
                                    # Verify relevance: search engines can return unrelated posts
                                    post_data = self._create_post_data(
                                        post_id=post['id'],
                                        content=post['content'],
                                        author=post['author'],
                                        timestamp=post['timestamp'],
                                        url=post['url'],
                                        engagement=post['engagement'],
                                        company=self._is_relevant_post(post['content']),
                                    )
                                    
                                    if post_data:
                                        self._send_to_kafka(post_data)
                                    
                                    await asyncio.sleep(0.5)
                                    
                                except Exception as e:
                                    logger.error(f"Error processing Reddit search result: {e}")
                                    continue
                            
                            await asyncio.sleep(random.uniform(10, 15))
                            
                        except Exception as e:
                            logger.error(f"Error searching Reddit for {keyword}: {e}")
                            continue
                
                # Wait before next scraping cycle
                logger.info("Completed Reddit scraping cycle, waiting 10 minutes...")
                await asyncio.sleep(600)  # 10 minutes between cycles
                
            except Exception as e:
                logger.error(f"Reddit scraper error: {e}")
                await asyncio.sleep(60)
    
    def __del__(self):
        """Cleanup"""
        try:
            if hasattr(self, 'selenium'):
                self.selenium.close()
        except:
            pass


if __name__ == "__main__":
    scraper = RedditScraper()
    scraper.run()
