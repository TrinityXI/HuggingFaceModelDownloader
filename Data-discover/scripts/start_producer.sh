#!/bin/bash
# 启动生产者脚本（单次运行）

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DISCOVER_DIR="$(dirname "$SCRIPT_DIR")"

cd "$DATA_DISCOVER_DIR"

# 激活虚拟环境（如果存在）
if [ -d "download/bin" ]; then
    source download/bin/activate
fi

# 默认参数
DAYS=${DAYS:-1}
LIMIT=${LIMIT:-100}
ENDPOINT=${ENDPOINT:-"https://huggingface.co"}

echo "=========================================="
echo "启动生产者（扫描最近 ${DAYS} 天）"
echo "=========================================="

python producer_lite.py \
    --days "$DAYS" \
    --limit "$LIMIT" \
    --endpoint "$ENDPOINT" \
    --db datasets.db

echo ""
echo "生产者运行完成！"
echo "查看队列状态: ./scripts/monitor.sh"

