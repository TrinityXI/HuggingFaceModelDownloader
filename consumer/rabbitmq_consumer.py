#!/usr/bin/env python3
"""
RabbitMQ 消费者服务
从 RabbitMQ 队列接收消息并处理下载任务
"""

import json
import time
import logging
import os
import sys
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import pika
import redis
import pymysql
from contextlib import contextmanager

# 配置日志 - 确保输出到 Docker 容器标准输出
handlers = [logging.StreamHandler(sys.stdout)]

# 尝试添加文件日志（如果目录存在且有权限）
try:
    log_dir = '/app/logs'
    if os.path.exists(log_dir) and os.access(log_dir, os.W_OK):
        handlers.append(logging.FileHandler('/app/logs/rabbitmq_consumer.log'))
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
logger.info("RabbitMQ Consumer 启动中...")
logger.info("="*60)


class DownloadProgressTracker:
    """
    下载进度跟踪器
    聚合 hfdownloader 的进度事件，计算总体下载进度百分比
    """
    def __init__(self, dataset_id):
        self.dataset_id = dataset_id
        
        # 总体统计
        self.total_bytes = 0  # 所有文件的总大小
        self.total_files = 0  # 文件总数
        self.completed_files = 0  # 已完成文件数
        self.skipped_files = 0  # 跳过的文件数
        
        # 文件级进度跟踪 {path: {'bytes': downloaded, 'total': total_size, 'skipped': bool}}
        self.file_progress = {}
        
        # 用于去重的集合
        self.planned_files = set()
        self.completed_files_set = set()
        self.skipped_files_set = set()
        
        # 实时速度计算（记录最近的下载量）
        self.last_speed_check_time = time.time()
        self.last_speed_check_bytes = 0  # 上次检查时的已下载字节数
        self.current_speed = 0  # 当前实时速度
        
        # 发布控制
        self.last_publish_time = time.time()
        self.last_publish_percentage = 0.0
        self.publish_interval = 10  # 最少每10秒发布一次
        self.publish_percentage_delta = 5.0  # 或进度变化超过5%
        
        # 开始时间
        self.start_time = time.time()
    
    def process_event(self, event):
        """处理单个进度事件"""
        event_type = event.get('event', '')
        
        if event_type == 'plan_item':
            # 记录计划下载的文件
            path = event.get('path', '')
            total = event.get('total', 0)
            
            if path and path not in self.planned_files:
                self.planned_files.add(path)
                self.total_files += 1
                self.total_bytes += total
                self.file_progress[path] = {'bytes': 0, 'total': total, 'skipped': False}
        
        elif event_type == 'file_progress':
            # 更新文件下载进度
            path = event.get('path', '')
            bytes_done = event.get('bytes', 0)
            total = event.get('total', 0)
            
            if path:
                if path not in self.file_progress:
                    self.file_progress[path] = {'bytes': 0, 'total': total, 'skipped': False}
                self.file_progress[path]['bytes'] = bytes_done
        
        elif event_type == 'file_done':
            # 文件完成
            path = event.get('path', '')
            message = event.get('message', '')
            
            if path and path not in self.completed_files_set:
                self.completed_files_set.add(path)
                
                # 所有完成的文件都计入 completed_files
                self.completed_files += 1
                
                # 检查是否是跳过的文件
                is_skipped = 'skip' in message.lower()
                if is_skipped:
                    self.skipped_files += 1
                    self.skipped_files_set.add(path)
                
                # 确保进度显示为100%
                if path in self.file_progress:
                    total = self.file_progress[path]['total']
                    self.file_progress[path]['bytes'] = total
                    self.file_progress[path]['skipped'] = is_skipped
    
    def get_overall_progress(self):
        """计算总体进度"""
        if self.total_bytes == 0:
            return {
                'percentage': 0.0,
                'downloaded_bytes': 0,
                'total_bytes': 0,
                'total_files': self.total_files,
                'completed_files': self.completed_files,
                'skipped_files': self.skipped_files,
                'active_files': 0,
                'elapsed_time': time.time() - self.start_time,
                'estimated_remaining': 0,
                'download_speed': 0
            }
        
        # 计算已下载的总字节数（包括跳过的）
        downloaded_bytes = sum(fp['bytes'] for fp in self.file_progress.values())
        
        # 计算实际下载的字节数（不包括跳过的文件）
        actual_downloaded = sum(
            fp['bytes'] for path, fp in self.file_progress.items()
            if path not in self.skipped_files_set
        )
        
        # 计算百分比
        percentage = (downloaded_bytes / self.total_bytes * 100) if self.total_bytes > 0 else 0.0
        
        # 计算活跃下载文件数（进度 > 0 且 < 100%）
        active_files = sum(
            1 for fp in self.file_progress.values()
            if 0 < fp['bytes'] < fp['total']
        )
        
        # 计算经过时间
        elapsed_time = time.time() - self.start_time
        
        # 计算需要实际下载的字节数（总字节数 - 跳过的文件大小）
        skipped_bytes = sum(
            fp['total'] for path, fp in self.file_progress.items()
            if path in self.skipped_files_set
        )
        bytes_to_download = self.total_bytes - skipped_bytes
        
        # 计算实时下载速度（使用最近的下载增量）
        current_time = time.time()
        time_delta = current_time - self.last_speed_check_time
        
        # 每隔1秒更新一次速度（避免频繁计算）
        if time_delta >= 1.0:
            bytes_delta = actual_downloaded - self.last_speed_check_bytes
            self.current_speed = bytes_delta / time_delta if time_delta > 0 else 0
            self.last_speed_check_time = current_time
            self.last_speed_check_bytes = actual_downloaded
        
        download_speed = self.current_speed
        
        # 估算剩余时间
        estimated_remaining = 0
        if download_speed > 0 and percentage < 100:
            remaining_bytes = bytes_to_download - actual_downloaded
            estimated_remaining = remaining_bytes / download_speed
        
        return {
            'percentage': round(percentage, 2),
            'downloaded_bytes': downloaded_bytes,
            'total_bytes': self.total_bytes,
            'total_files': self.total_files,
            'completed_files': self.completed_files,
            'skipped_files': self.skipped_files,
            'active_files': active_files,
            'elapsed_time': round(elapsed_time, 1),
            'estimated_remaining': round(estimated_remaining, 1),
            'download_speed': round(download_speed, 2)
        }
    
    def should_publish_progress(self):
        """判断是否应该发布进度更新"""
        current_time = time.time()
        current_progress = self.get_overall_progress()
        current_percentage = current_progress['percentage']
        
        # 条件1: 距离上次发布超过指定时间间隔
        time_elapsed = current_time - self.last_publish_time >= self.publish_interval
        
        # 条件2: 进度变化超过指定百分比
        percentage_changed = abs(current_percentage - self.last_publish_percentage) >= self.publish_percentage_delta
        
        if time_elapsed or percentage_changed:
            self.last_publish_time = current_time
            self.last_publish_percentage = current_percentage
            return True
        
        return False


