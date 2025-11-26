# 生产者-消费者服务部署指南

本指南介绍如何将生产者和消费者部署为服务，实现持续自动化的数据集下载。

## 部署方案选择

### 方案 1: Systemd Service（Linux 推荐）
适合 Linux 服务器，作为系统服务运行，支持开机自启。

### 方案 2: Launchd（macOS 推荐）
适合 macOS 系统，使用 launchd 管理服务。

### 方案 3: Docker Compose（容器化推荐）
适合容器化部署，统一管理生产者和消费者。

### 方案 4: Cron + 后台脚本（简单方案）
适合简单场景，使用 cron 定时运行生产者，消费者后台运行。

---

## 方案 1: Systemd Service（Linux）

### 1.1 创建服务文件

#### 生产者服务

```bash
sudo nano /etc/systemd/system/hf-producer.service
```

内容：
```ini
[Unit]
Description=HuggingFace Dataset Producer Service
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/Users/jjl/llm-infra/HuggingFaceModelDownloader/Data-discover
Environment="PATH=/Users/jjl/llm-infra/HuggingFaceModelDownloader/Data-discover/download/bin:/usr/local/bin:/usr/bin:/bin"
Environment="HF_TOKEN=your_token_here"
ExecStart=/Users/jjl/llm-infra/HuggingFaceModelDownloader/Data-discover/download/bin/python /Users/jjl/llm-infra/HuggingFaceModelDownloader/Data-discover/producer_service.py --interval 3600 --days 1 --limit 100
Restart=always
RestartSec=10
StandardOutput=append:/Users/jjl/llm-infra/HuggingFaceModelDownloader/Data-discover/logs/producer_service.log
StandardError=append:/Users/jjl/llm-infra/HuggingFaceModelDownloader/Data-discover/logs/producer_service.error.log

[Install]
WantedBy=multi-user.target
```

#### 消费者服务

```bash
sudo nano /etc/systemd/system/hf-consumer.service
```

内容：
```ini
[Unit]
Description=HuggingFace Dataset Consumer Service
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User=your_user
WorkingDirectory=/Users/jjl/llm-infra/HuggingFaceModelDownloader/Data-discover
Environment="PATH=/Users/jjl/llm-infra/HuggingFaceModelDownloader/Data-discover/download/bin:/usr/local/bin:/usr/bin:/bin"
Environment="HF_TOKEN=your_token_here"
ExecStart=/Users/jjl/llm-infra/HuggingFaceModelDownloader/Data-discover/download/bin/python /Users/jjl/llm-infra/HuggingFaceModelDownloader/Data-discover/consumer_docker.py --db datasets.db --output ../Datasets --docker-image huggingface-downloader:latest --endpoint https://hf-mirror.com --workers 1 --max-active 2 --connections 4
Restart=always
RestartSec=10
StandardOutput=append:/Users/jjl/llm-infra/HuggingFaceModelDownloader/Data-discover/logs/consumer_service.log
StandardError=append:/Users/jjl/llm-infra/HuggingFaceModelDownloader/Data-discover/logs/consumer_service.error.log

[Install]
WantedBy=multi-user.target
```

### 1.2 启动服务

```bash
# 重新加载 systemd 配置
sudo systemctl daemon-reload

# 启动生产者服务
sudo systemctl enable hf-producer.service
sudo systemctl start hf-producer.service

# 启动消费者服务
sudo systemctl enable hf-consumer.service
sudo systemctl start hf-consumer.service

# 查看状态
sudo systemctl status hf-producer.service
sudo systemctl status hf-consumer.service
```

### 1.3 管理服务

```bash
# 查看日志
sudo journalctl -u hf-producer.service -f
sudo journalctl -u hf-consumer.service -f

# 停止服务
sudo systemctl stop hf-producer.service
sudo systemctl stop hf-consumer.service

# 重启服务
sudo systemctl restart hf-producer.service
sudo systemctl restart hf-consumer.service
```

---

## 方案 2: Launchd（macOS）

### 2.1 创建 Launch Agent

#### 生产者服务

```bash
nano ~/Library/LaunchAgents/com.huggingface.producer.plist
```

