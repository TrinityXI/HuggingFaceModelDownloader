# RabbitMQ 下载系统

本目录包含基于 RabbitMQ 消息队列的 HuggingFace 数据集下载系统的完整代码。

## 系统架构

```
┌─────────────┐      ┌──────────────┐      ┌─────────────┐
│   Producer  │─────▶│  RabbitMQ    │◀─────│  Consumer   │
│  (生产者)    │      │  (消息队列)   │      │  (消费者)    │
└─────────────┘      └──────────────┘      └─────────────┘
                            │
                            ▼
                     ┌──────────────┐
                     │   Monitor    │
                     │  (监控服务)   │
                     └──────────────┘
```

## 组件说明

### 1. Producer (生产者服务)
- **文件**: `producer/rabbitmq_producer.py`
- **功能**: 
  - 定期扫描 HuggingFace Hub 获取最新数据集
  - 将数据集信息发送到 RabbitMQ 队列
  - 支持按日期范围查询和自动限流
- **Dockerfile**: `Dockerfile.rabbitmq-producer`

### 2. Consumer (消费者服务)
- **文件**: 
  - `consumer/rabbitmq_consumer.py` - RabbitMQ 消费者
  - `consumer/persistent_consumer.py` - 持久化消费者
- **功能**:
  - 从 RabbitMQ 队列接收下载任务
  - 调用 Go 下载器 (`hfdownloader`) 执行实际下载
  - 支持并发下载和失败重试
  - 支持死信队列 (DLQ) 处理失败任务
- **Dockerfile**: `Dockerfile.rabbitmq-consumer`
- **关键特性**:
  - 多线程工作池
  - 自动重试机制
  - 超时控制

### 3. Monitor (监控服务)
- **文件**: `monitor/monitor_service.py`
- **功能**:
  - 提供 HTTP API 监控系统状态
  - 队列状态查询
  - 健康检查端点
- **Dockerfile**: `Dockerfile.monitor`
- **端点**:
  - `http://localhost:8080/health` - 健康检查
  - `http://localhost:8080/metrics` - 系统指标

### 4. RabbitMQ (消息队列)
- **镜像**: `rabbitmq:3-management-alpine`
- **配置**: `config/rabbitmq.conf`
- **端口**:
  - 5672 - AMQP 协议
  - 15672 - 管理界面
- **管理界面**: `http://localhost:15672`
  - 默认用户名: `admin`
  - 默认密码: `password123`

### 5. HFDownloader (Go 下载器)
- **版本**: v2.0.0
- **语言**: Go 1.23
- **文件**: 
  - `main.go` - 主程序入口
  - `ui_progress.go` - UI 进度显示
  - `hfdownloader/` - 核心库
- **特性**:
  - 支持模型和数据集下载
  - 断点续传
  - 多线程并发下载
  - 镜像站点支持
  - LFS 大文件支持
- **命令格式**:
  ```bash
  # 下载数据集
  hfdownloader download --dataset --repo OWNER/NAME --output PATH --endpoint URL
  
  # 下载模型（不加 --dataset）
  hfdownloader download --repo OWNER/NAME --output PATH
  
  # 查看帮助
  hfdownloader --help
  ```
- **构建**: 在 Docker 多阶段构建中自动编译

## 部署方式

### 快速启动（推荐）

**Linux/Mac:**
```bash
chmod +x start.sh
./start.sh
```

**Windows:**
```cmd
start.bat
```

脚本会自动：
1. 检查 Docker 环境
2. 询问是否配置 HF_TOKEN
3. 构建 Docker 镜像
4. 启动所有服务
5. 显示访问地址和常用命令

### 手动启动

#### 使用 Docker Compose

```bash
# 启动所有服务
docker-compose -f docker-compose.rabbitmq.yml up -d

# 查看日志
docker-compose -f docker-compose.rabbitmq.yml logs -f

# 停止服务
docker-compose -f docker-compose.rabbitmq.yml down
```

### 环境变量配置

创建 `.env` 文件或在 `docker-compose.rabbitmq.yml` 中配置:

```env
# RabbitMQ 配置
RABBITMQ_USER=admin
RABBITMQ_PASSWORD=password123

# HuggingFace 配置
HF_ENDPOINT=https://hf-mirror.com
HF_TOKEN=your_token_here

# Producer 配置
PRODUCER_INTERVAL=3600        # 扫描间隔(秒)
PRODUCER_DAYS=7               # 查询最近 N 天的数据集
PRODUCER_LIMIT=50             # 每次扫描的最大数据集数量

# Consumer 配置
CONSUMER_WORKERS=4            # 并发工作线程数
CONSUMER_MAX_RETRIES=3        # 最大重试次数
CONSUMER_TIMEOUT=3600         # 下载超时时间(秒)
CONSUMER_REPLICAS=2           # 消费者副本数
```

