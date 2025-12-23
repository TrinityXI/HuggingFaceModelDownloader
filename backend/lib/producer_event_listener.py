#!/usr/bin/env python3
"""
Producer 事件监听器
监听 RabbitMQ 下载事件，更新 MySQL 队列状态并生成 dataset 记录

用法:
    python producer_event_listener.py
"""

import argparse
import os
import signal
import sys
import json
import time
from datetime import datetime
import pika

from mysql_queue import MySQLQueueManager
from dataset_db import DatasetDB


class ProducerEventListener:
    def __init__(self, config):
        self.config = config
        self.running = True
        
        # 初始化 MySQL 队列管理器
        mysql_config = {
            'host': config.get('mysql_host', 'localhost'),
            'port': config.get('mysql_port', 3306),
            'user': config.get('mysql_user', 'root'),
            'password': config.get('mysql_password', ''),
            'database': config.get('mysql_database', 'hf_datasets'),
            'charset': 'utf8mb4'
        }
        self.queue_manager = MySQLQueueManager(mysql_config)
        
        # 初始化 Dataset DB（SQLite，用于存储元数据）
        self.dataset_db = DatasetDB(config.get('db_path', 'datasets.db'))
        
        # RabbitMQ 配置
        self.rabbitmq_config = {
            'host': config.get('rabbitmq_host', 'localhost'),
            'port': config.get('rabbitmq_port', 5672),
            'user': config.get('rabbitmq_user', 'admin'),
            'password': config.get('rabbitmq_password', 'password123'),
            'vhost': config.get('rabbitmq_vhost', '/'),
            'event_exchange': config.get('rabbitmq_event_exchange', 'download_events'),
            'event_queue': config.get('rabbitmq_event_queue', 'producer_events')
        }
        
        self.rabbitmq_connection = None
        self.rabbitmq_channel = None
    
    def connect_rabbitmq(self):
        """连接到 RabbitMQ"""
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
            
            # 声明事件交换机
            self.rabbitmq_channel.exchange_declare(
                exchange=self.rabbitmq_config['event_exchange'],
                exchange_type='topic',
                durable=True
            )
            
            # 声明队列并绑定到交换机
            self.rabbitmq_channel.queue_declare(
                queue=self.rabbitmq_config['event_queue'],
                durable=True
            )
            
            # 绑定所有下载事件
            self.rabbitmq_channel.queue_bind(
                exchange=self.rabbitmq_config['event_exchange'],
                queue=self.rabbitmq_config['event_queue'],
                routing_key='download.*'
            )
            
            print(f"✓ 已连接到 RabbitMQ: {self.rabbitmq_config['host']}")
            print(f"✓ 监听队列: {self.rabbitmq_config['event_queue']}")
            print(f"✓ 绑定路由: download.*")
            
            return True
        except Exception as e:
            print(f"✗ 连接 RabbitMQ 失败: {e}")
            return False
    
    def disconnect_rabbitmq(self):
        """断开 RabbitMQ 连接"""
        if self.rabbitmq_connection and not self.rabbitmq_connection.is_closed:
            self.rabbitmq_connection.close()
    
    def handle_event(self, ch, method, properties, body):
        """
        处理下载事件
        
        Args:
            ch: Channel
            method: Method
            properties: Properties
            body: 消息体
        """
        try:
            event = json.loads(body)
            event_type = event.get('event_type')
            dataset_id = event.get('dataset_id')
            message = event.get('message', '')
            metadata = event.get('metadata', {})
            timestamp = event.get('timestamp')
            
            print(f"\n{'='*60}")
            print(f"收到事件: {event_type} - {dataset_id}")
            print(f"时间: {timestamp}")
            print(f"消息: {message}")
            print(f"{'='*60}")
            
            # 获取任务信息
            task = self.queue_manager.get_task_by_dataset_id(dataset_id)
            if not task:
                print(f"⚠️  未找到任务: {dataset_id}")
                ch.basic_ack(delivery_tag=method.delivery_tag)
                return
            
            # 根据事件类型处理
            if event_type == 'start':
                self._handle_start_event(task, dataset_id, message, metadata)
            elif event_type == 'complete':
                self._handle_complete_event(task, dataset_id, message, metadata)
            elif event_type == 'fail':
                self._handle_fail_event(task, dataset_id, message, metadata)
            elif event_type == 'retry':
                self._handle_retry_event(task, dataset_id, message, metadata)
            else:
                print(f"⚠️  未知事件类型: {event_type}")
            
            # 确认消息
            ch.basic_ack(delivery_tag=method.delivery_tag)
            
        except Exception as e:
            print(f"✗ 处理事件失败: {e}")
            import traceback
            traceback.print_exc()
            # 拒绝消息并重新入队
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
    
    def _handle_start_event(self, task, dataset_id, message, metadata):
        """处理下载开始事件"""
        print(f"→ 下载已开始: {dataset_id}")
        # MySQL 队列中的状态已由 consumer 更新为 'downloading'
        # 这里只需记录到事件日志
        self.queue_manager.log_event(dataset_id, 'start', message, metadata)
    
    def _handle_complete_event(self, task, dataset_id, message, metadata):
        """处理下载完成事件"""
        print(f"✓ 下载已完成: {dataset_id}")
        
        # 1. 更新 MySQL 队列状态（如果还没更新）
        if task['status'] != 'completed':
            self.queue_manager.update_status(task['id'], 'completed')
        
        # 2. 记录事件
        self.queue_manager.log_event(dataset_id, 'complete', message, metadata)
        
        # 3. 生成 dataset 记录到 SQLite
        self._create_dataset_record(dataset_id, metadata)
        
        print(f"✓ Dataset 记录已创建: {dataset_id}")
    
    def _handle_fail_event(self, task, dataset_id, message, metadata):
        """处理下载失败事件"""
        print(f"✗ 下载失败: {dataset_id}")
        
        # 更新状态（如果还没更新）
        if task['status'] != 'failed':
            self.queue_manager.update_status(task['id'], 'failed', message)
        
        # 记录事件
        self.queue_manager.log_event(dataset_id, 'fail', message, metadata)
    
    def _handle_retry_event(self, task, dataset_id, message, metadata):
        """处理重试事件"""
        retry_count = metadata.get('retry_count', 0)
        print(f"⟳ 将重试下载: {dataset_id} (第 {retry_count} 次)")
        
        # 记录事件
        self.queue_manager.log_event(dataset_id, 'retry', message, metadata)
    
    def _create_dataset_record(self, dataset_id, metadata):
        """
        创建 dataset 记录到 SQLite
        
        Args:
            dataset_id: 数据集 ID
            metadata: 元数据（可能包含下载时间、文件信息等）
        """
        try:
            # 构建 dataset 记录
            # 如果元数据中没有详细信息，只创建基本记录
            author, name = dataset_id.split('/', 1) if '/' in dataset_id else ('', dataset_id)
            
            dataset = {
                'id': dataset_id,
                'author': author,
                'name': name,
                'createdAt': metadata.get('created_at'),
                'lastModified': metadata.get('last_modified', datetime.now().isoformat()),
                'downloads': metadata.get('downloads', 0),
                'likes': metadata.get('likes', 0),
                'tags': metadata.get('tags', []),
            }
            
            # 插入或更新到 dataset_db
            self.dataset_db.upsert_dataset(dataset)
            
        except Exception as e:
            print(f"⚠️  创建 dataset 记录失败: {e}")
    
    def start_consuming(self):
        """开始消费事件"""
        print("="*60)
        print("Producer 事件监听器启动")
        print(f"MySQL: {self.config.get('mysql_host')}:{self.config.get('mysql_port')}")
        print(f"RabbitMQ: {self.rabbitmq_config['host']}:{self.rabbitmq_config['port']}")
        print(f"事件队列: {self.rabbitmq_config['event_queue']}")
        print("="*60)
        
        if not self.connect_rabbitmq():
            print("✗ 无法连接到 RabbitMQ，退出")
            return
        
        # 设置消费者
        self.rabbitmq_channel.basic_qos(prefetch_count=1)
        self.rabbitmq_channel.basic_consume(
            queue=self.rabbitmq_config['event_queue'],
            on_message_callback=self.handle_event,
            auto_ack=False
        )
        
        print("\n等待事件中... 按 Ctrl+C 停止\n")
        
        try:
            self.rabbitmq_channel.start_consuming()
        except KeyboardInterrupt:
            print("\n收到停止信号，正在退出...")
            self.rabbitmq_channel.stop_consuming()
        finally:
            self.disconnect_rabbitmq()
        
        print("事件监听器已停止")
    
    def run(self):
        """运行监听器"""
        # 注册信号处理
        def signal_handler(sig, frame):
            print("\n收到停止信号，正在安全退出...")
            self.running = False
            if self.rabbitmq_channel:
                self.rabbitmq_channel.stop_consuming()
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # 启动消费
        self.start_consuming()


