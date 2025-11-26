#!/bin/bash
# 构建生产者和消费者 Docker 镜像（支持多架构）

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 配置
PRODUCER_IMAGE="hf-producer"
CONSUMER_IMAGE="hf-consumer"
DOWNLOADER_IMAGE="huggingface-downloader"
DEFAULT_ARCH="amd64"

# 显示帮助信息
show_help() {
    echo -e "${BLUE}构建生产者和消费者 Docker 镜像${NC}"
    echo ""
    echo "用法:"
    echo "  $0 [选项]"
    echo ""
    echo "选项:"
    echo "  -a, --arch ARCH     指定架构 (amd64, arm64) [默认: amd64]"
    echo "  -t, --tag TAG       指定镜像标签 [默认: latest]"
    echo "  -p, --producer-only 只构建生产者镜像"
    echo "  -c, --consumer-only 只构建消费者镜像"
    echo "  -d, --downloader    同时构建下载器镜像"
    echo "  -h, --help          显示此帮助信息"
    echo ""
    echo "示例:"
    echo "  $0                          # 构建所有镜像（amd64）"
    echo "  $0 -a amd64                  # 构建 amd64 架构"
    echo "  $0 -a arm64                  # 构建 arm64 架构"
    echo "  $0 -p                        # 只构建生产者镜像"
    echo "  $0 -c -d                     # 构建消费者和下载器镜像"
    echo ""
}

# 解析参数
ARCH="${DEFAULT_ARCH}"
TAG="latest"
BUILD_PRODUCER=true
BUILD_CONSUMER=true
BUILD_DOWNLOADER=false

while [[ $# -gt 0 ]]; do
    case $1 in
        -a|--arch)
            ARCH="$2"
            shift 2
            ;;
        -t|--tag)
            TAG="$2"
            shift 2
            ;;
        -p|--producer-only)
            BUILD_CONSUMER=false
            BUILD_DOWNLOADER=false
            shift
            ;;
        -c|--consumer-only)
            BUILD_PRODUCER=false
            BUILD_DOWNLOADER=false
            shift
            ;;
        -d|--downloader)
            BUILD_DOWNLOADER=true
            shift
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            echo -e "${RED}未知参数: $1${NC}"
            show_help
            exit 1
            ;;
    esac
done

# 验证架构
if [[ "$ARCH" != "amd64" && "$ARCH" != "arm64" ]]; then
    echo -e "${RED}错误: 不支持的架构 '$ARCH'，仅支持 amd64 或 arm64${NC}"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DISCOVER_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_ROOT="$(dirname "$DATA_DISCOVER_DIR")"

cd "$DATA_DISCOVER_DIR"

# 构建函数
build_producer() {
    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}构建生产者镜像 (${ARCH})${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
    
    docker build \
        --build-arg TARGETOS=linux \
        --build-arg TARGETARCH=${ARCH} \
        -f Dockerfile.redis-producer \
        -t ${PRODUCER_IMAGE}:${TAG}-${ARCH} \
        .
    
    echo ""
    echo -e "${GREEN}✅ 生产者镜像构建成功！${NC}"
    echo -e "${GREEN}   镜像标签: ${PRODUCER_IMAGE}:${TAG}-${ARCH}${NC}"
    echo ""
}

build_consumer() {
    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}构建消费者镜像 (${ARCH})${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
    
    docker build \
        --build-arg TARGETOS=linux \
        --build-arg TARGETARCH=${ARCH} \
        -f Dockerfile.persistent-consumer \
        -t ${CONSUMER_IMAGE}:${TAG}-${ARCH} \
        .
    
    echo ""
    echo -e "${GREEN}✅ 消费者镜像构建成功！${NC}"
    echo -e "${GREEN}   镜像标签: ${CONSUMER_IMAGE}:${TAG}-${ARCH}${NC}"
    echo ""
}

build_downloader() {
    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}构建下载器镜像 (${ARCH})${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
    
    cd "$PROJECT_ROOT"
    
    docker build \
        --build-arg TARGETOS=linux \
        --build-arg TARGETARCH=${ARCH} \
        -f Dockerfile \
        -t ${DOWNLOADER_IMAGE}:${TAG}-${ARCH} \
        .
    
    echo ""
    echo -e "${GREEN}✅ 下载器镜像构建成功！${NC}"
    echo -e "${GREEN}   镜像标签: ${DOWNLOADER_IMAGE}:${TAG}-${ARCH}${NC}"
    echo ""
    
    cd "$DATA_DISCOVER_DIR"
}

# 主逻辑
echo -e "${BLUE}开始构建 Docker 镜像 (架构: ${ARCH})${NC}"

if [[ "$BUILD_PRODUCER" == true ]]; then
    build_producer
fi

if [[ "$BUILD_CONSUMER" == true ]]; then
    build_consumer
fi

if [[ "$BUILD_DOWNLOADER" == true ]]; then
    build_downloader
fi

# 显示镜像信息
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}构建完成！镜像列表:${NC}"
echo -e "${BLUE}========================================${NC}"
docker images | grep -E "${PRODUCER_IMAGE}|${CONSUMER_IMAGE}|${DOWNLOADER_IMAGE}" | grep "${TAG}-${ARCH}" | head -10

