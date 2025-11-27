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
    
    def add_to_queue(self, dataset_id: str, priority: int = 0) -> bool:
        """
        添加数据集到下载队列
        
        Args:
            dataset_id: 数据集 ID
            priority: 优先级（越大优先级越高）
        
        Returns:
            是否成功添加（如果已存在则返回 False）
        """
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
                    # 如果是 pending 或 failed，更新优先级
                    cursor.execute(
                        "UPDATE download_queue SET priority = %s, updated_at = NOW() WHERE dataset_id = %s",
                        (priority, dataset_id)
                    )
                else:
                    # 插入新任务
                    cursor.execute(
                        """INSERT INTO download_queue (dataset_id, priority, status)
                           VALUES (%s, %s, 'pending')""",
                        (dataset_id, priority)
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