def main():
    parser = argparse.ArgumentParser(description="Producer 事件监听器")
    
    # 数据库配置
    parser.add_argument("--db", default="datasets.db", help="SQLite 数据库路径（用于 dataset 元数据）")
    
    # MySQL 配置
    parser.add_argument("--mysql-host", default=None, help="MySQL主机")
    parser.add_argument("--mysql-port", type=int, default=3306, help="MySQL端口")
    parser.add_argument("--mysql-user", default=None, help="MySQL用户名")
    parser.add_argument("--mysql-password", default=None, help="MySQL密码")
    parser.add_argument("--mysql-database", default="hf_datasets", help="MySQL数据库名")
    
    # RabbitMQ 配置
    parser.add_argument("--rabbitmq-host", default=None, help="RabbitMQ主机")
    parser.add_argument("--rabbitmq-port", type=int, default=5672, help="RabbitMQ端口")
    parser.add_argument("--rabbitmq-user", default="admin", help="RabbitMQ用户名")
    parser.add_argument("--rabbitmq-password", default="password123", help="RabbitMQ密码")
    parser.add_argument("--rabbitmq-vhost", default="/", help="RabbitMQ虚拟主机")
    parser.add_argument("--rabbitmq-event-exchange", default="download_events", help="事件交换机名称")
    parser.add_argument("--rabbitmq-event-queue", default="producer_events", help="事件队列名称")
    
    args = parser.parse_args()
    
    config = {
        'db_path': args.db,
        
        # MySQL
        'mysql_host': args.mysql_host or os.getenv('MYSQL_HOST', 'localhost'),
        'mysql_port': args.mysql_port or int(os.getenv('MYSQL_PORT', 3306)),
        'mysql_user': args.mysql_user or os.getenv('MYSQL_USER', 'root'),
        'mysql_password': args.mysql_password or os.getenv('MYSQL_PASSWORD', ''),
        'mysql_database': args.mysql_database or os.getenv('MYSQL_DATABASE', 'hf_datasets'),
        
        # RabbitMQ
        'rabbitmq_host': args.rabbitmq_host or os.getenv('RABBITMQ_HOST', 'localhost'),
        'rabbitmq_port': args.rabbitmq_port or int(os.getenv('RABBITMQ_PORT', 5672)),
        'rabbitmq_user': args.rabbitmq_user or os.getenv('RABBITMQ_USER', 'admin'),
        'rabbitmq_password': args.rabbitmq_password or os.getenv('RABBITMQ_PASSWORD', 'password123'),
        'rabbitmq_vhost': args.rabbitmq_vhost or os.getenv('RABBITMQ_VHOST', '/'),
        'rabbitmq_event_exchange': args.rabbitmq_event_exchange or os.getenv('RABBITMQ_EVENT_EXCHANGE', 'download_events'),
        'rabbitmq_event_queue': args.rabbitmq_event_queue or os.getenv('RABBITMQ_EVENT_QUEUE', 'producer_events')
    }
    
    listener = ProducerEventListener(config)
    listener.run()


if __name__ == "__main__":
    main()
