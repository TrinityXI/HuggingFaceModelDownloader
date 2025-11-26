#!/bin/bash
# 快速启动脚本 - RabbitMQ 下载系统

echo "==================================="
echo "RabbitMQ 下载系统 - 快速启动"
echo "==================================="
echo ""

# 检查 Docker 是否运行
if ! docker info > /dev/null 2>&1; then
    echo "❌ 错误: Docker 未运行，请先启动 Docker"
    exit 1
fi

echo "✅ Docker 已运行"
echo ""

# 检查必要文件
if [ ! -f "docker-compose.rabbitmq.yml" ]; then
    echo "❌ 错误: 未找到 docker-compose.rabbitmq.yml"
    exit 1
fi

echo "✅ 配置文件检查通过"
echo ""

# 提示配置环境变量
echo "📝 配置提示:"
echo "   - HF_TOKEN: HuggingFace 访问令牌 (可选)"
echo "   - HF_ENDPOINT: 镜像站点 (默认: https://hf-mirror.com)"
echo ""

# 询问是否配置 Token
read -p "是否配置 HF_TOKEN? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    read -p "请输入 HF_TOKEN: " HF_TOKEN
    export HF_TOKEN
    echo "✅ HF_TOKEN 已设置"
else
    echo "⚠️  未设置 HF_TOKEN，将使用公开访问"
fi
echo ""

# 构建镜像
echo "🔨 开始构建 Docker 镜像..."
docker-compose -f docker-compose.rabbitmq.yml build

if [ $? -ne 0 ]; then
    echo "❌ 构建失败"
    exit 1
fi

echo "✅ 构建完成"
echo ""

# 启动服务
echo "🚀 启动服务..."
docker-compose -f docker-compose.rabbitmq.yml up -d

if [ $? -ne 0 ]; then
    echo "❌ 启动失败"
    exit 1
fi

echo ""
echo "✅ 服务启动成功！"
echo ""
echo "==================================="
echo "服务访问地址:"
echo "==================================="
echo "📊 RabbitMQ 管理界面: http://localhost:15672"
echo "   用户名: admin"
echo "   密码: password123"
echo ""
echo "📈 监控服务: http://localhost:8080/metrics"
echo "💚 健康检查: http://localhost:8080/health"
echo ""
echo "==================================="
echo "常用命令:"
echo "==================================="
echo "查看日志: docker-compose -f docker-compose.rabbitmq.yml logs -f"
echo "停止服务: docker-compose -f docker-compose.rabbitmq.yml down"
echo "重启服务: docker-compose -f docker-compose.rabbitmq.yml restart"
echo ""
echo "查看 consumer 日志:"
echo "  docker-compose -f docker-compose.rabbitmq.yml logs -f rabbitmq-consumer"
echo ""
echo "查看 producer 日志:"
echo "  docker-compose -f docker-compose.rabbitmq.yml logs -f rabbitmq-producer"
echo ""
