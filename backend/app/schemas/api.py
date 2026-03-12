from flask_restx import fields

def create_health_model(api):
    return api.model('HealthResponse', {
        'status': fields.String(required=True, description='服务状态'),
        'timestamp': fields.String(required=True, description='时间戳'),
        'service': fields.String(required=True, description='服务名称')
    })

def create_fetch_tasks_request(api):
    return api.model('FetchTasksRequest', {
        'worker_id': fields.String(required=False, description='Worker ID', default='unknown'),
        'limit': fields.Integer(required=False, description='获取任务数量', default=1, min=1, max=10)
    })

def create_tar_config_model(api):
    return api.model('TarConfig', {
        'enabled': fields.Boolean(required=True, description='是否启用tar打包'),
        'compress': fields.Boolean(required=True, description='是否压缩'),
        'split_size': fields.String(required=True, description='分卷大小'),
        'split_threshold': fields.String(required=True, description='分卷阈值'),
        'delete_source': fields.Boolean(required=True, description='是否删除源文件')
    })

def create_task_model(api, tar_config_model):
    return api.model('Task', {
        'task_id': fields.Integer(required=True, description='任务ID'),
        'dataset_id': fields.String(required=True, description='数据集ID'),
        'storage_path': fields.String(required=False, description='存储路径'),
        'priority': fields.Integer(required=True, description='优先级'),
        'retry_count': fields.Integer(required=True, description='重试次数'),
        'tar_config': fields.Nested(tar_config_model, required=False, description='tar打包配置'),
        'repo_type': fields.String(required=False, description='仓库类型 (dataset/model)', default='dataset')
    })

def create_fetch_tasks_response(api, task_model):
    return api.model('FetchTasksResponse', {
        'tasks': fields.List(fields.Nested(task_model), description='任务列表'),
        'count': fields.Integer(description='任务数量'),
        'message': fields.String(description='消息')
    })

def create_update_status_request(api):
    return api.model('UpdateStatusRequest', {
        'dataset_id': fields.String(required=True, description='数据集ID'),
        'status': fields.String(required=True, description='状态', enum=['downloading', 'completed', 'failed', 'pending']),
        'message': fields.String(required=False, description='错误信息（失败时可选）'),
        'storage_path': fields.String(required=False, description='存储路径（完成时可选）')
    })

def create_update_status_response(api):
    return api.model('UpdateStatusResponse', {
        'message': fields.String(required=True, description='响应消息'),
        'dataset_id': fields.String(required=True, description='数据集ID'),
        'status': fields.String(required=True, description='更新后的状态')
    })

def create_update_progress_request(api):
    return api.model('UpdateProgressRequest', {
        'dataset_id': fields.String(required=True, description='数据集ID'),
        'percentage': fields.Float(required=False, description='下载百分比', min=0, max=100),
        'downloaded_bytes': fields.Integer(required=False, description='已下载字节数'),
        'total_bytes': fields.Integer(required=False, description='总字节数'),
        'total_files': fields.Integer(required=False, description='总文件数'),
        'completed_files': fields.Integer(required=False, description='已完成文件数'),
        'download_speed': fields.Float(required=False, description='下载速度（字节/秒）'),
        'progress_status': fields.String(required=False, description='进度状态')
    })

def create_update_progress_response(api):
    return api.model('UpdateProgressResponse', {
        'message': fields.String(required=True, description='响应消息'),
        'dataset_id': fields.String(required=True, description='数据集ID')
    })

def create_log_event_request(api):
    return api.model('LogEventRequest', {
        'dataset_id': fields.String(required=True, description='数据集ID'),
        'event_type': fields.String(required=True, description='事件类型', enum=['start', 'complete', 'fail', 'retry']),
        'message': fields.String(required=False, description='事件消息'),
        'metadata': fields.Raw(required=False, description='附加元数据（JSON）')
    })

def create_log_event_response(api):
    return api.model('LogEventResponse', {
        'message': fields.String(required=True, description='响应消息')
    })

def create_fetch_interrupted_tasks_request(api):
    return api.model('FetchInterruptedTasksRequest', {
        'worker_id': fields.String(required=False, description='Worker ID', default='unknown'),
        'limit': fields.Integer(required=False, description='获取数量', default=1, min=1, max=10),
        'timeout_minutes': fields.Integer(required=False, description='超时时间（分钟）', default=30)
    })

