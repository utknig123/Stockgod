"""
Selenium helper utilities for web scraping
Fixed for Windows compatibility and improved reliability
"""
import logging
import os
import sys
import time
import random
import atexit

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException

logger = logging.getLogger(__name__)

# Global driver reference for cleanup
_active_drivers = []

def cleanup_drivers():
    """Cleanup all active drivers on exit"""
    global _active_drivers
    for driver in _active_drivers:
        try:
            driver.quit()
        except:
            pass
    _active_drivers = []

# Register cleanup on exit
atexit.register(cleanup_drivers)


def _resolve_chromedriver_path(path: str) -> str:
    """webdriver-manager 4.x can return a non-executable file inside the driver zip."""
    if os.path.isfile(path) and os.access(path, os.X_OK) and not path.endswith('.chromedriver'):
        return path

    search_roots = []
    if os.path.isfile(path):
        search_roots.append(os.path.dirname(path))
    elif os.path.isdir(path):
        search_roots.append(path)

    for root in search_roots:
        for dirpath, _, filenames in os.walk(root):
            for fname in filenames:
                if fname in ('chromedriver', 'chromedriver.exe'):
                    candidate = os.path.join(dirpath, fname)
                    if os.path.isfile(candidate):
                        try:
                            os.chmod(candidate, 0o755)
                        except OSError:
                            pass
                        return candidate

    raise FileNotFoundError(f"No chromedriver binary found near {path}")


