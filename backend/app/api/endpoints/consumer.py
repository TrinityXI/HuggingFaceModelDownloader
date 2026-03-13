import logging
from flask import request
from flask_restx import Resource
from app.services.queue import queue_service

logger = logging.getLogger(__name__)

def register_routes(ns, models):
    
    health_model = models['health_model']
    fetch_tasks_request = models['fetch_tasks_request']
    fetch_tasks_response = models['fetch_tasks_response']
    fetch_interrupted_tasks_request = models['fetch_interrupted_tasks_request']
    fetch_interrupted_tasks_response = models['fetch_interrupted_tasks_response']
    get_interrupted_tasks_response = models['get_interrupted_tasks_response']
    reset_interrupted_tasks_request = models['reset_interrupted_tasks_request']
    reset_interrupted_tasks_response = models['reset_interrupted_tasks_response']

    @ns.route('/health')
    @ns.doc(description='健康检查端点')
    @ns.response(200, '成功', health_model)
    class HealthCheck(Resource):
        def get(self):
            from datetime import datetime
            return {
                'status': 'healthy',
                'timestamp': datetime.now().isoformat(),
                'service': 'producer'
            }

    @ns.route('/fetch-tasks')
    @ns.doc(description='Consumer拉取待处理任务')
    @ns.expect(fetch_tasks_request, validate=True)
    @ns.response(200, '成功', fetch_tasks_response)
    @ns.response(500, '服务器错误')
    class FetchTasks(Resource):
        def post(self):
            try:
                data = request.get_json() or {}
                worker_id = data.get('worker_id', 'unknown')
                limit = min(int(data.get('limit', 1)), 10)

                tasks = queue_service.fetch_tasks(worker_id=worker_id, limit=limit)

                if not tasks:
                    return {'tasks': [], 'count': 0, 'message': 'No tasks available'}

                formatted_tasks = []
                for task in tasks:
                    task_data = {
                        'task_id': task['id'],
                        'dataset_id': task['dataset_id'],
                        'storage_path': task.get('storage_path', ''),
                        'priority': task['priority'],
                        'retry_count': task['retry_count'],
                        'repo_type': task.get('repo_type', 'dataset')
                    }
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
                return {'tasks': formatted_tasks, 'count': len(formatted_tasks)}

            except Exception as e:
                logger.error(f"拉取任务失败: {e}")
                return {'error': str(e)}, 500

    @ns.route('/update-status')
    class UpdateStatus(Resource):
        @ns.doc(description='Consumer 更新任务状态')
        def post(self):
            try:
                data = request.get_json()
                if not data:
                    return {'error': 'Request body is required'}, 400

                dataset_id = data.get('dataset_id')
                status = data.get('status')
                message = data.get('message', '')
                storage_path = data.get('storage_path', '')

                if not dataset_id or not status:
                    return {'error': 'dataset_id and status are required'}, 400

                if status not in ['downloading', 'completed', 'failed', 'pending']:
                    return {'error': 'Invalid status'}, 400

                try:
                    queue_service.update_status(dataset_id, status, message, storage_path)
                except ValueError as ve:
                    return {'error': str(ve)}, 404

                logger.info(f"任务状态已更新: {dataset_id} -> {status}")
                return {'message': 'Status updated successfully', 'dataset_id': dataset_id, 'status': status}

            except Exception as e:
                logger.error(f"更新状态失败: {e}")
                return {'error': str(e)}, 500

    @ns.route('/update-progress')
    class UpdateProgress(Resource):
        @ns.doc(description='Consumer 更新下载进度')
        def post(self):
            try:
                data = request.get_json()
                if not data:
                    return {'error': 'Request body is required'}, 400

                dataset_id = data.get('dataset_id')
                if not dataset_id:
                    return {'error': 'dataset_id is required'}, 400

                try:
                    queue_service.update_progress(dataset_id, data)
                except ValueError as ve:
                    return {'error': str(ve)}, 404

                return {'message': 'Progress updated successfully', 'dataset_id': dataset_id}

            except Exception as e:
                logger.error(f"更新进度失败: {e}")
                return {'error': str(e)}, 500

    @ns.route('/log-event')
    class LogEvent(Resource):
        @ns.doc(description='Consumer 记录事件')
        def post(self):
            try:
                data = request.get_json()
                if not data:
                    return {'error': 'Request body is required'}, 400

                dataset_id = data.get('dataset_id')
                event_type = data.get('event_type')
                message = data.get('message', '')
                metadata = data.get('metadata', {})

                if not dataset_id or not event_type:
                    return {'error': 'dataset_id and event_type are required'}, 400

                queue_service.log_event(dataset_id, event_type, message, metadata)
                return {'message': 'Event logged successfully'}

            except Exception as e:
                logger.error(f"记录事件失败: {e}")
                return {'error': str(e)}, 500

    @ns.route('/fetch-interrupted-tasks')
    @ns.doc(description='Consumer 拉取中断的下载任务')
    @ns.expect(fetch_interrupted_tasks_request, validate=True)
    @ns.response(200, '成功', fetch_interrupted_tasks_response)
    class FetchInterruptedTasks(Resource):
        def post(self):
            try:
                data = request.get_json() or {}
                worker_id = data.get('worker_id', 'unknown')
                limit = min(int(data.get('limit', 1)), 10)
                timeout_minutes = int(data.get('timeout_minutes', 30))

                tasks = queue_service.fetch_interrupted_tasks(worker_id, limit, timeout_minutes)
                
                formatted_tasks = []
                for task in tasks:
                    task_data = {
                        'task_id': task['id'],
                        'dataset_id': task['dataset_id'],
                        'storage_path': task.get('storage_path', ''),
                        'priority': task['priority'],
                        'retry_count': task['retry_count'],
                        'repo_type': task.get('repo_type', 'dataset'),
                        'is_recovery': True,
                        'previous_progress': {
                            'percentage': float(task.get('progress_percentage', 0)),
                            'downloaded_bytes': task.get('downloaded_bytes', 0),
                            'total_bytes': task.get('total_bytes', 0)
                        }
                    }
                    if task.get('tar_enabled'):
                        task_data['tar_config'] = {
                            'enabled': True,
                            'compress': task.get('tar_compress', True),
                            'split_size': task.get('tar_split_size', '50GiB'),
                            'split_threshold': task.get('tar_split_threshold', '100GiB'),
                            'delete_source': task.get('tar_delete_source', False)
                        }
                    formatted_tasks.append(task_data)

                if formatted_tasks:
                    logger.info(f"Worker {worker_id} 认领了 {len(formatted_tasks)} 个中断的任务")
                
                return {
                    'tasks': formatted_tasks,
                    'count': len(formatted_tasks),
                    'message': f'Recovered {len(formatted_tasks)} interrupted tasks'
                }

            except Exception as e:
                logger.error(f"拉取中断任务失败: {e}")
                return {'error': str(e)}, 500

    @ns.route('/get-interrupted-tasks')
    @ns.doc(description='获取中断的下载任务列表（不认领）')
    @ns.response(200, '成功', get_interrupted_tasks_response)
    class GetInterruptedTasks(Resource):
        def get(self):
            try:
                timeout_minutes = int(request.args.get('timeout_minutes', 30))
                tasks = queue_service.get_interrupted_tasks(timeout_minutes)
                
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
                
                return {
                    'tasks': formatted_tasks,
                    'count': len(formatted_tasks),
                    'timeout_minutes': timeout_minutes
                }

            except Exception as e:
                logger.error(f"获取中断任务失败: {e}")
                return {'error': str(e)}, 500

    @ns.route('/reset-interrupted-tasks')
    @ns.doc(description='重置所有中断的任务为 pending 状态')
    @ns.expect(reset_interrupted_tasks_request, validate=True)
    @ns.response(200, '成功', reset_interrupted_tasks_response)
    class ResetInterruptedTasks(Resource):
        def post(self):
            try:
                data = request.get_json() or {}
                timeout_minutes = int(data.get('timeout_minutes', 30))
                count = queue_service.reset_interrupted_tasks(timeout_minutes)
                return {
                    'message': f'Reset {count} interrupted tasks',
                    'count': count,
                    'timeout_minutes': timeout_minutes
                }
            except Exception as e:
                logger.error(f"重置中断任务失败: {e}")
                return {'error': str(e)}, 500