内容：
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.huggingface.producer</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/jjl/llm-infra/HuggingFaceModelDownloader/Data-discover/download/bin/python</string>
        <string>/Users/jjl/llm-infra/HuggingFaceModelDownloader/Data-discover/producer_service.py</string>
        <string>--interval</string>
        <string>3600</string>
        <string>--days</string>
        <string>1</string>
        <string>--limit</string>
        <string>100</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/jjl/llm-infra/HuggingFaceModelDownloader/Data-discover</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>HF_TOKEN</key>
        <string>your_token_here</string>
    </dict>
    <key>StandardOutPath</key>
    <string>/Users/jjl/llm-infra/HuggingFaceModelDownloader/Data-discover/logs/producer_service.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/jjl/llm-infra/HuggingFaceModelDownloader/Data-discover/logs/producer_service.error.log</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
```

#### 消费者服务

```bash
nano ~/Library/LaunchAgents/com.huggingface.consumer.plist
```

内容：
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.huggingface.consumer</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/jjl/llm-infra/HuggingFaceModelDownloader/Data-discover/download/bin/python</string>
        <string>/Users/jjl/llm-infra/HuggingFaceModelDownloader/Data-discover/consumer_docker.py</string>
        <string>--db</string>
        <string>datasets.db</string>
        <string>--output</string>
        <string>../Datasets</string>
        <string>--docker-image</string>
        <string>huggingface-downloader:latest</string>
        <string>--endpoint</string>
        <string>https://hf-mirror.com</string>
        <string>--workers</string>
        <string>1</string>
        <string>--max-active</string>
        <string>2</string>
        <string>--connections</string>
        <string>4</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/jjl/llm-infra/HuggingFaceModelDownloader/Data-discover</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>HF_TOKEN</key>
        <string>your_token_here</string>
    </dict>
    <key>StandardOutPath</key>
    <string>/Users/jjl/llm-infra/HuggingFaceModelDownloader/Data-discover/logs/consumer_service.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/jjl/llm-infra/HuggingFaceModelDownloader/Data-discover/logs/consumer_service.error.log</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
```

### 2.2 加载服务

```bash
# 加载生产者服务
launchctl load ~/Library/LaunchAgents/com.huggingface.producer.plist

# 加载消费者服务
launchctl load ~/Library/LaunchAgents/com.huggingface.consumer.plist

# 查看状态
launchctl list | grep huggingface
```

### 2.3 管理服务

```bash
# 卸载服务
launchctl unload ~/Library/LaunchAgents/com.huggingface.producer.plist
launchctl unload ~/Library/LaunchAgents/com.huggingface.consumer.plist

# 启动服务
launchctl start com.huggingface.producer
launchctl start com.huggingface.consumer

# 停止服务
launchctl stop com.huggingface.producer
launchctl stop com.huggingface.consumer
```

---

## 方案 3: Docker Compose（容器化）

### 3.1 准备 Dockerfile

已创建 `Dockerfile.redis-producer` 用于构建生产者镜像。

### 3.2 使用 Docker Compose

```bash
cd Data-discover

# 构建并启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f producer
docker-compose logs -f consumer

# 停止服务
docker-compose down

# 重启服务
docker-compose restart
```

### 3.3 注意事项

- 消费者服务需要访问 Docker daemon（挂载 `/var/run/docker.sock`）
- 需要确保数据库文件在容器间共享
- 需要确保输出目录在容器间共享

---

## 方案 4: Cron + 后台脚本（简单方案）

### 4.1 设置 Cron 定时任务

```bash
crontab -e
```

添加以下行（每小时运行一次生产者）：

```bash
0 * * * * cd /Users/jjl/llm-infra/HuggingFaceModelDownloader/Data-discover && source download/bin/activate && python producer_lite.py --days 1 --limit 100 >> logs/producer_cron.log 2>&1
```

### 4.2 启动消费者（后台运行）

```bash
cd Data-discover
./scripts/start_consumer.sh
```

---

## 推荐方案对比

