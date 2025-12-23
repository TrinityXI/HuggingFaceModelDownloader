#!/usr/bin/env python3
"""
MySQL 队列管理模块

用于管理下载队列，替代 SQLite
支持高并发、分布式访问
"""

import os
import pymysql
import logging
from datetime import datetime
from typing import Optional, Dict, List
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class MySQLQueueManager:
    """MySQL 下载队列管理类"""
    
    def __init__(self, config: Optional[Dict] = None):
        """
        初始化 MySQL 连接配置
        
        Args:
            config: 数据库配置字典，包含 host, port, user, password, database
        """
        if config is None:
            config = {
                'host': os.getenv('MYSQL_HOST', 'localhost'),
                'port': int(os.getenv('MYSQL_PORT', 3306)),
                'user': os.getenv('MYSQL_USER', 'root'),
                'password': os.getenv('MYSQL_PASSWORD', ''),
                'database': os.getenv('MYSQL_DATABASE', 'hf_datasets'),
                'charset': 'utf8mb4',
                'cursorclass': pymysql.cursors.DictCursor
            }
        
        self.config = config
        self._init_db()
    
    @contextmanager
    def get_connection(self):
        """获取数据库连接的上下文管理器"""
        conn = pymysql.connect(**self.config)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def _init_db(self):
        """初始化数据库表结构"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # 创建下载队列表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS download_queue (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    dataset_id VARCHAR(255) UNIQUE NOT NULL,
                    priority INT DEFAULT 0,
                    status ENUM('pending', 'downloading', 'completed', 'failed') DEFAULT 'pending',
                    retry_count INT DEFAULT 0,
                    last_error TEXT,
                    storage_path VARCHAR(512),
                    progress_percentage DECIMAL(5,2) DEFAULT 0.00,
                    downloaded_bytes BIGINT DEFAULT 0,
                    total_bytes BIGINT DEFAULT 0,
                    total_files INT DEFAULT 0,
                    completed_files INT DEFAULT 0,
                    download_speed DECIMAL(15,2) DEFAULT 0.00,
                    progress_status VARCHAR(32) DEFAULT 'pending',
                    tar_enabled BOOLEAN DEFAULT FALSE,
                    tar_compress BOOLEAN DEFAULT TRUE,
                    tar_split_size VARCHAR(32) DEFAULT '50GiB',
                    tar_split_threshold VARCHAR(32) DEFAULT '100GiB',
                    tar_delete_source BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    started_at TIMESTAMP NULL,
                    completed_at TIMESTAMP NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    INDEX idx_status_priority (status, priority DESC),
                    INDEX idx_status (status),
                    INDEX idx_dataset_id (dataset_id),
                    INDEX idx_created_at (created_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            
            # 检查并添加 storage_path 列（如果表已存在但没有此列）
            try:
                cursor.execute("""
                    SELECT storage_path FROM download_queue LIMIT 1
                """)
            except:
                # 列不存在，添加它
                cursor.execute("""
                    ALTER TABLE download_queue
                    ADD COLUMN storage_path VARCHAR(512) AFTER last_error
                """)
                logger.info("已添加 storage_path 列到 download_queue 表")
            
            # 检查并添加进度相关列
            try:
                cursor.execute("""
                    SELECT progress_percentage FROM download_queue LIMIT 1
                """)
            except:
                logger.info("添加进度相关列到 download_queue 表")
                cursor.execute("""
                    ALTER TABLE download_queue
                    ADD COLUMN progress_percentage DECIMAL(5,2) DEFAULT 0.00 AFTER storage_path,
                    ADD COLUMN downloaded_bytes BIGINT DEFAULT 0 AFTER progress_percentage,
                    ADD COLUMN total_bytes BIGINT DEFAULT 0 AFTER downloaded_bytes,
                    ADD COLUMN total_files INT DEFAULT 0 AFTER total_bytes,
                    ADD COLUMN completed_files INT DEFAULT 0 AFTER total_files,
                    ADD COLUMN download_speed DECIMAL(15,2) DEFAULT 0.00 AFTER completed_files,
                    ADD COLUMN progress_status VARCHAR(32) DEFAULT 'pending' AFTER download_speed
                """)
                logger.info("已添加进度相关列到 download_queue 表")
            
            # 检查并添加 progress_status 列（如果表已存在进度列但没有 progress_status）
            try:
                cursor.execute("""
                    SELECT progress_status FROM download_queue LIMIT 1
                """)
            except:
                logger.info("添加 progress_status 列到 download_queue 表")
                cursor.execute("""
                    ALTER TABLE download_queue
                    ADD COLUMN progress_status VARCHAR(32) DEFAULT 'pending' AFTER download_speed
                """)
                logger.info("已添加 progress_status 列到 download_queue 表")
            
            # 检查并添加 tar 配置相关列
            try:
                cursor.execute("""
                    SELECT tar_enabled FROM download_queue LIMIT 1
                """)
            except:
                logger.info("添加 tar 配置相关列到 download_queue 表")
                cursor.execute("""
                    ALTER TABLE download_queue
                    ADD COLUMN tar_enabled BOOLEAN DEFAULT FALSE AFTER progress_status,
                    ADD COLUMN tar_compress BOOLEAN DEFAULT TRUE AFTER tar_enabled,
                    ADD COLUMN tar_split_size VARCHAR(32) DEFAULT '50GiB' AFTER tar_compress,
                    ADD COLUMN tar_split_threshold VARCHAR(32) DEFAULT '100GiB' AFTER tar_split_size,
                    ADD COLUMN tar_delete_source BOOLEAN DEFAULT FALSE AFTER tar_split_threshold
                """)
                logger.info("已添加 tar 配置相关列到 download_queue 表")
            
            # 创建下载事件日志表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS download_events (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    dataset_id VARCHAR(255) NOT NULL,
                    event_type ENUM('start', 'complete', 'fail', 'retry') NOT NULL,
                    message TEXT,
                    metadata JSON,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_dataset_id (dataset_id),
                    INDEX idx_event_type (event_type),
                    INDEX idx_created_at (created_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)

            # 创建数据集元数据表 (替代 SQLite)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS datasets (
                    id VARCHAR(255) PRIMARY KEY,
                    author VARCHAR(255),
                    name VARCHAR(255),
                    downloads INT DEFAULT 0,
                    likes INT DEFAULT 0,
                    last_modified DATETIME,
                    created_at_hf DATETIME,
                    tags JSON,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    INDEX idx_downloads (downloads),
                    INDEX idx_likes (likes),
                    INDEX idx_last_modified (last_modified)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
    
    def upsert_dataset(self, dataset_info: Dict) -> bool:
        """
        更新或插入数据集元数据
        
        Args:
            dataset_info: 数据集信息字典
            
        Returns:
            是否成功
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # 提取字段
                dataset_id = dataset_info.get('id') or dataset_info.get('dataset_id')
                if not dataset_id:
                    return False
                    
                author = dataset_info.get('author', '')
                name = dataset_info.get('name', '')
                if not author or not name:
                    if '/' in dataset_id:
                        author, name = dataset_id.split('/', 1)
                    else:
                        name = dataset_id

                downloads = dataset_info.get('downloads', 0)
                likes = dataset_info.get('likes', 0)
                tags = dataset_info.get('tags', [])
                if isinstance(tags, list):
                    import json
                    tags = json.dumps(tags)
                
                # 处理时间格式
                last_modified = dataset_info.get('lastModified') or dataset_info.get('last_modified')
                created_at_hf = dataset_info.get('createdAt') or dataset_info.get('created_at')
                
                # 简单的 ISO 格式转换尝试 (如果需要更复杂的解析，建议在调用前处理)
                def parse_time(t):
                    if not t: return None
                    if isinstance(t, datetime): return t
                    try:
                        return datetime.fromisoformat(t.replace('Z', '+00:00'))
                    except:
                        return None

                last_modified_dt = parse_time(last_modified)
                created_at_hf_dt = parse_time(created_at_hf)

                cursor.execute("""
                    INSERT INTO datasets (
                        id, author, name, downloads, likes, 
                        last_modified, created_at_hf, tags
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        downloads = VALUES(downloads),
                        likes = VALUES(likes),
                        last_modified = VALUES(last_modified),
                        tags = VALUES(tags),
                        last_updated = NOW()
                """, (
                    dataset_id, author, name, downloads, likes,
                    last_modified_dt, created_at_hf_dt, tags
                ))
                
                return True
        except Exception as e:
            logger.error(f"Upsert dataset failed: {e}")
            return False

    def add_to_queue(self, dataset_id: str, priority: int = 0, storage_path: str = '',
                     tar_config: Optional[Dict] = None) -> bool:
        """
        添加数据集到下载队列

        Args:
            dataset_id: 数据集 ID
            priority: 优先级（越大优先级越高）
            storage_path: 存储路径
            tar_config: tar 压缩配置，包含 enabled, compress, split_size, split_threshold, delete_source

        Returns:
            是否成功添加（如果已存在则返回 False）
        """
        # 解析 tar 配置
        tar_enabled = False
        tar_compress = True
        tar_split_size = '50GiB'
        tar_split_threshold = '100GiB'
        tar_delete_source = False
        
        if tar_config:
            tar_enabled = tar_config.get('enabled', False)
            tar_compress = tar_config.get('compress', True)
            tar_split_size = tar_config.get('split_size', '50GiB')
            tar_split_threshold = tar_config.get('split_threshold', '100GiB')
            tar_delete_source = tar_config.get('delete_source', False)
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            try:
                # 检查是否已存在
                cursor.execute(
                    "SELECT status FROM download_queue WHERE dataset_id = %s",
                    (dataset_id,)
                )
                existing = cursor.fetchone()
                
                if existing:
                    status = existing['status']
                    # 如果已完成或正在下载，跳过
                    if status in ('completed', 'downloading'):
                        return False
                    # 如果是 pending 或 failed，更新优先级、存储路径和 tar 配置
                    cursor.execute(
                        """UPDATE download_queue 
                           SET priority = %s, storage_path = %s, 
                               tar_enabled = %s, tar_compress = %s, 
                               tar_split_size = %s, tar_split_threshold = %s, 
                               tar_delete_source = %s, updated_at = NOW() 
                           WHERE dataset_id = %s""",
                        (priority, storage_path, tar_enabled, tar_compress,
                         tar_split_size, tar_split_threshold, tar_delete_source, dataset_id)
                    )
                else:
                    # 插入新任务
                    cursor.execute(
                        """INSERT INTO download_queue 
                           (dataset_id, priority, status, storage_path,
                            tar_enabled, tar_compress, tar_split_size, 
                            tar_split_threshold, tar_delete_source)
                           VALUES (%s, %s, 'pending', %s, %s, %s, %s, %s, %s)""",
                        (dataset_id, priority, storage_path, tar_enabled, tar_compress,
                         tar_split_size, tar_split_threshold, tar_delete_source)
                    )
                
                return True
            except pymysql.IntegrityError:
                # 唯一键冲突，说明已存在
                return False
    
    def fetch_task(self) -> Optional[Dict]:
        """
        从队列获取一个待处理任务（带锁）
        
        Returns:
            任务字典或 None
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # 使用 SELECT ... FOR UPDATE 加锁
            cursor.execute("""
                SELECT id, dataset_id, priority, retry_count
                FROM download_queue
                WHERE status = 'pending'
                ORDER BY priority DESC, id ASC
                LIMIT 1
                FOR UPDATE
            """)
            
            row = cursor.fetchone()
            if not row:
                return None
            
            # 标记为正在处理
            cursor.execute("""
                UPDATE download_queue
                SET status = 'downloading', started_at = NOW()
                WHERE id = %s
            """, (row['id'],))
            
            return row
    
    def fetch_tasks_batch(self, limit: int = 1) -> List[Dict]:
        """
        批量获取待处理任务
        
        Args:
            limit: 获取数量
            
        Returns:
            任务列表
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # 选取任务（包括 tar 配置）
            cursor.execute("""
                SELECT id, dataset_id, priority, retry_count, storage_path,
                       tar_enabled, tar_compress, tar_split_size, 
                       tar_split_threshold, tar_delete_source
                FROM download_queue
                WHERE status = 'pending'
                ORDER BY priority DESC, id ASC
                LIMIT %s
                FOR UPDATE
            """, (limit,))
            
            rows = cursor.fetchall()
            if not rows:
                return []
            
            ids = [row['id'] for row in rows]
            if ids:
                # 批量更新状态
                format_strings = ','.join(['%s'] * len(ids))
                cursor.execute(f"""
                    UPDATE download_queue
                    SET status = 'downloading', started_at = NOW()
                    WHERE id IN ({format_strings})
                """, tuple(ids))
            
            return rows
    
    def update_status(self, task_id: int, status: str, error_msg: Optional[str] = None, storage_path: Optional[str] = None) -> bool:
        """
        更新任务状态
        
        Args:
            task_id: 任务 ID
            status: 新状态 ('downloading', 'completed', 'failed', 'pending')
            error_msg: 错误信息（仅用于失败状态）
            storage_path: 存储路径（仅用于完成状态）
        
        Returns:
            是否成功更新
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            if status == 'completed':
                if storage_path:
                    cursor.execute("""
                        UPDATE download_queue
                        SET status = %s, completed_at = NOW(), storage_path = %s
                        WHERE id = %s
                    """, (status, storage_path, task_id))
                else:
                    cursor.execute("""
                        UPDATE download_queue
                        SET status = %s, completed_at = NOW()
                        WHERE id = %s
                    """, (status, task_id))
            elif status == 'failed':
                cursor.execute("""
                    UPDATE download_queue
                    SET status = %s, last_error = %s
                    WHERE id = %s
                """, (status, error_msg, task_id))
            else:
                cursor.execute("""
                    UPDATE download_queue
                    SET status = %s
                    WHERE id = %s
                """, (status, task_id))
            
            return cursor.rowcount > 0
    
    def increment_retry(self, task_id: int, max_retries: int = 3, error_msg: Optional[str] = None) -> bool:
        """
        增加重试计数并重置为 pending 或标记为 failed
        
        Args:
            task_id: 任务 ID
            max_retries: 最大重试次数
            error_msg: 错误信息
        
        Returns:
            是否还可以重试（False 表示已达到最大重试次数）
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # 获取当前重试次数
            cursor.execute(
                "SELECT retry_count FROM download_queue WHERE id = %s",
                (task_id,)
            )
            row = cursor.fetchone()
            if not row:
                return False
            
            retry_count = row['retry_count'] + 1
            
            if retry_count >= max_retries:
                # 超过最大重试次数，标记为失败
                cursor.execute("""
                    UPDATE download_queue
                    SET status = 'failed', retry_count = %s, last_error = %s
                    WHERE id = %s
                """, (retry_count, error_msg, task_id))
                return False
            else:
                # 重置为 pending，允许重试
                cursor.execute("""
                    UPDATE download_queue
                    SET status = 'pending', retry_count = %s, last_error = %s
                    WHERE id = %s
                """, (retry_count, error_msg, task_id))
                return True
    
    def log_event(self, dataset_id: str, event_type: str, message: str = "", metadata: Optional[Dict] = None):
        """
        记录下载事件
        
        Args:
            dataset_id: 数据集 ID
            event_type: 事件类型 ('start', 'complete', 'fail', 'retry')
            message: 事件消息
            metadata: 附加元数据（JSON）
        """
        import json
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            metadata_json = json.dumps(metadata) if metadata else None
            
            cursor.execute("""
                INSERT INTO download_events (dataset_id, event_type, message, metadata)
                VALUES (%s, %s, %s, %s)
            """, (dataset_id, event_type, message, metadata_json))
    
    def get_queue_stats(self) -> Dict:
        """
        获取队列统计信息
        
        Returns:
            统计信息字典
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT 
                    status,
                    COUNT(*) as count
                FROM download_queue
                GROUP BY status
            """)
            
            stats = {row['status']: row['count'] for row in cursor.fetchall()}
            
            # 确保所有状态都有值
            for status in ['pending', 'downloading', 'completed', 'failed']:
                if status not in stats:
                    stats[status] = 0
            
            return stats
    
    def get_task_by_dataset_id(self, dataset_id: str) -> Optional[Dict]:
        """
        根据 dataset_id 获取任务信息
        
        Args:
            dataset_id: 数据集 ID
        
        Returns:
            任务字典或 None
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT id, dataset_id, priority, status, retry_count, last_error,
                       created_at, started_at, completed_at
                FROM download_queue
                WHERE dataset_id = %s
            """, (dataset_id,))
            
            return cursor.fetchone()
    
    def delete_task(self, task_id: int) -> bool:
        """
        删除任务
        
        Args:
            task_id: 任务 ID
        
        Returns:
            是否成功删除
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                DELETE FROM download_queue WHERE id = %s
            """, (task_id,))
            
            return cursor.rowcount > 0
    
    def get_interrupted_tasks(self, timeout_minutes: int = 30) -> List[Dict]:
        """
        获取中断的下载任务（状态为 downloading 但超过指定时间未更新）
        
        Args:
            timeout_minutes: 超时时间（分钟），超过此时间未更新的 downloading 任务被视为中断
        
        Returns:
            中断任务列表
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # 获取状态为 downloading 且超过 timeout_minutes 未更新的任务
            cursor.execute("""
                SELECT id, dataset_id, priority, retry_count, storage_path,
                       tar_enabled, tar_compress, tar_split_size,
                       tar_split_threshold, tar_delete_source,
                       progress_percentage, downloaded_bytes, total_bytes,
                       total_files, completed_files, started_at, updated_at
                FROM download_queue
                WHERE status = 'downloading'
                  AND (updated_at < DATE_SUB(NOW(), INTERVAL %s MINUTE)
                       OR updated_at IS NULL)
                ORDER BY priority DESC, id ASC
            """, (timeout_minutes,))
            
            return cursor.fetchall()
    
    def reset_interrupted_tasks(self, timeout_minutes: int = 30) -> int:
        """
        重置中断的下载任务为 pending 状态
        
        Args:
            timeout_minutes: 超时时间（分钟）
        
        Returns:
            重置的任务数量
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE download_queue
                SET status = 'pending',
                    started_at = NULL,
                    progress_percentage = 0,
                    downloaded_bytes = 0,
                    progress_status = 'pending'
                WHERE status = 'downloading'
                  AND (updated_at < DATE_SUB(NOW(), INTERVAL %s MINUTE)
                       OR updated_at IS NULL)
            """, (timeout_minutes,))
            
            count = cursor.rowcount
            if count > 0:
                logger.info(f"已重置 {count} 个中断的下载任务")
            
            return count
    
    def recover_task(self, dataset_id: str) -> Optional[Dict]:
        """
        恢复单个中断的任务（将 downloading 状态的任务重新标记为 pending）
        
        Args:
            dataset_id: 数据集 ID
        
        Returns:
            恢复的任务信息或 None
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # 先检查任务状态
            cursor.execute("""
                SELECT id, dataset_id, priority, status, retry_count, storage_path,
                       tar_enabled, tar_compress, tar_split_size,
                       tar_split_threshold, tar_delete_source
                FROM download_queue
                WHERE dataset_id = %s
            """, (dataset_id,))
            
            task = cursor.fetchone()
            if not task:
                return None
            
            if task['status'] != 'downloading':
                return None
            
            # 重置为 pending 状态
            cursor.execute("""
                UPDATE download_queue
                SET status = 'pending',
                    started_at = NULL,
                    progress_percentage = 0,
                    downloaded_bytes = 0,
                    progress_status = 'pending'
                WHERE dataset_id = %s AND status = 'downloading'
            """, (dataset_id,))
            
            if cursor.rowcount > 0:
                logger.info(f"已恢复任务: {dataset_id}")
                return task
            
            return None
    
    def claim_interrupted_task(self, worker_id: str, timeout_minutes: int = 30) -> Optional[Dict]:
        """
        认领一个中断的任务（直接将中断的 downloading 任务分配给当前 worker）
        
        Args:
            worker_id: Worker ID
            timeout_minutes: 超时时间（分钟）
        
        Returns:
            认领的任务或 None
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # 获取并锁定一个中断的任务
            cursor.execute("""
                SELECT id, dataset_id, priority, retry_count, storage_path,
                       tar_enabled, tar_compress, tar_split_size,
                       tar_split_threshold, tar_delete_source,
                       progress_percentage, downloaded_bytes, total_bytes
                FROM download_queue
                WHERE status = 'downloading'
                  AND (updated_at < DATE_SUB(NOW(), INTERVAL %s MINUTE)
                       OR updated_at IS NULL)
                ORDER BY priority DESC, id ASC
                LIMIT 1
                FOR UPDATE
            """, (timeout_minutes,))
            
            task = cursor.fetchone()
            if not task:
                return None
            
            # 更新任务状态，重新开始
            cursor.execute("""
                UPDATE download_queue
                SET started_at = NOW(),
                    updated_at = NOW(),
                    progress_percentage = 0,
                    downloaded_bytes = 0,
                    progress_status = 'downloading'
                WHERE id = %s
            """, (task['id'],))
            
            logger.info(f"Worker {worker_id} 认领了中断的任务: {task['dataset_id']}")
            return task
