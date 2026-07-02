import logging
from typing import Optional, Any
import redis
from app.config.settings import settings

logger = logging.getLogger(__name__)

class CacheService:
    def __init__(self):
        self.redis_client: Optional[redis.Redis] = None
        self.in_memory_cache: dict[str, Any] = {}
        
        if settings.REDIS_URL:
            try:
                self.redis_client = redis.from_url(
                    settings.REDIS_URL, 
                    decode_responses=True, 
                    socket_connect_timeout=2.0
                )
                # Test connection
                self.redis_client.ping()
                logger.info("Successfully connected to Redis cache.")
            except Exception as e:
                logger.warning(f"Failed to connect to Redis at {settings.REDIS_URL}. Falling back to in-memory cache. Error: {e}")
                self.redis_client = None
        else:
            logger.info("No REDIS_URL provided. Using in-memory cache.")

    def get(self, key: str) -> Optional[Any]:
        if self.redis_client:
            try:
                return self.redis_client.get(key)
            except Exception as e:
                logger.error(f"Redis get error: {e}")
                return self.in_memory_cache.get(key)
        return self.in_memory_cache.get(key)

    def set(self, key: str, value: Any, expire_seconds: Optional[int] = None) -> bool:
        if self.redis_client:
            try:
                if expire_seconds:
                    self.redis_client.setex(key, expire_seconds, str(value))
                else:
                    self.redis_client.set(key, str(value))
                return True
            except Exception as e:
                logger.error(f"Redis set error: {e}")
                # Fallback to memory
                self.in_memory_cache[key] = value
                return True
        else:
            self.in_memory_cache[key] = value
            # Note: in-memory simple cache does not support TTL for simplicity but we could implement basic timestamp logic if needed
            return True

    def delete(self, key: str) -> bool:
        if self.redis_client:
            try:
                self.redis_client.delete(key)
                return True
            except Exception as e:
                logger.error(f"Redis delete error: {e}")
                if key in self.in_memory_cache:
                    del self.in_memory_cache[key]
                return True
        else:
            if key in self.in_memory_cache:
                del self.in_memory_cache[key]
            return True

    def flush(self) -> bool:
        if self.redis_client:
            try:
                self.redis_client.flushdb()
                return True
            except Exception as e:
                logger.error(f"Redis flush error: {e}")
                self.in_memory_cache.clear()
                return True
        else:
            self.in_memory_cache.clear()
            return True

# Singleton cache service instance
cache_service = CacheService()
