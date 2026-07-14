"""
Rate limiting utility using Redis
"""
import redis
import time
import asyncio
from typing import Optional
import logging
import os

logger = logging.getLogger(__name__)

class RateLimiter:
    def __init__(self, redis_url: Optional[str] = None):
        redis_url = redis_url or os.getenv('REDIS_URL', 'redis://localhost:6379/0')
        try:
            self.redis_client = redis.from_url(redis_url, decode_responses=True)
            self.redis_client.ping()
        except Exception as e:
            logger.warning(f"Redis connection failed: {e}. Using in-memory rate limiting.")
            self.redis_client = None
            self.memory_store = {}
    
    def _get_key(self, platform: str, action: str) -> str:
        return f"rate_limit:{platform}:{action}"
    
    def check_rate_limit(self, platform: str, action: str, max_requests: int, window_seconds: int) -> bool:
        """Check if request is within rate limit"""
        key = self._get_key(platform, action)
        current_time = int(time.time())
        window_start = current_time - window_seconds
        
        if self.redis_client:
            try:
                # Sliding window: count first, only record the request if allowed —
                # otherwise waiting callers keep inflating the window and starve.
                pipe = self.redis_client.pipeline()
                pipe.zremrangebyscore(key, 0, window_start)
                pipe.zcard(key)
                results = pipe.execute()

                count = results[1]
                if count >= max_requests:
                    return False

                pipe = self.redis_client.pipeline()
                pipe.zadd(key, {f"{current_time}:{count}": current_time})
                pipe.expire(key, window_seconds)
                pipe.execute()
                return True
            except Exception as e:
                logger.error(f"Redis error: {e}")
                return True
        else:
            # In-memory fallback
            if key not in self.memory_store:
                self.memory_store[key] = []
            
            timestamps = [ts for ts in self.memory_store[key] if ts > window_start]
            if len(timestamps) >= max_requests:
                self.memory_store[key] = timestamps
                return False
            
            timestamps.append(current_time)
            self.memory_store[key] = timestamps
            return True
    
    async def wait_if_needed(self, platform: str, action: str, max_requests: int, window_seconds: int):
        """Wait if rate limit is exceeded"""
        while not self.check_rate_limit(platform, action, max_requests, window_seconds):
            wait_time = window_seconds / max_requests
            logger.info(f"Rate limit exceeded for {platform}:{action}. Waiting {wait_time}s")
            await asyncio.sleep(wait_time)