class RabbitMQConsumer:
    def __init__(self):
        self.rabbitmq_host = os.getenv('RABBITMQ_HOST', 'localhost')
        self.rabbitmq_port = int(os.getenv('RABBITMQ_PORT', 5672))
        self.rabbitmq_user = os.getenv('RABBITMQ_USER', 'admin')
        self.rabbitmq_password = os.getenv('RABBITMQ_PASSWORD', 'password123')
        self.rabbitmq_vhost = os.getenv('RABBITMQ_VHOST', '/')
        self.queue_name = os.getenv('RABBITMQ_QUEUE_NAME', 'hf_download_queue')
        self.dlq_name = os.getenv('RABBITMQ_DLQ_NAME', 'hf_download_dlq')

        # 消费者配置
        self.consumer_workers = int(os.getenv('CONSUMER_WORKERS', 4))
        self.consumer_max_retries = int(os.getenv('CONSUMER_MAX_RETRIES', 3))
        self.consumer_timeout = int(os.getenv('CONSUMER_TIMEOUT', 3600))

        # 下载器配置
        self.hf_endpoint = os.getenv('HF_ENDPOINT', 'https://huggingface.co')
        self.hf_token = os.getenv('HF_TOKEN', '')
        self.output_dir = os.getenv('OUTPUT_DIR', '/datasets')
        self.go_binary_path = os.getenv('GO_BINARY_PATH', '/app/hfdownloader-optimized')
        
        # 事件通知配置（必须启用，用于通知producer）
        self.event_exchange = os.getenv('RABBITMQ_EVENT_EXCHANGE', 'download_events')
        
        # Redis 配置（用于存储进度数据）
        self.redis_host = os.getenv('REDIS_HOST', 'localhost')
        self.redis_port = int(os.getenv('REDIS_PORT', 6379))
        self.redis_db = int(os.getenv('REDIS_DB', 0))
        self.redis_password = os.getenv('REDIS_PASSWORD', None)
        
        # MySQL 配置（用于直接更新进度到数据库）
        self.mysql_host = os.getenv('MYSQL_HOST', 'localhost')
        self.mysql_port = int(os.getenv('MYSQL_PORT', 3306))
        self.mysql_user = os.getenv('MYSQL_USER', 'root')
        self.mysql_password = os.getenv('MYSQL_PASSWORD', '')
        self.mysql_database = os.getenv('MYSQL_DATABASE', 'hf_datasets')

        # RabbitMQ 连接
        self.connection = None
        self.channel = None
        self.running = False
        
        # 当前处理的消息信息（用于心跳）
        self.current_channel = None
        self.current_delivery_tag = None
        self.last_heartbeat_time = time.time()
        self.heartbeat_interval = 300  # 每5分钟发送一次心跳
        
        # Redis 客户端
        self.redis_client = None
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
            logger.warning(f"连接 Redis 失败: {e}，进度数据将不会被存储")
            self.redis_client = None

        # 线程池
        self.executor = ThreadPoolExecutor(max_workers=self.consumer_workers)

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

            # 设置 QoS，控制并发处理数量
            self.channel.basic_qos(prefetch_count=self.consumer_workers)

            # 声明队列，增加 consumer timeout 配置（12小时）
            self.channel.queue_declare(
                queue=self.queue_name,
                durable=True,
                arguments={
                    'x-dead-letter-exchange': '',
                    'x-dead-letter-routing-key': self.dlq_name,
                    'x-consumer-timeout': 43200000  # 12 hours in milliseconds
                }
            )

            self.channel.queue_declare(
                queue=self.dlq_name,
                durable=True
            )
            
            # 声明事件交换机（用于发送下载事件通知producer）
            self.channel.exchange_declare(
                exchange=self.event_exchange,
                exchange_type='topic',
                durable=True
            )

            logger.info(f"成功连接到 RabbitMQ: {self.rabbitmq_host}:{self.rabbitmq_port}")
            return True

        except Exception as e:
            logger.error(f"连接 RabbitMQ 失败: {e}")
            return False

    def disconnect_rabbitmq(self):
        """断开 RabbitMQ 连接"""
        self.running = False
        try:
            if self.connection and not self.connection.is_closed:
                self.connection.close()
                logger.info("RabbitMQ 连接已关闭")
        except Exception as e:
            logger.error(f"关闭 RabbitMQ 连接时出错: {e}")
    
    def send_heartbeat(self):
        """发送心跳以保持 RabbitMQ 连接活跃"""
        try:
            current_time = time.time()
            if current_time - self.last_heartbeat_time >= self.heartbeat_interval:
                if self.connection and not self.connection.is_closed:
                    # 发送心跳包
                    self.connection.process_data_events(time_limit=0)
                    self.last_heartbeat_time = current_time
                    logger.debug("已发送 RabbitMQ 心跳")
        except Exception as e:
            logger.error(f"发送心跳失败: {e}")
    
    def publish_event(self, event_type, dataset_id, message='', metadata=None):
        """发布下载事件到 RabbitMQ，通知 producer 更新 MySQL"""
        try:
            event = {
                'event_type': event_type,
                'dataset_id': dataset_id,
                'message': message,
                'metadata': metadata or {},
                'timestamp': time.time()
            }
            
            routing_key = f'download.{event_type}'
            
            self.channel.basic_publish(
                exchange=self.event_exchange,
                routing_key=routing_key,
                body=json.dumps(event),
                properties=pika.BasicProperties(
                    delivery_mode=2,
                    content_type='application/json'
                )
            )
            
            logger.info(f"事件已发布: {routing_key} - {dataset_id}")
            
            # 如果是进度事件，同时存储到 Redis 和 MySQL
            if event_type == 'progress' and metadata:
                # 存储到 Redis 以便快速读取
                if self.redis_client:
                    try:
                        progress_key = f'task:progress:{dataset_id}'
                        # 存储进度数据，5分钟过期
                        self.redis_client.setex(
                            progress_key,
                            300,  # 5 minutes TTL
                            json.dumps(metadata)
                        )
                        logger.debug(f"进度数据已存储到 Redis: {dataset_id} - {metadata.get('percentage', 0):.1f}%")
                    except Exception as e:
                        logger.error(f"存储进度数据到 Redis 失败: {e}")
                
                # 同时更新到 MySQL 数据库
                try:
                    self.update_progress_to_db(dataset_id, metadata)
                except Exception as e:
                    logger.error(f"更新进度到数据库失败: {e}")
            
        except Exception as e:
            logger.error(f"发布事件失败: {e}")
    
    @contextmanager
    def get_mysql_connection(self):
        """获取 MySQL 连接的上下文管理器"""
        conn = None
        try:
            conn = pymysql.connect(
                host=self.mysql_host,
                port=self.mysql_port,
                user=self.mysql_user,
                password=self.mysql_password,
                database=self.mysql_database,
                charset='utf8mb4',
                cursorclass=pymysql.cursors.DictCursor
            )
            yield conn
            conn.commit()
        except Exception as e:
            if conn:
                conn.rollback()
            raise e
        finally:
            if conn:
                conn.close()
    
    def update_progress_to_db(self, dataset_id, metadata):
        """更新下载进度到 MySQL 数据库"""
        try:
            with self.get_mysql_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    UPDATE download_queue
                    SET progress_percentage = %s,
                        downloaded_bytes = %s,
                        total_bytes = %s,
                        total_files = %s,
                        completed_files = %s,
                        download_speed = %s,
                        updated_at = NOW()
                    WHERE dataset_id = %s
                """, (
                    metadata.get('percentage', 0),
                    metadata.get('downloaded_bytes', 0),
                    metadata.get('total_bytes', 0),
                    metadata.get('total_files', 0),
                    metadata.get('completed_files', 0),
                    metadata.get('download_speed', 0),
                    dataset_id
                ))
                
                logger.debug(f"进度已更新到数据库: {dataset_id} - {metadata.get('percentage', 0):.1f}%")
        except Exception as e:
            logger.error(f"更新进度到 MySQL 失败: {e}")
            raise

    def download_dataset(self, dataset_info):
        """下载数据集"""
        dataset_id = dataset_info.get('dataset_id', 'unknown')
        logger.info(f"开始下载数据集: {dataset_id}")
        
        # 发布开始事件（通知producer更新MySQL状态为downloading）
        self.publish_event('start', dataset_id, '开始下载任务')

        # 初始化进度跟踪器
        progress_tracker = DownloadProgressTracker(dataset_id)

        try:
            safe_dataset_id = dataset_id.replace('/', '_')
            # 构建输出路径
            storage_subpath = dataset_info.get('storage_path')
            if storage_subpath:
                # 去除开头的 / 以防止 os.path.join 忽略 output_dir
                if storage_subpath.startswith('/'):
                    storage_subpath = storage_subpath.lstrip('/')
                output_path = os.path.join(self.output_dir, storage_subpath)
                # join safe_dataset_id
                output_path = os.path.join(output_path, safe_dataset_id)
            else:
                output_path = os.path.join(self.output_dir, safe_dataset_id)
            
            # 构建下载命令 (hfdownloader v2.0 CLI) - 使用优化版本并显示进度
            cmd = [
                self.go_binary_path,
                'download',
                '--dataset',
                '--repo', dataset_id,
                '--output', output_path,
                '--endpoint', self.hf_endpoint,
                '--max-active', '2',
                '--connections', '4',
                '--json'  # 使用JSON输出格式以便解析进度
            ]

            # 添加 token（如果有）
            if self.hf_token:
                cmd.extend(['--token', self.hf_token])

            logger.info(f"执行命令: {' '.join(cmd)}")

            # 执行下载并实时显示进度
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )

            # 实时读取进度输出
            output_lines = []
            for line in process.stdout:
                line = line.strip()
                if line:
                    output_lines.append(line)
                    
                    # 定期发送心跳以保持 RabbitMQ 连接
                    self.send_heartbeat()
                    
                    # 解析JSON进度事件并记录
                    try:
                        event = json.loads(line)
                        event_type = event.get('event', '')
                        message = event.get('message', '')

                        # 更新进度跟踪器
                        progress_tracker.process_event(event)
                        
                        # 获取总体进度
                        overall_progress = progress_tracker.get_overall_progress()

                        if event_type == 'scan_progress':
                            logger.info(f"扫描进度: {message}")
                        elif event_type == 'plan_item':
                            # 记录计划项（用于总进度计算）
                            logger.debug(f"计划项: {event.get('path', 'unknown')} ({event.get('total', 0)} bytes)")
                        elif event_type == 'file_start':
                            logger.info(f"开始下载: {event.get('path', 'unknown')}")
                        elif event_type == 'file_progress':
                            path = event.get('path', 'unknown')
                            bytes_done = event.get('bytes', 0)
                            total = event.get('total', 1)
                            percent = (bytes_done / total * 100) if total > 0 else 0
                            logger.info(
                                f"文件进度: {path} - {percent:.1f}% ({bytes_done}/{total} bytes) | "
                                f"总体: {overall_progress['percentage']:.1f}% "
                                f"({overall_progress['completed_files']}/{overall_progress['total_files']} 文件)"
                            )
                            
                            # 发布进度事件到 RabbitMQ（节流控制：每5%或每10秒发布一次）
                            if progress_tracker.should_publish_progress():
                                self.publish_event(
                                    'progress',
                                    dataset_id,
                                    f"下载进度: {overall_progress['percentage']:.1f}%",
                                    overall_progress
                                )
                        elif event_type == 'file_done':
                            logger.info(
                                f"文件完成: {event.get('path', 'unknown')} | "
                                f"总体: {overall_progress['percentage']:.1f}%"
                            )
                        elif event_type == 'done':
                            logger.info(f"下载完成: {message}")
                            # 发布最终进度
                            self.publish_event('progress', dataset_id, '下载进度: 100%', overall_progress)
                        elif event_type == 'error':
                            logger.error(f"下载错误: {message}")
                        else:
                            logger.debug(f"进度事件: {event_type} - {message}")
                    except json.JSONDecodeError:
                        # 如果不是JSON格式，直接记录
                        logger.info(f"输出: {line}")

            # 等待进程完成
            process.wait()
            result = subprocess.CompletedProcess(
                args=cmd,
                returncode=process.returncode,
                stdout='\n'.join(output_lines),
                stderr=''
            )

            if result.returncode == 0:
                logger.info(f"下载成功: {dataset_id}")
                # 发布完成事件（通知producer更新MySQL状态为completed并生成dataset记录）
                # 包含存储路径信息
                metadata = {
                    'storage_path': output_path,
                    'dataset_id': dataset_id
                }
                self.publish_event('complete', dataset_id, '下载完成', metadata)
                return True, "下载成功"
            else:
                error_msg = f"下载失败: {result.stderr}"
                logger.error(f"{error_msg} - {dataset_id}")
                return False, error_msg

        except subprocess.TimeoutExpired:
            error_msg = f"下载超时: {dataset_id}"
            logger.error(error_msg)
            return False, error_msg
        except Exception as e:
            error_msg = f"下载异常: {str(e)}"
            logger.error(f"{error_msg} - {dataset_id}")
            return False, error_msg

    def process_message(self, ch, method, properties, body):
        """处理单个消息"""
        try:
            # 解析消息
            message = json.loads(body)
            dataset_info = message

            dataset_id = dataset_info.get('dataset_id', 'unknown')
            logger.info(f"收到下载任务: {dataset_id}")

            # 保存 channel 和 delivery_tag 以便在下载过程中发送心跳
            self.current_channel = ch
            self.current_delivery_tag = method.delivery_tag
            
            # 执行下载
            success, msg = self.download_dataset(dataset_info)

            if success:
                # 确认消息
                ch.basic_ack(delivery_tag=method.delivery_tag)
                logger.info(f"任务完成并确认: {dataset_id}")
            else:
                # 检查重试次数
                retry_count = dataset_info.get('retry_count', 0)
                
                if retry_count < self.consumer_max_retries:
                    # 重新入队进行重试
                    dataset_info['retry_count'] = retry_count + 1
                    dataset_info['last_error'] = msg

                    ch.basic_publish(
                        exchange='',
                        routing_key=self.queue_name,
                        body=json.dumps(dataset_info),
                        properties=pika.BasicProperties(
                            delivery_mode=2,
                            content_type='application/json',
                            headers={'x-retry-count': retry_count + 1}
                        )
                    )
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                    logger.warning(f"任务重试 {retry_count + 1}/{self.consumer_max_retries}: {dataset_id}")
                    
                    # 发布重试事件（通知producer更新MySQL状态）
                    self.publish_event('retry', dataset_id, msg, {'retry_count': retry_count + 1})
                else:
                    # 发送到死信队列
                    dataset_info['final_error'] = msg
                    dataset_info['failed_at'] = time.time()

                    ch.basic_publish(
                        exchange='',
                        routing_key=self.dlq_name,
                        body=json.dumps(dataset_info),
                        properties=pika.BasicProperties(
                            delivery_mode=2,
                            content_type='application/json'
                        )
                    )
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                    logger.error(f"任务失败并进入死信队列: {dataset_id}")
                    
                    # 发布失败事件（通知producer更新MySQL状态为failed）
                    self.publish_event('fail', dataset_id, msg, {'retry_count': retry_count + 1})

        except json.JSONDecodeError:
            logger.error("消息格式错误，拒绝消息")
            ch.basic_reject(delivery_tag=method.delivery_tag, requeue=False)
        except Exception as e:
            logger.error(f"处理消息时出错: {e}")
            ch.basic_reject(delivery_tag=method.delivery_tag, requeue=True)

    def start_consuming(self):
        """开始消费消息"""
        try:
            # 设置消息处理回调
            self.channel.basic_consume(
                queue=self.queue_name,
                on_message_callback=self.process_message,
                auto_ack=False
            )

            logger.info(f"开始消费消息，工作线程数: {self.consumer_workers}")
            logger.info(f"按 Ctrl+C 停止消费")

            self.running = True
            self.channel.start_consuming()

        except Exception as e:
            logger.error(f"消费消息时出错: {e}")
            raise

    def stop_consuming(self):
        """停止消费消息"""
        self.running = False
        try:
            if self.channel and self.channel.is_open:
                self.channel.stop_consuming()
                logger.info("已停止消费消息")
        except Exception as e:
            logger.error(f"停止消费时出错: {e}")

    def run(self):
        """运行消费者"""
        logger.info("启动 RabbitMQ 消费者")

        # 连接 RabbitMQ
        if not self.connect_rabbitmq():
            logger.error("无法连接到 RabbitMQ，退出")
            return

        try:
            self.start_consuming()
        except KeyboardInterrupt:
            logger.info("收到中断信号，停止消费者")
        except Exception as e:
            logger.error(f"消费者运行出错: {e}")
        finally:
            self.stop_consuming()
            self.disconnect_rabbitmq()
            self.executor.shutdown(wait=True)

    def __del__(self):
        """析构函数，确保资源清理"""
        self.disconnect_rabbitmq()
        try:
            self.executor.shutdown(wait=False)
        except:
            pass

def main():
    """主函数"""
    consumer = RabbitMQConsumer()
    consumer.run()

if __name__ == '__main__':
    main()