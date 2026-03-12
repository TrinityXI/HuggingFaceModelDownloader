import logging
import json
from typing import Optional, Dict, List
from app.crud.base import db

logger = logging.getLogger(__name__)

class TaskCRUD:
    def delete_batch(self, task_ids: List[int]) -> int:
        """批量删除任务，返回删除数量"""
        if not task_ids:
            return 0
        with db.get_connection() as conn:
            cursor = conn.cursor()
            format_strings = ','.join(['%s'] * len(task_ids))
            cursor.execute(f"DELETE FROM download_queue WHERE id IN ({format_strings})", tuple(task_ids))
            return cursor.rowcount

    def add_to_queue(self, dataset_id: str, priority: int = 0, storage_path: str = '',
                     tar_config: Optional[Dict] = None, repo_type: str = 'dataset') -> bool:
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
        
        with db.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "SELECT status FROM download_queue WHERE dataset_id = %s",
                    (dataset_id,)
                )
                existing = cursor.fetchone()
                
                if existing:
                    status = existing['status']
                    if status in ('completed', 'downloading'):
                        return False
                    cursor.execute(
                        """UPDATE download_queue 
                           SET priority = %s, storage_path = %s, 
                               tar_enabled = %s, tar_compress = %s, 
                               tar_split_size = %s, tar_split_threshold = %s, 
                               tar_delete_source = %s, repo_type = %s, updated_at = NOW() 
                           WHERE dataset_id = %s""",
                        (priority, storage_path, tar_enabled, tar_compress,
                         tar_split_size, tar_split_threshold, tar_delete_source, repo_type, dataset_id)
                    )
                else:
                    cursor.execute(
                        """INSERT INTO download_queue 
                           (dataset_id, priority, status, storage_path,
                            tar_enabled, tar_compress, tar_split_size, 
                            tar_split_threshold, tar_delete_source, repo_type)
                           VALUES (%s, %s, 'pending', %s, %s, %s, %s, %s, %s, %s)""",
                        (dataset_id, priority, storage_path, tar_enabled, tar_compress,
                         tar_split_size, tar_split_threshold, tar_delete_source, repo_type)
                    )
                return True
            except Exception:
                return False

    def fetch_tasks_batch(self, limit: int = 1) -> List[Dict]:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, dataset_id, priority, retry_count, storage_path,
                       tar_enabled, tar_compress, tar_split_size, 
                       tar_split_threshold, tar_delete_source, repo_type
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
                format_strings = ','.join(['%s'] * len(ids))
                cursor.execute(f"""
                    UPDATE download_queue
                    SET status = 'downloading', started_at = NOW()
                    WHERE id IN ({format_strings})
                """, tuple(ids))
            return rows

    def update_status(self, task_id: int, status: str, error_msg: Optional[str] = None, storage_path: Optional[str] = None) -> bool:
        with db.get_connection() as conn:
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

    def update_progress(self, dataset_id: str, progress_data: dict):
        with db.get_connection() as conn:
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

    def get_by_dataset_id(self, dataset_id: str) -> Optional[Dict]:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT *
                FROM download_queue
                WHERE dataset_id = %s
            """, (dataset_id,))
            return cursor.fetchone()

    def get_by_id(self, task_id: int) -> Optional[Dict]:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT *
                FROM download_queue
                WHERE id = %s
            """, (task_id,))
            return cursor.fetchone()

    def delete(self, task_id: int) -> bool:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM download_queue WHERE id = %s", (task_id,))
            return cursor.rowcount > 0

    def retry(self, task_id: int) -> bool:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE download_queue
                SET status = 'pending', retry_count = 0, last_error = NULL
                WHERE id = %s AND status = 'failed'
            """, (task_id,))
            return cursor.rowcount > 0

    def get_queue_stats(self) -> Dict:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT status, COUNT(*) as count
                FROM download_queue
                GROUP BY status
            """)
            stats = {row['status']: row['count'] for row in cursor.fetchall()}
            for status in ['pending', 'downloading', 'completed', 'failed']:
                if status not in stats:
                    stats[status] = 0
            
            # Today added
            cursor.execute("SELECT COUNT(*) as count FROM download_queue WHERE DATE(created_at) = CURDATE()")
            stats['today_added'] = cursor.fetchone()['count']
            
            # Today completed
            cursor.execute("SELECT COUNT(*) as count FROM download_queue WHERE DATE(completed_at) = CURDATE() AND status = 'completed'")
            stats['today_completed'] = cursor.fetchone()['count']
            
            return stats

    def get_list(self, page=1, per_page=20, status=None, dataset_id=None, priority=None):
        offset = (page - 1) * per_page
        with db.get_connection() as conn:
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

            # Count
            count_query = f"SELECT COUNT(*) as total FROM download_queue {where_clause}"
            cursor.execute(count_query, tuple(query_params))
            total = cursor.fetchone()['total']

            # Data
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
            return tasks, total

    def get_list_with_sort(self, status: str = None, limit: int = 10,
                          sort_by: str = None, sort_order: str = 'desc') -> Dict:
        """获取任务列表（支持排序和状态过滤）

        Args:
            status: 状态过滤
            limit: 返回数量限制
            sort_by: 排序字段
            sort_order: 排序方向 (asc/desc)

        Returns:
            任务列表字典
        """
        with db.get_connection() as conn:
            cursor = conn.cursor()

            # 构建WHERE条件
            where_conditions = []
            query_params = []

            if status:
                where_conditions.append("status = %s")
                query_params.append(status)

            where_clause = "WHERE " + " AND ".join(where_conditions) if where_conditions else ""

            # 构建ORDER BY
            valid_sort_fields = {
                'priority': 'priority',
                'progress_percentage': 'progress_percentage',
                'downloaded_bytes': 'downloaded_bytes',
                'created_at': 'created_at',
                'updated_at': 'updated_at',
                'download_speed': 'download_speed'
            }

            if sort_by and sort_by in valid_sort_fields:
                order_field = valid_sort_fields[sort_by]
            else:
                # 默认排序：按优先级和创建时间
                order_field = "priority DESC, created_at"
                sort_by = None

            sort_order = sort_order.upper() if sort_order else 'DESC'
            if sort_by:
                order_clause = f"ORDER BY {order_field} {sort_order}"
            else:
                order_clause = f"ORDER BY {order_field} DESC"

            # 执行查询
            query = f"""
                SELECT id, dataset_id, priority, status, retry_count, last_error,
                       storage_path, created_at, started_at, completed_at, updated_at,
                       progress_percentage, downloaded_bytes, total_bytes,
                       total_files, completed_files, download_speed, progress_status
                FROM download_queue
                {where_clause}
                {order_clause}
                LIMIT %s
            """
            cursor.execute(query, tuple(query_params + [limit]))
            tasks = cursor.fetchall()

            return {
                'tasks': tasks,
                'count': len(tasks)
            }

    def get_timeline_stats(self, days=7):
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DATE(completed_at) as date, COUNT(*) as count
                FROM download_queue
                WHERE completed_at >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
                  AND status = 'completed'
                GROUP BY DATE(completed_at)
                ORDER BY date DESC
            """, (days,))
            completed = list(cursor.fetchall())
            
            cursor.execute("""
                SELECT DATE(created_at) as date, COUNT(*) as count
                FROM download_queue
                WHERE created_at >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
                GROUP BY DATE(created_at)
                ORDER BY date DESC
            """, (days,))
            created = list(cursor.fetchall())
            return completed, created

    def get_interrupted(self, timeout_minutes=30):
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, dataset_id, priority, retry_count, storage_path,
                       progress_percentage, downloaded_bytes, total_bytes,
                       started_at, updated_at
                FROM download_queue
                WHERE status = 'downloading'
                  AND (updated_at < DATE_SUB(NOW(), INTERVAL %s MINUTE)
                       OR updated_at IS NULL)
                ORDER BY priority DESC, id ASC
            """, (timeout_minutes,))
            return cursor.fetchall()

    def reset_interrupted(self, timeout_minutes=30):
        with db.get_connection() as conn:
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
            return cursor.rowcount

    def claim_interrupted(self, worker_id, timeout_minutes=30):
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, dataset_id, priority, retry_count, storage_path,
                       tar_enabled, tar_compress, tar_split_size,
                       tar_split_threshold, tar_delete_source, repo_type,
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
            cursor.execute("""
                UPDATE download_queue
                SET started_at = NOW(),
                    updated_at = NOW(),
                    progress_percentage = 0,
                    downloaded_bytes = 0,
                    progress_status = 'downloading'
                WHERE id = %s
            """, (task['id'],))
            return task

task_crud = TaskCRUD()
