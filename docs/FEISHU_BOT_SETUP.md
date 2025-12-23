# 飞书机器人集成配置指南

本文档介绍如何配置 HuggingFace Model Downloader 的飞书机器人集成功能。

## 功能概述

飞书机器人集成提供以下功能：

1. **系统事件通知**：当新数据集被发现、下载任务开始/完成/失败时发送通知
2. **命令交互**：在飞书群中通过命令查询系统状态、触发操作
3. **实时监控**：监控下载队列状态和系统健康状态

## 配置步骤

### 步骤1：创建飞书群机器人

1. 在飞书中创建一个群聊（如果还没有）
2. 点击群设置 -> 添加机器人 -> 自定义机器人
3. 配置机器人：
   - 机器人名称：例如 "HuggingFace下载器"
   - 描述：可选
   - 选择消息类型：勾选"消息"和"卡片"
4. 获取 webhook URL 和签名密钥：
   - 复制 webhook URL（格式：`https://open.feishu.cn/open-apis/bot/v2/hook/xxxxx`）
   - 复制签名密钥（secret）

### 步骤2：配置环境变量

有两种方式配置飞书机器人：

#### 方式一：Docker Compose 环境变量

在 `docker-compose.yml` 文件所在目录创建 `.env` 文件：

```bash
# 飞书机器人配置
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxxxx
FEISHU_SECRET=your_secret_key_here
```

或者直接修改 `docker-compose.yml` 中的环境变量值。

#### 方式二：直接设置环境变量

```bash
export FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxxxx
export FEISHU_SECRET=your_secret_key_here
```

### 步骤3：重启服务

```bash
docker-compose down
docker-compose up -d producer
```

## API 端点

飞书机器人集成添加了以下 API 端点：

### 1. Webhook 端点
- **URL**: `POST /api/feishu/webhook`
- **用途**: 接收飞书机器人消息，处理命令
- **飞书配置**: 将此 URL 配置为机器人的 webhook URL（需公网可访问）

### 2. 通知端点
- **URL**: `POST /api/feishu/notify`
- **用途**: 内部 API，用于发送系统事件通知
- **请求体**:
  ```json
  {
    "event_type": "dataset_discovered",
    "dataset_id": "user/dataset-name",
    "message": "详细消息",
    "metadata": {"key": "value"}
  }
  ```

### 3. 测试端点
- **URL**: `GET /api/feishu/test`
- **用途**: 测试飞书机器人连接

## 可用命令

在飞书群中 @机器人 或直接发送命令：

### 基础命令
- `help` - 显示帮助信息
- `status` - 显示系统状态
- `config` - 查看当前配置

### 队列管理
- `queue stats` - 查看队列统计信息
- `queue pending` - 查看待处理任务
- `queue downloading` - 查看正在下载的任务

### 操作命令
- `scan now` - 立即触发数据集扫描
- `reset interrupted` - 重置所有中断的下载任务
- `stats` - 查看系统统计信息

### 任务查询
- `tasks <dataset_id>` - 查看特定数据集任务详情

## 事件通知

系统会自动发送以下事件的通知：

### 数据集发现
- **事件类型**: `dataset_discovered`
- **触发时机**: 扫描到新数据集并加入下载队列时
- **通知内容**: 发现的数据集数量、处理统计

### 下载状态
- `download_started` - 下载任务开始
- `download_completed` - 下载任务完成
- `download_failed` - 下载任务失败

### 系统状态
- `system_alert` - 系统告警
- `queue_status` - 队列状态变化（当队列积压时）
- `manual_trigger` - 手动触发操作

## 故障排除

### 1. 收不到通知
- 检查飞书机器人 webhook URL 是否正确配置
- 检查飞书机器人是否已添加到群聊
- 查看 producer 服务日志：`docker-compose logs producer`

### 2. 命令不响应
- 检查 webhook URL 是否可公网访问
- 验证飞书机器人签名密钥配置
- 测试 API 端点：`curl http://localhost:8000/api/feishu/test`

### 3. 签名验证失败
- 检查 `FEISHU_SECRET` 环境变量是否正确
- 确保飞书机器人的签名密钥与配置一致
- 检查系统时间是否准确（时间偏差不能超过5分钟）

## 安全注意事项

1. **签名验证**: 所有飞书 webhook 请求都会验证签名，防止伪造请求
2. **时间戳验证**: 防止重放攻击，只接受5分钟内的请求
3. **可选功能**: 飞书机器人是可选的，不配置不影响核心功能
4. **敏感信息**: 通知中不会包含敏感信息（如密码、密钥）

## 扩展开发

### 添加新命令
编辑 `producer/feishu_bot.py` 中的 `FeishuCommandHandler` 类，添加新的命令方法。

### 添加新事件类型
在 `FeishuBot.send_notification` 方法中添加新的事件类型配置。

### 自定义通知格式
修改 `FeishuBot.send_message` 方法中的消息模板。

## 参考链接

- [飞书开放平台 - 自定义机器人](https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot)
- [HuggingFace Model Downloader 项目文档](./docs/)