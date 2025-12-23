import logging
import json
import os
from datetime import datetime
from flask import request, jsonify
from flask_restx import Resource

logger = logging.getLogger(__name__)

def register_routes(api, consumer_ns, feishu_ns, monitor_ns, producer_core, models):
    """注册所有 API 路由"""

    # Consumer Models
    health_model = models['health_model']
    fetch_tasks_request = models['fetch_tasks_request']
    fetch_tasks_response = models['fetch_tasks_response']
    # update_status_request = models['update_status_request']
    # update_status_response = models['update_status_response']
    # update_progress_request = models['update_progress_request']
    # update_progress_response = models['update_progress_response']
    # log_event_request = models['log_event_request']
    # log_event_response = models['log_event_response']
    fetch_interrupted_tasks_request = models['fetch_interrupted_tasks_request']
    fetch_interrupted_tasks_response = models['fetch_interrupted_tasks_response']
    get_interrupted_tasks_response = models['get_interrupted_tasks_response']
    reset_interrupted_tasks_request = models['reset_interrupted_tasks_request']
    reset_interrupted_tasks_response = models['reset_interrupted_tasks_response']
    
    # Feishu Models
    feishu_webhook_model = models['feishu_webhook_model']
    feishu_webhook_response = models['feishu_webhook_response']
    feishu_notify_model = models['feishu_notify_model']
    feishu_notify_response = models['feishu_notify_response']

    # Monitor Models
    overview_stats_model = models['overview_stats_model']
    # queue_progress_model = models['queue_progress_model']
    queue_task_detail_model = models['queue_task_detail_model']
    queue_list_response = models['queue_list_response']
    timeline_stats_model = models['timeline_stats_model']
    # dataset_search_model = models['dataset_search_model']
    dataset_search_response = models['dataset_search_response']
    manual_task_request = models['manual_task_request']
    manual_task_response = models['manual_task_response']

    # =========================================================================
    # Consumer API Routes
    # =========================================================================

    @consumer_ns.route('/health')
    @consumer_ns.doc(description='健康检查端点，用于监控服务状态')
    @consumer_ns.response(200, '成功', health_model)
    class HealthCheck(Resource):
        def get(self):
            """健康检查"""
            return {
                'status': 'healthy',
                'timestamp': datetime.now().isoformat(),
                'service': 'producer'
            }

    @consumer_ns.route('/fetch-tasks')
    @consumer_ns.doc(description='Consumer拉取待处理任务')
    @consumer_ns.expect(fetch_tasks_request, validate=True)
    @consumer_ns.response(200, '成功', fetch_tasks_response)
    @consumer_ns.response(500, '服务器错误')
    class FetchTasks(Resource):
        def post(self):
            """拉取待处理任务"""
            try:
                data = request.get_json() or {}
                worker_id = data.get('worker_id', 'unknown')
                limit = min(int(data.get('limit', 1)), 10)

                tasks = producer_core.fetch_tasks(worker_id=worker_id, limit=limit)

                if not tasks:
                    return {'tasks': [], 'count': 0, 'message': 'No tasks available'}

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
                return {'tasks': formatted_tasks, 'count': len(formatted_tasks)}

            except Exception as e:
                logger.error(f"拉取任务失败: {e}")
                return {'error': str(e)}, 500

    @consumer_ns.route('/update-status')
    class UpdateStatus(Resource):
        @consumer_ns.doc(description='Consumer 更新任务状态')
        def post(self):
            """Consumer 更新任务状态"""
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
                    producer_core.update_task_status(dataset_id, status, message, storage_path)
                except ValueError as ve:
                    return {'error': str(ve)}, 404

                logger.info(f"任务状态已更新: {dataset_id} -> {status}")
                return {'message': 'Status updated successfully', 'dataset_id': dataset_id, 'status': status}

            except Exception as e:
                logger.error(f"更新状态失败: {e}")
                return {'error': str(e)}, 500

    @consumer_ns.route('/update-progress')
    class UpdateProgress(Resource):
        @consumer_ns.doc(description='Consumer 更新下载进度')
        def post(self):
            """Consumer 更新下载进度"""
            try:
                data = request.get_json()
                if not data:
                    return {'error': 'Request body is required'}, 400

                dataset_id = data.get('dataset_id')
                if not dataset_id:
                    return {'error': 'dataset_id is required'}, 400

                try:
                    producer_core.update_task_progress(dataset_id, data)
                except ValueError as ve:
                    return {'error': str(ve)}, 404

                return {'message': 'Progress updated successfully', 'dataset_id': dataset_id}

            except Exception as e:
                logger.error(f"更新进度失败: {e}")
                return {'error': str(e)}, 500

    @consumer_ns.route('/log-event')
    class LogEvent(Resource):
        @consumer_ns.doc(description='Consumer 记录事件')
        def post(self):
            """Consumer 记录事件"""
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

                producer_core.log_event(dataset_id, event_type, message, metadata)
                return {'message': 'Event logged successfully'}

            except Exception as e:
                logger.error(f"记录事件失败: {e}")
                return {'error': str(e)}, 500

    @consumer_ns.route('/fetch-interrupted-tasks')
    @consumer_ns.doc(description='Consumer 拉取中断的下载任务')
    @consumer_ns.expect(fetch_interrupted_tasks_request, validate=True)
    @consumer_ns.response(200, '成功', fetch_interrupted_tasks_response)
    class FetchInterruptedTasks(Resource):
        def post(self):
            """拉取中断的下载任务"""
            try:
                data = request.get_json() or {}
                worker_id = data.get('worker_id', 'unknown')
                limit = min(int(data.get('limit', 1)), 10)
                timeout_minutes = int(data.get('timeout_minutes', 30))

                tasks = producer_core.fetch_interrupted_tasks(worker_id, limit, timeout_minutes)
                
                formatted_tasks = []
                for task in tasks:
                    task_data = {
                        'task_id': task['id'],
                        'dataset_id': task['dataset_id'],
                        'storage_path': task.get('storage_path', ''),
                        'priority': task['priority'],
                        'retry_count': task['retry_count'],
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

    @consumer_ns.route('/get-interrupted-tasks')
    @consumer_ns.doc(description='获取中断的下载任务列表（不认领）')
    @consumer_ns.response(200, '成功', get_interrupted_tasks_response)
    class GetInterruptedTasks(Resource):
        def get(self):
            """获取中断的下载任务列表"""
            try:
                timeout_minutes = int(request.args.get('timeout_minutes', 30))
                tasks = producer_core.get_interrupted_tasks(timeout_minutes)
                
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

    @consumer_ns.route('/reset-interrupted-tasks')
    @consumer_ns.doc(description='重置所有中断的任务为 pending 状态')
    @consumer_ns.expect(reset_interrupted_tasks_request, validate=True)
    @consumer_ns.response(200, '成功', reset_interrupted_tasks_response)
    class ResetInterruptedTasks(Resource):
        def post(self):
            """重置中断的任务"""
            try:
                data = request.get_json() or {}
                timeout_minutes = int(data.get('timeout_minutes', 30))
                count = producer_core.reset_interrupted_tasks(timeout_minutes)
                return {
                    'message': f'Reset {count} interrupted tasks',
                    'count': count,
                    'timeout_minutes': timeout_minutes
                }
            except Exception as e:
                logger.error(f"重置中断任务失败: {e}")
                return {'error': str(e)}, 500

    # =========================================================================
    # Feishu API Routes
    # =========================================================================

    @feishu_ns.route('/webhook')
    class FeishuWebhook(Resource):
        @feishu_ns.expect(feishu_webhook_model, validate=False)
        @feishu_ns.response(200, '成功', feishu_webhook_response)
        def post(self):
            """飞书机器人webhook端点"""
            try:
                from feishu_bot import FeishuCommandHandler, verify_feishu_signature
                timestamp = request.headers.get('X-Lark-Request-Timestamp', '')
                signature = request.headers.get('X-Lark-Request-Signature', '')
                request_body = request.get_data(as_text=True)
                secret = os.getenv('FEISHU_SECRET', '')
                if not verify_feishu_signature(timestamp, signature, request_body, secret):
                    logger.warning(f"飞书签名验证失败: timestamp={timestamp}, signature={signature}")
                    return {'success': False, 'message': 'Invalid signature'}, 401
                data = request.get_json()
                if not data:
                    return {'success': False, 'message': 'Request body is required'}, 400
                if data.get('type') == 'url_verification':
                    challenge = data.get('challenge', '')
                    return {'challenge': challenge}
                event = data.get('event', {})
                if event.get('type') == 'message':
                    message_type = event.get('msg_type', '')
                    content = event.get('content', '')
                    if message_type == 'text':
                        try:
                            content_json = json.loads(content)
                            command_text = content_json.get('text', '').strip()
                            user_id = event.get('sender', {}).get('sender_id', {}).get('user_id', '')
                            if command_text:
                                handler = FeishuCommandHandler(producer_core)
                                result = handler.handle_command(command_text, user_id)
                                if result.get('success'):
                                    response_text = result.get('message', '命令执行成功')
                                else:
                                    response_text = f"❌ {result.get('message', '命令执行失败')}"
                                return {
                                    'msg_type': 'text',
                                    'content': {'text': response_text}
                                }
                        except json.JSONDecodeError:
                            logger.error(f"飞书消息内容解析失败: {content}")
                    return {'success': True, 'message': 'Message received'}
                return {'success': True, 'message': 'Event processed'}
            except Exception as e:
                logger.error(f"处理飞书webhook失败: {e}")
                return {'success': False, 'message': str(e)}, 500

    @feishu_ns.route('/notify')
    class FeishuNotify(Resource):
        @feishu_ns.expect(feishu_notify_model, validate=True)
        @feishu_ns.response(200, '成功', feishu_notify_response)
        def post(self):
            """发送通知到飞书"""
            try:
                from feishu_bot import FeishuBot
                data = request.get_json()
                if not data:
                    return {'success': False, 'message': 'Request body is required'}, 400
                event_type = data.get('event_type')
                dataset_id = data.get('dataset_id', '')
                message = data.get('message', '')
                metadata = data.get('metadata', {})
                if not event_type:
                    return {'success': False, 'message': 'event_type is required'}, 400
                bot = FeishuBot()
                success = bot.send_notification(event_type, dataset_id, message, metadata)
                return {
                    'success': success,
                    'message': 'Notification sent' if success else 'Notification failed'
                }
            except Exception as e:
                logger.error(f"发送飞书通知失败: {e}")
                return {'success': False, 'message': str(e)}, 500

    @feishu_ns.route('/test')
    class FeishuTest(Resource):
        @feishu_ns.response(200, '成功', feishu_notify_response)
        def get(self):
            """测试飞书机器人连接"""
            try:
                from feishu_bot import FeishuBot
                bot = FeishuBot()
                success = bot.send_message(
                    title="测试通知",
                    content="这是一条来自 HuggingFace Model Downloader 的测试消息\n\n系统运行正常！",
                    msg_type="interactive"
                )
                return {
                    'success': success,
                    'message': 'Test notification sent' if success else 'Test notification failed',
                    'webhook_configured': bool(os.getenv('FEISHU_WEBHOOK_URL')),
                    'secret_configured': bool(os.getenv('FEISHU_SECRET'))
                }
            except Exception as e:
                logger.error(f"飞书测试失败: {e}")
                return {'success': False, 'message': str(e)}, 500

    # =========================================================================
    # Monitor API Routes
    # =========================================================================

    @monitor_ns.route('/stats/overview')
    class MonitorStatsOverview(Resource):
        @monitor_ns.doc(description='获取总览统计数据')
        @monitor_ns.response(200, '成功', overview_stats_model)
        def get(self):
            """获取总览统计数据"""
            try:
                stats = producer_core.get_overview_stats()
                
                # 添加 RabbitMQ 统计
                rabbitmq_stats = producer_core.get_rabbitmq_stats()
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

    @monitor_ns.route('/stats/timeline')
    class MonitorStatsTimeline(Resource):
        @monitor_ns.doc(description='获取时间线统计数据')
        @monitor_ns.param('days', '查询天数', default=7)
        @monitor_ns.response(200, '成功', timeline_stats_model)
        def get(self):
            """获取时间线统计数据"""
            try:
                days = int(request.args.get('days', 7))
                return producer_core.get_timeline_stats(days)
            except Exception as e:
                logger.error(f"获取时间线统计失败: {e}")
                return {'error': str(e)}, 500

    @monitor_ns.route('/queue/list')
    class MonitorQueueList(Resource):
        @monitor_ns.doc(description='获取下载队列列表')
        @monitor_ns.param('page', '页码', default=1)
        @monitor_ns.param('per_page', '每页数量', default=20)
        @monitor_ns.param('status', '状态过滤')
        @monitor_ns.param('dataset_id', '数据集ID过滤')
        @monitor_ns.param('priority', '优先级过滤')
        @monitor_ns.response(200, '成功', queue_list_response)
        def get(self):
            """获取下载队列列表"""
            try:
                page = int(request.args.get('page', 1))
                per_page = int(request.args.get('per_page', 20))
                status = request.args.get('status')
                dataset_id = request.args.get('dataset_id')
                priority = request.args.get('priority')

                return producer_core.get_queue_list(page, per_page, status, dataset_id, priority)
            except Exception as e:
                logger.error(f"获取队列列表失败: {e}")
                return {'error': str(e)}, 500

    @monitor_ns.route('/queue/<int:task_id>')
    class MonitorQueueTask(Resource):
        @monitor_ns.doc(description='获取任务详情')
        @monitor_ns.response(200, '成功', queue_task_detail_model)
        def get(self, task_id):
            """获取任务详情"""
            try:
                task = producer_core.get_task_detail(task_id)
                if not task:
                    return {'error': 'Task not found'}, 404
                return task
            except Exception as e:
                logger.error(f"获取任务详情失败: {e}")
                return {'error': str(e)}, 500

        @monitor_ns.doc(description='删除任务')
        def delete(self, task_id):
            """删除任务"""
            try:
                success = producer_core.delete_task_by_id(task_id)
                if not success:
                    return {'error': 'Task not found or failed to delete'}, 404
                return {'message': 'Task deleted', 'task_id': task_id}
            except Exception as e:
                logger.error(f"删除任务失败: {e}")
                return {'error': str(e)}, 500

    @monitor_ns.route('/queue/<int:task_id>/progress')
    class MonitorQueueProgress(Resource):
        @monitor_ns.doc(description='获取任务实时进度')
        # @monitor_ns.response(200, '成功', queue_progress_model)
        def get(self, task_id):
            """获取任务实时进度"""
            try:
                progress = producer_core.get_task_progress(task_id)
                if not progress:
                    return {'error': 'Task not found'}, 404
                return progress
            except Exception as e:
                logger.error(f"获取任务进度失败: {e}")
                return {'error': str(e)}, 500

    @monitor_ns.route('/queue/<int:task_id>/retry')
    class MonitorQueueRetry(Resource):
        @monitor_ns.doc(description='重试失败的任务')
        def post(self, task_id):
            """重试失败的任务"""
            try:
                success = producer_core.retry_task(task_id)
                if not success:
                    return {'error': 'Task not found or not in failed status'}, 404
                return {'message': 'Task retry scheduled', 'task_id': task_id}
            except Exception as e:
                logger.error(f"重试任务失败: {e}")
                return {'error': str(e)}, 500

    @monitor_ns.route('/datasets/search')
    class MonitorDatasetSearch(Resource):
        @monitor_ns.doc(description='搜索 Hugging Face 数据集')
        @monitor_ns.param('q', '查询关键词', required=True)
        @monitor_ns.param('limit', '结果数量', default=20)
        @monitor_ns.response(200, '成功', dataset_search_response)
        def get(self):
            """搜索 Hugging Face 数据集"""
            try:
                query = request.args.get('q', '')
                limit = int(request.args.get('limit', 20))
                if not query:
                    return {'error': 'Query parameter q is required'}, 400
                
                datasets = producer_core.search_datasets(query, limit)
                return {
                    'datasets': datasets,
                    'total': len(datasets),
                    'query': query
                }
            except Exception as e:
                logger.error(f"搜索数据集失败: {e}")
                return {'error': str(e)}, 500

    @monitor_ns.route('/queue/manual')
    class MonitorManualTask(Resource):
        @monitor_ns.doc(description='手动创建下载任务')
        @monitor_ns.expect(manual_task_request, validate=True)
        @monitor_ns.response(200, '成功', manual_task_response)
        def post(self):
            """手动创建下载任务"""
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
                    task, message = producer_core.create_manual_task(
                        dataset_id, priority, storage_path, force, tar_config
                    )
                    return {
                        'message': message,
                        'task_id': task['id'] if task else None,
                        'dataset_id': dataset_id
                    }
                except ValueError as ve:
                    return {'error': str(ve)}, 409 # Conflict
                except Exception as e:
                    logger.error(f"创建手动任务失败: {e}")
                    return {'error': str(e)}, 500

            except Exception as e:
                logger.error(f"手动创建任务异常: {e}")
                return {'error': str(e)}, 500

    @monitor_ns.route('/scan/config')
    class MonitorScanConfig(Resource):
        @monitor_ns.doc(description='获取扫描配置')
        def get(self):
            """获取扫描配置"""
            try:
                return producer_core.get_scan_config_from_redis()
            except Exception as e:
                return {'error': str(e)}, 500

        @monitor_ns.doc(description='更新扫描配置')
        def post(self):
            """更新扫描配置"""
            try:
                data = request.get_json() or {}
                # TODO: Validate config keys
                config = producer_core.update_scan_config_redis(data)
                return {'message': 'Config updated successfully', 'config': config}
            except Exception as e:
                return {'error': str(e)}, 500

    @monitor_ns.route('/scan/config/reset')
    class MonitorScanConfigReset(Resource):
        @monitor_ns.doc(description='重置扫描配置')
        def post(self):
            """重置扫描配置"""
            try:
                config = producer_core.reset_scan_config_redis()
                return {'message': 'Config reset successfully', 'config': config}
            except Exception as e:
                return {'error': str(e)}, 500

    @monitor_ns.route('/scan/trigger')
    class MonitorScanTrigger(Resource):
        @monitor_ns.doc(description='触发扫描')
        def post(self):
            """触发扫描"""
            try:
                producer_core.trigger_scan_redis()
                return {'message': 'Scan triggered successfully'}
            except Exception as e:
                return {'error': str(e)}, 500