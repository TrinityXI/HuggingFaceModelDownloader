# Docker 镜像构建指南（x86/amd64）

本指南说明如何在 x86 (amd64) 机器上构建生产者和消费者服务的 Docker 镜像。

## 架构说明

系统包含三个 Docker 镜像：

1. **hf-producer** - 生产者服务镜像（定期扫描 HF 数据集）
2. **hf-consumer** - 消费者服务镜像（从队列读取任务并下载）
3. **huggingface-downloader** - 下载器镜像（实际执行下载）

## 前置条件

1. **Docker 已安装**
   ```bash
   docker --version
   # 需要 Docker 20.10+
   ```

2. **Docker Compose 已安装**（可选，用于统一管理）
   ```bash
   docker-compose --version
   ```

3. **足够的磁盘空间**
   - 基础镜像：~500MB
   - 构建后的镜像：~200-300MB 每个

## 快速开始

### 方式 1: 使用构建脚本（推荐）

```bash
cd Data-discover

# 构建所有镜像（amd64）
./scripts/build-services.sh -a amd64

# 只构建生产者镜像
./scripts/build-services.sh -p -a amd64

# 只构建消费者镜像
./scripts/build-services.sh -c -a amd64

# 同时构建下载器镜像
./scripts/build-services.sh -a amd64 -d
```

### 方式 2: 手动构建

#### 1. 构建下载器镜像（必须先构建）

```bash
cd /Users/jjl/llm-infra/HuggingFaceModelDownloader

docker build \
  --build-arg TARGETOS=linux \
  --build-arg TARGETARCH=amd64 \
  -t huggingface-downloader:latest-amd64 \
  .
```

#### 2. 构建生产者镜像

```bash
cd Data-discover

docker build \
  --build-arg TARGETOS=linux \
  --build-arg TARGETARCH=amd64 \
  -f Dockerfile.redis-producer \
  -t hf-producer:latest-amd64 \
  .
```

#### 3. 构建消费者镜像

```bash
cd Data-discover

docker build \
  --build-arg TARGETOS=linux \
  --build-arg TARGETARCH=amd64 \
  -f Dockerfile.persistent-consumer \
  -t hf-consumer:latest-amd64 \
  .
```

## 详细构建说明

### 1. 下载器镜像（huggingface-downloader）

**用途**: 实际执行数据集/模型下载的 Go 程序

**构建命令**:
```bash
cd /Users/jjl/llm-infra/HuggingFaceModelDownloader

docker build \
  --build-arg TARGETOS=linux \
  --build-arg TARGETARCH=amd64 \
  -t huggingface-downloader:latest-amd64 \
  .
```

**镜像特点**:
- 基于 `golang:1.23-alpine` 构建
- 多阶段构建，最终镜像仅 ~27.5MB
- 支持多架构（amd64, arm64）
- 包含完整的下载功能

**验证**:
```bash
docker run --rm huggingface-downloader:latest-amd64 download --help
```

### 2. 生产者镜像（hf-producer）

**用途**: 定期扫描 Hugging Face 数据集并添加到 SQLite 队列

**构建命令**:
```bash
cd Data-discover

docker build \
  --build-arg TARGETOS=linux \
  --build-arg TARGETARCH=amd64 \
  -f Dockerfile.redis-producer \
  -t hf-producer:latest-amd64 \
  .
```

**镜像特点**:
- 基于 `python:3.11-slim`（~150MB）
- 包含所有 Python 依赖
- 支持环境变量配置
- 非 root 用户运行（安全）

**环境变量**:
- `PRODUCER_INTERVAL`: 扫描间隔（秒，默认: 3600）
- `PRODUCER_DAYS`: 每次扫描最近 N 天（默认: 1）
- `PRODUCER_LIMIT`: 每天最多查询 N 个（默认: 100）
- `PRODUCER_ENDPOINT`: HF API 端点（默认: https://huggingface.co）
- `HF_TOKEN`: Hugging Face Token（可选）

**验证**:
```bash
docker run --rm hf-producer:latest-amd64 python producer_service.py --help
```

### 3. 消费者镜像（hf-consumer）

**用途**: 从 SQLite 队列读取任务并调用下载器镜像进行下载

**构建命令**:
```bash
cd Data-discover

docker build \
  --build-arg TARGETOS=linux \
  --build-arg TARGETARCH=amd64 \
  -f Dockerfile.persistent-consumer \
  -t hf-consumer:latest-amd64 \
  .
```

