#!/usr/bin/env python3
"""
Producer Main Service
Supports RabbitMQ and HTTP API
"""

import time
import logging
import os
import sys
from threading import Thread

# Ensure backend root is in path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.main import app
from app.core.config import settings
from app.services.rabbitmq import rabbitmq_service
from app.services.scanner import scanner_service
from app.services.config import config_service

# Configure Logging
handlers = [logging.StreamHandler(sys.stdout)]
try:
    log_dir = settings.LOG_DIR
    if os.path.exists(log_dir) and os.access(log_dir, os.W_OK):
        handlers.append(logging.FileHandler(os.path.join(log_dir, 'producer.log')))
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=handlers,
    force=True
)
logger = logging.getLogger(__name__)

class ProducerService:
    def __init__(self):
        self.interval = settings.DEFAULT_PRODUCER_INTERVAL

    def _check_trigger_scan(self):
        if config_service.redis_client:
            try:
                trigger = config_service.redis_client.get(settings.REDIS_TRIGGER_KEY)
                if trigger:
                    config_service.redis_client.delete(settings.REDIS_TRIGGER_KEY)
                    logger.info("Manual scan triggered")
                    return True
            except Exception as e:
                logger.warning(f"Check trigger failed: {e}")
        return False

    def run_scan_loop(self):
        logger.info(f"Starting scan loop, interval: {self.interval}s")
        last_scan_time = 0

        while True:
            try:
                current_time = time.time()
                
                # Update config from Redis
                config = config_service.get_config()
                scanner_service.update_config(config)
                self.interval = config.get('producer_interval', 3600)

                # Periodic Scan
                if current_time - last_scan_time >= self.interval:
                    scanner_service.scan_and_enqueue()
                    last_scan_time = current_time
                    logger.info(f"Scan complete, next in {self.interval}s")
                
                # Manual Trigger
                elif self._check_trigger_scan():
                    logger.info("Manual scan triggering...")
                    scanner_service.scan_and_enqueue()
                    last_scan_time = current_time

                # RabbitMQ Dispatch
                if rabbitmq_service.connection:
                     rabbitmq_service.dispatch_tasks()

                time.sleep(5)

            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Scan loop error: {e}")
                time.sleep(60)

    def run(self):
        # Connect RabbitMQ
        rabbitmq_connected = rabbitmq_service.connect()
        if rabbitmq_connected:
            rabbitmq_service.start_event_listener()
            logger.info("RabbitMQ Mode Started")
        else:
            logger.warning("RabbitMQ connection failed, running in HTTP/DB only mode")

        # Start Scan Thread
        scan_thread = Thread(target=self.run_scan_loop, daemon=True)
        scan_thread.start()

        # Run Flask App
        logger.info(f"Starting HTTP API on {settings.HOST}:{settings.PORT}")
        try:
            app.run(host=settings.HOST, port=settings.PORT, debug=False, threaded=True)
        except KeyboardInterrupt:
            logger.info("Stopping...")
        finally:
            if rabbitmq_connected:
                rabbitmq_service.disconnect()

def main():
    service = ProducerService()
    service.run()

if __name__ == '__main__':
    main()