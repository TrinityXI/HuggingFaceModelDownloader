#!/usr/bin/env python3
"""
轻量级生产者：扫描 HF 数据集并添加到下载队列

用法:
    python producer_lite.py                    # 使用默认配置
    python producer_lite.py --days 7           # 扫描最近 7 天
    python producer_lite.py --limit 1000       # 每天最多 1000 个
"""

import argparse
import os
import sys
import json
from datetime import datetime, timedelta
from pathlib import Path
import pika

# 导入现有模块
from query_datasets_by_date import HuggingFaceDatasetQuery
from dataset_db import DatasetDB
from mysql_queue import MySQLQueueManager


class LightweightProducer:
    def __init__(self, db_path="datasets.db", endpoint="https://huggingface.co", token=None, 
                 mysql_config=None, rabbitmq_config=None):
        self.db_path = db_path
        self.db = DatasetDB(db_path)  # 仍然使用SQLite存储dataset元数据
        self.query = HuggingFaceDatasetQuery(endpoint=endpoint, token=token)
        
        # 使用MySQL管理下载队列
        self.queue_manager = MySQLQueueManager(mysql_config)
        
        # RabbitMQ配置（可选，用于发送任务到消费者）
        self.rabbitmq_config = rabbitmq_config or {
            'host': os.getenv('RABBITMQ_HOST', 'localhost'),
            'port': int(os.getenv('RABBITMQ_PORT', 5672)),
            'user': os.getenv('RABBITMQ_USER', 'admin'),
            'password': os.getenv('RABBITMQ_PASSWORD', 'password123'),
            'vhost': os.getenv('RABBITMQ_VHOST', '/'),
            'queue_name': os.getenv('RABBITMQ_QUEUE_NAME', 'hf_download_queue')
        }
        self.rabbitmq_enabled = rabbitmq_config is not None or os.getenv('RABBITMQ_HOST')
        self.rabbitmq_connection = None
        self.rabbitmq_channel = None

    def _connect_rabbitmq(self):
        """连接到RabbitMQ"""
        if not self.rabbitmq_enabled:
            return False
        
        try:
            credentials = pika.PlainCredentials(
                self.rabbitmq_config['user'], 
                self.rabbitmq_config['password']
            )
            parameters = pika.ConnectionParameters(
                host=self.rabbitmq_config['host'],
                port=self.rabbitmq_config['port'],
                virtual_host=self.rabbitmq_config['vhost'],
                credentials=credentials,
                heartbeat=600,
                blocked_connection_timeout=300
            )
            
            self.rabbitmq_connection = pika.BlockingConnection(parameters)
            self.rabbitmq_channel = self.rabbitmq_connection.channel()
            
            # 声明队列
            self.rabbitmq_channel.queue_declare(
                queue=self.rabbitmq_config['queue_name'],
                durable=True
            )
            
            print(f"已连接到 RabbitMQ: {self.rabbitmq_config['host']}")
            return True
        except Exception as e:
            print(f"连接 RabbitMQ 失败: {e}")
            self.rabbitmq_enabled = False
            return False
    
    def _disconnect_rabbitmq(self):
        """断开RabbitMQ连接"""
        if self.rabbitmq_connection and not self.rabbitmq_connection.is_closed:
            self.rabbitmq_connection.close()
    
    def _publish_task(self, dataset_id: str, priority: int):
        """发布任务到RabbitMQ队列"""
        if not self.rabbitmq_enabled:
            return
        
        if not self.rabbitmq_connection or self.rabbitmq_connection.is_closed:
            if not self._connect_rabbitmq():
                return
        
        try:
            message = {
                'dataset_id': dataset_id,
                'priority': priority,
                'created_at': datetime.now().isoformat()
            }
            
            self.rabbitmq_channel.basic_publish(
                exchange='',
                routing_key=self.rabbitmq_config['queue_name'],
                body=json.dumps(message),
                properties=pika.BasicProperties(
                    delivery_mode=2,  # 持久化消息
                    priority=min(priority, 10)  # RabbitMQ优先级范围0-10
                )
            )
        except Exception as e:
            print(f"发布任务到 RabbitMQ 失败: {e}")

    def scan_and_queue(self, days=7, limit_per_day=1000, min_downloads=0, min_likes=0):
        """扫描最近 N 天的数据集并加入队列"""
        print(f"开始扫描最近 {days} 天的数据集...")

        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        total_scanned = 0
        total_queued = 0
        total_skipped = 0

        # 逐天扫描
        current = start_date
        while current <= end_date:
            date_str = current.strftime("%Y-%m-%d")
            print(f"\n扫描日期: {date_str}")

            try:
                datasets = self.query.get_datasets_by_date(
                    target_date=date_str,
                    limit=limit_per_day,
                    use_created_at=True,
                    auto_limit=False
                )

                print(f"  找到 {len(datasets)} 个数据集")

                for ds in datasets:
                    total_scanned += 1

                    # 过滤条件
                    if ds.get('downloads', 0) < min_downloads:
                        continue
                    if ds.get('likes', 0) < min_likes:
                        continue

                    # 添加到队列
                    if self._add_to_queue(ds):
                        total_queued += 1
                    else:
                        total_skipped += 1

                print(f"  本日新增: {total_queued - (total_scanned - len(datasets))}")

            except Exception as e:
                print(f"  错误: {e}")

            current += timedelta(days=1)

        print(f"\n" + "="*60)
        print(f"扫描完成！")
        print(f"总扫描: {total_scanned}")
        print(f"新增队列: {total_queued}")
        print(f"已存在/跳过: {total_skipped}")
        print("="*60)

    def _add_to_queue(self, dataset):
        """添加数据集到下载队列"""
        dataset_id = dataset.get('id')
        if not dataset_id:
            return False

        # 计算优先级
        priority = self._calculate_priority(dataset)

        # 添加到MySQL队列
        added = self.queue_manager.add_to_queue(dataset_id, priority)
        
        if added:
            # 如果启用了RabbitMQ，发布任务
            self._publish_task(dataset_id, priority)
        
        return added

    def _calculate_priority(self, dataset):
        """计算优先级（简单算法）"""
        downloads = dataset.get('downloads', 0)
        likes = dataset.get('likes', 0)

        # 优先级 = 下载数/1000 + 点赞数
        score = int(downloads / 1000) + likes
        return min(score, 9999)  # 限制最大值


