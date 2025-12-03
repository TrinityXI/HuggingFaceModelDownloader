#!/usr/bin/env python3
"""
RabbitMQ 生产者服务
定期扫描 Hugging Face 数据集并发送到 RabbitMQ 队列
使用 query_datasets_by_date.py 中的高级查询功能
支持从 Redis 动态读取配置参数
"""

import json
import time
import logging
import os
import sys
from datetime import datetime, timedelta
import pika
import redis

# 添加 Data-discover 目录到 Python 路径，以便导入模块
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'Data-discover'))
from query_datasets_by_date import HuggingFaceDatasetQuery
from dataset_db import DatasetDB
from mysql_queue import MySQLQueueManager

# 配置日志 - 确保输出到 Docker 容器标准输出
handlers = [logging.StreamHandler(sys.stdout)]

# 尝试添加文件日志（如果目录存在且有权限）
try:
    log_dir = '/app/logs'
    if os.path.exists(log_dir) and os.access(log_dir, os.W_OK):
        handlers.append(logging.FileHandler('/app/logs/rabbitmq_producer.log'))
except Exception:
    pass  # 忽略文件日志错误，至少保证控制台输出

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=handlers,
    force=True  # 强制重新配置
)
logger = logging.getLogger(__name__)

# 输出启动信息
logger.info("="*60)
logger.info("RabbitMQ Producer 启动中...")
logger.info("="*60)

