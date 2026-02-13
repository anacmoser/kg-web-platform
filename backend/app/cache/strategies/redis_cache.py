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
        self.cache_file = settings.STORAGE_DIR / "cache" / "local_cache.pkl"
        self.use_redis = None # None means not yet checked
        
        # Ensure cache directory exists
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Load local cache on start is fine as it's just a file read
        self._load_local_cache()
    
    def _ensure_connected(self):
        """Lazy connection to Redis"""
        if self.use_redis is not None:
            return self.use_redis
            
        self.use_redis = self._connect_redis()
        return self.use_redis
    
    def _load_local_cache(self):
        """Load fallback cache from disk"""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'rb') as f:
                    self.fallback_cache = pickle.load(f)
                logger.info(f"Loaded {len(self.fallback_cache)} items from persistent local cache")
            except Exception as e:
                logger.error(f"Failed to load persistent local cache: {e}")

    def _save_local_cache(self):
        """Save fallback cache to disk"""
        try:
            with open(self.cache_file, 'wb') as f:
                pickle.dump(self.fallback_cache, f)
            logger.debug("Persistent local cache saved")
        except Exception as e:
            logger.error(f"Failed to save persistent local cache: {e}")

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
            if self._ensure_connected() and self.redis_client:
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
            
            if self._ensure_connected() and self.redis_client:
                self.redis_client.setex(key, ttl, serialized)
                logger.debug(f"Cache SET (Redis): {key} (TTL: {ttl}s)")
            else:
                # Fallback to in-memory (no TTL enforcement)
                self.fallback_cache[key] = value
                self._save_local_cache()
                logger.debug(f"Cache SET (Memory + Disk): {key}")
        except Exception as e:
            logger.error(f"Cache set error for {key}: {e}")
    
    def delete(self, key: str):
        """Delete key from cache"""
        try:
            if self._ensure_connected() and self.redis_client:
                self.redis_client.delete(key)
            else:
                self.fallback_cache.pop(key, None)
                self._save_local_cache()
            logger.debug(f"Cache DELETE: {key}")
        except Exception as e:
            logger.error(f"Cache delete error for {key}: {e}")
    
    def invalidate_pattern(self, pattern: str):
        """Invalidate all keys matching pattern"""
        try:
            if self._ensure_connected() and self.redis_client:
                for key in self.redis_client.scan_iter(match=pattern):
                    self.redis_client.delete(key)
                logger.info(f"Invalidated cache pattern: {pattern}")
            else:
                # In-memory pattern matching
                keys_to_delete = [k for k in self.fallback_cache.keys() if pattern in k]
                for key in keys_to_delete:
                    del self.fallback_cache[key]
                if keys_to_delete:
                    self._save_local_cache()
                logger.info(f"Invalidated {len(keys_to_delete)} cache keys matching: {pattern}")
        except Exception as e:
            logger.error(f"Cache invalidation error for pattern {pattern}: {e}")

# Global cache instance
cache = RedisCache()