**镜像特点**:
- 基于 `python:3.11-slim`
- 需要访问 Docker daemon（挂载 `/var/run/docker.sock`）
- 支持调用其他 Docker 容器
- 非 root 用户运行

**环境变量**:
- `CONSUMER_DB`: 数据库路径（默认: datasets.db）
- `CONSUMER_OUTPUT`: 输出目录（默认: /data）
- `CONSUMER_DOCKER_IMAGE`: 下载器镜像名称（默认: huggingface-downloader:latest）
- `CONSUMER_ENDPOINT`: HF API 端点（默认: https://hf-mirror.com）
- `CONSUMER_WORKERS`: Worker 数量（默认: 1）
- `CONSUMER_MAX_ACTIVE`: 最大并发下载数（默认: 2）
- `CONSUMER_CONNECTIONS`: 每个文件的连接数（默认: 4）
- `HF_TOKEN`: Hugging Face Token（可选）

**验证**:
```bash
docker run --rm hf-consumer:latest-amd64 python consumer_docker.py --help
```

## 使用 Docker Compose 部署

### 1. 准备环境变量

创建 `.env` 文件（可选）:
```bash
cd Data-discover

cat > .env <<EOF
HF_TOKEN=your_token_here
PRODUCER_DAYS=1
PRODUCER_LIMIT=100
PRODUCER_INTERVAL=3600
PRODUCER_ENDPOINT=https://huggingface.co
CONSUMER_ENDPOINT=https://hf-mirror.com
CONSUMER_WORKERS=1
CONSUMER_MAX_ACTIVE=2
CONSUMER_CONNECTIONS=4
EOF
```

### 2. 初始化数据库

```bash
# 使用生产者容器初始化数据库
docker run --rm \
  -v $(pwd)/datasets.db:/app/datasets.db \
  hf-producer:latest-amd64 \
  python producer_lite.py --days 0
```

### 3. 启动服务

```bash
# 使用 Docker Compose 启动所有服务
docker-compose up -d

# 查看日志
docker-compose logs -f producer
docker-compose logs -f consumer

# 查看状态
docker-compose ps
```

### 4. 停止服务

```bash
docker-compose down
```

## 单独运行容器

### 运行生产者服务

```bash
cd Data-discover

docker run -d \
  --name hf-producer \
  --restart unless-stopped \
  -v $(pwd)/datasets.db:/app/datasets.db \
  -v $(pwd)/logs:/app/logs \
  -e HF_TOKEN=your_token_here \
  -e PRODUCER_INTERVAL=3600 \
  -e PRODUCER_DAYS=1 \
  -e PRODUCER_LIMIT=100 \
  hf-producer:latest-amd64
```

### 运行消费者服务

```bash
cd Data-discover

docker run -d \
  --name hf-consumer \
  --restart unless-stopped \
  -v $(pwd)/../Datasets:/data \
  -v $(pwd)/datasets.db:/app/datasets.db \
  -v $(pwd)/logs:/app/logs \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -e HF_TOKEN=your_token_here \
  -e CONSUMER_DOCKER_IMAGE=huggingface-downloader:latest-amd64 \
  -e CONSUMER_ENDPOINT=https://hf-mirror.com \
  -e CONSUMER_WORKERS=1 \
  -e CONSUMER_MAX_ACTIVE=2 \
  -e CONSUMER_CONNECTIONS=4 \
  hf-consumer:latest-amd64
```

**重要**: 消费者需要访问 Docker daemon，因此需要挂载 `/var/run/docker.sock`。

## 镜像验证

### 检查镜像是否构建成功

```bash
docker images | grep -E "hf-producer|hf-consumer|huggingface-downloader"
```

应该看到类似输出：
```
hf-producer              latest-amd64    <image-id>   <time>   200MB
hf-consumer              latest-amd64    <image-id>   <time>   250MB
huggingface-downloader   latest-amd64    <image-id>   <time>   27.5MB
```

### 测试镜像功能

#### 测试生产者镜像

```bash
# 测试单次运行
docker run --rm \
  -v $(pwd)/datasets.db:/app/datasets.db \
  hf-producer:latest-amd64 \
  python producer_service.py --once --days 1 --limit 5
```

#### 测试消费者镜像（dry-run）

