#!/usr/bin/env python3
"""
Producer 核心逻辑
负责扫描 Hugging Face 数据集并添加到队列
"""

import json
import logging
import os
import sys
import requests
import time
from datetime import datetime, timedelta

# Import from local lib package
try:
    from lib.query_datasets_by_date import HuggingFaceDatasetQuery
    from lib.mysql_queue import MySQLQueueManager
except ImportError:
    # Fallback for when running directly or in different context
    sys.path.append(os.path.join(os.path.dirname(__file__), 'lib'))
    from query_datasets_by_date import HuggingFaceDatasetQuery
    from mysql_queue import MySQLQueueManager

logger = logging.getLogger(__name__)


class ProducerCore:
    """Producer 核心业务逻辑"""

    def __init__(self):
        # Hugging Face 配置
        self.hf_endpoint = os.getenv('HF_ENDPOINT', 'https://hf-mirror.com')
        self.hf_token = os.getenv('HF_TOKEN', '')

        # 生产者配置 (默认值)
        self._default_config = {
            'producer_interval': int(os.getenv('PRODUCER_INTERVAL', 3600)),
            'producer_days': int(os.getenv('PRODUCER_DAYS', 7)),
            'producer_limit': int(os.getenv('PRODUCER_LIMIT', 50)),
            'producer_timezone_offset': int(os.getenv('PRODUCER_TIMEZONE_OFFSET', 8)),
            'producer_use_created_at': os.getenv('PRODUCER_USE_CREATED_AT', 'false').lower() == 'true',
            'producer_auto_limit': os.getenv('PRODUCER_AUTO_LIMIT', 'true').lower() == 'true',
            'hf_endpoint': self.hf_endpoint
        }

        # 当前配置
        self.producer_interval = self._default_config['producer_interval']
        self.producer_days = self._default_config['producer_days']
        self.producer_limit = self._default_config['producer_limit']
        self.producer_timezone_offset = self._default_config['producer_timezone_offset']
        self.producer_use_created_at = self._default_config['producer_use_created_at']
        self.producer_auto_limit = self._default_config['producer_auto_limit']

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

        # 飞书机器人（可选）
        self.feishu_bot = None
        try:
            from feishu_bot import FeishuBot
            self.feishu_bot = FeishuBot()
            if self.feishu_bot.webhook_url:
                logger.info("飞书机器人已初始化")
            else:
                logger.info("飞书机器人未配置，通知功能将不可用")
                self.feishu_bot = None
        except ImportError:
            logger.warning("无法导入飞书机器人模块，通知功能将不可用")
        except Exception as e:
            logger.warning(f"初始化飞书机器人失败: {e}")
            self.feishu_bot = None
        
        # RabbitMQ Handler (set later)
        self.rabbitmq_handler = None
        
        # Redis Client (set later)
        self.redis_client = None
        self.redis_config_key = None
        self.redis_trigger_key = None

    def set_rabbitmq_handler(self, handler):
        """设置 RabbitMQ 处理器"""
        self.rabbitmq_handler = handler

    def set_redis_client(self, redis_client, config_key='hf_producer_config', trigger_key='hf_producer_trigger_scan'):
        """设置 Redis 客户端"""
        self.redis_client = redis_client
        self.redis_config_key = config_key
        self.redis_trigger_key = trigger_key

    def get_rabbitmq_stats(self):
        """获取 RabbitMQ 统计信息"""
        if self.rabbitmq_handler:
            return self.rabbitmq_handler.get_queue_stats()
        return {'error': 'RabbitMQ handler not configured'}

    def get_scan_config_from_redis(self):
        """获取扫描配置（优先从Redis）"""
        if self.redis_client:
            try:
                config_str = self.redis_client.get(self.redis_config_key)
                if config_str:
                    return json.loads(config_str)
            except Exception as e:
                logger.warning(f"Failed to get config from Redis: {e}")
        
        # Fallback to current memory config
        return self.get_config()

    def update_scan_config_redis(self, new_config):
        """更新扫描配置（保存到Redis）"""
        # Update local first
        self.update_config(new_config)
        
        # Save to Redis
        if self.redis_client:
            try:
                # Merge with current config to ensure all fields exist
                current = self.get_config()
                current.update(new_config)
                current['updated_at'] = datetime.now().isoformat()
                self.redis_client.set(self.redis_config_key, json.dumps(current))
                return current
            except Exception as e:
                logger.error(f"Failed to save config to Redis: {e}")
                raise e
        return self.get_config()

    def reset_scan_config_redis(self):
        """重置扫描配置（删除Redis中的配置）"""
        if self.redis_client:
            try:
                self.redis_client.delete(self.redis_config_key)
            except Exception as e:
                logger.error(f"Failed to delete config from Redis: {e}")
        
        # Reset local config to defaults
        self.producer_interval = self._default_config['producer_interval']
        self.producer_days = self._default_config['producer_days']
        self.producer_limit = self._default_config['producer_limit']
        self.producer_timezone_offset = self._default_config['producer_timezone_offset']
        self.producer_use_created_at = self._default_config['producer_use_created_at']
        self.producer_auto_limit = self._default_config['producer_auto_limit']
        self.hf_endpoint = self._default_config['hf_endpoint']
        
        if self.query.endpoint != self.hf_endpoint:
            self.query = HuggingFaceDatasetQuery(endpoint=self.hf_endpoint, token=self.hf_token)
        
        return self.get_config()

    def trigger_scan_redis(self):
        """触发扫描"""
        if self.redis_client:
            try:
                self.redis_client.set(self.redis_trigger_key, '1')
                self.redis_client.expire(self.redis_trigger_key, 300)
                return True
            except Exception as e:
                logger.error(f"Failed to set trigger key in Redis: {e}")
                raise e
        return False

    def send_feishu_notification(self, event_type: str, dataset_id: str = "",
                                 message: str = "", metadata: dict = None):
        """
        发送飞书通知（如果飞书机器人已配置）

        Args:
            event_type: 事件类型
            dataset_id: 数据集ID
            message: 消息内容
            metadata: 元数据
        """
        if not self.feishu_bot:
            return False

        try:
            return self.feishu_bot.send_notification(
                event_type=event_type,
                dataset_id=dataset_id,
                message=message,
                metadata=metadata or {}
            )
        except Exception as e:
            logger.warning(f"发送飞书通知失败: {e}")
            return False

    def update_config(self, config):
        """更新配置"""
        self.producer_interval = config.get('producer_interval', self._default_config['producer_interval'])
        self.producer_days = config.get('producer_days', self._default_config['producer_days'])
        self.producer_limit = config.get('producer_limit', self._default_config['producer_limit'])
        self.producer_timezone_offset = config.get('producer_timezone_offset', self._default_config['producer_timezone_offset'])
        self.producer_use_created_at = config.get('producer_use_created_at', self._default_config['producer_use_created_at'])
        self.producer_auto_limit = config.get('producer_auto_limit', self._default_config['producer_auto_limit'])
        self.hf_endpoint = config.get('hf_endpoint', self._default_config['hf_endpoint'])

        # 更新查询器端点
        if self.query.endpoint != self.hf_endpoint:
            self.query = HuggingFaceDatasetQuery(endpoint=self.hf_endpoint, token=self.hf_token)
            logger.info(f"已更新 HuggingFace 端点为: {self.hf_endpoint}")

    def get_config(self):
        """获取当前配置"""
        return {
            'producer_interval': self.producer_interval,
            'producer_days': self.producer_days,
            'producer_limit': self.producer_limit,
            'producer_timezone_offset': self.producer_timezone_offset,
            'producer_use_created_at': self.producer_use_created_at,
            'producer_auto_limit': self.producer_auto_limit,
            'hf_endpoint': self.hf_endpoint
        }

    def scan_datasets(self):
        """扫描 Hugging Face 数据集"""
        try:
            target_date = (datetime.now() - timedelta(days=self.producer_days)).strftime('%Y-%m-%d')
            logger.info(f"开始扫描数据集: 日期 {target_date}，查询过去 {self.producer_days} 天的数据集")

            datasets = self.query.get_datasets_by_date(
                target_date=target_date,
                limit=self.producer_limit,
                timezone_offset=self.producer_timezone_offset,
                use_created_at=self.producer_use_created_at,
                auto_limit=self.producer_auto_limit
            )

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

                    if dataset_info['downloads'] >= 0 and dataset_info['likes'] >= 0:
                        valid_datasets.append(dataset_info)

            logger.info(f"扫描完成，找到 {len(valid_datasets)} 个有效数据集")
            return valid_datasets

        except Exception as e:
            logger.error(f"扫描数据集时出错: {e}")
            return []

    def _calculate_priority(self, dataset):
        """计算数据集下载优先级"""
        priority = 0
        downloads = dataset.get('downloads', 0)
        if downloads > 10000:
            priority += 3
        elif downloads > 1000:
            priority += 2
        elif downloads > 100:
            priority += 1

        likes = dataset.get('likes', 0)
        if likes > 100:
            priority += 2
        elif likes > 10:
            priority += 1

        tags = dataset.get('tags', [])
        popular_tags = ['text-classification', 'text-generation', 'translation',
                       'question-answering', 'summarization', 'sentiment-analysis']
        for tag in tags:
            if tag in popular_tags:
                priority += 1
                break

        return priority

    def add_datasets_to_queue(self, datasets):
        """添加数据集到队列"""
        success_count = 0
        skipped_count = 0

        for dataset in datasets:
            try:
                dataset_id = dataset.get('dataset_id')
                priority = dataset.get('priority', 0)

                # 检查是否已存在
                existing_task = self.queue_manager.get_task_by_dataset_id(dataset_id)
                if existing_task:
                    status = existing_task.get('status')
                    if status in ('completed', 'downloading', 'pending'):
                        logger.debug(f"跳过已存在的数据集: {dataset_id} (状态: {status})")
                        skipped_count += 1
                        continue

                # 添加到元数据数据库 (MySQL)
                try:
                    self.queue_manager.upsert_dataset(dataset)
                except Exception as e:
                    logger.warning(f"保存元数据失败: {e}")

                # 添加到 MySQL 队列
                added = self.queue_manager.add_to_queue(dataset_id, priority)

                if added:
                    success_count += 1
                    logger.info(f"✓ 已添加到队列: {dataset_id} (优先级: {priority})")
                else:
                    skipped_count += 1

            except Exception as e:
                logger.error(f"处理数据集失败 {dataset.get('dataset_id', 'unknown')}: {e}")

        logger.info(f"处理完成，成功 {success_count}/{len(datasets)}，跳过 {skipped_count}")

        # 发送飞书通知（如果成功添加了数据集）
        if success_count > 0:
            self.send_feishu_notification(
                event_type="dataset_discovered",
                message=f"发现 {success_count} 个新数据集并加入下载队列",
                metadata={
                    "success_count": success_count,
                    "skipped_count": skipped_count,
                    "total_datasets": len(datasets)
                }
            )

        return success_count, skipped_count

    def scan_and_enqueue(self):
        """扫描并添加到队列（组合操作）"""
        datasets = self.scan_datasets()
        if not datasets:
            logger.warning("未找到有效数据集")
            return 0, 0

        return self.add_datasets_to_queue(datasets)

    # =========================================================================
    # Queue Operations (Facade for QueueManager)
    # =========================================================================

    def fetch_tasks(self, worker_id: str, limit: int = 1):
        """获取待处理任务"""
        return self.queue_manager.fetch_tasks_batch(limit=limit)

    def get_task_by_dataset_id(self, dataset_id: str):
        """获取任务详情"""
        return self.queue_manager.get_task_by_dataset_id(dataset_id)

    def update_task_status(self, dataset_id: str, status: str, message: str = None, storage_path: str = None):
        """更新任务状态"""
        task = self.queue_manager.get_task_by_dataset_id(dataset_id)
        if not task:
            raise ValueError(f"Task not found: {dataset_id}")

        self.queue_manager.update_status(
            task['id'],
            status,
            message if status == 'failed' else None,
            storage_path if status == 'completed' else None
        )

        # 如果是完成状态，创建/更新 dataset 记录
        if status == 'completed':
            try:
                self._upsert_dataset_record(dataset_id)
            except Exception as e:
                logger.warning(f"创建 dataset 记录失败: {e}")

    def update_task_progress(self, dataset_id: str, progress_data: dict):
        """更新任务进度"""
        task = self.queue_manager.get_task_by_dataset_id(dataset_id)
        if not task:
            raise ValueError(f"Task not found: {dataset_id}")

        with self.queue_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE download_queue
                SET progress_percentage = %s,
                    downloaded_bytes = %s,
                    total_bytes = %s,
                    total_files = %s,
                    completed_files = %s,
                    download_speed = %s,
                    progress_status = %s,
                    updated_at = NOW()
                WHERE dataset_id = %s
            """, (
                progress_data.get('percentage', 0),
                progress_data.get('downloaded_bytes', 0),
                progress_data.get('total_bytes', 0),
                progress_data.get('total_files', 0),
                progress_data.get('completed_files', 0),
                progress_data.get('download_speed', 0),
                progress_data.get('progress_status', 'downloading'),
                dataset_id
            ))

    def log_event(self, dataset_id: str, event_type: str, message: str = "", metadata: dict = None):
        """记录事件"""
        self.queue_manager.log_event(dataset_id, event_type, message, metadata)

    def fetch_interrupted_tasks(self, worker_id: str, limit: int = 1, timeout_minutes: int = 30):
        """获取中断的任务"""
        tasks = []
        for _ in range(limit):
            task = self.queue_manager.claim_interrupted_task(
                worker_id=worker_id,
                timeout_minutes=timeout_minutes
            )
            if task:
                tasks.append(task)
            else:
                break
        return tasks

    def get_interrupted_tasks(self, timeout_minutes: int = 30):
        """查看中断的任务（不认领）"""
        return self.queue_manager.get_interrupted_tasks(timeout_minutes)

    def reset_interrupted_tasks(self, timeout_minutes: int = 30):
        """重置中断的任务"""
        return self.queue_manager.reset_interrupted_tasks(timeout_minutes)

    def _upsert_dataset_record(self, dataset_id: str):
        """更新/插入数据集记录 (Internal)"""
        author, name = dataset_id.split('/', 1) if '/' in dataset_id else ('', dataset_id)
        dataset = {
            'id': dataset_id,
            'author': author,
            'name': name,
            'lastModified': datetime.now().isoformat(),
            'downloads': 0,
            'likes': 0,
            'tags': [],
        }
        self.queue_manager.upsert_dataset(dataset)

    # =========================================================================
    # Monitor API Support Methods
    # =========================================================================

    def get_rabbitmq_stats(self):
        """获取 RabbitMQ 统计信息"""
        if self.rabbitmq_handler:
            return self.rabbitmq_handler.get_queue_stats()
        return {'error': 'RabbitMQ handler not configured'}

    def get_overview_stats(self):
        """获取总览统计数据"""
        with self.queue_manager.get_connection() as conn:
            cursor = conn.cursor()

            # 按状态统计任务数量
            cursor.execute("""
                SELECT status, COUNT(*) as count
                FROM download_queue
                GROUP BY status
            """)
            status_counts = {row['status']: row['count'] for row in cursor.fetchall()}

            # 获取今日新增任务数
            cursor.execute("""
                SELECT COUNT(*) as count
                FROM download_queue
                WHERE DATE(created_at) = CURDATE()
            """)
            today_added = cursor.fetchone()['count']

            # 获取今日完成任务数
            cursor.execute("""
                SELECT COUNT(*) as count
                FROM download_queue
                WHERE DATE(completed_at) = CURDATE() AND status = 'completed'
            """)
            today_completed = cursor.fetchone()['count']

            # 获取失败任务数
            cursor.execute("""
                SELECT COUNT(*) as count
                FROM download_queue
                WHERE status = 'failed'
            """)
            failed_count = cursor.fetchone()['count']

        return {
            'status_counts': status_counts,
            'today_added': today_added,
            'today_completed': today_completed,
            'failed_count': failed_count,
            'timestamp': datetime.now().isoformat()
        }

    def get_queue_list(self, page=1, per_page=20, status=None, dataset_id=None, priority=None):
        """获取下载队列列表"""
        offset = (page - 1) * per_page
        with self.queue_manager.get_connection() as conn:
            cursor = conn.cursor()

            where_conditions = []
            query_params = []

            if status:
                where_conditions.append("status = %s")
                query_params.append(status)

            if dataset_id:
                where_conditions.append("dataset_id LIKE %s")
                query_params.append(f"%{dataset_id}%")

            if priority:
                where_conditions.append("priority = %s")
                query_params.append(int(priority))

            where_clause = "WHERE " + " AND ".join(where_conditions) if where_conditions else ""

            # 获取总数
            count_query = f"""
                SELECT COUNT(*) as total
                FROM download_queue
                {where_clause}
            """
            cursor.execute(count_query, tuple(query_params))
            total = cursor.fetchone()['total']

            # 获取数据
            data_query = f"""
                SELECT id, dataset_id, priority, status, retry_count, last_error,
                       storage_path, created_at, started_at, completed_at, updated_at,
                       progress_percentage, downloaded_bytes, total_bytes,
                       total_files, completed_files, download_speed, progress_status
                FROM download_queue
                {where_clause}
                ORDER BY
                    CASE
                        WHEN status = 'downloading' THEN 1
                        WHEN status = 'pending' THEN 2
                        WHEN status = 'failed' THEN 3
                        WHEN status = 'completed' THEN 4
                    END,
                    created_at DESC,
                    priority DESC
                LIMIT %s OFFSET %s
            """
            cursor.execute(data_query, tuple(query_params + [per_page, offset]))
            tasks = cursor.fetchall()

            # 格式化数据
            for task in tasks:
                for key in ['created_at', 'started_at', 'completed_at', 'updated_at']:
                    if task[key]:
                        task[key] = task[key].isoformat()
                
                # 构造 progress 对象
                if task.get('progress_percentage') is not None or task.get('total_files', 0) > 0:
                    task['progress'] = {
                        'percentage': float(task.get('progress_percentage', 0)),
                        'downloaded_bytes': task.get('downloaded_bytes', 0),
                        'total_bytes': task.get('total_bytes', 0),
                        'total_files': task.get('total_files', 0),
                        'completed_files': task.get('completed_files', 0),
                        'download_speed': float(task.get('download_speed', 0)),
                        'progress_status': task.get('progress_status', 'pending'),
                        'estimated_remaining': 0
                    }
                
                # 清除外层多余字段
                for key in ['progress_percentage', 'downloaded_bytes', 'total_bytes', 
                           'total_files', 'completed_files', 'download_speed', 'progress_status']:
                    if key in task:
                        del task[key]

        return {
            'tasks': tasks,
            'total': total,
            'page': page,
            'per_page': per_page,
            'total_pages': (total + per_page - 1) // per_page
        }

    def get_task_detail(self, task_id):
        """获取任务详情，包含事件日志"""
        with self.queue_manager.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT id, dataset_id, priority, status, retry_count, last_error,
                       storage_path, created_at, started_at, completed_at, updated_at
                FROM download_queue
                WHERE id = %s
            """, (task_id,))

            task = cursor.fetchone()
            if not task:
                return None

            for key in ['created_at', 'started_at', 'completed_at', 'updated_at']:
                if task[key]:
                    task[key] = task[key].isoformat()

            # 获取事件日志
            cursor.execute("""
                SELECT id, event_type, message, metadata, created_at
                FROM download_events
                WHERE dataset_id = %s
                ORDER BY created_at DESC
                LIMIT 50
            """, (task['dataset_id'],))

            events = cursor.fetchall()
            for event in events:
                if event['created_at']:
                    event['created_at'] = event['created_at'].isoformat()
                if event['metadata']:
                    try:
                        event['metadata'] = json.loads(event['metadata']) if isinstance(event['metadata'], str) else event['metadata']
                    except:
                        pass
            
            task['events'] = events
            return task

    def get_task_progress(self, task_id):
        """获取任务实时进度"""
        with self.queue_manager.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT id, dataset_id, status, 
                       progress_percentage, downloaded_bytes, total_bytes,
                       total_files, completed_files, download_speed, progress_status
                FROM download_queue
                WHERE id = %s
            """, (task_id,))
            
            task = cursor.fetchone()
            if not task:
                return None
            
            # 格式化返回
            if task['status'] == 'completed':
                return {
                    'percentage': 100.0,
                    'status': 'completed',
                    'progress_status': 'completed'
                }
            
            return {
                'percentage': float(task.get('progress_percentage', 0)),
                'downloaded_bytes': task.get('downloaded_bytes', 0),
                'total_bytes': task.get('total_bytes', 0),
                'total_files': task.get('total_files', 0),
                'completed_files': task.get('completed_files', 0),
                'download_speed': float(task.get('download_speed', 0)),
                'progress_status': task.get('progress_status', 'pending'),
                'status': task['status']
            }

    def get_timeline_stats(self, days=7):
        """获取时间线统计"""
        with self.queue_manager.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT DATE(completed_at) as date, COUNT(*) as count
                FROM download_queue
                WHERE completed_at >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
                  AND status = 'completed'
                GROUP BY DATE(completed_at)
                ORDER BY date DESC
            """, (days,))
            completed_timeline = list(cursor.fetchall())

            cursor.execute("""
                SELECT DATE(created_at) as date, COUNT(*) as count
                FROM download_queue
                WHERE created_at >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
                GROUP BY DATE(created_at)
                ORDER BY date DESC
            """, (days,))
            created_timeline = list(cursor.fetchall())

            for item in completed_timeline + created_timeline:
                if item['date']:
                    item['date'] = item['date'].isoformat()
        
        return {
            'completed_timeline': completed_timeline,
            'created_timeline': created_timeline
        }

    def retry_task(self, task_id):
        """重试失败的任务"""
        with self.queue_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE download_queue
                SET status = 'pending', retry_count = 0, last_error = NULL
                WHERE id = %s AND status = 'failed'
            """, (task_id,))
            return cursor.rowcount > 0

    def delete_task_by_id(self, task_id):
        """删除任务"""
        return self.queue_manager.delete_task(task_id)

    def search_datasets(self, query, limit=20):
        """搜索 Hugging Face 数据集"""
        headers = {}
        if self.hf_token:
            headers['Authorization'] = f'Bearer {self.hf_token}'

        search_url = f"{self.hf_endpoint}/api/datasets"
        params = {
            'search': query,
            'limit': limit,
            'full': 'true'
        }

        response = requests.get(search_url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        datasets = response.json()

        formatted = []
        for d in datasets:
            formatted.append({
                'id': d.get('id', ''),
                'name': d.get('id', ''),
                'description': d.get('description', ''),
                'downloads': d.get('downloads', 0),
                'likes': d.get('likes', 0),
                'last_modified': d.get('lastModified', ''),
                'created_at': d.get('createdAt', ''),
                'tags': d.get('tags', []),
                'author': d.get('author', ''),
            })
        return formatted

    def create_manual_task(self, dataset_id, priority=0, storage_path='', force=False, tar_config=None):
        """手动创建任务"""
        # 验证数据集是否存在
        headers = {}
        if self.hf_token:
            headers['Authorization'] = f'Bearer {self.hf_token}'
        
        dataset_url = f"{self.hf_endpoint}/api/datasets/{dataset_id}"
        resp = requests.get(dataset_url, headers=headers, timeout=30)
        if resp.status_code == 404:
            raise ValueError(f"Dataset {dataset_id} not found")
        elif resp.status_code != 200:
            raise Exception(f"HF API error: {resp.status_code}")

        if force:
            existing = self.queue_manager.get_task_by_dataset_id(dataset_id)
            if existing:
                self.queue_manager.delete_task(existing['id'])

        added = self.queue_manager.add_to_queue(dataset_id, priority, storage_path, tar_config)
        
        message = "Task created"
        if not added:
            existing = self.queue_manager.get_task_by_dataset_id(dataset_id)
            if existing and existing['status'] in ('completed', 'downloading'):
                 raise ValueError(f"Dataset already in queue with status: {existing['status']}")
            message = "Task updated"

        task = self.queue_manager.get_task_by_dataset_id(dataset_id)
        
        # 通知 RabbitMQ
        if self.rabbitmq_handler:
            task_info = {
                'dataset_id': dataset_id,
                'priority': priority,
                'storage_path': storage_path,
                'created_at': datetime.now().isoformat(),
                'manual': True
            }
            if tar_config:
                task_info['tar_config'] = tar_config
                
            self.rabbitmq_handler.send_message(task_info)
        
        return task, message