def main():
    parser = argparse.ArgumentParser(description="轻量级数据集队列生产者")
    parser.add_argument("--db", default="datasets.db", help="SQLite数据库路径（用于dataset元数据）")
    parser.add_argument("--days", type=int, default=7, help="扫描最近 N 天")
    parser.add_argument("--limit", type=int, default=1000, help="每天最多查询 N 个")
    parser.add_argument("--min-downloads", type=int, default=0, help="最小下载量过滤")
    parser.add_argument("--min-likes", type=int, default=0, help="最小点赞数过滤")
    parser.add_argument("--endpoint", default="https://huggingface.co", help="HF API 端点")
    parser.add_argument("--token", help="HF Token（或使用 HF_TOKEN 环境变量）")
    parser.add_argument("--mysql-host", default=None, help="MySQL主机（默认从环境变量读取）")
    parser.add_argument("--mysql-port", type=int, default=3306, help="MySQL端口")
    parser.add_argument("--mysql-user", default=None, help="MySQL用户名")
    parser.add_argument("--mysql-password", default=None, help="MySQL密码")
    parser.add_argument("--mysql-database", default="hf_datasets", help="MySQL数据库名")
    parser.add_argument("--enable-rabbitmq", action="store_true", help="启用RabbitMQ任务发布")

    args = parser.parse_args()

    token = args.token or os.getenv("HF_TOKEN")
    
    # MySQL配置
    mysql_config = None
    if args.mysql_host or os.getenv('MYSQL_HOST'):
        mysql_config = {
            'host': args.mysql_host or os.getenv('MYSQL_HOST', 'localhost'),
            'port': args.mysql_port or int(os.getenv('MYSQL_PORT', 3306)),
            'user': args.mysql_user or os.getenv('MYSQL_USER', 'root'),
            'password': args.mysql_password or os.getenv('MYSQL_PASSWORD', ''),
            'database': args.mysql_database or os.getenv('MYSQL_DATABASE', 'hf_datasets'),
            'charset': 'utf8mb4'
        }
    
    # RabbitMQ配置（如果启用）
    rabbitmq_config = {} if args.enable_rabbitmq else None

    producer = LightweightProducer(
        db_path=args.db,
        endpoint=args.endpoint,
        token=token,
        mysql_config=mysql_config,
        rabbitmq_config=rabbitmq_config
    )
    
    try:
        producer.scan_and_queue(
            days=args.days,
            limit_per_day=args.limit,
            min_downloads=args.min_downloads,
            min_likes=args.min_likes
        )
    finally:
        producer._disconnect_rabbitmq()


if __name__ == "__main__":
    main()