```bash
# 测试消费者（dry-run 模式）
docker run --rm \
  -v $(pwd)/../Datasets:/data \
  -v $(pwd)/datasets.db:/app/datasets.db \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -e CONSUMER_DOCKER_IMAGE=huggingface-downloader:latest-amd64 \
  hf-consumer:latest-amd64 \
  python consumer_docker.py --dry-run --poll-interval 5
```

## 构建参数说明

### TARGETOS 和 TARGETARCH

参考主项目的 `Dockerfile`，支持多架构构建：

- `TARGETOS`: 目标操作系统（`linux`）
- `TARGETARCH`: 目标架构（`amd64` 或 `arm64`）

### 构建优化

- **多阶段构建**: 减少最终镜像大小
- **非 root 用户**: 提高安全性
- **最小化依赖**: 只包含运行时必需的包

## 常见问题

### 1. 构建失败 - 无法拉取基础镜像

**解决方案**:
```bash
# 手动拉取基础镜像
docker pull python:3.11-slim
docker pull golang:1.23-alpine
docker pull alpine:latest
```

### 2. 消费者无法调用 Docker

**问题**: 消费者容器无法访问 Docker daemon

**解决方案**:
- 确保挂载了 `/var/run/docker.sock`
- 检查 Docker daemon 是否运行
- 检查容器用户权限（可能需要将用户添加到 docker 组）

### 3. 数据库权限问题

**问题**: 容器无法写入数据库文件

**解决方案**:
```bash
# 确保数据库文件有正确的权限
chmod 666 datasets.db
chmod 666 datasets.db-shm
chmod 666 datasets.db-wal
```

### 4. 网络问题

**问题**: 容器内无法访问 Hugging Face API

**解决方案**:
- 检查网络配置
- 使用镜像站点（`https://hf-mirror.com`）
- 配置 DNS（`--dns 8.8.8.8`）

## 生产环境部署建议

### 1. 使用 Docker Compose

推荐使用 `docker-compose.yml` 统一管理服务：

```bash
cd Data-discover
docker-compose up -d
```

### 2. 配置日志轮转

```bash
# 在 docker-compose.yml 中添加日志配置
logging:
  driver: "json-file"
  options:
    max-size: "10m"
    max-file: "3"
```

### 3. 资源限制

```yaml
# 在 docker-compose.yml 中添加资源限制
deploy:
  resources:
    limits:
      cpus: '1.0'
      memory: 512M
```

### 4. 健康检查

服务已包含健康检查配置，可以通过以下命令查看：

```bash
docker-compose ps
```

## 完整部署流程

### 步骤 1: 构建所有镜像

```bash
cd Data-discover

# 构建所有镜像
./scripts/build-services.sh -a amd64 -d
```

### 步骤 2: 初始化数据库

```bash
# 使用生产者容器初始化
docker run --rm \
  -v $(pwd)/datasets.db:/app/datasets.db \
  hf-producer:latest-amd64 \
  python producer_lite.py --days 0
```

### 步骤 3: 启动服务

```bash
# 使用 Docker Compose
docker-compose up -d

# 或手动启动
docker run -d --name hf-producer ... hf-producer:latest-amd64
docker run -d --name hf-consumer ... hf-consumer:latest-amd64
```

### 步骤 4: 监控服务

```bash
# 查看日志
docker-compose logs -f

# 查看队列状态（需要在容器内或挂载脚本）
docker exec hf-producer python -c "import sqlite3; conn = sqlite3.connect('datasets.db'); print(conn.execute('SELECT COUNT(*) FROM download_queue WHERE status=\"pending\"').fetchone()[0])"
```

## 镜像大小参考

| 镜像 | 基础镜像 | 最终大小 | 说明 |
|------|---------|---------|------|
| huggingface-downloader | alpine:latest | ~27.5MB | Go 二进制，最小化 |
| hf-producer | python:3.11-slim | ~200MB | Python 运行时 + 依赖 |
| hf-consumer | python:3.11-slim | ~250MB | Python 运行时 + 依赖 + Docker CLI |

## 总结

通过 Docker 容器化部署，您可以：

✅ **统一环境** - 所有服务运行在相同的容器环境中  
✅ **易于部署** - 一次构建，到处运行  
✅ **资源隔离** - 每个服务独立运行，互不干扰  
✅ **易于扩展** - 可以轻松扩展多个消费者实例  
✅ **版本管理** - 通过镜像标签管理不同版本  

现在您可以在 x86 机器上轻松部署生产者和消费者服务了！

