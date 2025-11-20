#!/bin/bash
# 便捷下载脚本 - 简化 Docker 使用

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 默认值
IMAGE_NAME="huggingface-downloader:latest"
DEFAULT_OUTPUT="/data"
DEFAULT_ENDPOINT="https://hf-mirror.com"
IS_DATASET=false

# 帮助信息
show_help() {
    cat << EOF
用法: $0 <repo> [output_dir] [options]

参数:
  repo              数据集或模型名称 (例如: fka/awesome-chatgpt-prompts)
  output_dir        输出目录 (默认: /data, 对应挂载的本地目录)

选项:
  -d, --dataset     指定这是数据集（不是模型）
  -m, --model       指定这是模型（默认）
  -e, --endpoint    指定端点 URL (默认: https://hf-mirror.com)
  -t, --token       设置 Hugging Face token
  -h, --help        显示此帮助信息

示例:
  # 下载数据集
  $0 fka/awesome-chatgpt-prompts ./Datasets/test2 --dataset

  # 下载模型
  $0 TheBloke/Mistral-7B-Instruct-v0.2-GGUF:q4_0 ./Models

  # 使用自定义端点
  $0 facebook/flores ./Datasets --dataset --endpoint https://huggingface.co

EOF
}

# 解析参数
REPO=""
OUTPUT_DIR="$DEFAULT_OUTPUT"
ENDPOINT="$DEFAULT_ENDPOINT"
TOKEN=""
EXTRA_ARGS=()

while [[ $# -gt 0 ]]; do
    case $1 in
        -d|--dataset)
            IS_DATASET=true
            shift
            ;;
        -m|--model)
            IS_DATASET=false
            shift
            ;;
        -e|--endpoint)
            ENDPOINT="$2"
            shift 2
            ;;
        -t|--token)
            TOKEN="$2"
            shift 2
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        -*)
            # 其他参数传递给 docker 命令
            EXTRA_ARGS+=("$1")
            if [[ "$2" != "" && "$2" != -* ]]; then
                EXTRA_ARGS+=("$2")
                shift
            fi
            shift
            ;;
        *)
            if [[ -z "$REPO" ]]; then
                REPO="$1"
            elif [[ "$OUTPUT_DIR" == "$DEFAULT_OUTPUT" ]]; then
                OUTPUT_DIR="$1"
            fi
            shift
            ;;
    esac
done

# 检查必需参数
if [[ -z "$REPO" ]]; then
    echo -e "${RED}错误: 必须指定数据集或模型名称${NC}"
    echo ""
    show_help
    exit 1
fi

# 检查镜像是否存在
if ! docker image inspect "$IMAGE_NAME" &>/dev/null; then
    echo -e "${YELLOW}警告: 镜像 $IMAGE_NAME 不存在，正在构建...${NC}"
    docker build -t "$IMAGE_NAME" .
fi

# 构建 Docker 命令（添加 DNS 配置以避免 DNS 超时）
DOCKER_CMD=(
    docker run --rm
    --dns 8.8.8.8
    --dns 114.114.114.114
    -v "$(pwd)/Datasets:/data"
    huggingface-downloader:latest
    download "$REPO"
)

# 添加数据集标志
if [[ "$IS_DATASET" == true ]]; then
    DOCKER_CMD+=(--dataset)
fi

# 添加输出目录
DOCKER_CMD+=(-o "$OUTPUT_DIR")

# 添加端点
DOCKER_CMD+=(--endpoint "$ENDPOINT")

# 添加 token（如果提供）
if [[ -n "$TOKEN" ]]; then
    DOCKER_CMD+=(-t "$TOKEN")
fi

# 添加额外参数
DOCKER_CMD+=("${EXTRA_ARGS[@]}")

# 显示执行信息
echo -e "${GREEN}正在下载: ${NC}$REPO"
echo -e "${GREEN}输出目录: ${NC}$OUTPUT_DIR"
echo -e "${GREEN}端点: ${NC}$ENDPOINT"
if [[ "$IS_DATASET" == true ]]; then
    echo -e "${GREEN}类型: ${NC}数据集"
else
    echo -e "${GREEN}类型: ${NC}模型"
fi
echo ""

# 执行命令
"${DOCKER_CMD[@]}"

echo ""
echo -e "${GREEN}✓ 下载完成！${NC}"

