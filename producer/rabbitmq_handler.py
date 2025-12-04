#!/usr/bin/env python3
"""
Producer RabbitMQ Handler
负责 RabbitMQ 相关的消息发送和事件处理
"""

import json
import time
import logging
import os
from datetime import datetime
from threading import Thread
import pika

logger = logging.getLogger(__name__)


class RabbitMQHandler:
    """RabbitMQ 消息处理器"""

    def __init__(self, producer_core):
        self.producer_core = producer_core

        # RabbitMQ 配置
        self.rabbitmq_host = os.getenv('RABBITMQ_HOST', 'localhost')
        self.rabbitmq_port = int(os.getenv('RABBITMQ_PORT', 5672))
        self.rabbitmq_user = os.getenv('RABBITMQ_USER', 'admin')
        self.rabbitmq_password = os.getenv('RABBITMQ_PASSWORD', 'password123')
        self.rabbitmq_vhost = os.getenv('RABBITMQ_VHOST', '/')
        self.queue_name = os.getenv('RABBITMQ_QUEUE_NAME', 'hf_download_queue')
        self.dlq_name = os.getenv('RABBITMQ_DLQ_NAME', 'hf_download_dlq')

        # 事件配置
        self.event_exchange = os.getenv('RABBITMQ_EVENT_EXCHANGE', 'download_events')
        self.event_queue = os.getenv('RABBITMQ_EVENT_QUEUE', 'producer_events')

        # 连接
        self.connection = None
        self.channel = None
        self.event_connection = None
        self.event_channel = None

    def connect(self):
        """连接到 RabbitMQ"""
        try:
            credentials = pika.PlainCredentials(self.rabbitmq_user, self.rabbitmq_password)
            parameters = pika.ConnectionParameters(
                host=self.rabbitmq_host,
                port=self.rabbitmq_port,
                virtual_host=self.rabbitmq_vhost,
                credentials=credentials,
                heartbeat=600,
                blocked_connection_timeout=300
            )

            self.connection = pika.BlockingConnection(parameters)
            self.channel = self.connection.channel()

            # 设置 QoS
            self.channel.basic_qos(prefetch_count=2)

            # 声明队列
            self.channel.queue_declare(
                queue=self.queue_name,
                durable=True,
                arguments={
                    'x-dead-letter-exchange': '',
                    'x-dead-letter-routing-key': self.dlq_name
                }
            )

            self.channel.queue_declare(
                queue=self.dlq_name,
                durable=True
            )

            # 声明事件交换机
            self.channel.exchange_declare(
                exchange=self.event_exchange,
                exchange_type='topic',
                durable=True
            )

            self.channel.queue_declare(
                queue=self.event_queue,
                durable=True
            )

            # 绑定事件
            self.channel.queue_bind(
                exchange=self.event_exchange,
                queue=self.event_queue,
                routing_key='download.*'
            )

            logger.info(f"成功连接到 RabbitMQ: {self.rabbitmq_host}:{self.rabbitmq_port}")
            return True

        except Exception as e:
            logger.error(f"连接 RabbitMQ 失败: {e}")
            return False

    def disconnect(self):
        """断开 RabbitMQ 连接"""
        try:
            if self.connection and not self.connection.is_closed:
                self.connection.close()
                logger.info("RabbitMQ 连接已关闭")
        except Exception as e:
            logger.error(f"关闭 RabbitMQ 连接时出错: {e}")

    def send_message(self, message):
        """发送消息到队列"""
        try:
            if not self.channel or self.channel.is_closed:
                if not self.connect():
                    return False

            self.channel.basic_publish(
                exchange='',
                routing_key=self.queue_name,
                body=json.dumps(message),
                properties=pika.BasicProperties(
                    delivery_mode=2,
                    content_type='application/json',
                    timestamp=int(time.time())
                )
            )

            logger.info(f"消息已发送: {message.get('dataset_id', 'Unknown')}")
            return True

        except Exception as e:
            logger.error(f"发送消息失败: {e}")
            return False

    def dispatch_tasks(self):
        """调度任务：从 MySQL 取出任务发送到 RabbitMQ"""
        try:
            if not self.channel or self.channel.is_closed:
                if not self.connect():
                    return

            # 获取队列状态
            try:
                queue_state = self.channel.queue_declare(
                    queue=self.queue_name,
                    passive=True
                )
                message_count = queue_state.method.message_count
                consumer_count = queue_state.method.consumer_count
            except Exception as e:
                logger.warning(f"获取队列状态失败: {e}")
                return

            if consumer_count == 0:
                return

            # 计算需要补充的任务数
            prefetch_count = 2
            target_depth = consumer_count * prefetch_count
            needed = target_depth - message_count

            if needed <= 0:
                return

            # 限制单次调度数量
            batch_size = min(needed, 10)

            # 从 MySQL 获取任务
            tasks = self.producer_core.queue_manager.fetch_tasks_batch(limit=batch_size)

            if not tasks:
                return

            logger.info(f"调度任务: 队列消息={message_count}, 消费者={consumer_count}, 需补充={needed}, 本次获取={len(tasks)}")

            # 发送到 RabbitMQ
            sent_count = 0
            for task in tasks:
                dataset_info = {
                    'dataset_id': task['dataset_id'],
                    'storage_path': task.get('storage_path', ''),
                    'priority': task['priority'],
                    'retry_count': task['retry_count']
                }

                if self.send_message(dataset_info):
                    sent_count += 1
                else:
                    # 发送失败，回滚状态
                    self.producer_core.queue_manager.update_status(task['id'], 'pending')
                    logger.error(f"发送消息失败，回滚状态: {task['dataset_id']}")

            logger.info(f"成功调度 {sent_count}/{len(tasks)} 个任务")

        except Exception as e:
            logger.error(f"调度任务出错: {e}")

    def handle_download_event(self, ch, method, properties, body):
        """处理来自 consumer 的下载事件"""
        try:
            event = json.loads(body)
            event_type = event.get('event_type')
            dataset_id = event.get('dataset_id')
            message = event.get('message', '')
            metadata = event.get('metadata', {})

            logger.info(f"收到事件: {event_type} - {dataset_id}")

            task = self.producer_core.queue_manager.get_task_by_dataset_id(dataset_id)
            if not task:
                logger.debug(f"跳过事件（任务不在队列中）: {dataset_id}")
                ch.basic_ack(delivery_tag=method.delivery_tag)
                return

            # 根据事件类型处理
            if event_type == 'start':
                self.producer_core.queue_manager.update_status(task['id'], 'downloading')
                self.producer_core.queue_manager.log_event(dataset_id, 'start', message, metadata)
                logger.info(f"→ 已更新状态为 downloading: {dataset_id}")

            elif event_type == 'complete':
                storage_path = metadata.get('storage_path', '')
                self.producer_core.queue_manager.update_status(task['id'], 'completed', storage_path=storage_path)
                self.producer_core.queue_manager.log_event(dataset_id, 'complete', message, metadata)
                self._create_dataset_record(dataset_id, metadata)
                logger.info(f"✓ 已更新状态为 completed: {dataset_id}")

            elif event_type == 'fail':
                self.producer_core.queue_manager.update_status(task['id'], 'failed', message)
                self.producer_core.queue_manager.log_event(dataset_id, 'fail', message, metadata)
                logger.error(f"✗ 已更新状态为 failed: {dataset_id}")

            elif event_type == 'retry':
                retry_count = metadata.get('retry_count', 0)
                self.producer_core.queue_manager.increment_retry(task['id'], 10, message)
                self.producer_core.queue_manager.log_event(dataset_id, 'retry', message, metadata)
                logger.warning(f"⟳ 已标记重试: {dataset_id} (第{retry_count}次)")

            ch.basic_ack(delivery_tag=method.delivery_tag)

        except Exception as e:
            logger.error(f"处理事件失败: {e}")
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    def _create_dataset_record(self, dataset_id, metadata):
        """创建 dataset 记录"""
        try:
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

            if self.producer_core.dataset_db:
                try:
                    self.producer_core.dataset_db.upsert_dataset(dataset)
                    logger.info(f"✓ Dataset 记录已创建: {dataset_id}")
                except Exception as e:
                    logger.warning(f"保存元数据失败: {e}")

        except Exception as e:
            logger.error(f"创建 dataset 记录失败: {e}")

    def start_event_listener(self):
        """启动事件监听器"""
        def listener_thread():
            try:
                credentials = pika.PlainCredentials(self.rabbitmq_user, self.rabbitmq_password)
                parameters = pika.ConnectionParameters(
                    host=self.rabbitmq_host,
                    port=self.rabbitmq_port,
                    virtual_host=self.rabbitmq_vhost,
                    credentials=credentials,
                    heartbeat=600,
                    blocked_connection_timeout=300
                )

                self.event_connection = pika.BlockingConnection(parameters)
                self.event_channel = self.event_connection.channel()

                self.event_channel.queue_declare(
                    queue=self.event_queue,
                    durable=True
                )

                self.event_channel.basic_qos(prefetch_count=1)
                self.event_channel.basic_consume(
                    queue=self.event_queue,
                    on_message_callback=self.handle_download_event,
                    auto_ack=False
                )

                logger.info(f"事件监听器已启动，监听队列: {self.event_queue}")
                self.event_channel.start_consuming()

            except KeyboardInterrupt:
                logger.info("事件监听器收到停止信号")
                if self.event_channel:
                    self.event_channel.stop_consuming()
            except Exception as e:
                logger.error(f"事件监听器异常: {e}")
            finally:
                if self.event_connection and not self.event_connection.is_closed:
                    try:
                        self.event_connection.close()
                        logger.info("事件监听器连接已关闭")
                    except:
                        pass

        listener = Thread(target=listener_thread, daemon=True)
        listener.start()
        logger.info("事件监听器线程已启动")
        return listener
