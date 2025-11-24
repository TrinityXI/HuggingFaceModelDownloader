#!/bin/bash
# 部署生产者和消费者服务（macOS Launchd）

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DISCOVER_DIR="$(dirname "$SCRIPT_DIR")"
SERVICES_DIR="$DATA_DISCOVER_DIR/services"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"

echo "=========================================="
echo "部署 HuggingFace 生产者和消费者服务"
echo "=========================================="

# 创建日志目录
mkdir -p "$DATA_DISCOVER_DIR/logs"

# 检查服务文件是否存在
if [ ! -f "$SERVICES_DIR/producer.plist" ] || [ ! -f "$SERVICES_DIR/consumer.plist" ]; then
    echo "错误: 服务文件不存在"
    echo "请确保以下文件存在:"
    echo "  - $SERVICES_DIR/producer.plist"
    echo "  - $SERVICES_DIR/consumer.plist"
    exit 1
fi

# 复制服务文件到 LaunchAgents
echo ""
echo "复制服务文件到 LaunchAgents..."
cp "$SERVICES_DIR/producer.plist" "$LAUNCH_AGENTS_DIR/com.huggingface.producer.plist"
cp "$SERVICES_DIR/consumer.plist" "$LAUNCH_AGENTS_DIR/com.huggingface.consumer.plist"

echo "✅ 服务文件已复制"
echo ""

# 提示用户修改配置
echo "⚠️  请编辑以下文件，修改路径和配置："
echo "  - $LAUNCH_AGENTS_DIR/com.huggingface.producer.plist"
echo "  - $LAUNCH_AGENTS_DIR/com.huggingface.consumer.plist"
echo ""
echo "特别是："
echo "  1. 修改 HF_TOKEN（如果需要）"
echo "  2. 确认所有路径正确"
echo ""

read -p "是否已修改配置？(y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "请先修改配置，然后重新运行此脚本"
    exit 1
fi

# 加载服务
echo ""
echo "加载服务..."

# 先卸载（如果已存在）
launchctl unload "$LAUNCH_AGENTS_DIR/com.huggingface.producer.plist" 2>/dev/null || true
launchctl unload "$LAUNCH_AGENTS_DIR/com.huggingface.consumer.plist" 2>/dev/null || true

# 加载服务
launchctl load "$LAUNCH_AGENTS_DIR/com.huggingface.producer.plist"
launchctl load "$LAUNCH_AGENTS_DIR/com.huggingface.consumer.plist"

echo "✅ 服务已加载"
echo ""

# 启动服务
echo "启动服务..."
launchctl start com.huggingface.producer
launchctl start com.huggingface.consumer

echo "✅ 服务已启动"
echo ""

# 显示状态
echo "=========================================="
echo "服务状态"
echo "=========================================="
launchctl list | grep huggingface || echo "未找到服务（可能需要等待几秒）"
echo ""

echo "=========================================="
echo "管理命令"
echo "=========================================="
echo "查看状态: launchctl list | grep huggingface"
echo "查看日志: tail -f $DATA_DISCOVER_DIR/logs/producer_service.log"
echo "查看日志: tail -f $DATA_DISCOVER_DIR/logs/consumer_service.log"
echo "停止服务: launchctl stop com.huggingface.producer"
echo "停止服务: launchctl stop com.huggingface.consumer"
echo "卸载服务: launchctl unload $LAUNCH_AGENTS_DIR/com.huggingface.producer.plist"
echo "卸载服务: launchctl unload $LAUNCH_AGENTS_DIR/com.huggingface.consumer.plist"
echo ""

