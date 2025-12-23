import logging
from flask import request
from flask_restx import Resource
from app.services.queue import queue_service
from app.services.scanner import scanner_service
from app.services.rabbitmq import rabbitmq_service
from app.services.config import config_service

logger = logging.getLogger(__name__)

def register_routes(ns, models):
    
    overview_stats_model = models['overview_stats_model']
    timeline_stats_model = models['timeline_stats_model']
    queue_list_response = models['queue_list_response']
    queue_task_detail_model = models['queue_task_detail_model']
    dataset_search_response = models['dataset_search_response']
    manual_task_request = models['manual_task_request']
    manual_task_response = models['manual_task_response']

    @ns.route('/stats/overview')
    class MonitorStatsOverview(Resource):
        @ns.doc(description='获取总览统计数据')
        @ns.response(200, '成功', overview_stats_model)
        def get(self):
            try:
                stats = queue_service.get_overview_stats()
                rabbitmq_stats = rabbitmq_service.get_queue_stats()
                if 'error' not in rabbitmq_stats:
                    stats['rabbitmq_queue'] = rabbitmq_stats.get('queue_length', 0)
                    stats['rabbitmq_dlq'] = rabbitmq_stats.get('dlq_length', 0)
                else:
                    stats['rabbitmq_queue'] = -1
                    stats['rabbitmq_dlq'] = -1
                return stats
            except Exception as e:
                logger.error(f"获取概览统计失败: {e}")
                return {'error': str(e)}, 500

    @ns.route('/stats/timeline')
    class MonitorStatsTimeline(Resource):
        @ns.doc(description='获取时间线统计数据')
        @ns.param('days', '查询天数', default=7)
        @ns.response(200, '成功', timeline_stats_model)
        def get(self):
            try:
                days = int(request.args.get('days', 7))
                return queue_service.get_timeline_stats(days)
            except Exception as e:
                logger.error(f"获取时间线统计失败: {e}")
                return {'error': str(e)}, 500

    @ns.route('/queue/list')
    class MonitorQueueList(Resource):
        @ns.doc(description='获取下载队列列表')
        @ns.param('page', '页码', default=1)
        @ns.param('per_page', '每页数量', default=20)
        @ns.param('status', '状态过滤')
        @ns.param('dataset_id', '数据集ID过滤')
        @ns.param('priority', '优先级过滤')
        @ns.response(200, '成功', queue_list_response)
        def get(self):
            try:
                page = int(request.args.get('page', 1))
                per_page = int(request.args.get('per_page', 20))
                status = request.args.get('status')
                dataset_id = request.args.get('dataset_id')
                priority = request.args.get('priority')

                return queue_service.get_queue_list(page, per_page, status, dataset_id, priority)
            except Exception as e:
                logger.error(f"获取队列列表失败: {e}")
                return {'error': str(e)}, 500

    @ns.route('/queue/<int:task_id>')
    class MonitorQueueTask(Resource):
        @ns.doc(description='获取任务详情')
        @ns.response(200, '成功', queue_task_detail_model)
        def get(self, task_id):
            try:
                task = queue_service.get_task_detail(task_id)
                if not task:
                    return {'error': 'Task not found'}, 404
                return task
            except Exception as e:
                logger.error(f"获取任务详情失败: {e}")
                return {'error': str(e)}, 500

        @ns.doc(description='删除任务')
        def delete(self, task_id):
            try:
                success = queue_service.delete_task(task_id)
                if not success:
                    return {'error': 'Task not found or failed to delete'}, 404
                return {'message': 'Task deleted', 'task_id': task_id}
            except Exception as e:
                logger.error(f"删除任务失败: {e}")
                return {'error': str(e)}, 500

    @ns.route('/queue/<int:task_id>/progress')
    class MonitorQueueProgress(Resource):
        @ns.doc(description='获取任务实时进度')
        def get(self, task_id):
            try:
                progress = queue_service.get_task_progress(task_id)
                if not progress:
                    return {'error': 'Task not found'}, 404
                return progress
            except Exception as e:
                logger.error(f"获取任务进度失败: {e}")
                return {'error': str(e)}, 500

    @ns.route('/queue/<int:task_id>/retry')
    class MonitorQueueRetry(Resource):
        @ns.doc(description='重试失败的任务')
        def post(self, task_id):
            try:
                success = queue_service.retry_task(task_id)
                if not success:
                    return {'error': 'Task not found or not in failed status'}, 404
                return {'message': 'Task retry scheduled', 'task_id': task_id}
            except Exception as e:
                logger.error(f"重试任务失败: {e}")
                return {'error': str(e)}, 500

    @ns.route('/datasets/search')
    class MonitorDatasetSearch(Resource):
        @ns.doc(description='搜索 Hugging Face 数据集')
        @ns.param('q', '查询关键词', required=True)
        @ns.param('limit', '结果数量', default=20)
        @ns.response(200, '成功', dataset_search_response)
        def get(self):
            try:
                query = request.args.get('q', '')
                limit = int(request.args.get('limit', 20))
                if not query:
                    return {'error': 'Query parameter q is required'}, 400
                
                datasets = scanner_service.search_remote_datasets(query, limit)
                return {
                    'datasets': datasets,
                    'total': len(datasets),
                    'query': query
                }
            except Exception as e:
                logger.error(f"搜索数据集失败: {e}")
                return {'error': str(e)}, 500

    @ns.route('/queue/manual')
    class MonitorManualTask(Resource):
        @ns.doc(description='手动创建下载任务')
        @ns.expect(manual_task_request, validate=True)
        @ns.response(200, '成功', manual_task_response)
        def post(self):
            try:
                data = request.get_json()
                dataset_id = data.get('dataset_id')
                priority = data.get('priority', 0)
                storage_path = data.get('storage_path', '')
                force = data.get('force', False)
                
                tar_config = None
                if data.get('tar_enabled'):
                    tar_config = {
                        'enabled': data.get('tar_enabled', False),
                        'compress': data.get('tar_compress', True),
                        'split_size': data.get('tar_split_size', '50GiB'),
                        'split_threshold': data.get('tar_split_threshold', '100GiB'),
                        'delete_source': data.get('tar_delete_source', False)
                    }
                
                try:
                    task, message = queue_service.create_manual_task(
                        dataset_id, priority, storage_path, force, tar_config
                    )
                    # Notify RabbitMQ
                    # This logic was in ProducerCore.create_manual_task.
                    # I should probably move it to QueueService or here.
                    # QueueService is about DB. RabbitMQService is about Messaging.
                    # Ideally QueueService calls RabbitMQService or a higher level orchestrator calls both.
                    # For simplicity, I'll call RabbitMQService here if successful.
                    if rabbitmq_service:
                        from datetime import datetime
                        task_info = {
                            'dataset_id': dataset_id,
                            'priority': priority,
                            'storage_path': storage_path,
                            'created_at': datetime.now().isoformat(),
                            'manual': True
                        }
                        if tar_config:
                            task_info['tar_config'] = tar_config
                        rabbitmq_service.send_message(task_info)
                    
                    return {
                        'message': message,
                        'task_id': task['id'] if task else None,
                        'dataset_id': dataset_id
                    }
                except ValueError as ve:
                    return {'error': str(ve)}, 409
                except Exception as e:
                    logger.error(f"创建手动任务失败: {e}")
                    return {'error': str(e)}, 500

            except Exception as e:
                logger.error(f"手动创建任务异常: {e}")
                return {'error': str(e)}, 500

    @ns.route('/scan/config')
    class MonitorScanConfig(Resource):
        @ns.doc(description='获取扫描配置')
        def get(self):
            try:
                return config_service.get_config()
            except Exception as e:
                return {'error': str(e)}, 500

        @ns.doc(description='更新扫描配置')
        def post(self):
            try:
                data = request.get_json() or {}
                config = config_service.update_config(data)
                return {'message': 'Config updated successfully', 'config': config}
            except Exception as e:
                return {'error': str(e)}, 500

    @ns.route('/scan/config/reset')
    class MonitorScanConfigReset(Resource):
        @ns.doc(description='重置扫描配置')
        def post(self):
            try:
                config = config_service.reset_config()
                return {'message': 'Config reset successfully', 'config': config}
            except Exception as e:
                return {'error': str(e)}, 500

    @ns.route('/scan/trigger')
    class MonitorScanTrigger(Resource):
        @ns.doc(description='触发扫描')
        def post(self):
            try:
                config_service.trigger_scan()
                return {'message': 'Scan triggered successfully'}
            except Exception as e:
                return {'error': str(e)}, 500
