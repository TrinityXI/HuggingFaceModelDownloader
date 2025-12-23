#!/usr/bin/env python3
"""
Producer 主服务
同时支持 RabbitMQ 和 HTTP API
"""

import json
import time
import logging
import os
import sys
from threading import Thread
import redis

# 导入模块
from core import ProducerCore
from http_api import create_http_api
from rabbitmq_handler import RabbitMQHandler

# 配置日志
handlers = [logging.StreamHandler(sys.stdout)]

try:
    log_dir = '/app/logs'
    if os.path.exists(log_dir) and os.access(log_dir, os.W_OK):
        handlers.append(logging.FileHandler('/app/logs/producer.log'))
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=handlers,
    force=True
)
logger = logging.getLogger(__name__)

logger.info("="*60)
logger.info("Producer 启动中...")
logger.info("="*60)


class Producer:
    """Producer 主服务"""

    def __init__(self):
        # 核心业务逻辑
        self.core = ProducerCore()

        # RabbitMQ 处理器
        self.rabbitmq_handler = RabbitMQHandler(self.core)

        # Redis 配置（用于动态配置）
        self.redis_host = os.getenv('REDIS_HOST', 'localhost')
        self.redis_port = int(os.getenv('REDIS_PORT', 6379))
        self.redis_db = int(os.getenv('REDIS_DB', 0))
        self.redis_password = os.getenv('REDIS_PASSWORD', None)
        self.redis_config_key = os.getenv('REDIS_CONFIG_KEY', 'hf_producer_config')
        self.redis_trigger_key = 'hf_producer_trigger_scan'

        # 初始化 Redis
        self.redis_client = None
        self._init_redis()

        # 从 Redis 加载配置
        self._load_config_from_redis()

        logger.info("Producer 初始化完成")

    def _init_redis(self):
        """初始化 Redis 连接"""
        try:
            self.redis_client = redis.Redis(
                host=self.redis_host,
                port=self.redis_port,
                db=self.redis_db,
                password=self.redis_password,
                decode_responses=True
            )
            self.redis_client.ping()
            self.core.set_redis_client(self.redis_client, self.redis_config_key, self.redis_trigger_key)
            logger.info(f"成功连接到 Redis: {self.redis_host}:{self.redis_port}")
        except Exception as e:
            logger.warning(f"无法连接到 Redis: {e}")
            self.redis_client = None

    def _load_config_from_redis(self):
        """从 Redis 加载配置"""
        if self.redis_client:
            try:
                config_str = self.redis_client.get(self.redis_config_key)
                if config_str:
                    config = json.loads(config_str)
                    self.core.update_config(config)
                    logger.info(f"从 Redis 加载配置成功")
                    return
            except Exception as e:
                logger.warning(f"从 Redis 加载配置失败: {e}")

        # 保存默认配置到 Redis
        self._save_config_to_redis()

    def _save_config_to_redis(self):
        """保存当前配置到 Redis"""
        if self.redis_client:
            try:
                config = self.core.get_config()
                self.redis_client.set(self.redis_config_key, json.dumps(config))
            except Exception as e:
                logger.error(f"保存配置到 Redis 失败: {e}")

    def _check_trigger_scan(self):
        """检查是否有手动触发扫描的请求"""
        if self.redis_client:
            try:
                trigger = self.redis_client.get(self.redis_trigger_key)
                if trigger:
                    self.redis_client.delete(self.redis_trigger_key)
                    logger.info("检测到手动触发扫描请求")
                    return True
            except Exception as e:
                logger.warning(f"检查触发扫描标志失败: {e}")
        return False

    def run_scan_loop(self):
        """扫描循环（RabbitMQ 模式）"""
        logger.info(f"启动扫描循环，间隔: {self.core.producer_interval} 秒")
        last_scan_time = 0

        while True:
            try:
                current_time = time.time()

                # 定期扫描
                if current_time - last_scan_time >= self.core.producer_interval:
                    # 重新加载配置
                    self._load_config_from_redis()

                    # 执行扫描
                    self.core.scan_and_enqueue()
                    last_scan_time = current_time
                    logger.info(f"扫描完成，下次扫描在 {self.core.producer_interval} 秒后")

                # 检查手动触发
                elif self._check_trigger_scan():
                    logger.info("手动触发扫描...")
                    self.core.scan_and_enqueue()
                    last_scan_time = current_time

                # 调度任务（RabbitMQ）
                self.rabbitmq_handler.dispatch_tasks()

                # 短暂休眠
                time.sleep(5)

            except KeyboardInterrupt:
                logger.info("收到中断信号")
                break
            except Exception as e:
                logger.error(f"扫描循环出错: {e}")
                time.sleep(60)

    def run_http_only_scan_loop(self):
        """扫描循环（HTTP 模式 - 不调度到 RabbitMQ）"""
        logger.info(f"启动 HTTP 扫描循环，间隔: {self.core.producer_interval} 秒")
        last_scan_time = 0

        while True:
            try:
                current_time = time.time()

                # 定期扫描
                if current_time - last_scan_time >= self.core.producer_interval:
                    self._load_config_from_redis()
                    self.core.scan_and_enqueue()
                    last_scan_time = current_time
                    logger.info(f"扫描完成，下次扫描在 {self.core.producer_interval} 秒后")

                # 检查手动触发
                elif self._check_trigger_scan():
                    logger.info("手动触发扫描...")
                    self.core.scan_and_enqueue()
                    last_scan_time = current_time

                time.sleep(10)

            except KeyboardInterrupt:
                logger.info("收到中断信号")
                break
            except Exception as e:
                logger.error(f"扫描循环出错: {e}")
                time.sleep(60)

    def run(self):
        """运行 Producer（同时支持 RabbitMQ 和 HTTP API）"""
        # 连接 RabbitMQ
        rabbitmq_connected = self.rabbitmq_handler.connect()
        if rabbitmq_connected:
            # 启动事件监听器
            self.rabbitmq_handler.start_event_listener()

            # 启动 RabbitMQ 扫描和调度线程
            rabbitmq_thread = Thread(target=self.run_scan_loop, daemon=True)
            rabbitmq_thread.start()
            logger.info("RabbitMQ 模式已启动")
        else:
            logger.warning("RabbitMQ 连接失败，将只运行 HTTP API 模式")
            # 启动 HTTP 扫描线程（不包含 RabbitMQ 调度）
            scan_thread = Thread(target=self.run_http_only_scan_loop, daemon=True)
            scan_thread.start()

        # 启动 HTTP API 服务器（主线程）
        host = os.getenv('PRODUCER_HOST', '0.0.0.0')
        port = int(os.getenv('PRODUCER_PORT', 8000))
        logger.info(f"启动 HTTP API 服务: {host}:{port}")

        app = create_http_api(self.core)
        try:
            app.run(host=host, port=port, debug=False, threaded=True)
        except KeyboardInterrupt:
            logger.info("收到中断信号")
        finally:
            if rabbitmq_connected:
                self.rabbitmq_handler.disconnect()


def main():
    """主函数"""
    producer = Producer()
    try:
        producer.run()
    except KeyboardInterrupt:
        logger.info("程序被用户中断")
    except Exception as e:
        logger.error(f"程序异常: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
