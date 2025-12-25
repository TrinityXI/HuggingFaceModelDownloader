import logging
import json
from datetime import datetime
from typing import Dict
from app.crud.base import db

logger = logging.getLogger(__name__)

class DatasetCRUD:
    def upsert(self, dataset_info: Dict) -> bool:
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                
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
                    tags = json.dumps(tags)
                
                last_modified = dataset_info.get('lastModified') or dataset_info.get('last_modified')
                created_at_hf = dataset_info.get('createdAt') or dataset_info.get('created_at')
                
                def parse_time(t):
                    if not t: return None
                    if isinstance(t, datetime): return t
                    try:
                        return datetime.fromisoformat(str(t).replace('Z', '+00:00'))
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

    def get_by_dataset_id(self, dataset_id: str):
        """Get dataset by dataset_id"""
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM datasets
                    WHERE id = %s
                    LIMIT 1
                """, (dataset_id,))
                result = cursor.fetchone()
                return result
        except Exception as e:
            logger.error(f"Get dataset by id failed: {e}")
            return None

    def search(self, query: str, limit: int = 20):
        # NOTE: This searches local DB.
        # The original code searched HF API directly in core.py.
        # This CRUD is for the 'datasets' table which is a cache/metadata store.
        # If we want to search local cache:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM datasets
                WHERE id LIKE %s OR name LIKE %s
                LIMIT %s
            """, (f"%{query}%", f"%{query}%", limit))
            return cursor.fetchall()

dataset_crud = DatasetCRUD()
