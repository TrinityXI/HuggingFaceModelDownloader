import logging
import json
from datetime import datetime
from typing import Dict, List, Optional

from app.crud.task import task_crud
from app.crud.event import event_crud
from app.crud.dataset import dataset_crud
from app.core.config import settings

logger = logging.getLogger(__name__)

class QueueService:
    def fetch_tasks(self, worker_id: str, limit: int = 1):
        return task_crud.fetch_tasks_batch(limit)

    def update_status(self, dataset_id: str, status: str, message: str = None, storage_path: str = None):
        task = task_crud.get_by_dataset_id(dataset_id)
        if not task:
            raise ValueError(f"Task not found: {dataset_id}")
        
        task_crud.update_status(task['id'], status, message, storage_path)
        
        if status == 'completed':
            self._upsert_dataset_record(dataset_id)

    def update_progress(self, dataset_id: str, progress_data: dict):
        task = task_crud.get_by_dataset_id(dataset_id)
        if not task:
            raise ValueError(f"Task not found: {dataset_id}")
        task_crud.update_progress(dataset_id, progress_data)

    def log_event(self, dataset_id: str, event_type: str, message: str = "", metadata: dict = None):
        event_crud.log(dataset_id, event_type, message, metadata)

    def fetch_interrupted_tasks(self, worker_id: str, limit: int = 1, timeout_minutes: int = 30):
        tasks = []
        for _ in range(limit):
            task = task_crud.claim_interrupted(worker_id, timeout_minutes)
            if task:
                tasks.append(task)
            else:
                break
        return tasks
    
    def get_interrupted_tasks(self, timeout_minutes: int = 30):
        return task_crud.get_interrupted(timeout_minutes)
    
    def reset_interrupted_tasks(self, timeout_minutes: int = 30):
        return task_crud.reset_interrupted(timeout_minutes)

    def get_overview_stats(self):
        raw_stats = task_crud.get_queue_stats()
        
        status_counts = {
            'pending': raw_stats.get('pending', 0),
            'downloading': raw_stats.get('downloading', 0),
            'completed': raw_stats.get('completed', 0),
            'failed': raw_stats.get('failed', 0)
        }
        
        return {
            'status_counts': status_counts,
            'today_added': raw_stats.get('today_added', 0),
            'today_completed': raw_stats.get('today_completed', 0),
            'failed_count': raw_stats.get('failed', 0),
            'timestamp': datetime.now().isoformat()
        }

    def get_timeline_stats(self, days: int = 7):
        completed, created = task_crud.get_timeline_stats(days)
        for item in completed + created:
            if item.get('date'):
                item['date'] = item['date'].isoformat()
        return {
            'completed_timeline': completed,
            'created_timeline': created
        }

    def get_queue_list(self, page=1, per_page=20, status=None, dataset_id=None, priority=None):
        tasks, total = task_crud.get_list(page, per_page, status, dataset_id, priority)
        # Format tasks
        formatted = []
        for task in tasks:
            for key in ['created_at', 'started_at', 'completed_at', 'updated_at']:
                if task.get(key):
                    task[key] = task[key].isoformat()
            
            # Construct progress object
            if task.get('progress_percentage') is not None or task.get('total_files', 0) > 0:
                task['progress'] = {
                    'percentage': float(task.get('progress_percentage', 0)),
                    'downloaded_bytes': task.get('downloaded_bytes', 0),
                    'total_bytes': task.get('total_bytes', 0),
                    'total_files': task.get('total_files', 0),
                    'completed_files': task.get('completed_files', 0),
                    'download_speed': float(task.get('download_speed', 0)),
                    'progress_status': task.get('progress_status', 'pending'),
                }
                # Cleanup flat fields
                for key in ['progress_percentage', 'downloaded_bytes', 'total_bytes', 
                           'total_files', 'completed_files', 'download_speed', 'progress_status']:
                    if key in task:
                        del task[key]
            formatted.append(task)
            
        return {
            'tasks': formatted,
            'total': total,
            'page': page,
            'per_page': per_page,
            'total_pages': (total + per_page - 1) // per_page
        }

    def get_task_detail(self, task_id: int):
        task = task_crud.get_by_id(task_id)
        if not task:
            return None
        
        for key in ['created_at', 'started_at', 'completed_at', 'updated_at']:
            if task.get(key):
                task[key] = task[key].isoformat()
        
        events = event_crud.get_by_dataset(task['dataset_id'])
        for event in events:
            if event.get('created_at'):
                event['created_at'] = event['created_at'].isoformat()
            if event.get('metadata'):
                try:
                    if isinstance(event['metadata'], str):
                        event['metadata'] = json.loads(event['metadata'])
                except:
                    pass
        task['events'] = events
        return task
    
    def get_task_progress(self, task_id: int):
        task = task_crud.get_by_id(task_id)
        if not task:
            return None
        
        if task['status'] == 'completed':
            return {'percentage': 100.0, 'status': 'completed', 'progress_status': 'completed'}
            
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

    def delete_task(self, task_id: int):
        return task_crud.delete(task_id)

    def retry_task(self, task_id: int):
        return task_crud.retry(task_id)

    def create_manual_task(self, dataset_id: str, priority: int = 0, storage_path: str = '', force: bool = False, tar_config: dict = None):
        # Validation of dataset existence via HF API should be done in Scanner or here?
        # Let's keep it here but using a util from scanner if possible.
        # For now, just DB logic.
        
        if force:
            existing = task_crud.get_by_dataset_id(dataset_id)
            if existing:
                task_crud.delete(existing['id'])
        
        added = task_crud.add_to_queue(dataset_id, priority, storage_path, tar_config)
        message = "Task created"
        if not added:
            existing = task_crud.get_by_dataset_id(dataset_id)
            if existing and existing['status'] in ('completed', 'downloading'):
                raise ValueError(f"Dataset already in queue with status: {existing['status']}")
            message = "Task updated"
            
        task = task_crud.get_by_dataset_id(dataset_id)
        return task, message

    def _upsert_dataset_record(self, dataset_id: str):
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
        dataset_crud.upsert(dataset)

queue_service = QueueService()
