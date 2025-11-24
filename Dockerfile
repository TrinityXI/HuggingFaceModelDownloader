# 多阶段构建：先编译，后运行
# Stage 1: 构建阶段
FROM golang:1.23-alpine AS builder

# 构建参数：支持多架构
ARG TARGETOS=linux
ARG TARGETARCH=amd64

# 安装必要的构建工具
RUN apk add --no-cache git

# 设置工作目录
WORKDIR /build

# 复制 go mod 文件
COPY go.mod go.sum ./

# 下载依赖
RUN go mod download

# 复制源代码
COPY . .

# 整理模块依赖（确保本地包被识别）
RUN go mod tidy

# 构建二进制文件（使用构建参数）
RUN CGO_ENABLED=0 GOOS=${TARGETOS} GOARCH=${TARGETARCH} go build -ldflags="-w -s" -o hfd .

# Stage 2: 运行阶段
FROM alpine:latest

# 安装必要的运行时依赖（ca-certificates 用于 HTTPS）
RUN apk --no-cache add ca-certificates tzdata

# 创建非 root 用户
RUN addgroup -g 1000 hfduser && \
    adduser -D -u 1000 -G hfduser hfduser

# 设置工作目录
WORKDIR /app

# 从构建阶段复制二进制文件
COPY --from=builder /build/hfd /app/hfd

# 设置权限
RUN chmod +x /app/hfd

# 切换到非 root 用户
USER hfduser

# 设置默认的数据目录
ENV HFD_OUTPUT_DIR=/data

# 设置默认镜像端点（适合国内网络环境）
ENV HFD_ENDPOINT=https://hf-mirror.com

# 入口点
ENTRYPOINT ["/app/hfd"]

# 默认命令
CMD ["download", "--help"]

