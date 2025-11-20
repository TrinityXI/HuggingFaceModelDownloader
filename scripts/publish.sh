#!/bin/bash
# Docker Hub 发布脚本

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 配置
DOCKERHUB_USERNAME="${DOCKERHUB_USERNAME:-}"
IMAGE_NAME="huggingface-downloader"
VERSION="${VERSION:-v2.0.0}"

# 检查用户名
if [[ -z "$DOCKERHUB_USERNAME" ]]; then
    echo -e "${RED}错误: 请设置 DOCKERHUB_USERNAME 环境变量${NC}"
    echo ""
    echo "使用方式:"
    echo "  export DOCKERHUB_USERNAME=yourusername"
    echo "  ./scripts/publish.sh"
    echo ""
    exit 1
fi

echo -e "${GREEN}🚀 发布 Docker 镜像到 Docker Hub${NC}"
echo "用户名: $DOCKERHUB_USERNAME"
echo "镜像名: $IMAGE_NAME"
echo "版本: $VERSION"
echo ""

# 检查本地镜像是否存在
if ! docker image inspect ${IMAGE_NAME}:latest &>/dev/null; then
    echo -e "${YELLOW}⚠️  本地镜像不存在，正在构建...${NC}"
    docker build -t ${IMAGE_NAME}:latest .
fi

# 检查是否已登录（检查 Docker 配置文件）
if [ ! -f ~/.docker/config.json ] || ! grep -q "auths" ~/.docker/config.json 2>/dev/null; then
    echo -e "${YELLOW}⚠️  请先登录 Docker Hub:${NC}"
    echo "  docker login"
    exit 1
fi

# 尝试获取当前登录用户（可选检查）
CURRENT_USER=$(docker info 2>/dev/null | grep -i "username" | awk '{print $2}' || echo "")
if [[ -n "$CURRENT_USER" ]]; then
    echo -e "${GREEN}✓ 已登录 Docker Hub (用户: $CURRENT_USER)${NC}"
fi

# 打标签
echo -e "${GREEN}📦 给镜像打标签...${NC}"
docker tag ${IMAGE_NAME}:latest ${DOCKERHUB_USERNAME}/${IMAGE_NAME}:latest
docker tag ${IMAGE_NAME}:latest ${DOCKERHUB_USERNAME}/${IMAGE_NAME}:${VERSION}

echo "  ✓ ${DOCKERHUB_USERNAME}/${IMAGE_NAME}:latest"
echo "  ✓ ${DOCKERHUB_USERNAME}/${IMAGE_NAME}:${VERSION}"

# 推送
echo ""
echo -e "${GREEN}⬆️  推送镜像到 Docker Hub...${NC}"
docker push ${DOCKERHUB_USERNAME}/${IMAGE_NAME}:latest
docker push ${DOCKERHUB_USERNAME}/${IMAGE_NAME}:${VERSION}

echo ""
echo -e "${GREEN}✅ 发布成功！${NC}"
echo ""
echo "其他人可以使用以下命令拉取镜像："
echo ""
echo "  docker pull ${DOCKERHUB_USERNAME}/${IMAGE_NAME}:latest"
echo ""
echo "或直接使用："
echo ""
echo "  docker run --rm \\"
echo "    --dns 8.8.8.8 \\"
echo "    --dns 114.114.114.114 \\"
echo "    -v \$(pwd)/Datasets:/data \\"
echo "    ${DOCKERHUB_USERNAME}/${IMAGE_NAME}:latest \\"
echo "    download fka/awesome-chatgpt-prompts \\"
echo "    --dataset -o /data/test2 \\"
echo "    --endpoint https://hf-mirror.com"
echo ""

