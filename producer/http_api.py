#!/usr/bin/env python3
"""
Producer HTTP API
提供 REST API 供 consumer 调用
"""

import logging
from datetime import datetime
from flask import Flask, request, jsonify

logger = logging.getLogger(__name__)


def create_http_api(producer_core):
    """创建 Flask HTTP API 应用"""
    app = Flask(__name__)

    @app.route('/api/consumer/health', methods=['GET'])
    def health_check():
        """健康检查"""
        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'service': 'producer'
        })

    @app.route('/api/consumer/fetch-tasks', methods=['POST'])
    def fetch_tasks():
        """
        Consumer 拉取待处理任务
        Request body: {"worker_id": "consumer-1", "limit": 5}
        """
        try:
            data = request.get_json() or {}
            worker_id = data.get('worker_id', 'unknown')
            limit = min(int(data.get('limit', 1)), 10)

            tasks = producer_core.queue_manager.fetch_tasks_batch(limit=limit)

            if not tasks:
                return jsonify({'tasks': [], 'count': 0, 'message': 'No tasks available'})

            formatted_tasks = []
            for task in tasks:
                task_data = {
                    'task_id': task['id'],
                    'dataset_id': task['dataset_id'],
                    'storage_path': task.get('storage_path', ''),
                    'priority': task['priority'],
                    'retry_count': task['retry_count']
                }
                
                # 添加 tar 配置（如果存在）
                if task.get('tar_enabled'):
                    task_data['tar_config'] = {
                        'enabled': True,
                        'compress': task.get('tar_compress', True),
                        'split_size': task.get('tar_split_size', '50GiB'),
                        'split_threshold': task.get('tar_split_threshold', '100GiB'),
                        'delete_source': task.get('tar_delete_source', False)
                    }
                
                formatted_tasks.append(task_data)

            logger.info(f"Worker {worker_id} 拉取了 {len(formatted_tasks)} 个任务")
            return jsonify({'tasks': formatted_tasks, 'count': len(formatted_tasks)})

        except Exception as e:
            logger.error(f"拉取任务失败: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/consumer/update-status', methods=['POST'])
    def update_status():
        """
        Consumer 更新任务状态
        Request body: {"dataset_id": "user/dataset", "status": "downloading|completed|failed",
                      "message": "...", "storage_path": "..."}
        """
        try:
            data = request.get_json()
            if not data:
                return jsonify({'error': 'Request body is required'}), 400

            dataset_id = data.get('dataset_id')
            status = data.get('status')
            message = data.get('message', '')
            storage_path = data.get('storage_path', '')

            if not dataset_id or not status:
                return jsonify({'error': 'dataset_id and status are required'}), 400

            if status not in ['downloading', 'completed', 'failed', 'pending']:
                return jsonify({'error': 'Invalid status'}), 400

            task = producer_core.queue_manager.get_task_by_dataset_id(dataset_id)
            if not task:
                return jsonify({'error': 'Task not found'}), 404

            producer_core.queue_manager.update_status(
                task['id'],
                status,
                message if status == 'failed' else None,
                storage_path if status == 'completed' else None
            )

            # 如果是完成状态，创建 dataset 记录
            if status == 'completed' and producer_core.dataset_db:
                try:
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
                    producer_core.dataset_db.upsert_dataset(dataset)
                except Exception as e:
                    logger.warning(f"创建 dataset 记录失败: {e}")

            logger.info(f"任务状态已更新: {dataset_id} -> {status}")
            return jsonify({'message': 'Status updated successfully', 'dataset_id': dataset_id, 'status': status})

        except Exception as e:
            logger.error(f"更新状态失败: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/consumer/update-progress', methods=['POST'])
    def update_progress():
        """
        Consumer 更新下载进度
        Request body: {"dataset_id": "user/dataset", "percentage": 45.5, ...}
        """
        try:
            data = request.get_json()
            if not data:
                return jsonify({'error': 'Request body is required'}), 400

            dataset_id = data.get('dataset_id')
            if not dataset_id:
                return jsonify({'error': 'dataset_id is required'}), 400

            task = producer_core.queue_manager.get_task_by_dataset_id(dataset_id)
            if not task:
                return jsonify({'error': 'Task not found'}), 404

            with producer_core.queue_manager.get_connection() as conn:
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
                    data.get('percentage', 0),
                    data.get('downloaded_bytes', 0),
                    data.get('total_bytes', 0),
                    data.get('total_files', 0),
                    data.get('completed_files', 0),
                    data.get('download_speed', 0),
                    data.get('progress_status', 'downloading'),
                    dataset_id
                ))

            return jsonify({'message': 'Progress updated successfully', 'dataset_id': dataset_id})

        except Exception as e:
            logger.error(f"更新进度失败: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/consumer/log-event', methods=['POST'])
    def log_event():
        """
        Consumer 记录事件
        Request body: {"dataset_id": "user/dataset", "event_type": "start", "message": "...", "metadata": {}}
        """
        try:
            data = request.get_json()
            if not data:
                return jsonify({'error': 'Request body is required'}), 400

            dataset_id = data.get('dataset_id')
            event_type = data.get('event_type')
            message = data.get('message', '')
            metadata = data.get('metadata', {})

            if not dataset_id or not event_type:
                return jsonify({'error': 'dataset_id and event_type are required'}), 400

            producer_core.queue_manager.log_event(dataset_id, event_type, message, metadata)
            return jsonify({'message': 'Event logged successfully'})

        except Exception as e:
            logger.error(f"记录事件失败: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/consumer/fetch-interrupted-tasks', methods=['POST'])
    def fetch_interrupted_tasks():
        """
        Consumer 拉取中断的下载任务（状态为 downloading 但长时间未更新的任务）
        Request body: {"worker_id": "consumer-1", "limit": 5, "timeout_minutes": 30}
        """
        try:
            data = request.get_json() or {}
            worker_id = data.get('worker_id', 'unknown')
            limit = min(int(data.get('limit', 1)), 10)
            timeout_minutes = int(data.get('timeout_minutes', 30))

            tasks = []
            for _ in range(limit):
                task = producer_core.queue_manager.claim_interrupted_task(
                    worker_id=worker_id,
                    timeout_minutes=timeout_minutes
                )
                if task:
                    task_data = {
                        'task_id': task['id'],
                        'dataset_id': task['dataset_id'],
                        'storage_path': task.get('storage_path', ''),
                        'priority': task['priority'],
                        'retry_count': task['retry_count'],
                        'is_recovery': True,  # 标记这是恢复的任务
                        'previous_progress': {
                            'percentage': float(task.get('progress_percentage', 0)),
                            'downloaded_bytes': task.get('downloaded_bytes', 0),
                            'total_bytes': task.get('total_bytes', 0)
                        }
                    }
                    
                    # 添加 tar 配置（如果存在）
                    if task.get('tar_enabled'):
                        task_data['tar_config'] = {
                            'enabled': True,
                            'compress': task.get('tar_compress', True),
                            'split_size': task.get('tar_split_size', '50GiB'),
                            'split_threshold': task.get('tar_split_threshold', '100GiB'),
                            'delete_source': task.get('tar_delete_source', False)
                        }
                    
                    tasks.append(task_data)
                else:
                    break

            if tasks:
                logger.info(f"Worker {worker_id} 认领了 {len(tasks)} 个中断的任务")
            
            return jsonify({
                'tasks': tasks,
                'count': len(tasks),
                'message': f'Recovered {len(tasks)} interrupted tasks'
            })

        except Exception as e:
            logger.error(f"拉取中断任务失败: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/consumer/get-interrupted-tasks', methods=['GET'])
    def get_interrupted_tasks():
        """
        获取中断的下载任务列表（不认领，仅查看）
        Query params: timeout_minutes=30
        """
        try:
            timeout_minutes = int(request.args.get('timeout_minutes', 30))
            
            tasks = producer_core.queue_manager.get_interrupted_tasks(timeout_minutes)
            
            formatted_tasks = []
            for task in tasks:
                formatted_tasks.append({
                    'task_id': task['id'],
                    'dataset_id': task['dataset_id'],
                    'priority': task['priority'],
                    'retry_count': task['retry_count'],
                    'progress_percentage': float(task.get('progress_percentage', 0)),
                    'downloaded_bytes': task.get('downloaded_bytes', 0),
                    'total_bytes': task.get('total_bytes', 0),
                    'started_at': task.get('started_at').isoformat() if task.get('started_at') else None,
                    'updated_at': task.get('updated_at').isoformat() if task.get('updated_at') else None
                })
            
            return jsonify({
                'tasks': formatted_tasks,
                'count': len(formatted_tasks),
                'timeout_minutes': timeout_minutes
            })

        except Exception as e:
            logger.error(f"获取中断任务失败: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/consumer/reset-interrupted-tasks', methods=['POST'])
    def reset_interrupted_tasks():
        """
        重置所有中断的任务为 pending 状态
        Request body: {"timeout_minutes": 30}
        """
        try:
            data = request.get_json() or {}
            timeout_minutes = int(data.get('timeout_minutes', 30))
            
            count = producer_core.queue_manager.reset_interrupted_tasks(timeout_minutes)
            
            return jsonify({
                'message': f'Reset {count} interrupted tasks',
                'count': count,
                'timeout_minutes': timeout_minutes
            })

        except Exception as e:
            logger.error(f"重置中断任务失败: {e}")
            return jsonify({'error': str(e)}), 500

    return app
