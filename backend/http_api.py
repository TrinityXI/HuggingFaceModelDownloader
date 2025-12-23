#!/usr/bin/env python3
"""
Producer HTTP API
提供 REST API 供 consumer 调用
"""

import logging
from flask import Flask
from flask_restx import Api, Namespace
from flask_cors import CORS
import api_schemas
from api_routes import register_routes

logger = logging.getLogger(__name__)

def create_http_api(producer_core):
    """创建 Flask HTTP API 应用"""
    app = Flask(__name__)

    # 启用CORS
    CORS(app)

    # 创建Flask-RESTX API实例
    api = Api(
        app,
        version='1.0.0',
        title='HuggingFace Model Downloader API',
        description='Producer服务REST API，提供数据集下载队列管理功能',
        doc='/api/docs/',  # Swagger UI路径
        default='Consumer API',
        default_label='消费者相关API端点'
    )

    # 创建命名空间
    consumer_ns = Namespace('consumer', description='消费者API')
    feishu_ns = Namespace('feishu', description='飞书机器人API')
    monitor_ns = Namespace('monitor', description='监控管理API', path='/api') # Root path for monitor routes to match existing structure if possible, or use /api/monitor

    # 注册命名空间
    api.add_namespace(consumer_ns, path='/api/consumer')
    api.add_namespace(feishu_ns, path='/api/feishu')
    # Monitor routes were like /api/stats, /api/queue. To keep compat, maybe use /api directly or map manually.
    # But namespaces usually append to path.
    # Let's use /api and define sub-resources like /stats/overview
    api.add_namespace(monitor_ns, path='/api')

    # 定义/创建数据模型
    models = {
        'health_model': api_schemas.create_health_model(api),
        'tar_config_model': api_schemas.create_tar_config_model(api),
        'fetch_tasks_request': api_schemas.create_fetch_tasks_request(api),
        'update_status_request': api_schemas.create_update_status_request(api),
        'update_status_response': api_schemas.create_update_status_response(api),
        'update_progress_request': api_schemas.create_update_progress_request(api),
        'update_progress_response': api_schemas.create_update_progress_response(api),
        'log_event_request': api_schemas.create_log_event_request(api),
        'log_event_response': api_schemas.create_log_event_response(api),
        'fetch_interrupted_tasks_request': api_schemas.create_fetch_interrupted_tasks_request(api),
        'get_interrupted_tasks_response': api_schemas.create_get_interrupted_tasks_response(api),
        'reset_interrupted_tasks_request': api_schemas.create_reset_interrupted_tasks_request(api),
        'reset_interrupted_tasks_response': api_schemas.create_reset_interrupted_tasks_response(api),
        'feishu_webhook_model': api_schemas.create_feishu_webhook_model(api),
        'feishu_webhook_response': api_schemas.create_feishu_webhook_response(api),
        'feishu_notify_model': api_schemas.create_feishu_notify_model(api),
        'feishu_notify_response': api_schemas.create_feishu_notify_response(api),
        
        # Monitor models
        'overview_stats_model': api_schemas.create_overview_stats_model(api),
        'timeline_stats_model': api_schemas.create_timeline_stats_model(api),
        'dataset_search_model': api_schemas.create_dataset_search_model(api),
        'manual_task_request': api_schemas.create_manual_task_request(api),
        'manual_task_response': api_schemas.create_manual_task_response(api),
        'queue_progress_model': api_schemas.create_queue_progress_model(api)
    }

    # 依赖模型 (nested)
    models['task_model'] = api_schemas.create_task_model(api, models['tar_config_model'])
    models['fetch_tasks_response'] = api_schemas.create_fetch_tasks_response(api, models['task_model'])
    models['interrupted_task_model'] = api_schemas.create_interrupted_task_model(api)
    models['fetch_interrupted_tasks_response'] = api_schemas.create_fetch_interrupted_tasks_response(api, models['interrupted_task_model'])
    
    # Monitor nested models
    models['queue_task_detail_model'] = api_schemas.create_queue_task_detail_model(api, models['queue_progress_model'])
    models['queue_list_response'] = api_schemas.create_queue_list_response(api, models['queue_task_detail_model'])
    models['dataset_search_response'] = api_schemas.create_dataset_search_response(api, models['dataset_search_model'])

    # 注册路由
    register_routes(api, consumer_ns, feishu_ns, monitor_ns, producer_core, models)

    return app