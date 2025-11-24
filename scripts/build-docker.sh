#!/bin/bash
# Docker 镜像构建脚本 - 支持多架构

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 配置
IMAGE_NAME="huggingface-downloader"
DEFAULT_ARCH="amd64"

# 显示帮助信息
show_help() {
    echo -e "${BLUE}Docker 镜像构建脚本${NC}"
    echo ""
    echo "用法:"
    echo "  $0 [选项]"
    echo ""
    echo "选项:"
    echo "  -a, --arch ARCH     指定架构 (amd64, arm64) [默认: amd64]"
    echo "  -t, --tag TAG       指定镜像标签 [默认: latest]"
    echo "  -b, --both          构建两个架构版本 (amd64 和 arm64)"
    echo "  -h, --help          显示此帮助信息"
    echo ""
    echo "示例:"
    echo "  $0                          # 构建 amd64 版本"
    echo "  $0 -a arm64                  # 构建 arm64 版本"
    echo "  $0 -a amd64 -t v2.0.0        # 构建 amd64 版本并打标签 v2.0.0"
    echo "  $0 -b                        # 构建两个架构版本"
    echo ""
}

# 解析参数
ARCH="${DEFAULT_ARCH}"
TAG="latest"
BUILD_BOTH=false

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
        -b|--both)
            BUILD_BOTH=true
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

# 构建函数
build_image() {
    local target_arch=$1
    local image_tag=$2
    local target_os="linux"
    
    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}构建 ${target_arch} 架构镜像${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
    
    # 根据架构设置 TARGETARCH
    local docker_arch=$target_arch
    if [[ "$target_arch" == "amd64" ]]; then
        docker_arch="amd64"
    elif [[ "$target_arch" == "arm64" ]]; then
        docker_arch="arm64"
    fi
    
    echo -e "${BLUE}架构: ${target_arch}${NC}"
    echo -e "${BLUE}标签: ${image_tag}${NC}"
    echo ""
    
    # 构建镜像（只创建带架构后缀的标签）
    docker build \
        --build-arg TARGETOS=${target_os} \
        --build-arg TARGETARCH=${docker_arch} \
        -t ${IMAGE_NAME}:${image_tag}-${target_arch} \
        .
    
    echo ""
    echo -e "${GREEN}✅ ${target_arch} 架构镜像构建成功！${NC}"
    echo -e "${GREEN}   镜像标签: ${IMAGE_NAME}:${image_tag}-${target_arch}${NC}"
    echo ""
}

# 主逻辑
if [[ "$BUILD_BOTH" == true ]]; then
    echo -e "${YELLOW}构建两个架构版本 (amd64 和 arm64)...${NC}"
    build_image "amd64" "$TAG"
    build_image "arm64" "$TAG"
    
    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}✅ 所有架构构建完成！${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
    echo "构建的镜像："
    echo "  - ${IMAGE_NAME}:${TAG}-amd64"
    echo "  - ${IMAGE_NAME}:${TAG}-arm64"
    echo ""
else
    build_image "$ARCH" "$TAG"
fi

# 显示镜像信息
echo -e "${BLUE}镜像列表:${NC}"
docker images | grep "${IMAGE_NAME}" | head -5

