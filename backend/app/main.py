import logging
from flask import Flask
from flask_restx import Api, Namespace
from flask_cors import CORS

from app.crud.base import db
from app.schemas.api import (
    create_health_model, create_fetch_tasks_request, create_tar_config_model,
    create_task_model, create_fetch_tasks_response, create_update_status_request,
    create_update_status_response, create_update_progress_request,
    create_update_progress_response, create_log_event_request, create_log_event_response,
    create_fetch_interrupted_tasks_request, create_interrupted_task_model,
    create_fetch_interrupted_tasks_response, create_get_interrupted_tasks_response,
    create_reset_interrupted_tasks_request, create_reset_interrupted_tasks_response,
    create_feishu_webhook_model, create_feishu_webhook_response,
    create_feishu_notify_model, create_feishu_notify_response,
    create_overview_stats_model, create_queue_progress_model,
    create_queue_task_detail_model, create_queue_list_response,
    create_timeline_stats_model, create_dataset_search_model,
    create_dataset_search_response, create_manual_task_request,
    create_manual_task_response, create_batch_delete_request,
    create_batch_delete_response
)

from app.api.endpoints import consumer, monitor, feishu

logger = logging.getLogger(__name__)

def create_app():
    # Initialize Database
    try:
        db.init_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")

    app = Flask(__name__)
    CORS(app)

    api = Api(
        app,
        version='1.0.0',
        title='HuggingFace Model Downloader API',
        description='Producer服务REST API',
        doc='/api/docs/',
        default='API',
        default_label='API Endpoints'
    )

    # Create Models
    models = {}
    models['health_model'] = create_health_model(api)
    models['tar_config_model'] = create_tar_config_model(api)
    models['task_model'] = create_task_model(api, models['tar_config_model'])
    models['fetch_tasks_request'] = create_fetch_tasks_request(api)
    models['fetch_tasks_response'] = create_fetch_tasks_response(api, models['task_model'])
    models['update_status_request'] = create_update_status_request(api)
    models['update_status_response'] = create_update_status_response(api)
    models['update_progress_request'] = create_update_progress_request(api)
    models['update_progress_response'] = create_update_progress_response(api)
    models['log_event_request'] = create_log_event_request(api)
    models['log_event_response'] = create_log_event_response(api)
    
    models['interrupted_task_model'] = create_interrupted_task_model(api)
    models['fetch_interrupted_tasks_request'] = create_fetch_interrupted_tasks_request(api)
    models['fetch_interrupted_tasks_response'] = create_fetch_interrupted_tasks_response(api, models['interrupted_task_model'])
    models['get_interrupted_tasks_response'] = create_get_interrupted_tasks_response(api)
    models['reset_interrupted_tasks_request'] = create_reset_interrupted_tasks_request(api)
    models['reset_interrupted_tasks_response'] = create_reset_interrupted_tasks_response(api)

    models['feishu_webhook_model'] = create_feishu_webhook_model(api)
    models['feishu_webhook_response'] = create_feishu_webhook_response(api)
    models['feishu_notify_model'] = create_feishu_notify_model(api)
    models['feishu_notify_response'] = create_feishu_notify_response(api)

    models['overview_stats_model'] = create_overview_stats_model(api)
    models['queue_progress_model'] = create_queue_progress_model(api)
    models['queue_task_detail_model'] = create_queue_task_detail_model(api, models['queue_progress_model'])
    models['queue_list_response'] = create_queue_list_response(api, models['queue_task_detail_model'])
    models['timeline_stats_model'] = create_timeline_stats_model(api)
    models['dataset_search_model'] = create_dataset_search_model(api)
    models['dataset_search_response'] = create_dataset_search_response(api, models['dataset_search_model'])
    models['manual_task_request'] = create_manual_task_request(api)
    models['manual_task_response'] = create_manual_task_response(api)
    models['batch_delete_request'] = create_batch_delete_request(api)
    models['batch_delete_response'] = create_batch_delete_response(api)

    # Namespaces
    consumer_ns = Namespace('consumer', description='Consumer API')
    monitor_ns = Namespace('monitor', description='Monitor API', path='/api') # Keep /api prefix logic for monitor
    feishu_ns = Namespace('feishu', description='Feishu API')

    api.add_namespace(consumer_ns, path='/api/consumer')
    api.add_namespace(feishu_ns, path='/api/feishu')
    api.add_namespace(monitor_ns, path='/api') # This maps /api/stats/overview etc.

    # Register Routes
    consumer.register_routes(consumer_ns, models)
    monitor.register_routes(monitor_ns, models)
    feishu.register_routes(feishu_ns, models)

    return app

app = create_app()
