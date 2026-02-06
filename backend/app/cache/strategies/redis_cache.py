import redis
import pickle
import logging
from typing import Any, Optional
from app.config import settings

logger = logging.getLogger(__name__)

class RedisCache:
    """
    Redis-based caching strategy with 7-day TTL.
    Falls back to in-memory if Redis is unavailable (Lite Mode).
    """
    
    def __init__(self):
        self.redis_client = None
        self.fallback_cache = {}  # In-memory fallback
        self.use_redis = self._connect_redis()
    
    def _connect_redis(self) -> bool:
        """Attempt to connect to Redis"""
        try:
            self.redis_client = redis.from_url(
                settings.REDIS_URL,
                decode_responses=False  # We'll handle binary data
            )
            # Test connection
            self.redis_client.ping()
            logger.info("Redis cache connected successfully")
            return True
        except Exception as e:
            logger.warning(f"Redis unavailable, using in-memory cache: {e}")
            return False
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        try:
            if self.use_redis and self.redis_client:
                value = self.redis_client.get(key)
                if value:
                    logger.debug(f"Cache HIT (Redis): {key}")
                    return pickle.loads(value)
            else:
                # Fallback to in-memory
                if key in self.fallback_cache:
                    logger.debug(f"Cache HIT (Memory): {key}")
                    return self.fallback_cache[key]
            
            logger.debug(f"Cache MISS: {key}")
            return None
        except Exception as e:
            logger.error(f"Cache get error for {key}: {e}")
            return None
    
    def set(self, key: str, value: Any, ttl: int = None):
        """
        Set value in cache with TTL.
        Default TTL: 7 days (604800 seconds)
        """
        if ttl is None:
            ttl = settings.CACHE_TTL
        
        try:
            serialized = pickle.dumps(value)
            
            if self.use_redis and self.redis_client:
                self.redis_client.setex(key, ttl, serialized)
                logger.debug(f"Cache SET (Redis): {key} (TTL: {ttl}s)")
            else:
                # Fallback to in-memory (no TTL enforcement)
                self.fallback_cache[key] = value
                logger.debug(f"Cache SET (Memory): {key}")
        except Exception as e:
            logger.error(f"Cache set error for {key}: {e}")
    
    def delete(self, key: str):
        """Delete key from cache"""
        try:
            if self.use_redis and self.redis_client:
                self.redis_client.delete(key)
            else:
                self.fallback_cache.pop(key, None)
            logger.debug(f"Cache DELETE: {key}")
        except Exception as e:
            logger.error(f"Cache delete error for {key}: {e}")
    
    def invalidate_pattern(self, pattern: str):
        """Invalidate all keys matching pattern"""
        try:
            if self.use_redis and self.redis_client:
                for key in self.redis_client.scan_iter(match=pattern):
                    self.redis_client.delete(key)
                logger.info(f"Invalidated cache pattern: {pattern}")
            else:
                # In-memory pattern matching
                keys_to_delete = [k for k in self.fallback_cache.keys() if pattern in k]
                for key in keys_to_delete:
                    del self.fallback_cache[key]
                logger.info(f"Invalidated {len(keys_to_delete)} cache keys matching: {pattern}")
        except Exception as e:
            logger.error(f"Cache invalidation error for pattern {pattern}: {e}")

# Global cache instance
cache = RedisCache()
