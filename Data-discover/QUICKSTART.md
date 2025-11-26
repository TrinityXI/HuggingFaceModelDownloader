# 快速开始：生产者-消费者联调指南

本指南将帮助您快速启动生产者和消费者，实现自动化的数据集下载。

## 架构概览

```
┌────────────────────┐         ┌──────────────────┐         ┌────────────────────┐
│  Producer          │────────▶│  SQLite 队列     │◀────────│  Consumer          │
│  (Python)          │         │  (download_queue)│         │  (Python + Docker)│
│                    │         │                  │         │                    │
│ - 扫描 HF API      │         │ - 待下载任务     │         │ - 读取待处理任务   │
│ - 插入待下载任务   │         │ - 任务状态       │         │ - 调用 Docker 下载  │
│ - 去重检查         │         │ - 优先级         │         │ - 更新任务状态     │
└────────────────────┘         └──────────────────┘         └────────────────────┘
```

## 前置条件

### 方式 A: 本地 Python 环境（开发/测试）

1. **Docker 已安装并运行**
   ```bash
   docker --version
   ```

2. **Python 环境已配置**
   ```bash
   cd Data-discover
   # 如果使用虚拟环境
   source download/bin/activate
   ```

3. **Docker 镜像已构建**
   ```bash
   cd /Users/jjl/llm-infra/HuggingFaceModelDownloader
   docker build -t huggingface-downloader:latest .
   ```

### 方式 B: Docker 容器化部署（生产环境推荐）

1. **Docker 和 Docker Compose 已安装**
   ```bash
   docker --version
   docker-compose --version
   ```

2. **构建所有必需的镜像**
   ```bash
   cd Data-discover
   ./scripts/build-services.sh -a amd64
   ```

   这会构建：
   - `hf-producer:latest-amd64` - 生产者服务镜像
   - `hf-consumer:latest-amd64` - 消费者服务镜像
   - `huggingface-downloader:latest-amd64` - 下载器镜像（如果使用 `-d` 选项）

## 步骤 1: 初始化数据库

首次运行前，需要初始化数据库表结构：

```bash
cd Data-discover
python producer_lite.py --days 0  # 只初始化表，不扫描数据
```

或者直接运行一次生产者（会自动创建表）：

```bash
./scripts/start_producer.sh
```

## 步骤 2: 启动生产者（扫描数据集）

生产者负责扫描 Hugging Face 上的数据集并添加到下载队列。

### 方式 1: 使用脚本（推荐）

```bash
# 扫描最近 1 天，每天最多 100 个数据集
DAYS=1 LIMIT=100 ./scripts/start_producer.sh
```

### 方式 2: 直接运行

```bash
python producer_lite.py --days 1 --limit 100
```

### 参数说明

- `--days N`: 扫描最近 N 天的数据集（默认: 7）
- `--limit N`: 每天最多查询 N 个数据集（默认: 1000）
- `--min-downloads N`: 最小下载量过滤（默认: 0）
- `--min-likes N`: 最小点赞数过滤（默认: 0）
- `--endpoint URL`: HF API 端点（默认: https://huggingface.co）

### 查看队列状态

```bash
./scripts/monitor.sh
```

## 步骤 3: 启动消费者（下载数据集）

消费者从队列读取任务并调用 Docker 下载器进行下载。

### 方式 1: 使用脚本（推荐）

```bash
# 使用默认配置启动
./scripts/start_consumer.sh

# 或自定义配置
DOCKER_IMAGE=huggingface-downloader:latest \
OUTPUT_DIR=../Datasets \
WORKERS=1 \
./scripts/start_consumer.sh
```

### 方式 2: 直接运行（前台）

```bash
python consumer_docker.py \
    --db datasets.db \
    --output ../Datasets \
    --docker-image huggingface-downloader:latest \
    --endpoint https://hf-mirror.com \
    --workers 1 \
    --max-active 2 \
    --connections 4
```

### 参数说明

- `--db PATH`: SQLite 数据库路径（默认: datasets.db）
- `--output DIR`: 输出目录（默认: ./Datasets）
- `--docker-image NAME`: Docker 镜像名称（默认: huggingface-downloader:latest）
- `--endpoint URL`: HF API 端点（默认: https://hf-mirror.com）
- `--workers N`: Worker 数量（建议 1-3，默认: 1）
- `--max-active N`: 最大并发下载数（默认: 2）
- `--connections N`: 每个文件的连接数（默认: 4）
- `--poll-interval N`: 轮询间隔（秒，默认: 10）

