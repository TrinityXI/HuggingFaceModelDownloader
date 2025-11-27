@echo off
REM 快速启动脚本 - RabbitMQ 下载系统 (Windows)

echo ===================================
echo RabbitMQ 下载系统 - 快速启动
echo ===================================
echo.

REM 检查 Docker 是否运行
docker info >nul 2>&1
if errorlevel 1 (
    echo ❌ 错误: Docker 未运行，请先启动 Docker
    pause
    exit /b 1
)

echo ✅ Docker 已运行
echo.

REM 检查必要文件
if not exist "docker-compose.rabbitmq.yml" (
    echo ❌ 错误: 未找到 docker-compose.rabbitmq.yml
    pause
    exit /b 1
)

echo ✅ 配置文件检查通过
echo.

echo 📝 配置提示:
echo    - HF_TOKEN: HuggingFace 访问令牌 (可选)
echo    - HF_ENDPOINT: 镜像站点 (默认: https://hf-mirror.com)
echo.

REM 询问是否配置 Token
set /p CONFIG_TOKEN="是否配置 HF_TOKEN? (y/N): "
if /i "%CONFIG_TOKEN%"=="y" (
    set /p HF_TOKEN="请输入 HF_TOKEN: "
    echo ✅ HF_TOKEN 已设置
) else (
    echo ⚠️  未设置 HF_TOKEN，将使用公开访问
)
echo.

REM 构建镜像
echo 🔨 开始构建 Docker 镜像...
docker-compose -f docker-compose.rabbitmq.yml build

if errorlevel 1 (
    echo ❌ 构建失败
    pause
    exit /b 1
)

echo ✅ 构建完成
echo.

REM 启动服务
echo 🚀 启动服务...
docker-compose -f docker-compose.rabbitmq.yml up -d

if errorlevel 1 (
    echo ❌ 启动失败
    pause
    exit /b 1
)

echo.
echo ✅ 服务启动成功！
echo.
echo ===================================
echo 服务访问地址:
echo ===================================
echo 📊 RabbitMQ 管理界面: http://localhost:15672
echo    用户名: admin
echo    密码: password123
echo.
echo 📈 监控服务: http://localhost:8080/metrics
echo 💚 健康检查: http://localhost:8080/health
echo.
echo ===================================
echo 常用命令:
echo ===================================
echo 查看日志: docker-compose -f docker-compose.rabbitmq.yml logs -f
echo 停止服务: docker-compose -f docker-compose.rabbitmq.yml down
echo 重启服务: docker-compose -f docker-compose.rabbitmq.yml restart
echo.
echo 查看 consumer 日志:
echo   docker-compose -f docker-compose.rabbitmq.yml logs -f rabbitmq-consumer
echo.
echo 查看 producer 日志:
echo   docker-compose -f docker-compose.rabbitmq.yml logs -f rabbitmq-producer
echo.
pause
