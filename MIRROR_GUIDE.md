# HF-Mirror 镜像集成指南

## 概述

HuggingFaceModelDownloader 现已支持镜像源功能，可以在主源连接失败时自动切换到镜像源（如 HF-Mirror），提高下载成功率和稳定性，特别适用于网络受限的环境。

## 功能特性

✅ **灵活的 Endpoint 配置** - 支持自定义 Hugging Face API 端点  
✅ **自动故障切换** - 主源失败时自动尝试镜像源  
✅ **完整的 URL 重写** - 所有 API 和下载 URL 都支持镜像  
✅ **无缝集成** - 与现有功能完全兼容  
✅ **状态透明** - 清晰的日志提示使用的源

## CLI 参数

### 新增参数

```bash
--endpoint string
    Base URL for HuggingFace API
    默认值: https://huggingface.co
    示例: --endpoint https://hf-mirror.com

--mirror string
    Mirror URL for fallback
    示例: --mirror https://hf-mirror.com

--use-mirror-on-failure
    Automatically fallback to mirror if primary endpoint fails
    需要同时设置 --mirror 参数
```

## 使用示例

### 1. 仅使用镜像源

直接指定镜像作为主要端点：

```bash
./hfd download fka/awesome-chatgpt-prompts \
  --dataset \
  -o ./Datasets \
  --endpoint https://hf-mirror.com
```

### 2. 自动故障切换（推荐）

主源失败时自动切换到镜像源：

```bash
./hfd download fka/awesome-chatgpt-prompts \
  --dataset \
  -o ./Datasets \
  --mirror https://hf-mirror.com \
  --use-mirror-on-failure
```

这种方式的优势：
- 优先尝试官方源（可能速度更快）
- 失败时自动降级到镜像
- 获得最佳的可用性和性能平衡

### 3. 下载模型

```bash
# 使用镜像下载模型
./hfd download TheBloke/Mistral-7B-Instruct-v0.2-GGUF:q4_0 \
  -o ./Models \
  --endpoint https://hf-mirror.com

# 或使用故障切换
./hfd download TheBloke/Mistral-7B-Instruct-v0.2-GGUF:q4_0 \
  -o ./Models \
  --mirror https://hf-mirror.com \
  --use-mirror-on-failure
```

### 4. 配合其他参数使用

```bash
./hfd download TheBloke/vicuna-13b-v1.3.0-GGML:q4_0,q5_0 \
  --append-filter-subdir \
  -o ./Models \
  -c 8 \
  --max-active 3 \
  --mirror https://hf-mirror.com \
  --use-mirror-on-failure \
  --json
```

## 配置文件支持

可以在 `~/.config/hfdownloader.json` 中设置默认值：

```json
{
  "output": "Storage",
  "connections": 8,
  "max-active": 3,
  "endpoint": "https://huggingface.co",
  "mirror-endpoint": "https://hf-mirror.com",
  "use-mirror-on-failure": true,
  "verify": "size",
  "retries": 4,
  "backoff-initial": "400ms",
  "backoff-max": "10s"
}
```

注：CLI 参数优先级高于配置文件。

## Go 库使用

```go
package main

import (
    "context"
    "log"
    "github.com/bodaay/HuggingFaceModelDownloader/hfdownloader"
)

func main() {
    job := hfdownloader.Job{
        Repo:      "fka/awesome-chatgpt-prompts",
        Revision:  "main",
        IsDataset: true,
    }

    cfg := hfdownloader.Settings{
        OutputDir:          "Storage",
        Concurrency:        8,
        MaxActiveDownloads: 3,
        Endpoint:           "https://huggingface.co",         // 主源
        MirrorEndpoint:     "https://hf-mirror.com",           // 镜像源
        UseMirrorOnFailure: true,                              // 启用自动切换
        Verify:             "size",
        Retries:            4,
        BackoffInitial:     "400ms",
        BackoffMax:         "10s",
    }

    progress := func(ev hfdownloader.ProgressEvent) {
        switch ev.Event {
        case "info":
            log.Printf("[INFO] %s", ev.Message)
        case "file_done":
            log.Printf("✓ %s", ev.Path)
        case "error":
            log.Printf("✗ %s: %s", ev.Path, ev.Message)
        }
    }

    if err := hfdownloader.Download(context.Background(), job, cfg, progress); err != nil {
        log.Fatal(err)
    }
}
```

## 工作原理

### URL 重写机制

所有 Hugging Face URL 现在都通过动态构建：

```
原来: https://huggingface.co/datasets/{repo}/tree/{revision}
现在: {endpoint}/datasets/{repo}/tree/{revision}
```

支持的 URL 类型：
- ✅ API 树结构查询 (`/api/models/...`, `/api/datasets/...`)
- ✅ LFS 文件解析 (`/resolve/...`)
- ✅ 原始文件下载 (`/raw/...`)
- ✅ 协议页面 (`/datasets/...`, `/...`)

### 故障切换流程

