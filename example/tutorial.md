# HuggingFace Model Downloader - Docker 使用教程

本教程将指导您如何构建和使用 HuggingFace Model Downloader 的 Docker 镜像。

## 前提条件

- 已安装 Docker
- 网络连接正常（建议配置 DNS：8.8.8.8 和 114.114.114.114）

## 步骤 1: 构建 Docker 镜像

在项目根目录执行以下命令构建镜像：

```bash
docker build -t huggingface-downloader:latest .
```

### 构建说明

- **镜像名称**: `huggingface-downloader:latest`
- **构建时间**: 首次构建约需 2-5 分钟（取决于网络速度）
- **镜像大小**: 约 27.5MB（多阶段构建，最终镜像仅包含运行时必需文件）

### 构建过程

镜像使用多阶段构建：

1. **构建阶段** (golang:1.23-alpine):
   - 编译 Go 源代码
   - 生成静态链接的二进制文件 `hfd`

2. **运行阶段** (alpine:latest):
   - 仅包含运行时依赖
   - 使用非 root 用户运行（安全）
   - 默认端点设置为 `https://hf-mirror.com`（适合国内网络环境）

## 步骤 2: 验证镜像构建

检查镜像是否构建成功：

```bash
docker images | grep huggingface-downloader
```

应该看到类似输出：
```
huggingface-downloader   latest    <image-id>   <time>   27.5MB
```

## 步骤 3: 使用镜像下载数据集

### 基本用法

```bash
docker run --rm \
  --dns 8.8.8.8 \
  --dns 114.114.114.114 \
  -v $(pwd)/Datasets:/data \
  huggingface-downloader:latest \
  download fka/awesome-chatgpt-prompts \
  --dataset \
  -o /data/tutorial_test \
  --endpoint https://hf-mirror.com \
  --max-active 2 \
  --connections 4
```

### 参数说明

- `--rm`: 容器运行后自动删除
- `--dns 8.8.8.8 --dns 114.114.114.114`: 配置 DNS 服务器（解决网络问题）
- `-v $(pwd)/Datasets:/data`: 挂载本地目录到容器内的 `/data` 目录
- `download`: 下载命令
- `fka/awesome-chatgpt-prompts`: 要下载的数据集名称（格式：owner/repo）
- `--dataset`: 指定这是数据集（而非模型）
- `-o /data/tutorial_test`: 输出目录（容器内路径，对应挂载的本地目录）
- `--endpoint https://hf-mirror.com`: 使用镜像站点（适合国内网络）
- `--max-active 2`: 最大并发文件数（避免 429 错误）
- `--connections 4`: 每个文件的最大连接数（避免 429 错误）

### 下载模型

```bash
docker run --rm \
  --dns 8.8.8.8 \
  --dns 114.114.114.114 \
  -v $(pwd)/Models:/data \
  huggingface-downloader:latest \
  download TheBloke/Mistral-7B-Instruct-v0.2-GGUF \
  -o /data/mistral \
  --endpoint https://hf-mirror.com \
  --max-active 2 \
  --connections 4
```

### 使用官方 HuggingFace 站点

```bash
docker run --rm \
  -v $(pwd)/Datasets:/data \
  huggingface-downloader:latest \
  download facebook/flores \
  --dataset \
  -o /data/flores \
  --max-active 2 \
  --connections 4
```

## 步骤 4: 验证下载结果

检查下载的文件：

```bash
ls -lh Datasets/tutorial_test/fka/awesome-chatgpt-prompts/
```

应该看到类似输出：
```
total 216
-rw-r--r--  1 user  staff   339B  Nov 24 21:40 README.md
-rw-r--r--  1 user  staff   102K  Nov 24 21:40 prompts.csv
-rw-r--r--  1 user  staff   2.2K  Nov 24 21:40 .gitattributes
```

## 常见使用场景

### 场景 1: 下载大型模型（使用过滤器）

```bash
docker run --rm \
  --dns 8.8.8.8 \
  --dns 114.114.114.114 \
  -v $(pwd)/Models:/data \
  huggingface-downloader:latest \
  download TheBloke/Mistral-7B-Instruct-v0.2-GGUF:q4_0,q5_0 \
  --append-filter-subdir \
  -o /data/mistral \
  --endpoint https://hf-mirror.com \
  --max-active 2 \
  --connections 4
```

### 场景 2: 使用 JSON 输出模式（适合 CI/CD）

```bash
docker run --rm \
  -v $(pwd)/Datasets:/data \
  huggingface-downloader:latest \
  download fka/awesome-chatgpt-prompts \
  --dataset \
  -o /data/test \
  --endpoint https://hf-mirror.com \
  --max-active 2 \
  --connections 4 \
  --json
```

### 场景 3: 仅查看下载计划（不实际下载）

```bash
docker run --rm \
  huggingface-downloader:latest \
  download fka/awesome-chatgpt-prompts \
  --dataset \
  --endpoint https://hf-mirror.com \
  --dry-run
```

## 重要提示

### 避免 429 错误（速率限制）

推荐使用以下参数组合来避免触发服务器的速率限制：

- `--max-active 2`: 限制同时下载的文件数
- `--connections 4`: 限制每个文件的并发连接数

**为什么有效？**
- 降低并发请求数 = 降低请求速率 = 减少触发速率限制的概率
- 默认值（`--max-active 3`, `--connections 8`）可能产生最多 24 个并发连接
- 推荐值（`--max-active 2`, `--connections 4`）最多只有 8 个并发连接，更安全

### 网络问题处理

如果遇到网络连接问题：

1. **使用镜像站点**:
   ```bash
   --endpoint https://hf-mirror.com
   ```

2. **配置 DNS**:
   ```bash
   --dns 8.8.8.8 --dns 114.114.114.114
   ```

3. **使用自动回退**:
   ```bash
   --mirror https://hf-mirror.com --use-mirror-on-failure
   ```

### 查看帮助信息

```bash
docker run --rm huggingface-downloader:latest download --help
```

## 故障排除

### 问题 1: 构建失败 - 无法拉取基础镜像

**解决方案**:
- 检查网络连接
- 配置 Docker 镜像源
- 手动拉取基础镜像：
  ```bash
  docker pull golang:1.23-alpine
  docker pull alpine:latest
  ```

### 问题 2: 下载失败 - 429 Too Many Requests

**解决方案**:
- 降低并发参数（使用 `--max-active 2 --connections 4`）
- 工具会自动检测 429 错误并重试（等待 60 秒或使用 `Retry-After` 头）
- 增加重试次数：`--retries 8 --backoff-initial 2s --backoff-max 30s`

### 问题 3: 权限问题

**解决方案**:
- 确保挂载的目录有写权限
- 容器内使用非 root 用户运行，确保目录权限正确

## 总结

通过本教程，您已经学会了：

1. ✅ 如何构建 HuggingFace Model Downloader Docker 镜像
2. ✅ 如何使用镜像下载数据集和模型
3. ✅ 如何配置参数避免速率限制
4. ✅ 如何处理常见的网络和权限问题

现在您可以开始使用 Docker 镜像来下载 Hugging Face 上的模型和数据集了！