class SeleniumHelper:
    def __init__(self, headless=True, use_undetected=True):
        self.headless = headless
        self.use_undetected = use_undetected
        self.driver = None
        self._is_closed = False
    
    def get_driver(self):
        """Get configured Chrome driver with improved error handling"""
        if self.driver and not self._is_closed:
            return self.driver
        
        # Determine if running on Windows or Linux/Docker
        is_windows = sys.platform.startswith('win')
        is_docker = os.path.exists('/.dockerenv') or os.environ.get('DOCKER_CONTAINER', False)
        
        if self.use_undetected:
            try:
                import undetected_chromedriver as uc
                
                options = uc.ChromeOptions()
                
                # Headless mode settings
                if self.headless:
                    options.add_argument('--headless=new')
                    options.add_argument('--disable-gpu')
                
                # Common options
                options.add_argument('--no-sandbox')
                options.add_argument('--disable-dev-shm-usage')
                options.add_argument('--disable-blink-features=AutomationControlled')
                options.add_argument('--disable-extensions')
                options.add_argument('--disable-infobars')
                options.add_argument('--disable-popup-blocking')
                options.add_argument('--window-size=1920,1080')
                options.add_argument('--start-maximized')
                options.add_argument('--ignore-certificate-errors')
                options.add_argument('--allow-running-insecure-content')
                
                # User agent
                options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36')
                
                # Experimental options
                options.add_experimental_option("excludeSwitches", ["enable-automation"])
                options.add_experimental_option('useAutomationExtension', False)
                
                # Platform-specific settings
                if is_docker:
                    options.binary_location = '/usr/bin/google-chrome-stable'
                    self.driver = uc.Chrome(
                        options=options,
                        version_main=None,
                        driver_executable_path=None,
                        browser_executable_path='/usr/bin/google-chrome-stable',
                        use_subprocess=True
                    )
                else:
                    # Windows/local
                    self.driver = uc.Chrome(
                        options=options,
                        version_main=None,
                        use_subprocess=True  # Important for Windows cleanup
                    )
                
                self._apply_driver_timeouts()
                logger.info("Successfully initialized undetected Chrome driver")
                _active_drivers.append(self.driver)
                self._is_closed = False
                
            except Exception as e:
                logger.warning(f"Failed to use undetected Chrome: {e}. Falling back to regular Chrome.")
                self.use_undetected = False
        
        if not self.use_undetected or self.driver is None:
            try:
                from webdriver_manager.chrome import ChromeDriverManager
                
                options = Options()
                
                if self.headless:
                    options.add_argument('--headless=new')
                    options.add_argument('--disable-gpu')
                
                options.add_argument('--no-sandbox')
                options.add_argument('--disable-dev-shm-usage')
                options.add_argument('--disable-blink-features=AutomationControlled')
                options.add_argument('--window-size=1920,1080')
                options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36')
                
                options.add_experimental_option("excludeSwitches", ["enable-automation"])
                options.add_experimental_option('useAutomationExtension', False)
                
                if is_docker:
                    options.binary_location = '/usr/bin/google-chrome-stable'
                    if os.path.exists('/usr/local/bin/chromedriver'):
                        driver_path = '/usr/local/bin/chromedriver'
                    else:
                        driver_path = _resolve_chromedriver_path(ChromeDriverManager().install())
                    service = Service(driver_path)
                else:
                    service = Service(_resolve_chromedriver_path(ChromeDriverManager().install()))
                
                self.driver = webdriver.Chrome(service=service, options=options)
                self._apply_driver_timeouts()
                logger.info("Successfully initialized regular Chrome driver")
                _active_drivers.append(self.driver)
                self._is_closed = False
                
            except Exception as e:
                logger.error(f"Failed to initialize Chrome driver: {e}")
                raise
        
        # Execute script to hide webdriver property
        try:
            self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        except:
            pass
        
        return self.driver

    def _apply_driver_timeouts(self):
        """Avoid multi-minute hangs when sites block automation."""
        if self.driver:
            self.driver.set_page_load_timeout(45)
            self.driver.set_script_timeout(30)
    
    def wait_for_element(self, by, value, timeout=10):
        """Wait for element to be present"""
        try:
            if not self.driver:
                return None
            wait = WebDriverWait(self.driver, timeout)
            return wait.until(EC.presence_of_element_located((by, value)))
        except TimeoutException:
            return None
        except Exception as e:
            logger.debug(f"Error waiting for element: {e}")
            return None
    
    def wait_for_elements(self, by, value, timeout=10):
        """Wait for elements to be present"""
        try:
            if not self.driver:
                return []
            wait = WebDriverWait(self.driver, timeout)
            return wait.until(EC.presence_of_all_elements_located((by, value)))
        except TimeoutException:
            return []
        except Exception as e:
            logger.debug(f"Error waiting for elements: {e}")
            return []
    
    def wait_for_clickable(self, by, value, timeout=10):
        """Wait for element to be clickable"""
        try:
            if not self.driver:
                return None
            wait = WebDriverWait(self.driver, timeout)
            return wait.until(EC.element_to_be_clickable((by, value)))
        except TimeoutException:
            return None
    
    def scroll_page(self, scroll_pause_time=2, max_scrolls=5):
        """Scroll page to load more content"""
        if not self.driver:
            return
            
        last_height = self.driver.execute_script("return document.body.scrollHeight")
        scroll_count = 0
        
        while scroll_count < max_scrolls:
            # Scroll down
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(scroll_pause_time)
            
            # Calculate new scroll height
            new_height = self.driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height
            scroll_count += 1
    
    def scroll_by(self, pixels=500):
        """Scroll by specific pixels"""
        if self.driver:
            self.driver.execute_script(f"window.scrollBy(0, {pixels});")
    
    def random_delay(self, min_seconds=1, max_seconds=3):
        """Random delay to appear more human-like"""
        time.sleep(random.uniform(min_seconds, max_seconds))
    
    def get_page_source(self):
        """Get current page source"""
        if self.driver:
            return self.driver.page_source
        return ""
    
    def take_screenshot(self, filename="screenshot.png"):
        """Take screenshot for debugging"""
        if self.driver:
            try:
                self.driver.save_screenshot(filename)
                logger.info(f"Screenshot saved to {filename}")
            except Exception as e:
                logger.error(f"Failed to take screenshot: {e}")
    
    def close(self):
        """Close the driver safely"""
        global _active_drivers
        
        if self._is_closed:
            return
            
        self._is_closed = True
        
        if self.driver:
            try:
                # Remove from global list
                if self.driver in _active_drivers:
                    _active_drivers.remove(self.driver)
                
                # Try graceful quit
                self.driver.quit()
            except OSError:
                # Windows handle error - ignore
                pass
            except Exception as e:
                logger.debug(f"Error closing driver: {e}")
            finally:
                self.driver = None
    
    def __del__(self):
        """Destructor - close driver"""
        try:
            self.close()
        except:
            pass
    
    def __enter__(self):
        """Context manager entry"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.close()
        return False
