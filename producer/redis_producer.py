#!/usr/bin/env python3
"""
Redis 生产者：将数据集发现任务推送到 Redis 队列

支持分布式部署，多个生产者可以同时工作。

用法：
    python redis_producer.py                    # 使用默认配置
    python redis_producer.py --interval 3600    # 每 1 小时运行一次
    python redis_producer.py --once             # 只运行一次后退出
"""

import argparse
import json
import os
import signal
import sys
import time
import uuid
from datetime import datetime, timedelta

try:
    import redis
except ImportError:
    print("请安装 redis 库: pip install redis")
    sys.exit(1)

# 导入现有的生产者逻辑
sys.path.append('..')
from Data-discover.producer_lite import LightweightProducer


class RedisProducer:
    def __init__(self, config):
        self.config = config
        self.running = True

        # 初始化 Redis 连接
        self.redis_client = redis.Redis(
            host=config['redis_host'],
            port=config['redis_port'],
            db=config['redis_db'],
            password=config.get('redis_password'),
            decode_responses=True
        )

        self.queue_name = config['queue_name']

        # 初始化原有的生产者
        self.producer = LightweightProducer(
            db_path=config.get('db_path', 'datasets.db'),  # 可选，用于元数据存储
            endpoint=config['endpoint'],
            token=config.get('token')
        )

        print(f"Redis 生产者初始化完成")
        print(f"Redis: {config['redis_host']}:{config['redis_port']}")
        print(f"队列: {self.queue_name}")

    def signal_handler(self, sig, frame):
        """处理停止信号"""
        print("\n收到停止信号，正在安全退出...")
        self.running = False

    def push_task(self, dataset_id, priority=0):
        """推送单个任务到 Redis 队列"""
        task = {
            'id': str(uuid.uuid4()),
            'dataset_id': dataset_id,
            'priority': priority,
            'created_at': datetime.now().isoformat(),
            'retry_count': 0,
            'producer_id': self.config.get('producer_id', 'default')
        }

        try:
            # 使用 LPUSH 添加任务到队列头部
            # 如果需要优先级队列，可以使用有序集合 (ZSET)
            self.redis_client.lpush(self.queue_name, json.dumps(task))

            print(f"📤 推送任务: {dataset_id} (优先级: {priority})")
            return task['id']

        except redis.exceptions.ConnectionError:
            print(f"❌ Redis 连接失败，无法推送任务: {dataset_id}")
            return None
        except Exception as e:
            print(f"❌ 推送任务失败: {dataset_id}, 错误: {e}")
            return None

    def scan_and_queue_datasets(self):
        """扫描数据集并添加到队列"""
        print(f"\n{'='*60}")
        print(f"开始扫描任务 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}")

        try:
            # 使用原有的扫描逻辑
            datasets = self.producer.scan_datasets(
                days=self.config['days'],
                limit_per_day=self.config['limit'],
                min_downloads=self.config.get('min_downloads', 0),
                min_likes=self.config.get('min_likes', 0)
            )

            print(f"发现 {len(datasets)} 个数据集")

            # 推送任务到 Redis 队列
            queued_count = 0
            for dataset in datasets:
                # 计算优先级（基于下载量和点赞数）
                priority = self._calculate_priority(dataset)

                task_id = self.push_task(dataset['id'], priority)
                if task_id:
                    queued_count += 1

            print(f"成功推送 {queued_count}/{len(datasets)} 个任务到队列")

            # 输出队列统计
            queue_length = self.redis_client.llen(self.queue_name)
            print(f"当前队列长度: {queue_length}")

            return queued_count

        except Exception as e:
            print(f"扫描失败: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            return 0

    def _calculate_priority(self, dataset):
        """计算任务优先级"""
        priority = 0

        # 基于下载量
        downloads = dataset.get('downloads', 0)
        if downloads > 10000:
            priority += 3
        elif downloads > 1000:
            priority += 2
        elif downloads > 100:
            priority += 1

        # 基于点赞数
        likes = dataset.get('likes', 0)
        if likes > 1000:
            priority += 2
        elif likes > 100:
            priority += 1

        # 基于更新时间（越新优先级越高）
        last_modified = dataset.get('lastModified')
        if last_modified:
            try:
                # 假设 lastModified 是 ISO 格式字符串
                modified_date = datetime.fromisoformat(last_modified.replace('Z', '+00:00'))
                days_ago = (datetime.now().replace(tzinfo=modified_date.tzinfo) - modified_date).days

                if days_ago <= 7:  # 一周内
                    priority += 2
                elif days_ago <= 30:  # 一月内
                    priority += 1
            except:
                pass

        return priority

    def run_once(self):
        """执行一次扫描"""
        return self.scan_and_queue_datasets()

    def run(self):
        """运行生产者服务（持续运行）"""
        # 注册信号处理
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

        interval = self.config.get('interval', 3600)  # 默认 1 小时

        print("="*60)
        print("Redis 生产者服务启动")
        print(f"Redis: {self.config['redis_host']}:{self.config['redis_port']}")
        print(f"队列: {self.queue_name}")
        print(f"扫描间隔: {interval} 秒 ({interval/3600:.1f} 小时)")
        print(f"每次扫描: 最近 {self.config['days']} 天，每天最多 {self.config['limit']} 个")
        print("="*60)

        # 立即执行一次
        self.run_once()

        # 循环执行
        while self.running:
            try:
                # 等待指定间隔
                print(f"\n等待 {interval} 秒后执行下次扫描...")
                print(f"下次扫描时间: {(datetime.now().timestamp() + interval):.0f}")

                # 分段等待，以便响应停止信号
                waited = 0
                while waited < interval and self.running:
                    time.sleep(min(10, interval - waited))  # 每 10 秒检查一次
                    waited += 10

                if self.running:
                    self.run_once()

            except KeyboardInterrupt:
                self.running = False
                break

        print("\nRedis 生产者服务已停止")


def main():
    parser = argparse.ArgumentParser(description="Redis 生产者服务")
    parser.add_argument("--redis-host", default="localhost", help="Redis 主机")
    parser.add_argument("--redis-port", type=int, default=6379, help="Redis 端口")
    parser.add_argument("--redis-db", type=int, default=0, help="Redis 数据库")
    parser.add_argument("--redis-password", help="Redis 密码")
    parser.add_argument("--queue-name", default="hf_download_queue", help="任务队列名称")
    parser.add_argument("--db", default="datasets.db", help="SQLite 数据库路径（用于元数据）")
    parser.add_argument("--endpoint", default="https://hf-mirror.com", help="HF API 端点")
    parser.add_argument("--token", help="HF Token")
    parser.add_argument("--days", type=int, default=7, help="扫描最近多少天的数据")
    parser.add_argument("--limit", type=int, default=50, help="每天最多扫描多少个数据集")
    parser.add_argument("--min-downloads", type=int, default=0, help="最小下载量过滤")
    parser.add_argument("--min-likes", type=int, default=0, help="最小点赞数过滤")
    parser.add_argument("--interval", type=int, default=3600, help="扫描间隔（秒）")
    parser.add_argument("--once", action="store_true", help="只运行一次后退出")
    parser.add_argument("--producer-id", default="default", help="生产者标识")

    args = parser.parse_args()

    config = {
        'redis_host': args.redis_host,
        'redis_port': args.redis_port,
        'redis_db': args.redis_db,
        'redis_password': args.redis_password,
        'queue_name': args.queue_name,
        'db_path': args.db,
        'endpoint': args.endpoint,
        'token': args.token,
        'days': args.days,
        'limit': args.limit,
        'min_downloads': args.min_downloads,
        'min_likes': args.min_likes,
        'interval': args.interval,
        'producer_id': args.producer_id
    }

    producer = RedisProducer(config)

    if args.once:
        producer.run_once()
    else:
        producer.run()


if __name__ == "__main__":
    main()