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
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

# 导入现有模块
from query_datasets_by_date import HuggingFaceDatasetQuery
from dataset_db import DatasetDB


class LightweightProducer:
    def __init__(self, db_path="datasets.db", endpoint="https://huggingface.co", token=None):
        self.db_path = db_path
        self.db = DatasetDB(db_path)
        self.query = HuggingFaceDatasetQuery(endpoint=endpoint, token=token)
        self._init_queue_table()

    def _init_queue_table(self):
        """初始化下载队列表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS download_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dataset_id TEXT UNIQUE NOT NULL,
                priority INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',
                retry_count INTEGER DEFAULT 0,
                last_error TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                started_at TEXT,
                completed_at TEXT,
                FOREIGN KEY (dataset_id) REFERENCES datasets(dataset_id)
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_queue_status_priority
            ON download_queue(status, priority DESC)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_queue_status
            ON download_queue(status)
        """)

        conn.commit()
        conn.close()

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

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # 检查是否已存在
            cursor.execute(
                "SELECT status FROM download_queue WHERE dataset_id = ?",
                (dataset_id,)
            )
            existing = cursor.fetchone()

            if existing:
                status = existing[0]
                # 如果已完成或正在下载，跳过
                if status in ('completed', 'downloading'):
                    return False
                # 如果是 pending 或 failed，更新优先级
                cursor.execute(
                    "UPDATE download_queue SET priority = ? WHERE dataset_id = ?",
                    (priority, dataset_id)
                )
            else:
                # 插入新任务
                cursor.execute(
                    """
                    INSERT INTO download_queue (dataset_id, priority, status)
                    VALUES (?, ?, 'pending')
                    """,
                    (dataset_id, priority)
                )

            conn.commit()
            return True

        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()

    def _calculate_priority(self, dataset):
        """计算优先级（简单算法）"""
        downloads = dataset.get('downloads', 0)
        likes = dataset.get('likes', 0)

        # 优先级 = 下载数/1000 + 点赞数
        score = int(downloads / 1000) + likes
        return min(score, 9999)  # 限制最大值


def main():
    parser = argparse.ArgumentParser(description="轻量级数据集队列生产者")
    parser.add_argument("--db", default="datasets.db", help="数据库路径")
    parser.add_argument("--days", type=int, default=7, help="扫描最近 N 天")
    parser.add_argument("--limit", type=int, default=1000, help="每天最多查询 N 个")
    parser.add_argument("--min-downloads", type=int, default=0, help="最小下载量过滤")
    parser.add_argument("--min-likes", type=int, default=0, help="最小点赞数过滤")
    parser.add_argument("--endpoint", default="https://huggingface.co", help="HF API 端点")
    parser.add_argument("--token", help="HF Token（或使用 HF_TOKEN 环境变量）")

    args = parser.parse_args()

    token = args.token or os.getenv("HF_TOKEN")

    producer = LightweightProducer(
        db_path=args.db,
        endpoint=args.endpoint,
        token=token
    )

    producer.scan_and_queue(
        days=args.days,
        limit_per_day=args.limit,
        min_downloads=args.min_downloads,
        min_likes=args.min_likes
    )


if __name__ == "__main__":
    main()