1. 使用 `Endpoint`（或默认值）扫描仓库结构
2. 如果扫描失败且满足以下条件：
   - `UseMirrorOnFailure = true`
   - `MirrorEndpoint` 已设置
   - 镜像地址与主源不同
3. 自动切换到 `MirrorEndpoint` 并重试
4. 如果两者都失败，返回详细错误信息
5. 成功后的下载操作使用最后成功的 endpoint

### 日志示例

启用故障切换时，你会看到类似的日志：

```
[INFO] scanning repo
[INFO] primary endpoint failed (dial tcp ...: connect: no route to host), trying mirror: https://hf-mirror.com
[INFO] using mirror endpoint for download
✓ README.md
✓ .gitattributes
✓ prompts.csv
```

## HF-Mirror 镜像说明

### 优点

- ✅ 国内访问友好，速度快
- ✅ 完整的 Hugging Face 镜像
- ✅ 支持模型和数据集
- ✅ 公益项目，免费使用

### 限制

- ⚠️ **同步延迟**：可能不包含最新更新的模型/数据集
- ⚠️ **Gated Repo**：受限访问的仓库可能不可用
- ⚠️ **无 SLA**：作为公益项目，不保证服务可用性
- ⚠️ **版本一致性**：建议记录使用的源以便追踪

### 最佳实践

1. **优先使用故障切换模式**
   ```bash
   --mirror https://hf-mirror.com --use-mirror-on-failure
   ```
   
2. **记录下载源**
   使用 `--json` 模式记录日志，便于追踪使用了哪个源：
   ```bash
   ./hfd download ... --json > download.log
   ```

3. **版本校验**
   下载完成后，如果可能的话，对比主源和镜像的文件哈希值

4. **敏感项目**
   对于生产环境或敏感项目，建议：
   - 首次从官方源下载
   - 验证完整性后缓存到内部存储
   - 后续使用内部缓存

## 环境变量

虽然不直接支持环境变量配置 endpoint，但可以通过配置文件实现：

```bash
# 创建配置文件
cat > ~/.config/hfdownloader.json << EOF
{
  "endpoint": "${HF_ENDPOINT:-https://huggingface.co}",
  "mirror-endpoint": "https://hf-mirror.com",
  "use-mirror-on-failure": true
}
EOF

# 使用配置文件
./hfd download fka/awesome-chatgpt-prompts --dataset
```

## 故障排除

### 问题：镜像也无法连接

```bash
error: both primary (https://huggingface.co) and mirror (https://hf-mirror.com) failed: ...
```

**解决方案：**
1. 检查网络连接
2. 尝试其他镜像站点
3. 配置 HTTP 代理：
   ```bash
   export HTTP_PROXY=http://your-proxy:port
   export HTTPS_PROXY=http://your-proxy:port
   ./hfd download ...
   ```

### 问题：下载的文件版本不对

**原因：** 镜像同步延迟

**解决方案：**
1. 使用 `--revision` 指定具体版本/分支：
   ```bash
   ./hfd download repo/name --revision v1.0.0
   ```
2. 或直接使用主源：
   ```bash
   ./hfd download repo/name --endpoint https://huggingface.co
   ```

### 问题：私有/Gated 仓库无法访问

**原因：** 镜像可能不支持需要认证的仓库

**解决方案：**
必须使用官方源并提供 token：
```bash
HF_TOKEN=your_token ./hfd download owner/private-repo \
  --endpoint https://huggingface.co
```

## 性能建议

1. **网络良好时**：使用官方源
   ```bash
   ./hfd download ... --endpoint https://huggingface.co
   ```

2. **网络受限时**：直接使用镜像
   ```bash
   ./hfd download ... --endpoint https://hf-mirror.com
   ```

3. **不确定时**：启用故障切换
   ```bash
   ./hfd download ... --mirror https://hf-mirror.com --use-mirror-on-failure
   ```

4. **批量下载**：配置文件 + 脚本
   ```bash
   # 设置配置文件
   echo '{"mirror-endpoint":"https://hf-mirror.com","use-mirror-on-failure":true}' \
     > ~/.config/hfdownloader.json
   
   # 批量下载脚本
   for repo in repo1 repo2 repo3; do
     ./hfd download $repo -o ./Models
   done
   ```

## 更新日志

### v2.1.0 (2025-11-19)

- ✅ 添加 `--endpoint` 参数支持自定义 API 端点
- ✅ 添加 `--mirror` 和 `--use-mirror-on-failure` 支持镜像故障切换
- ✅ 重构 URL 构建逻辑，支持动态 endpoint
- ✅ 添加镜像切换日志和错误提示
- ✅ 配置文件支持新参数
- ✅ Go 库 API 扩展

## 参考链接

- **HF-Mirror 官网**: https://hf-mirror.com/
- **项目仓库**: https://github.com/bodaay/HuggingFaceModelDownloader
- **Hugging Face Hub**: https://huggingface.co/

---

## 贡献

欢迎提交问题和改进建议！如果你发现其他可用的镜像站点，也欢迎分享。