## 主要修复

### 1. HFDownloader CLI 兼容性
- **问题**: 旧版使用 `--type dataset`，新版 v2.0 使用 `download --dataset`
- **修复**: 更新了 `rabbitmq_consumer.py` 和 `persistent_consumer.py` 中的命令行参数

**旧命令格式**:
```bash
hfdownloader --type dataset --repo REPO --output PATH
```

**新命令格式**:
```bash
hfdownloader download --dataset --repo REPO --output PATH --endpoint URL
```

### 2. Go Binary 编译问题
- **问题**: 
  - 错误的模块结构导致无法编译
  - 名称冲突导致复制目录而非二进制文件
  - Go 版本不匹配 (需要 1.23)
- **修复**:
  - 在 `go.mod` 中添加了 replace 指令
  - 将输出二进制重命名为 `hfdownloader-bin` 避免冲突
  - 更新 Dockerfile 使用 Go 1.23

### 3. Docker 多阶段构建优化
- 第一阶段: 编译 Go 二进制文件
- 第二阶段: 创建最小化运行环境
- 使用层缓存优化构建速度

## 监控和维护

### 查看队列状态
访问 RabbitMQ 管理界面: `http://localhost:15672`

### 查看服务日志
```bash
# 所有服务
docker-compose -f docker-compose.rabbitmq.yml logs -f

# 特定服务
docker-compose -f docker-compose.rabbitmq.yml logs -f rabbitmq-consumer
docker-compose -f docker-compose.rabbitmq.yml logs -f rabbitmq-producer
```

### 扩展消费者
修改 `docker-compose.rabbitmq.yml` 中的 `CONSUMER_REPLICAS` 环境变量或使用:
```bash
docker-compose -f docker-compose.rabbitmq.yml up -d --scale rabbitmq-consumer=4
```

## 故障排查

### Consumer 无法连接到 RabbitMQ
1. 确保 RabbitMQ 服务已启动并健康
2. 检查网络配置
3. 验证用户名和密码

### 下载失败
1. 检查 HF_TOKEN 是否有效
2. 查看 consumer 日志确认错误信息
3. 检查死信队列 (DLQ) 中的失败任务

### 队列堆积
1. 增加 consumer 副本数
2. 调整 `CONSUMER_WORKERS` 增加并发
3. 检查下载速度和网络连接

## 文件结构

```
refactoring/rabbitmq-system/
├── README.md                           # 本文件
├── CHANGELOG.md                        # 变更日志
├── docker-compose.rabbitmq.yml         # Docker Compose 配置
├── Dockerfile.rabbitmq-consumer        # Consumer Dockerfile
├── Dockerfile.rabbitmq-producer        # Producer Dockerfile
├── Dockerfile.monitor                  # Monitor Dockerfile
├── go.mod                              # Go 模块定义
├── go.sum                              # Go 依赖校验
├── main.go                             # Go 主程序入口
├── ui_progress.go                      # Go UI 进度显示
├── hfdownloader/                       # Go 下载器库
│   ├── downloader.go                  # 下载器核心逻辑
│   ├── progress.go                    # 进度跟踪
│   ├── types.go                       # 类型定义
│   └── go.mod                         # 子模块定义
├── Data-discover/                      # 数据集发现模块
│   ├── query_datasets_by_date.py      # 按日期查询数据集
│   ├── dataset_db.py                  # 数据库操作
│   ├── producer_service.py            # 生产者服务
│   └── requirements.txt
├── consumer/                           # 消费者代码
│   ├── rabbitmq_consumer.py
│   ├── persistent_consumer.py
│   └── requirements.txt
├── producer/                           # 生产者代码
│   ├── rabbitmq_producer.py
│   └── requirements.txt
├── monitor/                            # 监控服务代码
│   ├── monitor_service.py
│   └── requirements.txt
└── config/                             # 配置文件
    └── rabbitmq.conf
```

## 技术栈

- **消息队列**: RabbitMQ 3.13
- **编程语言**: Python 3.11 (服务), Go 1.23 (下载器)
- **容器化**: Docker, Docker Compose
- **Web 框架**: Flask (监控服务)
- **Python 库**: pika (RabbitMQ 客户端), requests (HTTP 客户端)

## 许可证

Apache 2.0
