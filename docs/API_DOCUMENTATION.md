# HuggingFace Model Downloader API 文档

本文档描述 Producer 服务的 REST API 接口。

## Swagger UI

服务提供了 Swagger UI 界面，用于交互式 API 文档和测试：

- **URL**: `http://localhost:8000/api/docs/`
- **描述**: 完整的 OpenAPI 3.0 文档，包含所有已注册的 API 端点

## API 端点概览

### 消费者 API (`/api/consumer`)

| 端点 | 方法 | 描述 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/fetch-tasks` | POST | 拉取待处理任务 |
| `/update-status` | POST | 更新任务状态 |
| `/update-progress` | POST | 更新下载进度 |
| `/log-event` | POST | 记录事件 |
| `/fetch-interrupted-tasks` | POST | 拉取中断的任务 |
| `/get-interrupted-tasks` | GET | 获取中断任务列表 |
| `/reset-interrupted-tasks` | POST | 重置中断任务 |

### 飞书机器人 API (`/api/feishu`)

| 端点 | 方法 | 描述 |
|------|------|------|
| `/webhook` | POST | 飞书机器人 webhook 端点 |
| `/notify` | POST | 发送通知到飞书（内部 API） |
| `/test` | GET | 测试飞书机器人连接 |

## 详细端点说明

### 1. 健康检查

```
GET /api/consumer/health
```

**响应**:
```json
{
  "status": "healthy",
  "timestamp": "2025-12-23T10:30:00.123456",
  "service": "producer"
}
```

### 2. 拉取待处理任务

```
POST /api/consumer/fetch-tasks
```

**请求体**:
```json
{
  "worker_id": "consumer-1",
  "limit": 5
}
```

**参数**:
- `worker_id`: Worker 标识符（可选）
- `limit`: 获取任务数量（1-10，默认1）

**响应**:
```json
{
  "tasks": [
    {
      "task_id": 123,
      "dataset_id": "user/dataset-name",
      "storage_path": "/path/to/storage",
      "priority": 3,
      "retry_count": 0,
      "tar_config": {
        "enabled": true,
        "compress": true,
        "split_size": "50GiB",
        "split_threshold": "100GiB",
        "delete_source": false
      }
    }
  ],
  "count": 1,
  "message": "成功"
}
```

### 3. 更新任务状态

```
POST /api/consumer/update-status
```

**请求体**:
```json
{
  "dataset_id": "user/dataset",
  "status": "downloading|completed|failed|pending",
  "message": "错误信息（可选）",
  "storage_path": "存储路径（完成时可选）"
}
```

### 4. 飞书机器人 Webhook

```
POST /api/feishu/webhook
```

**请求头**:
- `X-Lark-Request-Timestamp`: 时间戳
- `X-Lark-Request-Signature`: 签名

**请求体**（飞书事件格式）:
```json
{
  "type": "url_verification",
  "challenge": "test-challenge"
}
```

或
```json
{
  "type": "event_callback",
  "event": {
    "type": "message",
    "msg_type": "text",
    "content": "{\"text\":\"status\"}"
  }
}
```

## 使用 Swagger UI

### 访问 Swagger UI

1. 启动 Producer 服务:
   ```bash
   docker-compose up -d producer
   ```

2. 打开浏览器访问:
   ```
   http://localhost:8000/api/docs/
   ```

### 功能特性

1. **交互式文档**: 查看所有 API 端点的详细说明
2. **在线测试**: 直接在浏览器中测试 API 调用
3. **模型定义**: 查看请求和响应的数据模型
4. **认证信息**: 显示需要的认证头信息

### 在 Swagger UI 中测试 API

1. 展开感兴趣的 API 端点
2. 点击 "Try it out" 按钮
3. 填写请求参数（如果需要）
4. 点击 "Execute" 发送请求
5. 查看服务器响应和状态码

## 开发说明

### 添加新的 API 端点

要添加新的 API 端点并自动包含在 Swagger 文档中，使用以下模式:

```python
from flask_restx import Resource, fields

# 1. 定义数据模型
new_model = api.model('NewModel', {
    'field1': fields.String(required=True, description='字段说明'),
    'field2': fields.Integer(required=False, description='数字字段')
})

# 2. 创建资源类
@consumer_ns.route('/new-endpoint')
@consumer_ns.doc(description='端点说明')
@consumer_ns.expect(new_model, validate=True)
@consumer_ns.response(200, '成功', new_model)
@consumer_ns.response(400, '请求错误')
class NewEndpoint(Resource):
    def post(self):
        """处理 POST 请求"""
        data = request.get_json()
        # 处理逻辑
        return {'result': 'success'}, 200
```

### 现有路由的 Swagger 集成

当前部分路由已集成 Swagger 文档:
- `/api/consumer/health` - 完全集成
- `/api/consumer/fetch-tasks` - 完全集成

其他路由仍使用传统的 `@app.route` 装饰器，但可以通过类似模式逐步迁移。

## 故障排除

### Swagger UI 无法访问

1. **检查服务状态**:
   ```bash
   docker-compose logs producer
   ```

2. **检查依赖安装**:
   ```bash
   docker-compose exec producer pip list | grep flask-restx
   ```

3. **验证端口**:
   ```bash
   curl http://localhost:8000/api/docs/
   ```

### API 调用失败

1. **查看服务日志**:
   ```bash
   docker-compose logs --tail=50 producer
   ```

2. **检查请求格式**:
   - 确认 Content-Type: application/json
   - 验证 JSON 格式正确

3. **验证签名**（飞书 API）:
   - 检查 `FEISHU_SECRET` 环境变量
   - 验证时间戳在 5 分钟内

## 相关文档

- [飞书机器人配置指南](./FEISHU_BOT_SETUP.md)
- [Docker 部署指南](./docker-compose.yml)
- [生产者服务代码](./producer/)