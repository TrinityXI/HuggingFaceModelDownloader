# Docker 使用指南

本指南介绍如何使用 Docker 镜像来运行 HuggingFaceModelDownloader。

---

## 🚀 快速开始

### 方式一：从 Docker Hub 拉取（推荐）⭐

如果镜像已发布到 Docker Hub，直接拉取使用：

```bash
# 拉取镜像（替换 yourusername 为实际的 Docker Hub 用户名）
docker pull yourusername/huggingface-downloader:latest

# 下载数据集
docker run --rm \
  --dns 8.8.8.8 \
  --dns 114.114.114.114 \
  -v $(pwd)/Datasets:/data \
  yourusername/huggingface-downloader:latest \
  download fka/awesome-chatgpt-prompts \
  --dataset \
  -o /data/test2 \
  --endpoint https://hf-mirror.com
```

### 方式二：本地构建

#### 1. 构建镜像

```bash
docker build -t huggingface-downloader:latest .
```

#### 2. 下载数据集

```bash
# 基本用法（推荐：添加 DNS 配置避免超时）
docker run --rm \
  --dns 8.8.8.8 \
  --dns 114.114.114.114 \
  -v $(pwd)/Datasets:/data \
  huggingface-downloader:latest \
  download fka/awesome-chatgpt-prompts \
  --dataset \
  -o /data \
  --endpoint https://hf-mirror.com
```

**⚠️ 重要**：如果遇到 DNS 解析超时错误，请添加 `--dns` 参数。详见 [故障排除指南](./DOCKER_TROUBLESHOOTING.md)。

**参数说明**：
- `--rm`: 容器运行后自动删除
- `-v $(pwd)/Datasets:/data`: 将当前目录的 `Datasets` 文件夹挂载到容器的 `/data` 目录
- `fka/awesome-chatgpt-prompts`: 数据集名称
- `--dataset`: 指定这是数据集（不是模型）
- `-o /data`: 输出目录（容器内的路径）
- `--endpoint https://hf-mirror.com`: 使用镜像端点

#### 3. 下载模型

```bash
docker run --rm \
  -v $(pwd)/Models:/data \
  huggingface-downloader:latest \
  download TheBloke/Mistral-7B-Instruct-v0.2-GGUF:q4_0 \
  -o /data \
  --endpoint https://hf-mirror.com
```

---

### 方式二：使用 Docker Compose（推荐）

#### 1. 构建并运行

```bash
# 下载数据集
docker-compose run --rm hfdownloader \
  download fka/awesome-chatgpt-prompts \
  --dataset \
  -o /data \
  --endpoint https://hf-mirror.com
```

#### 2. 自定义配置

编辑 `docker-compose.yml` 文件：

```yaml
services:
  hfdownloader:
    volumes:
      - /your/custom/path:/data  # 修改为你的路径
    environment:
      - HFD_ENDPOINT=https://hf-mirror.com
      - HF_TOKEN=your_token_here  # 如果需要 token
```

---

## 📝 常用命令示例

### 下载数据集到指定目录

```bash
docker run --rm \
  -v /path/to/your/datasets:/data \
  huggingface-downloader:latest \
  download fka/awesome-chatgpt-prompts \
  --dataset \
  -o /data/test2 \
  --endpoint https://hf-mirror.com
```

### 使用环境变量设置端点

```bash
docker run --rm \
  -v $(pwd)/Datasets:/data \
  -e HFD_ENDPOINT=https://hf-mirror.com \
  huggingface-downloader:latest \
  download facebook/flores \
  --dataset \
  -o /data
```

### 下载需要认证的私有仓库

```bash
docker run --rm \
  -v $(pwd)/Models:/data \
  -e HF_TOKEN=your_token_here \
  huggingface-downloader:latest \
  download owner/private-model \
  -o /data \
  --endpoint https://hf-mirror.com
```

### 预览下载计划（Dry-Run）

```bash
docker run --rm \
  -v $(pwd)/Datasets:/data \
  huggingface-downloader:latest \
  download fka/awesome-chatgpt-prompts \
  --dataset \
  -o /data \
  --endpoint https://hf-mirror.com \
  --dry-run
```

### 使用 JSON 输出（适合 CI/CD）

```bash
docker run --rm \
  -v $(pwd)/Datasets:/data \
  huggingface-downloader:latest \
  download fka/awesome-chatgpt-prompts \
  --dataset \
  -o /data \
  --endpoint https://hf-mirror.com \
  --json | jq '.'
```