class RabbitMQProducer:
    def __init__(self):
        self.rabbitmq_host = os.getenv('RABBITMQ_HOST', 'localhost')
        self.rabbitmq_port = int(os.getenv('RABBITMQ_PORT', 5672))
        self.rabbitmq_user = os.getenv('RABBITMQ_USER', 'admin')
        self.rabbitmq_password = os.getenv('RABBITMQ_PASSWORD', 'password123')
        self.rabbitmq_vhost = os.getenv('RABBITMQ_VHOST', '/')
        self.queue_name = os.getenv('RABBITMQ_QUEUE_NAME', 'hf_download_queue')
        self.dlq_name = os.getenv('RABBITMQ_DLQ_NAME', 'hf_download_dlq')

        # Redis 配置
        self.redis_host = os.getenv('REDIS_HOST', 'localhost')
        self.redis_port = int(os.getenv('REDIS_PORT', 6379))
        self.redis_db = int(os.getenv('REDIS_DB', 0))
        self.redis_password = os.getenv('REDIS_PASSWORD', None)
        self.redis_config_key = os.getenv('REDIS_CONFIG_KEY', 'hf_producer_config')
        self.redis_trigger_key = 'hf_producer_trigger_scan'
        
        # 初始化 Redis 客户端
        self.redis_client = None
        self._init_redis()

        # Hugging Face 配置 (默认值，可被 Redis 配置覆盖)
        self.hf_endpoint = os.getenv('HF_ENDPOINT', 'https://hf-mirror.com')
        self.hf_token = os.getenv('HF_TOKEN', '')

        # 生产者配置 (默认值，可被 Redis 配置覆盖)
        self._default_config = {
            'producer_interval': int(os.getenv('PRODUCER_INTERVAL', 3600)),
            'producer_days': int(os.getenv('PRODUCER_DAYS', 7)),
            'producer_limit': int(os.getenv('PRODUCER_LIMIT', 50)),
            'producer_timezone_offset': int(os.getenv('PRODUCER_TIMEZONE_OFFSET', 8)),
            'producer_use_created_at': os.getenv('PRODUCER_USE_CREATED_AT', 'false').lower() == 'true',
            'producer_auto_limit': os.getenv('PRODUCER_AUTO_LIMIT', 'true').lower() == 'true',
            'hf_endpoint': self.hf_endpoint
        }
        
        # 当前配置 (初始化时从 Redis 加载，如果没有则使用默认值)
        self._load_config_from_redis()

        # Hugging Face 查询器
        self.query = HuggingFaceDatasetQuery(endpoint=self.hf_endpoint, token=self.hf_token)

        # MySQL 队列管理器
        mysql_config = {
            'host': os.getenv('MYSQL_HOST', 'localhost'),
            'port': int(os.getenv('MYSQL_PORT', 3306)),
            'user': os.getenv('MYSQL_USER', 'root'),
            'password': os.getenv('MYSQL_PASSWORD', ''),
            'database': os.getenv('MYSQL_DATABASE', 'hf_datasets'),
            'charset': 'utf8mb4',
            'cursorclass': __import__('pymysql').cursors.DictCursor
        }
        self.queue_manager = MySQLQueueManager(mysql_config)
        
        # Dataset 元数据数据库 (SQLite) - 可选，仅用于元数据记录
        self.dataset_db = None
        db_path = os.getenv('SQLITE_DB_PATH', '')
        if db_path:
            try:
                self.dataset_db = DatasetDB(db_path)
                logger.info(f"SQLite元数据数据库已启用: {db_path}")
            except Exception as e:
                logger.warning(f"无法初始化SQLite数据库，将跳过元数据记录: {e}")
        else:
            logger.info("未配置SQLite数据库，将跳过元数据记录")
        
        # 事件监听配置
        self.event_exchange = os.getenv('RABBITMQ_EVENT_EXCHANGE', 'download_events')
        self.event_queue = os.getenv('RABBITMQ_EVENT_QUEUE', 'producer_events')

        # RabbitMQ 连接
        self.connection = None
        self.channel = None
        self.event_connection = None  # 独立的事件监听连接
        self.event_channel = None  # 用于监听事件的独立channel

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
            logger.info(f"成功连接到 Redis: {self.redis_host}:{self.redis_port}")
        except Exception as e:
            logger.warning(f"无法连接到 Redis: {e}，将使用环境变量配置")
            self.redis_client = None

    def _save_config_to_redis(self):
        """保存当前配置到 Redis"""
        if self.redis_client:
            try:
                config = {
                    'producer_interval': self.producer_interval,
                    'producer_days': self.producer_days,
                    'producer_limit': self.producer_limit,
                    'producer_timezone_offset': self.producer_timezone_offset,
                    'producer_use_created_at': self.producer_use_created_at,
                    'producer_auto_limit': self.producer_auto_limit,
                    'hf_endpoint': self.hf_endpoint
                }
                self.redis_client.set(self.redis_config_key, json.dumps(config))
                # logger.info("已将当前配置保存到 Redis")
            except Exception as e:
                logger.error(f"保存配置到 Redis 失败: {e}")

    def _load_config_from_redis(self):
        """从 Redis 加载配置"""
        if self.redis_client:
            try:
                config_str = self.redis_client.get(self.redis_config_key)
                if config_str:
                    config = json.loads(config_str)
                    self.producer_interval = config.get('producer_interval', self._default_config['producer_interval'])
                    self.producer_days = config.get('producer_days', self._default_config['producer_days'])
                    self.producer_limit = config.get('producer_limit', self._default_config['producer_limit'])
                    self.producer_timezone_offset = config.get('producer_timezone_offset', self._default_config['producer_timezone_offset'])
                    self.producer_use_created_at = config.get('producer_use_created_at', self._default_config['producer_use_created_at'])
                    self.producer_auto_limit = config.get('producer_auto_limit', self._default_config['producer_auto_limit'])
                    self.hf_endpoint = config.get('hf_endpoint', self._default_config['hf_endpoint'])
                    logger.info(f"从 Redis 加载配置: days={self.producer_days}, limit={self.producer_limit}, interval={self.producer_interval}")
                    return
            except Exception as e:
                logger.warning(f"从 Redis 加载配置失败: {e}")
        
        # 使用默认配置
        self.producer_interval = self._default_config['producer_interval']
        self.producer_days = self._default_config['producer_days']
        self.producer_limit = self._default_config['producer_limit']
        self.producer_timezone_offset = self._default_config['producer_timezone_offset']
        self.producer_use_created_at = self._default_config['producer_use_created_at']
        self.producer_auto_limit = self._default_config['producer_auto_limit']
        self.hf_endpoint = self._default_config['hf_endpoint']
        logger.info(f"使用默认配置: days={self.producer_days}, limit={self.producer_limit}, interval={self.producer_interval}")
        
        # 将默认配置保存到 Redis，以便后续可以通过 Redis 修改
        self._save_config_to_redis()

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


    def connect_rabbitmq(self):
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

            # 声明队列和死信队列
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
            
            # 声明事件交换机和队列（用于接收consumer的下载事件）
            self.channel.exchange_declare(
                exchange=self.event_exchange,
                exchange_type='topic',
                durable=True
            )
            
            self.channel.queue_declare(
                queue=self.event_queue,
                durable=True
            )
            
            # 绑定所有下载事件
            self.channel.queue_bind(
                exchange=self.event_exchange,
                queue=self.event_queue,
                routing_key='download.*'
            )

            logger.info(f"成功连接到 RabbitMQ: {self.rabbitmq_host}:{self.rabbitmq_port}")
            logger.info(f"事件监听队列: {self.event_queue} (绑定到 {self.event_exchange})")
            return True

        except Exception as e:
            logger.error(f"连接 RabbitMQ 失败: {e}")
            return False

    def disconnect_rabbitmq(self):
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
                if not self.connect_rabbitmq():
                    return False

            self.channel.basic_publish(
                exchange='',
                routing_key=self.queue_name,
                body=json.dumps(message),
                properties=pika.BasicProperties(
                    delivery_mode=2,  # 持久化消息
                    content_type='application/json',
                    timestamp=int(time.time())
                )
            )

            logger.info(f"消息已发送到队列: {message.get('dataset_id', 'Unknown')}")
            return True

        except Exception as e:
            logger.error(f"发送消息失败: {e}")
            return False

    def scan_datasets(self):
        """扫描 Hugging Face 数据集
        使用 query_datasets_by_date.py 中的高级查询功能
        """
        try:
            # 计算目标日期（最近 N 天）
            target_date = (datetime.now() - timedelta(days=self.producer_days)).strftime('%Y-%m-%d')

            logger.info(f"开始扫描数据集: 日期 {target_date}，查询过去 {self.producer_days} 天的数据集")

            # 使用高级查询功能获取数据集
            datasets = self.query.get_datasets_by_date(
                target_date=target_date,
                limit=self.producer_limit,
                timezone_offset=self.producer_timezone_offset,
                use_created_at=self.producer_use_created_at,
                auto_limit=self.producer_auto_limit
            )

            # 格式化数据集信息
            valid_datasets = []
            for dataset in datasets:
                if isinstance(dataset, dict):
                    dataset_info = {
                        'id': dataset.get('id', ''),
                        'dataset_id': dataset.get('id', ''),
                        'name': dataset.get('id', ''),
                        'description': dataset.get('description', ''),
                        'downloads': dataset.get('downloads', 0),
                        'likes': dataset.get('likes', 0),
                        'last_modified': dataset.get('lastModified', ''),
                        'created_at': dataset.get('createdAt', ''),
                        'tags': dataset.get('tags', []),
                        'author': dataset.get('author', ''),
                        'created_at_producer': datetime.now().isoformat(),
                        'priority': self._calculate_priority(dataset)
                    }

                    # 过滤条件
                    if (dataset_info['downloads'] >= 0 and
                        dataset_info['likes'] >= 0):
                        valid_datasets.append(dataset_info)

            logger.info(f"扫描完成，找到 {len(valid_datasets)} 个有效数据集")
            return valid_datasets

        except Exception as e:
            logger.error(f"扫描数据集时出错: {e}")
            return []

    def _calculate_priority(self, dataset):
        """计算数据集下载优先级"""
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
        if likes > 100:
            priority += 2
        elif likes > 10:
            priority += 1

        # 基于标签（热门标签加分）
        tags = dataset.get('tags', [])
        popular_tags = ['text-classification', 'text-generation', 'translation',
                       'question-answering', 'summarization', 'sentiment-analysis']
        for tag in tags:
            if tag in popular_tags:
                priority += 1
                break

        return priority

    def run_once(self):
        """运行一次扫描和发送"""
        logger.info("开始单次扫描...")

        # 扫描数据集
        datasets = self.scan_datasets()

        if not datasets:
            logger.warning("未找到有效数据集")
            return

        # 添加到MySQL队列和SQLite元数据库
        success_count = 0
        skipped_count = 0
        
        for dataset in datasets:
            try:
                dataset_id = dataset.get('dataset_id')
                priority = dataset.get('priority', 0)
                
                # 1. 检查数据集是否已在队列中
                existing_task = self.queue_manager.get_task_by_dataset_id(dataset_id)
                if existing_task:
                    status = existing_task.get('status')
                    if status in ('completed', 'downloading', 'pending'):
                        logger.debug(f"  跳过已存在的数据集: {dataset_id} (状态: {status})")
                        skipped_count += 1
                        continue
                    # 如果状态是 failed，允许重新添加
                
                # 2. 添加到 Dataset 元数据数据库 (SQLite) - 可选
                if self.dataset_db:
                    try:
                        self.dataset_db.upsert_dataset(dataset)
                    except Exception as e:
                        logger.warning(f"保存元数据失败: {e}")
                
                # 3. 添加到 MySQL 下载队列
                added = self.queue_manager.add_to_queue(dataset_id, priority)
                
                # 4. 如果成功添加到队列
                if added:
                    success_count += 1
                    logger.info(f"✓ 已添加到 MySQL 队列: {dataset_id} (优先级: {priority})")
                else:
                    logger.debug(f"  未能添加到队列: {dataset_id}")
                    skipped_count += 1
                    
            except Exception as e:
                logger.error(f"处理数据集失败 {dataset.get('dataset_id', 'unknown')}: {e}")

        logger.info(f"扫描完成，成功添加 {success_count}/{len(datasets)} 个数据集到队列，跳过 {skipped_count} 个")

    def dispatch_tasks(self):
        """调度任务：从 MySQL 取出任务发送到 RabbitMQ"""
        try:
            # 1. 获取 RabbitMQ 队列状态
            if not self.channel or self.channel.is_closed:
                if not self.connect_rabbitmq():
                    return

            # 使用 passive=True 获取队列状态
            try:
                queue_state = self.channel.queue_declare(
                    queue=self.queue_name,
                    passive=True
                )
                message_count = queue_state.method.message_count
                consumer_count = queue_state.method.consumer_count
            except Exception as e:
                # 如果队列不存在，可能需要重新声明，或者直接返回
                logger.warning(f"获取队列状态失败: {e}")
                return
            
            if consumer_count == 0:
                # logger.debug("当前无消费者，暂停调度")
                return

            # 2. 计算需要补充的任务数
            # 目标队列深度 = 消费者数 * 预取数 * 2 (保持一定积压以防断供)
            prefetch_count = 2
            target_depth = consumer_count * prefetch_count
            needed = target_depth - message_count
            
            if needed <= 0:
                # logger.debug(f"队列充足 (msg={message_count}, consumers={consumer_count}), 暂不调度")
                return
            
            # 限制单次调度数量，防止突发流量
            batch_size = min(needed, 10)
            
            # 3. 从 MySQL 获取任务
            tasks = self.queue_manager.fetch_tasks_batch(limit=batch_size)
            
            if not tasks:
                return
                
            logger.info(f"调度任务: 队列消息={message_count}, 消费者={consumer_count}, 需补充={needed}, 本次获取={len(tasks)}")
            
            # 4. 发送到 RabbitMQ
            sent_count = 0
            for task in tasks:
                # 构造消息体 (需要包含 dataset_info)
                # Consumer 需要: dataset_id, storage_path (可选)
                dataset_info = {
                    'dataset_id': task['dataset_id'],
                    'storage_path': task.get('storage_path', ''),
                    'priority': task['priority'],
                    'retry_count': task['retry_count']
                }
                
                if self.send_message(dataset_info):
                    sent_count += 1
                else:
                    # 发送失败，回滚状态为 pending
                    self.queue_manager.update_status(task['id'], 'pending')
                    logger.error(f"发送消息失败，回滚状态: {task['dataset_id']}")
            
            logger.info(f"成功调度 {sent_count}/{len(tasks)} 个任务")
            
        except Exception as e:
            logger.error(f"调度任务出错: {e}")

    def handle_download_event(self, ch, method, properties, body):
        """处理来自consumer的下载事件"""
        try:
            event = json.loads(body)
            event_type = event.get('event_type')
            dataset_id = event.get('dataset_id')
            message = event.get('message', '')
            metadata = event.get('metadata', {})
            
            logger.info(f"收到事件: {event_type} - {dataset_id}")
            
            # 获取任务信息
            task = self.queue_manager.get_task_by_dataset_id(dataset_id)
            if not task:
                logger.debug(f"跳过事件（任务不在队列中）: {dataset_id} - 可能已完成或来自旧消息")
                ch.basic_ack(delivery_tag=method.delivery_tag)
                return
            
            # 根据事件类型处理
            if event_type == 'start':
                # 下载开始，更新状态为downloading
                self.queue_manager.update_status(task['id'], 'downloading')
                self.queue_manager.log_event(dataset_id, 'start', message, metadata)
                logger.info(f"→ 已更新状态为downloading: {dataset_id}")
                
            elif event_type == 'complete':
                # 下载完成，更新状态为completed并生成dataset记录
                # 从 metadata 获取存储路径
                storage_path = metadata.get('storage_path', '')
                self.queue_manager.update_status(task['id'], 'completed', storage_path=storage_path)
                self.queue_manager.log_event(dataset_id, 'complete', message, metadata)
                
                # 生成dataset记录到SQLite
                self._create_dataset_record(dataset_id, metadata)
                logger.info(f"✓ 已更新状态为completed并记录存储路径: {dataset_id} -> {storage_path}")
                logger.info(f"✓ 已更新状态为completed并生成dataset记录: {dataset_id}")
                
            elif event_type == 'fail':
                # 下载失败，更新状态为failed
                self.queue_manager.update_status(task['id'], 'failed', message)
                self.queue_manager.log_event(dataset_id, 'fail', message, metadata)
                logger.error(f"✗ 已更新状态为failed: {dataset_id}")
                
            elif event_type == 'retry':
                # 重试，更新状态为pending并增加retry_count
                retry_count = metadata.get('retry_count', 0)
                self.queue_manager.increment_retry(task['id'], 10, message)  # max_retries设大一点，由consumer控制
                self.queue_manager.log_event(dataset_id, 'retry', message, metadata)
                logger.warning(f"⟳ 已标记重试: {dataset_id} (第{retry_count}次)")
            
            # 确认消息
            ch.basic_ack(delivery_tag=method.delivery_tag)
            
        except Exception as e:
            logger.error(f"处理事件失败: {e}")
            import traceback
            traceback.print_exc()
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
    
    def _create_dataset_record(self, dataset_id, metadata):
        """创建dataset记录到SQLite"""
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
            
            if self.dataset_db:
                try:
                    self.dataset_db.upsert_dataset(dataset)
                    logger.info(f"✓ Dataset记录已创建: {dataset_id}")
                except Exception as e:
                    logger.warning(f"保存元数据失败: {e}")
            else:
                logger.info(f"✓ Dataset记录已添加到队列: {dataset_id}")
            
        except Exception as e:
            logger.error(f"创建dataset记录失败: {e}")
    
    def start_event_listener(self):
        """启动事件监听器（在独立线程中运行）"""
        import threading
        
        def listener_thread():
            try:
                # 创建独立的连接用于事件监听
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
                
                # 确保队列存在
                self.event_channel.queue_declare(
                    queue=self.event_queue,
                    durable=True
                )
                
                # 设置消费者
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
        
        listener = threading.Thread(target=listener_thread, daemon=True)
        listener.start()
        logger.info("事件监听器线程已启动")
        return listener

    def run_continuous(self):
        """持续运行生产者"""
        logger.info(f"启动 RabbitMQ 生产者，扫描间隔: {self.producer_interval} 秒")
        
        # 启动事件监听器
        self.start_event_listener()
        
        last_scan_time = 0

        while True:
            try:
                current_time = time.time()
                
                # 1. 定期扫描 (低频)
                if current_time - last_scan_time >= self.producer_interval:
                    # 每次扫描前从 Redis 重新加载配置
                    self._load_config_from_redis()
                    
                    # 更新查询器的端点（如果配置变化）
                    if self.query.endpoint != self.hf_endpoint:
                        self.query = HuggingFaceDatasetQuery(endpoint=self.hf_endpoint, token=self.hf_token)
                        logger.info(f"已更新 HuggingFace 端点为: {self.hf_endpoint}")
                    
                    self.run_once()
                    last_scan_time = current_time
                    logger.info(f"扫描完成，下次扫描在 {self.producer_interval} 秒后")
                
                # 2. 检查手动触发
                elif self._check_trigger_scan():
                    logger.info("手动触发扫描，立即执行...")
                    self.run_once()
                    last_scan_time = current_time
                
                # 3. 调度任务 (高频)
                self.dispatch_tasks()
                
                # 4. 短暂休眠 (避免空转，但要保持响应)
                time.sleep(5)

            except KeyboardInterrupt:
                logger.info("收到中断信号，停止生产者")
                break
            except Exception as e:
                logger.error(f"生产者运行出错: {e}")
                time.sleep(60)  # 出错后等待 1 分钟再重试

    def __del__(self):
        """析构函数，确保连接关闭"""
        self.disconnect_rabbitmq()

def main():
    """主函数"""
    producer = RabbitMQProducer()

    # 测试连接
    if not producer.connect_rabbitmq():
        logger.error("无法连接到 RabbitMQ，退出")
        return

    try:
        # 运行生产者
        producer.run_continuous()
    except KeyboardInterrupt:
        logger.info("程序被用户中断")
    finally:
        producer.disconnect_rabbitmq()

if __name__ == '__main__':
    main()