### 查看日志

```bash
# 查看实时日志
tail -f logs/consumer.log

# 查看最后 50 行
tail -n 50 logs/consumer.log
```

### 停止消费者

```bash
# 如果使用脚本启动，会保存 PID
kill $(cat logs/consumer.pid)

# 或手动查找进程
ps aux | grep consumer_docker
kill <PID>
```

## 步骤 4: 监控和调试

### 查看队列状态

```bash
./scripts/monitor.sh
```

输出示例：
```
=== Download Queue Status ===
status      count  total_priority
----------  -----  --------------
pending     15     1250
downloading 1      0
completed   5      0
failed      2      0
```

### 查看下载进度

```bash
# 查看消费者日志
tail -f logs/consumer.log

# 查看下载的文件
ls -lh ../Datasets/
```

### 重置失败任务

```bash
sqlite3 datasets.db <<EOF
UPDATE download_queue
SET status = 'pending', retry_count = 0, last_error = NULL
WHERE status = 'failed';
EOF
```

## 完整联调示例

### 1. 初始化并添加测试任务

```bash
cd Data-discover

# 初始化数据库
python producer_lite.py --days 0

# 手动添加一个测试数据集
sqlite3 datasets.db <<EOF
INSERT OR IGNORE INTO download_queue (dataset_id, priority, status)
VALUES ('fka/awesome-chatgpt-prompts', 100, 'pending');
EOF

# 查看队列
./scripts/monitor.sh
```

### 2. 启动消费者

```bash
# 确保 Docker 镜像存在
cd ..
docker images | grep huggingface-downloader

# 启动消费者（前台运行，方便观察）
cd Data-discover
python consumer_docker.py \
    --db datasets.db \
    --output ../Datasets \
    --docker-image huggingface-downloader:latest \
    --endpoint https://hf-mirror.com \
    --workers 1
```

### 3. 观察下载过程

消费者会：
1. 从队列读取任务
2. 调用 Docker 下载器
3. 更新任务状态

您会看到类似输出：
```
============================================================
Docker 消费者启动
数据库: datasets.db
输出目录: /Users/jjl/llm-infra/HuggingFaceModelDownloader/Datasets
Docker 镜像: huggingface-downloader:latest
Worker 数量: 1
轮询间隔: 10 秒
============================================================
Worker 1 启动
[1] 开始下载: fka/awesome-chatgpt-prompts
  命令: docker run --rm --dns 8.8.8.8...
[1] ✅ 下载成功: fka/awesome-chatgpt-prompts
```

### 4. 添加更多任务

在另一个终端运行生产者：

```bash
cd Data-discover
python producer_lite.py --days 1 --limit 10
```

消费者会自动处理新添加的任务。

## 定时任务设置（可选）

### 设置生产者定时运行

```bash
crontab -e
```

添加以下行（每小时运行一次）：

```bash
0 * * * * cd /Users/jjl/llm-infra/HuggingFaceModelDownloader/Data-discover && source download/bin/activate && python producer_lite.py --days 1 --limit 100 >> logs/producer.log 2>&1
```

### 设置消费者开机自启

创建 systemd 服务文件（Linux）或使用 launchd（macOS）。

## 常见问题

### 1. Docker 镜像不存在

```bash
cd /Users/jjl/llm-infra/HuggingFaceModelDownloader
docker build -t huggingface-downloader:latest .
```

### 2. 数据库锁定错误

SQLite 的并发限制。建议：
- 使用单个 worker（`--workers 1`）
- 或使用 WAL 模式（已自动启用）

### 3. 下载失败

检查：
- Docker 是否正常运行
- 网络连接是否正常
- 输出目录是否有写权限
- 查看 `logs/consumer.log` 中的错误信息

### 4. 429 错误（速率限制）

消费者已使用推荐参数（`--max-active 2 --connections 4`）。
如果仍遇到，可以：
- 降低并发数
- 增加轮询间隔（`--poll-interval 30`）

## 下一步

- 查看 [LIGHTWEIGHT_INTEGRATION.md](./LIGHTWEIGHT_INTEGRATION.md) 了解详细设计
- 查看 [INTEGRATION_DESIGN.md](./INTEGRATION_DESIGN.md) 了解完整架构
- 调整生产者和消费者的参数以优化性能