### 调整并发参数

```bash
docker run --rm \
  -v $(pwd)/Datasets:/data \
  huggingface-downloader:latest \
  download large-dataset \
  --dataset \
  -o /data \
  --endpoint https://hf-mirror.com \
  --connections 16 \
  --max-active 5
```

---

## 🔧 高级用法

### 创建便捷脚本

创建 `download.sh` 脚本：

```bash
#!/bin/bash
# download.sh - 便捷下载脚本

REPO=$1
OUTPUT_DIR=${2:-/data}
DATASET_FLAG=${3:-""}  # 如果第三个参数是 "dataset"，则添加 --dataset

if [ "$DATASET_FLAG" = "dataset" ]; then
  docker run --rm \
    -v $(pwd)/Datasets:/data \
    huggingface-downloader:latest \
    download "$REPO" \
    --dataset \
    -o "$OUTPUT_DIR" \
    --endpoint https://hf-mirror.com
else
  docker run --rm \
    -v $(pwd)/Models:/data \
    huggingface-downloader:latest \
    download "$REPO" \
    -o "$OUTPUT_DIR" \
    --endpoint https://hf-mirror.com
fi
```

使用方式：

```bash
chmod +x download.sh

# 下载数据集
./download.sh fka/awesome-chatgpt-prompts /data/test2 dataset

# 下载模型
./download.sh TheBloke/Mistral-7B-Instruct-v0.2-GGUF:q4_0 /data
```

### 使用别名简化命令

在 `~/.bashrc` 或 `~/.zshrc` 中添加：

```bash
alias hfd='docker run --rm -v $(pwd)/Datasets:/data huggingface-downloader:latest'
```

然后就可以直接使用：

```bash
hfd download fka/awesome-chatgpt-prompts --dataset -o /data/test2 --endpoint https://hf-mirror.com
```

---

## 📦 镜像信息

### 镜像大小

- 构建阶段：~300MB（包含 Go 编译环境）
- 最终镜像：~20MB（Alpine Linux + 二进制文件）

### 镜像标签

```bash
# 构建带版本标签的镜像
docker build -t huggingface-downloader:v2.0.0 .
docker build -t huggingface-downloader:latest .
```

### 推送到 Docker Hub

```bash
# 登录
docker login

# 标记镜像
docker tag huggingface-downloader:latest yourusername/huggingface-downloader:latest

# 推送
docker push yourusername/huggingface-downloader:latest
```

---

## 🐛 故障排除

### 权限问题

如果遇到权限问题，可以：

1. **检查挂载目录权限**：
   ```bash
   ls -la Datasets/
   ```

2. **使用 root 用户运行**（不推荐，仅用于测试）：
   ```bash
   docker run --rm --user root \
     -v $(pwd)/Datasets:/data \
     huggingface-downloader:latest \
     download ...
   ```

### 网络问题

如果镜像端点无法访问：

1. **尝试官方端点**：
   ```bash
   docker run --rm \
     -v $(pwd)/Datasets:/data \
     huggingface-downloader:latest \
     download ... \
     --endpoint https://huggingface.co
   ```

2. **使用自动故障切换**：
   ```bash
   docker run --rm \
     -v $(pwd)/Datasets:/data \
     huggingface-downloader:latest \
     download ... \
     --mirror https://hf-mirror.com \
     --use-mirror-on-failure
   ```

### 查看帮助

```bash
docker run --rm huggingface-downloader:latest download --help
```

---

## 📚 相关文档

- [README.md](./README.md) - 完整功能文档
- [MIRROR_GUIDE.md](./MIRROR_GUIDE.md) - 镜像使用指南
- [COMPARISON.md](./COMPARISON.md) - 与官方工具对比

---

## 💡 最佳实践

1. **使用命名卷**（适合生产环境）：
   ```bash
   docker volume create hf-datasets
   docker run --rm -v hf-datasets:/data ...
   ```

2. **设置资源限制**：
   ```bash
   docker run --rm \
     --memory="2g" \
     --cpus="2" \
     -v $(pwd)/Datasets:/data \
     ...
   ```

3. **使用环境变量文件**：
   ```bash
   # .env 文件
   HFD_ENDPOINT=https://hf-mirror.com
   HF_TOKEN=your_token
   
   # 使用
   docker run --rm --env-file .env ...
   ```

4. **定期更新镜像**：
   ```bash
   docker pull huggingface-downloader:latest
   ```

