#!/usr/bin/env python3
"""
Producer 核心逻辑
负责扫描 Hugging Face 数据集并添加到队列
"""

import json
import logging
import os
import sys
from datetime import datetime, timedelta

# 添加 Data-discover 目录到 Python 路径
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'Data-discover'))
from query_datasets_by_date import HuggingFaceDatasetQuery
from dataset_db import DatasetDB
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

        # Dataset 元数据数据库 (SQLite)
        self.dataset_db = None
        db_path = os.getenv('SQLITE_DB_PATH', '')
        if db_path:
            try:
                self.dataset_db = DatasetDB(db_path)
                logger.info(f"SQLite元数据数据库已启用: {db_path}")
            except Exception as e:
                logger.warning(f"无法初始化SQLite数据库: {e}")

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

                # 添加到元数据数据库
                if self.dataset_db:
                    try:
                        self.dataset_db.upsert_dataset(dataset)
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
        return success_count, skipped_count

    def scan_and_enqueue(self):
        """扫描并添加到队列（组合操作）"""
        datasets = self.scan_datasets()
        if not datasets:
            logger.warning("未找到有效数据集")
            return 0, 0

        return self.add_datasets_to_queue(datasets)
