# Docker Hub 快速发布指南

## 🚀 三步发布到 Docker Hub

### 步骤 1: 登录 Docker Hub

```bash
docker login
```

输入你的 Docker Hub 用户名和密码。

### 步骤 2: 使用发布脚本（推荐）

```bash
# 设置你的 Docker Hub 用户名
export DOCKERHUB_USERNAME=yourusername

# 执行发布脚本
./scripts/publish.sh
```

### 步骤 3: 验证发布

```bash
# 测试拉取镜像
docker pull yourusername/huggingface-downloader:latest

# 测试运行
docker run --rm yourusername/huggingface-downloader:latest download --help
```

---

## 📝 手动发布步骤

如果不想使用脚本，可以手动执行：

```bash
# 1. 登录
docker login

# 2. 打标签（替换 yourusername）
docker tag huggingface-downloader:latest yourusername/huggingface-downloader:latest
docker tag huggingface-downloader:latest yourusername/huggingface-downloader:v2.0.0

# 3. 推送
docker push yourusername/huggingface-downloader:latest
docker push yourusername/huggingface-downloader:v2.0.0
```

---

## 🎯 使用发布的镜像

其他人可以这样使用：

```bash
# 拉取镜像
docker pull yourusername/huggingface-downloader:latest

# 下载数据集
docker run --rm \
  --dns 8.8.8.8 \
  --dns 114.114.114.114 \
  -v $(pwd)/Datasets:/data \
  yourusername/huggingface-downloader:latest \
  download RUC-NLPIR/FlashRAG_datasets \
  --dataset -o /data/FlashRAG_datasets \
  --endpoint https://hf-mirror.com
```

---

## 📚 详细文档

- [完整发布指南](./DOCKER_PUBLISH.md) - 详细的发布说明和最佳实践
- [Docker 使用指南](./DOCKER_GUIDE.md) - 如何使用 Docker 镜像