def create_interrupted_task_model(api):
    return api.model('InterruptedTask', {
        'task_id': fields.Integer(required=True, description='任务ID'),
        'dataset_id': fields.String(required=True, description='数据集ID'),
        'storage_path': fields.String(required=False, description='存储路径'),
        'priority': fields.Integer(required=True, description='优先级'),
        'retry_count': fields.Integer(required=True, description='重试次数'),
        'is_recovery': fields.Boolean(required=True, description='是否为恢复任务'),
        'previous_progress': fields.Nested(api.model('PreviousProgress', {
            'percentage': fields.Float(description='先前进度百分比'),
            'downloaded_bytes': fields.Integer(description='已下载字节数'),
            'total_bytes': fields.Integer(description='总字节数')
        }), required=False, description='先前进度信息')
    })

def create_fetch_interrupted_tasks_response(api, interrupted_task_model):
    return api.model('FetchInterruptedTasksResponse', {
        'tasks': fields.List(fields.Nested(interrupted_task_model), description='中断任务列表'),
        'count': fields.Integer(description='任务数量'),
        'message': fields.String(description='消息')
    })

def create_get_interrupted_tasks_response(api):
    return api.model('GetInterruptedTasksResponse', {
        'tasks': fields.List(fields.Nested(api.model('InterruptedTaskInfo', {
            'task_id': fields.Integer(required=True, description='任务ID'),
            'dataset_id': fields.String(required=True, description='数据集ID'),
            'priority': fields.Integer(required=True, description='优先级'),
            'retry_count': fields.Integer(required=True, description='重试次数'),
            'progress_percentage': fields.Float(description='进度百分比'),
            'downloaded_bytes': fields.Integer(description='已下载字节数'),
            'total_bytes': fields.Integer(description='总字节数'),
            'started_at': fields.String(description='开始时间'),
            'updated_at': fields.String(description='更新时间')
        })), description='中断任务列表'),
        'count': fields.Integer(description='任务数量'),
        'timeout_minutes': fields.Integer(description='超时时间')
    })

def create_reset_interrupted_tasks_request(api):
    return api.model('ResetInterruptedTasksRequest', {
        'timeout_minutes': fields.Integer(required=False, description='超时时间（分钟）', default=30)
    })

def create_reset_interrupted_tasks_response(api):
    return api.model('ResetInterruptedTasksResponse', {
        'message': fields.String(required=True, description='响应消息'),
        'count': fields.Integer(required=True, description='重置的任务数量'),
        'timeout_minutes': fields.Integer(required=True, description='超时时间')
    })

def create_feishu_webhook_model(api):
    return api.model('FeishuWebhookRequest', {
        'schema': fields.String(description='事件模式版本'),
        'header': fields.Raw(description='事件头信息'),
        'event': fields.Raw(description='事件体'),
        'type': fields.String(description='事件类型 (兼容旧版)'),
        'challenge': fields.String(description='URL验证challenge'),
        'token': fields.String(description='验证令牌')
    })

def create_feishu_webhook_response(api):
    return api.model('FeishuWebhookResponse', {
        'challenge': fields.String(description='URL验证challenge'),
        'code': fields.Integer(description='Lark响应码'),
        'msg': fields.String(description='Lark响应消息'),
        'success': fields.Boolean(description='业务处理是否成功'),
        'message': fields.String(description='业务响应消息')
    })

def create_feishu_notify_model(api):
    return api.model('FeishuNotifyRequest', {
        'event_type': fields.String(required=True, description='事件类型'),
        'dataset_id': fields.String(description='数据集ID'),
        'message': fields.String(description='消息内容'),
        'metadata': fields.Raw(description='附加元数据')
    })

def create_feishu_notify_response(api):
    return api.model('FeishuNotifyResponse', {
        'success': fields.Boolean(description='是否成功'),
        'message': fields.String(description='响应消息')
    })

# =========================================================================
# Monitor API Models
# =========================================================================

