#!/bin/bash
# 启动 Docker 消费者

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DISCOVER_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_ROOT="$(dirname "$DATA_DISCOVER_DIR")"

cd "$DATA_DISCOVER_DIR"

# 激活虚拟环境（如果存在）
if [ -d "download/bin" ]; then
    source download/bin/activate
fi

# 默认配置
DOCKER_IMAGE=${DOCKER_IMAGE:-"huggingface-downloader:latest"}
OUTPUT_DIR=${OUTPUT_DIR:-"$PROJECT_ROOT/Datasets"}
ENDPOINT=${ENDPOINT:-"https://hf-mirror.com"}
WORKERS=${WORKERS:-1}
DB_PATH=${DB_PATH:-"datasets.db"}

# 创建日志目录
mkdir -p logs

echo "=========================================="
echo "启动 Docker 消费者"
echo "=========================================="
echo "Docker 镜像: $DOCKER_IMAGE"
echo "输出目录: $OUTPUT_DIR"
echo "数据库: $DB_PATH"
echo "Worker 数量: $WORKERS"
echo "=========================================="

# 检查 Docker 镜像是否存在
if ! docker image inspect "$DOCKER_IMAGE" &>/dev/null; then
    echo "⚠️  警告: Docker 镜像 $DOCKER_IMAGE 不存在"
    echo "请先构建镜像: cd $PROJECT_ROOT && docker build -t $DOCKER_IMAGE ."
    exit 1
fi

# 启动消费者（后台运行）
nohup python consumer_docker.py \
    --db "$DB_PATH" \
    --output "$OUTPUT_DIR" \
    --docker-image "$DOCKER_IMAGE" \
    --endpoint "$ENDPOINT" \
    --workers "$WORKERS" \
    --max-active 2 \
    --connections 4 \
    > logs/consumer.log 2>&1 &

CONSUMER_PID=$!
echo "消费者已启动 (PID: $CONSUMER_PID)"
echo "日志文件: logs/consumer.log"
echo ""
echo "查看日志: tail -f logs/consumer.log"
echo "停止消费者: kill $CONSUMER_PID"
echo ""

# 保存 PID
echo $CONSUMER_PID > logs/consumer.pid

