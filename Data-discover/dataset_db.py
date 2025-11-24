#!/usr/bin/env python3
"""
数据集数据库模块

用于存储和查询 Hugging Face 数据集的元数据
"""

import sqlite3
import json
from datetime import datetime, timezone
from typing import Optional, Dict, List
from pathlib import Path


class DatasetDB:
    """数据集数据库管理类"""
    
    def __init__(self, db_path: str = "datasets.db"):
        """
        初始化数据库
        
        Args:
            db_path: 数据库文件路径
        """
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """初始化数据库表结构"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 创建数据集表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS datasets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dataset_id TEXT UNIQUE NOT NULL,
                author TEXT,
                name TEXT,
                created_at TEXT,
                last_modified TEXT,
                downloads INTEGER DEFAULT 0,
                likes INTEGER DEFAULT 0,
                tags TEXT,
                metadata TEXT,
                first_discovered_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_checked_at TEXT DEFAULT CURRENT_TIMESTAMP,
                change_count INTEGER DEFAULT 0,
                UNIQUE(dataset_id)
            )
        """)
        
        # 创建变更历史表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS change_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dataset_id TEXT NOT NULL,
                field_name TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT,
                changed_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (dataset_id) REFERENCES datasets(dataset_id)
            )
        """)
        
        # 创建索引
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_dataset_id ON datasets(dataset_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_last_modified ON datasets(last_modified)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_last_checked ON datasets(last_checked_at)
        """)
        
        conn.commit()
        conn.close()
    
    def upsert_dataset(self, dataset: Dict) -> bool:
        """
        插入或更新数据集信息
        
        Args:
            dataset: 数据集字典，包含 id, author, name, createdAt, lastModified 等字段
        
        Returns:
            如果数据集有更新，返回 True；如果是新数据集，返回 False
        """
        dataset_id = dataset.get("id", "")
        if not dataset_id:
            return False
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 检查数据集是否已存在
        cursor.execute("SELECT last_modified, change_count FROM datasets WHERE dataset_id = ?", (dataset_id,))
        existing = cursor.fetchone()
        
        is_update = existing is not None
        old_last_modified = existing[0] if existing else None
        change_count = existing[1] if existing else 0
        
        # 准备数据
        author = dataset.get("author", "")
        name = dataset.get("name", "")
        created_at = dataset.get("createdAt", "")
        last_modified = dataset.get("lastModified", "")
        downloads = dataset.get("downloads", 0)
        likes = dataset.get("likes", 0)
        tags = json.dumps(dataset.get("tags", []))
        metadata = json.dumps(dataset)
        
        now = datetime.now(timezone.utc).isoformat()
        
        if is_update:
            # 更新现有数据集
            cursor.execute("""
                UPDATE datasets 
                SET author = ?, name = ?, created_at = ?, last_modified = ?,
                    downloads = ?, likes = ?, tags = ?, metadata = ?,
                    last_checked_at = ?, change_count = change_count + 1
                WHERE dataset_id = ?
            """, (author, name, created_at, last_modified, downloads, likes, tags, metadata, now, dataset_id))
            
            # 如果 last_modified 改变了，记录变更历史
            if old_last_modified != last_modified:
                cursor.execute("""
                    INSERT INTO change_history (dataset_id, field_name, old_value, new_value)
                    VALUES (?, ?, ?, ?)
                """, (dataset_id, "last_modified", old_last_modified, last_modified))
                change_count += 1
        else:
            # 插入新数据集
            cursor.execute("""
                INSERT INTO datasets 
                (dataset_id, author, name, created_at, last_modified, downloads, likes, tags, metadata, first_discovered_at, last_checked_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (dataset_id, author, name, created_at, last_modified, downloads, likes, tags, metadata, now, now))
        
        conn.commit()
        conn.close()
        
        return is_update
    
    def get_dataset(self, dataset_id: str) -> Optional[Dict]:
        """
        获取数据集信息
        
        Args:
            dataset_id: 数据集 ID，例如 "hoangphuongnam19933/hoangphuongnam19933"
        
        Returns:
            数据集信息字典，如果不存在返回 None
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM datasets WHERE dataset_id = ?", (dataset_id,))
        row = cursor.fetchone()
        
        conn.close()
        
        if row:
            return dict(row)
        return None
    
    def check_updated(self, dataset_id: str, current_last_modified: str) -> Dict:
        """
        检查数据集是否已更新
        
        Args:
            dataset_id: 数据集 ID
            current_last_modified: 当前的最后修改时间
        
        Returns:
            包含更新信息的字典：
            {
                "exists": bool,  # 数据集是否存在
                "updated": bool,  # 是否已更新
                "old_last_modified": str,  # 旧的最后修改时间
                "new_last_modified": str   # 新的最后修改时间
            }
        """
        dataset = self.get_dataset(dataset_id)
        
        if not dataset:
            return {
                "exists": False,
                "updated": False,
                "old_last_modified": None,
                "new_last_modified": current_last_modified
            }
        
        old_last_modified = dataset.get("last_modified", "")
        updated = old_last_modified != current_last_modified
        
        return {
            "exists": True,
            "updated": updated,
            "old_last_modified": old_last_modified,
            "new_last_modified": current_last_modified
        }
    
    def get_all_datasets(self, limit: Optional[int] = None) -> List[Dict]:
        """
        获取所有数据集
        
        Args:
            limit: 限制返回数量
        
        Returns:
            数据集列表
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        query = "SELECT * FROM datasets ORDER BY last_checked_at DESC"
        if limit:
            query += f" LIMIT {limit}"
        
        cursor.execute(query)
        rows = cursor.fetchall()
        
        conn.close()
        
        return [dict(row) for row in rows]
    
    def get_change_history(self, dataset_id: str, limit: int = 10) -> List[Dict]:
        """
        获取数据集的变更历史
        
        Args:
            dataset_id: 数据集 ID
            limit: 限制返回数量
        
        Returns:
            变更历史列表
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM change_history 
            WHERE dataset_id = ? 
            ORDER BY changed_at DESC 
            LIMIT ?
        """, (dataset_id, limit))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def get_datasets_by_date_range(self, start_date: str, end_date: str, use_created_at: bool = False) -> List[Dict]:
        """
        获取指定日期范围内的数据集
        
        Args:
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
            use_created_at: 如果为 True，使用 created_at；否则使用 last_modified
        
        Returns:
            数据集列表
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        date_field = "created_at" if use_created_at else "last_modified"
        
        cursor.execute(f"""
            SELECT * FROM datasets 
            WHERE {date_field} >= ? AND {date_field} < ?
            ORDER BY {date_field} DESC
        """, (start_date, end_date))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]

