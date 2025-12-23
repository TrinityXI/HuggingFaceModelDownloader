import json
import redis
import logging
from datetime import datetime
from app.core.config import settings

logger = logging.getLogger(__name__)

class ConfigService:
    def __init__(self):
        self.redis_client = None
        self._init_redis()

    def _init_redis(self):
        try:
            self.redis_client = redis.Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                db=settings.REDIS_DB,
                password=settings.REDIS_PASSWORD,
                decode_responses=True
            )
            self.redis_client.ping()
        except Exception as e:
            logger.warning(f"Redis connection failed: {e}")
            self.redis_client = None

    def get_config(self):
        if self.redis_client:
            try:
                config_str = self.redis_client.get(settings.REDIS_CONFIG_KEY)
                if config_str:
                    return json.loads(config_str)
            except Exception as e:
                logger.warning(f"Failed to get config from Redis: {e}")
        
        # Fallback to defaults
        return {
            'producer_interval': settings.DEFAULT_PRODUCER_INTERVAL,
            'producer_days': settings.DEFAULT_PRODUCER_DAYS,
            'producer_limit': settings.DEFAULT_PRODUCER_LIMIT,
            'producer_timezone_offset': settings.DEFAULT_PRODUCER_TIMEZONE_OFFSET,
            'producer_use_created_at': settings.DEFAULT_PRODUCER_USE_CREATED_AT,
            'producer_auto_limit': settings.DEFAULT_PRODUCER_AUTO_LIMIT,
            'hf_endpoint': settings.HF_ENDPOINT
        }

    def update_config(self, new_config):
        current = self.get_config()
        current.update(new_config)
        current['updated_at'] = datetime.now().isoformat()
        
        if self.redis_client:
            try:
                self.redis_client.set(settings.REDIS_CONFIG_KEY, json.dumps(current))
            except Exception as e:
                logger.error(f"Failed to save config to Redis: {e}")
                raise e
        return current

    def reset_config(self):
        if self.redis_client:
            try:
                self.redis_client.delete(settings.REDIS_CONFIG_KEY)
            except Exception as e:
                logger.error(f"Failed to delete config from Redis: {e}")
        
        return self.get_config() # Returns defaults if Redis key missing

    def trigger_scan(self):
        if self.redis_client:
            try:
                self.redis_client.set(settings.REDIS_TRIGGER_KEY, '1')
                self.redis_client.expire(settings.REDIS_TRIGGER_KEY, 300)
                return True
            except Exception as e:
                logger.error(f"Failed to set trigger key: {e}")
                raise e
        return False

config_service = ConfigService()
