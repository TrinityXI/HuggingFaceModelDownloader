# DNS 超时快速修复

## 🚨 遇到 DNS 超时错误？

```
error: dial tcp: lookup hf-mirror.com on ...:53: i/o timeout
```

## ✅ 快速解决方案

### 方法 1: 添加 DNS 参数（最简单）

在 Docker 命令中添加 `--dns` 参数：

```bash
docker run --rm \
  --dns 8.8.8.8 \
  --dns 114.114.114.114 \
  -v $(pwd)/Datasets:/data \
  huggingface-downloader:latest \
  download fka/awesome-chatgpt-prompts \
  --dataset -o /data/test2 \
  --endpoint https://hf-mirror.com
```

### 方法 2: 使用更新后的脚本（已自动包含 DNS）

```bash
./scripts/download.sh fka/awesome-chatgpt-prompts ./Datasets/test2 --dataset
```

脚本已自动包含 DNS 配置，无需手动添加。

---

## 📋 推荐 DNS 服务器

| DNS | 地址 | 说明 |
|-----|------|------|
| Google DNS | `8.8.8.8` | 全球稳定 |
| 114 DNS | `114.114.114.114` | 国内快速 |
| 阿里 DNS | `223.5.5.5` | 国内备用 |
| Cloudflare | `1.1.1.1` | 全球快速 |

---

## 🔧 永久解决方案

### 创建别名（推荐）

在 `~/.zshrc` 或 `~/.bashrc` 中添加：

```bash
alias hfd='docker run --rm --dns 8.8.8.8 --dns 114.114.114.114 -v $(pwd)/Datasets:/data huggingface-downloader:latest'
```

然后直接使用：

```bash
hfd download fka/awesome-chatgpt-prompts --dataset -o /data/test2 --endpoint https://hf-mirror.com
```

---

## 📚 详细文档

- [完整故障排除指南](./DOCKER_TROUBLESHOOTING.md)
- [Docker 使用指南](./DOCKER_GUIDE.md)