| 方案 | 优点 | 缺点 | 适用场景 |
|------|------|------|----------|
| **Systemd** | 稳定、开机自启、日志管理好 | 仅 Linux | Linux 服务器 |
| **Launchd** | macOS 原生、开机自启 | 仅 macOS | macOS 开发机 |
| **Docker Compose** | 容器化、易于部署、隔离好 | 需要 Docker | 容器化环境 |
| **Cron + 后台** | 简单、无需 root | 无自动重启 | 简单场景 |

---

## 服务联动说明

### 工作流程

```
生产者服务 (定期运行)
    ↓
扫描 HF API → 添加到 SQLite 队列
    ↓
消费者服务 (持续运行)
    ↓
从队列读取 → 调用 Docker 下载器 → 更新状态
```

### 数据共享

- **SQLite 数据库** (`datasets.db`): 生产者和消费者共享
- **输出目录** (`../Datasets`): 消费者写入，生产者不访问

### 服务依赖

- **生产者**: 独立运行，不依赖消费者
- **消费者**: 独立运行，不依赖生产者（但需要队列中有任务）

### 启动顺序

1. 先启动生产者（初始化数据库和队列）
2. 再启动消费者（开始处理队列）

或同时启动，两者互不干扰。

---

## 监控和维护

### 查看服务状态

```bash
# Systemd
sudo systemctl status hf-producer.service
sudo systemctl status hf-consumer.service

# Launchd
launchctl list | grep huggingface

# Docker Compose
docker-compose ps
```

### 查看日志

```bash
# Systemd
sudo journalctl -u hf-producer.service -f
sudo journalctl -u hf-consumer.service -f

# Launchd
tail -f ~/Library/Logs/com.huggingface.producer.log
tail -f ~/Library/Logs/com.huggingface.consumer.log

# Docker Compose
docker-compose logs -f producer
docker-compose logs -f consumer

# 脚本方式
tail -f Data-discover/logs/producer_service.log
tail -f Data-discover/logs/consumer_service.log
```

### 监控队列

```bash
cd Data-discover
./scripts/monitor.sh
```

---

## 故障排除

### 生产者服务无法启动

1. 检查 Python 环境和依赖
2. 检查数据库文件权限
3. 查看日志文件

### 消费者服务无法启动

1. 检查 Docker 是否运行
2. 检查 Docker 镜像是否存在
3. 检查输出目录权限
4. 查看日志文件

### 服务无法联动

1. 检查数据库文件路径是否一致
2. 检查数据库文件权限
3. 使用 `monitor.sh` 查看队列状态

---

## 快速开始

### 使用 Systemd（Linux）

```bash
# 1. 复制服务文件
sudo cp Data-discover/services/producer.service /etc/systemd/system/
sudo cp Data-discover/services/consumer.service /etc/systemd/system/

# 2. 修改服务文件中的路径和用户
sudo nano /etc/systemd/system/hf-producer.service
sudo nano /etc/systemd/system/hf-consumer.service

# 3. 启动服务
sudo systemctl daemon-reload
sudo systemctl enable --now hf-producer.service
sudo systemctl enable --now hf-consumer.service
```

### 使用 Launchd（macOS）

```bash
# 1. 复制 plist 文件
cp Data-discover/services/producer.plist ~/Library/LaunchAgents/com.huggingface.producer.plist
cp Data-discover/services/consumer.plist ~/Library/LaunchAgents/com.huggingface.consumer.plist

# 2. 修改 plist 文件中的路径
nano ~/Library/LaunchAgents/com.huggingface.producer.plist

# 3. 加载服务
launchctl load ~/Library/LaunchAgents/com.huggingface.producer.plist
launchctl load ~/Library/LaunchAgents/com.huggingface.consumer.plist
```

### 使用 Docker Compose

```bash
cd Data-discover
docker-compose up -d
```

---

## 总结

通过将生产者和消费者部署为服务，您可以：

✅ **自动化运行** - 无需手动启动  
✅ **持续扫描** - 定期发现新数据集  
✅ **自动下载** - 队列中的任务自动处理  
✅ **服务管理** - 使用系统工具管理服务  
✅ **日志记录** - 完整的日志记录和监控  

选择适合您环境的部署方案，开始自动化下载 Hugging Face 数据集！