def create_overview_stats_model(api):
    return api.model('OverviewStats', {
        'status_counts': fields.Raw(description='各状态任务数量'),
        'today_added': fields.Integer(description='今日新增'),
        'today_completed': fields.Integer(description='今日完成'),
        'failed_count': fields.Integer(description='失败总数'),
        'timestamp': fields.String(description='统计时间')
    })

def create_queue_progress_model(api):
    return api.model('QueueProgress', {
        'percentage': fields.Float(description='进度百分比'),
        'downloaded_bytes': fields.Integer(description='已下载字节'),
        'total_bytes': fields.Integer(description='总字节'),
        'total_files': fields.Integer(description='总文件数'),
        'completed_files': fields.Integer(description='已完成文件数'),
        'download_speed': fields.Float(description='下载速度'),
        'progress_status': fields.String(description='进度状态')
    })

def create_queue_task_detail_model(api, progress_model):
    return api.model('QueueTaskDetail', {
        'id': fields.Integer(description='任务ID'),
        'dataset_id': fields.String(description='数据集ID'),
        'priority': fields.Integer(description='优先级'),
        'status': fields.String(description='状态'),
        'retry_count': fields.Integer(description='重试次数'),
        'last_error': fields.String(description='最后错误信息'),
        'storage_path': fields.String(description='存储路径'),
        'created_at': fields.String(description='创建时间'),
        'started_at': fields.String(description='开始时间'),
        'completed_at': fields.String(description='完成时间'),
        'updated_at': fields.String(description='更新时间'),
        'progress': fields.Nested(progress_model, description='进度信息')
    })

def create_queue_list_response(api, task_detail_model):
    return api.model('QueueListResponse', {
        'tasks': fields.List(fields.Nested(task_detail_model), description='任务列表'),
        'total': fields.Integer(description='总数'),
        'page': fields.Integer(description='当前页'),
        'per_page': fields.Integer(description='每页数量'),
        'total_pages': fields.Integer(description='总页数')
    })

def create_timeline_stats_model(api):
    return api.model('TimelineStats', {
        'completed_timeline': fields.List(fields.Raw, description='每日完成数'),
        'created_timeline': fields.List(fields.Raw, description='每日新增数')
    })

def create_dataset_search_model(api):
    return api.model('DatasetSearchResult', {
        'id': fields.String(description='ID'),
        'name': fields.String(description='名称'),
        'description': fields.String(description='描述'),
        'downloads': fields.Integer(description='下载量'),
        'likes': fields.Integer(description='点赞数'),
        'last_modified': fields.String(description='最后修改时间'),
        'tags': fields.List(fields.String, description='标签'),
        'author': fields.String(description='作者')
    })

def create_dataset_search_response(api, dataset_model):
    return api.model('DatasetSearchResponse', {
        'datasets': fields.List(fields.Nested(dataset_model), description='搜索结果'),
        'total': fields.Integer(description='总数'),
        'query': fields.String(description='查询关键词')
    })

def create_manual_task_request(api):
    return api.model('ManualTaskRequest', {
        'dataset_id': fields.String(required=True, description='数据集或模型 ID'),
        'priority': fields.Integer(description='优先级', default=0),
        'storage_path': fields.String(description='存储路径'),
        'force': fields.Boolean(description='强制重新下载', default=False),
        'repo_type': fields.String(description='仓库类型 (dataset/model)', default='dataset'),
        'tar_enabled': fields.Boolean(description='是否启用打包'),
        'tar_compress': fields.Boolean(description='是否压缩'),
        'tar_split_size': fields.String(description='分卷大小'),
        'tar_split_threshold': fields.String(description='分卷阈值'),
        'tar_delete_source': fields.Boolean(description='是否删除源文件')
    })

def create_manual_task_response(api):
    return api.model('ManualTaskResponse', {
        'message': fields.String(description='消息'),
        'task_id': fields.Integer(description='任务ID'),
        'dataset_id': fields.String(description='数据集ID')
    })

# Monitor 批量删除任务
def create_batch_delete_request(api):
    return api.model('BatchDeleteRequest', {
        'task_ids': fields.List(fields.Integer, required=True, description='要删除的任务ID列表')
    })

def create_batch_delete_response(api):
    return api.model('BatchDeleteResponse', {
        'deleted': fields.Integer(description='成功删除的任务数量'),
        'task_ids': fields.List(fields.Integer, description='已删除的任务ID')
    })
