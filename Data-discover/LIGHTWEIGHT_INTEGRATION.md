# 轻量级持续下载方案

## 核心思想

**用 SQLite 作为任务队列**，不需要 Redis，不需要常驻服务，只需要定时脚本。

```
┌────────────────────┐         ┌──────────────────┐         ┌────────────────────┐
│  Python 定时脚本   │────────▶│  SQLite 任务表   │◀────────│   Go 消费脚本      │
│                    │         │                  │         │                    │
│ - 扫描 HF API      │         │ - 待下载任务     │         │ - 读取待处理任务   │
│ - 插入待下载任务   │         │ - 任务状态       │         │ - 调用 hfdownloader│
│ - 去重检查         │         │ - 优先级         │         │ - 更新任务状态     │
└────────────────────┘         └──────────────────┘         └────────────────────┘
         ↑                               ↑                            ↑
         │                               │                            │
         └───────────────────────────────┴────────────────────────────┘
                            cron 定时调度
                  (producer 每小时运行一次，consumer 持续运行)
```

## 优势

✅ **无需 Redis** - 只依赖 SQLite
✅ **简单部署** - 两个脚本 + cron 定时任务
✅ **资源占用低** - 不需要额外服务
✅ **易于调试** - 直接查询 SQLite 即可看到状态
✅ **利用现有代码** - Python 部分直接用现有的查询脚本
✅ **灵活控制** - 可随时暂停/恢复/修改任务

---

## 数据库设计（简化版）

### 扩展现有的 `datasets.db`

```sql
-- 下载队列表（作为任务队列）
CREATE TABLE IF NOT EXISTS download_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id TEXT UNIQUE NOT NULL,
    priority INTEGER DEFAULT 0,         -- 优先级（越大越优先）
    status TEXT DEFAULT 'pending',      -- pending, downloading, completed, failed, skipped
    retry_count INTEGER DEFAULT 0,
    last_error TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT,
    completed_at TEXT,
    FOREIGN KEY (dataset_id) REFERENCES datasets(dataset_id)
);

CREATE INDEX IF NOT EXISTS idx_queue_status_priority ON download_queue(status, priority DESC);
CREATE INDEX IF NOT EXISTS idx_queue_status ON download_queue(status);
```

就这么简单！只需一张表。

---

## 实现方案

### 方案架构

```bash
Data-discover/
├── datasets.db                      # SQLite 数据库
├── producer_lite.py                 # 生产者脚本（定时运行）
├── consumer_lite.go                 # 消费者脚本（持续运行）
├── config_lite.yaml                 # 配置文件
└── scripts/
    ├── start_consumer.sh            # 启动消费者
    ├── run_producer_once.sh         # 手动运行生产者
    └── monitor.sh                   # 监控脚本
```

---

## 1. Producer（Python 定时脚本）

### `producer_lite.py`

```python
#!/usr/bin/env python3
"""
轻量级生产者：扫描 HF 数据集并添加到下载队列

用法:
    python producer_lite.py                    # 使用默认配置
    python producer_lite.py --days 7           # 扫描最近 7 天
    python producer_lite.py --limit 1000       # 每天最多 1000 个
"""

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

# 导入现有模块
from query_datasets_by_date import HuggingFaceDatasetQuery
from dataset_db import DatasetDB


class LightweightProducer:
    def __init__(self, db_path="datasets.db", endpoint="https://huggingface.co", token=None):
        self.db_path = db_path
        self.db = DatasetDB(db_path)
        self.query = HuggingFaceDatasetQuery(endpoint=endpoint, token=token)
        self._init_queue_table()

    def _init_queue_table(self):
        """初始化下载队列表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS download_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dataset_id TEXT UNIQUE NOT NULL,
                priority INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',
                retry_count INTEGER DEFAULT 0,
                last_error TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                started_at TEXT,
                completed_at TEXT,
                FOREIGN KEY (dataset_id) REFERENCES datasets(dataset_id)
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_queue_status_priority
            ON download_queue(status, priority DESC)
        """)

        conn.commit()
        conn.close()

    def scan_and_queue(self, days=7, limit_per_day=1000, min_downloads=0, min_likes=0):
        """扫描最近 N 天的数据集并加入队列"""
        print(f"开始扫描最近 {days} 天的数据集...")

        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        total_scanned = 0
        total_queued = 0
        total_skipped = 0

        # 逐天扫描
        current = start_date
        while current <= end_date:
            date_str = current.strftime("%Y-%m-%d")
            print(f"\n扫描日期: {date_str}")

            try:
                datasets = self.query.get_datasets_by_date(
                    target_date=date_str,
                    limit=limit_per_day,
                    use_created_at=True,
                    auto_limit=False
                )

                print(f"  找到 {len(datasets)} 个数据集")

                for ds in datasets:
                    total_scanned += 1

                    # 过滤条件
                    if ds.get('downloads', 0) < min_downloads:
                        continue
                    if ds.get('likes', 0) < min_likes:
                        continue

                    # 添加到队列
                    if self._add_to_queue(ds):
                        total_queued += 1
                    else:
                        total_skipped += 1

                print(f"  本日新增: {total_queued - (total_scanned - len(datasets))}")

            except Exception as e:
                print(f"  错误: {e}")

            current += timedelta(days=1)

        print(f"\n" + "="*60)
        print(f"扫描完成！")
        print(f"总扫描: {total_scanned}")
        print(f"新增队列: {total_queued}")
        print(f"已存在/跳过: {total_skipped}")
        print("="*60)

    def _add_to_queue(self, dataset):
        """添加数据集到下载队列"""
        dataset_id = dataset.get('id')
        if not dataset_id:
            return False

        # 计算优先级
        priority = self._calculate_priority(dataset)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # 检查是否已存在
            cursor.execute(
                "SELECT status FROM download_queue WHERE dataset_id = ?",
                (dataset_id,)
            )
            existing = cursor.fetchone()

            if existing:
                status = existing[0]
                # 如果已完成或正在下载，跳过
                if status in ('completed', 'downloading'):
                    return False
                # 如果是 pending 或 failed，更新优先级
                cursor.execute(
                    "UPDATE download_queue SET priority = ? WHERE dataset_id = ?",
                    (priority, dataset_id)
                )
            else:
                # 插入新任务
                cursor.execute(
                    """
                    INSERT INTO download_queue (dataset_id, priority, status)
                    VALUES (?, ?, 'pending')
                    """,
                    (dataset_id, priority)
                )

            conn.commit()
            return True

        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()

    def _calculate_priority(self, dataset):
        """计算优先级（简单算法）"""
        downloads = dataset.get('downloads', 0)
        likes = dataset.get('likes', 0)

        # 优先级 = 下载数/1000 + 点赞数
        score = int(downloads / 1000) + likes
        return min(score, 9999)  # 限制最大值


def main():
    parser = argparse.ArgumentParser(description="轻量级数据集队列生产者")
    parser.add_argument("--db", default="datasets.db", help="数据库路径")
    parser.add_argument("--days", type=int, default=7, help="扫描最近 N 天")
    parser.add_argument("--limit", type=int, default=1000, help="每天最多查询 N 个")
    parser.add_argument("--min-downloads", type=int, default=0, help="最小下载量过滤")
    parser.add_argument("--min-likes", type=int, default=0, help="最小点赞数过滤")
    parser.add_argument("--endpoint", default="https://huggingface.co", help="HF API 端点")
    parser.add_argument("--token", help="HF Token（或使用 HF_TOKEN 环境变量）")

    args = parser.parse_args()

    token = args.token or os.getenv("HF_TOKEN")

    producer = LightweightProducer(
        db_path=args.db,
        endpoint=args.endpoint,
        token=token
    )

    producer.scan_and_queue(
        days=args.days,
        limit_per_day=args.limit,
        min_downloads=args.min_downloads,
        min_likes=args.min_likes
    )


if __name__ == "__main__":
    main()
```

### 定时运行（Cron）

```bash
# 每小时运行一次，扫描最近 1 天的数据集
0 * * * * cd /path/to/Data-discover && source download/bin/activate && python producer_lite.py --days 1 >> logs/producer.log 2>&1

# 或者每天凌晨运行一次，扫描最近 7 天
0 2 * * * cd /path/to/Data-discover && source download/bin/activate && python producer_lite.py --days 7 >> logs/producer.log 2>&1
```

---

## 2. Consumer（Go 持续运行脚本）

### `consumer_lite.go`

```go
package main

import (
	"context"
	"database/sql"
	"flag"
	"fmt"
	"log"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"github.com/bodaay/HuggingFaceModelDownloader/hfdownloader"
	_ "github.com/mattn/go-sqlite3"
)

type Config struct {
	DBPath          string
	OutputDir       string
	Endpoint        string
	Mirror          string
	Token           string
	Workers         int
	PollInterval    time.Duration
	MaxRetries      int
	Concurrency     int
	MaxActive       int
}

type Consumer struct {
	db     *sql.DB
	config Config
	ctx    context.Context
	cancel context.CancelFunc
}

func NewConsumer(config Config) (*Consumer, error) {
	db, err := sql.Open("sqlite3", config.DBPath)
	if err != nil {
		return nil, err
	}

	// 启用 WAL 模式（提高并发性能）
	db.Exec("PRAGMA journal_mode=WAL")

	ctx, cancel := context.WithCancel(context.Background())

	return &Consumer{
		db:     db,
		config: config,
		ctx:    ctx,
		cancel: cancel,
	}, nil
}

func (c *Consumer) Run() {
	log.Printf("Consumer started with %d workers", c.config.Workers)

	// 启动多个 worker
	for i := 0; i < c.config.Workers; i++ {
		go c.worker(i)
	}

	// 等待信号
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, os.Interrupt, syscall.SIGTERM)
	<-sigCh

	log.Println("Shutting down...")
	c.cancel()
	time.Sleep(2 * time.Second)
	c.db.Close()
}

func (c *Consumer) worker(id int) {
	log.Printf("Worker %d started", id)

	for {
		select {
		case <-c.ctx.Done():
			log.Printf("Worker %d stopped", id)
			return
		default:
			// 获取任务
			task, err := c.fetchTask()
			if err != nil {
				log.Printf("Worker %d: fetch task error: %v", id, err)
				time.Sleep(5 * time.Second)
				continue
			}

			if task == nil {
				// 没有任务，休眠
				time.Sleep(c.config.PollInterval)
				continue
			}

			// 处理任务
			log.Printf("Worker %d: processing %s (priority=%d, retry=%d)",
				id, task.DatasetID, task.Priority, task.RetryCount)

			if err := c.processTask(task); err != nil {
				log.Printf("Worker %d: failed to download %s: %v", id, task.DatasetID, err)
				c.handleFailure(task, err)
			} else {
				log.Printf("Worker %d: successfully downloaded %s", id, task.DatasetID)
				c.handleSuccess(task)
			}
		}
	}
}

type Task struct {
	ID         int64
	DatasetID  string
	Priority   int
	RetryCount int
}

func (c *Consumer) fetchTask() (*Task, error) {
	tx, err := c.db.BeginTx(c.ctx, nil)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()

	// 查询优先级最高的待处理任务
	var task Task
	err = tx.QueryRow(`
		SELECT id, dataset_id, priority, retry_count
		FROM download_queue
		WHERE status = 'pending'
		ORDER BY priority DESC, id ASC
		LIMIT 1
	`).Scan(&task.ID, &task.DatasetID, &task.Priority, &task.RetryCount)

	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}

	// 标记为正在处理
	_, err = tx.Exec(`
		UPDATE download_queue
		SET status = 'downloading', started_at = ?
		WHERE id = ?
	`, time.Now().Format(time.RFC3339), task.ID)

	if err != nil {
		return nil, err
	}

	if err := tx.Commit(); err != nil {
		return nil, err
	}

	return &task, nil
}

func (c *Consumer) processTask(task *Task) error {
	// 准备下载任务
	job := hfdownloader.Job{
		Repo:      task.DatasetID,
		IsDataset: true,
		Revision:  "main",
	}

	// 准备配置
	cfg := hfdownloader.Settings{
		OutputDir:          filepath.Join(c.config.OutputDir, task.DatasetID),
		Concurrency:        c.config.Concurrency,
		MaxActiveDownloads: c.config.MaxActive,
		MultipartThreshold: "256MiB",
		Verify:             "size",
		Retries:            4,
		BackoffInitial:     "400ms",
		BackoffMax:         "10s",
		Token:              c.config.Token,
		Endpoint:           c.config.Endpoint,
		MirrorEndpoint:     c.config.Mirror,
		UseMirrorOnFailure: true,
	}

	// 进度回调（可选）
	progress := func(ev hfdownloader.ProgressEvent) {
		// 可以选择记录关键事件
		if ev.Event == "done" {
			log.Printf("Download completed: %s - %s", task.DatasetID, ev.Message)
		}
	}

	// 执行下载
	return hfdownloader.Download(c.ctx, job, cfg, progress)
}

func (c *Consumer) handleSuccess(task *Task) {
	_, err := c.db.Exec(`
		UPDATE download_queue
		SET status = 'completed', completed_at = ?
		WHERE id = ?
	`, time.Now().Format(time.RFC3339), task.ID)

	if err != nil {
		log.Printf("Failed to update task status: %v", err)
	}
}

func (c *Consumer) handleFailure(task *Task, downloadErr error) {
	if task.RetryCount >= c.config.MaxRetries {
		// 超过最大重试次数，标记为失败
		_, err := c.db.Exec(`
			UPDATE download_queue
			SET status = 'failed', last_error = ?
			WHERE id = ?
		`, downloadErr.Error(), task.ID)

		if err != nil {
			log.Printf("Failed to update task status: %v", err)
		}
		return
	}

	// 重试：重置为 pending，增加重试计数
	_, err := c.db.Exec(`
		UPDATE download_queue
		SET status = 'pending', retry_count = retry_count + 1, last_error = ?
		WHERE id = ?
	`, downloadErr.Error(), task.ID)

	if err != nil {
		log.Printf("Failed to update task for retry: %v", err)
	}
}

func main() {
	var config Config

	flag.StringVar(&config.DBPath, "db", "datasets.db", "SQLite database path")
	flag.StringVar(&config.OutputDir, "output", "./Datasets", "Output directory")
	flag.StringVar(&config.Endpoint, "endpoint", "https://huggingface.co", "HF endpoint")
	flag.StringVar(&config.Mirror, "mirror", "https://hf-mirror.com", "HF mirror")
	flag.IntVar(&config.Workers, "workers", 3, "Number of workers")
	flag.DurationVar(&config.PollInterval, "poll", 10*time.Second, "Poll interval")
	flag.IntVar(&config.MaxRetries, "max-retries", 3, "Max retry count")
	flag.IntVar(&config.Concurrency, "concurrency", 8, "Download concurrency")
	flag.IntVar(&config.MaxActive, "max-active", 3, "Max active downloads")
	flag.Parse()

	// 从环境变量读取 token
	config.Token = os.Getenv("HF_TOKEN")

	consumer, err := NewConsumer(config)
	if err != nil {
		log.Fatalf("Failed to create consumer: %v", err)
	}

	consumer.Run()
}
```

### 依赖

```bash
# 在 Data-discover 目录下
go mod init github.com/bodaay/HuggingFaceModelDownloader/data-discover
go get github.com/mattn/go-sqlite3
```

### 编译和运行

```bash
# 编译
cd Data-discover
go build -o consumer_lite consumer_lite.go

# 运行
HF_TOKEN=your_token ./consumer_lite --workers 3 --db datasets.db --output ./Datasets
```

---

## 3. 辅助脚本

### `scripts/monitor.sh` - 监控脚本

```bash
#!/bin/bash
# 监控队列状态

DB_PATH="${1:-datasets.db}"

echo "=== Download Queue Status ==="
echo "Time: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

sqlite3 "$DB_PATH" <<EOF
.mode column
.headers on

SELECT
    status,
    COUNT(*) as count,
    SUM(CASE WHEN status = 'pending' THEN priority ELSE 0 END) as total_priority
FROM download_queue
GROUP BY status;

EOF

echo ""
echo "=== Top 10 Pending Tasks ==="
sqlite3 "$DB_PATH" <<EOF
.mode column
.headers on

SELECT
    dataset_id,
    priority,
    retry_count,
    created_at
FROM download_queue
WHERE status = 'pending'
ORDER BY priority DESC
LIMIT 10;

EOF

echo ""
echo "=== Recent Failures ==="
sqlite3 "$DB_PATH" <<EOF
.mode column
.headers on

SELECT
    dataset_id,
    retry_count,
    SUBSTR(last_error, 1, 50) as error
FROM download_queue
WHERE status = 'failed'
ORDER BY id DESC
LIMIT 5;

EOF
```

### `scripts/reset_failed.sh` - 重置失败任务

```bash
#!/bin/bash
# 重置失败的任务，允许重试

DB_PATH="${1:-datasets.db}"

echo "Resetting failed tasks..."

COUNT=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM download_queue WHERE status = 'failed';")
echo "Found $COUNT failed tasks"

sqlite3 "$DB_PATH" <<EOF
UPDATE download_queue
SET status = 'pending', retry_count = 0, last_error = NULL
WHERE status = 'failed';
EOF

echo "Done! All failed tasks have been reset to pending."
```

### `scripts/stats.sh` - 统计信息

```bash
#!/bin/bash
# 显示详细统计

DB_PATH="${1:-datasets.db}"

sqlite3 "$DB_PATH" <<EOF
.mode column
.headers on

-- 总体统计
SELECT
    COUNT(*) as total,
    SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
    SUM(CASE WHEN status = 'downloading' THEN 1 ELSE 0 END) as downloading,
    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed
FROM download_queue;

EOF
```

---

## 4. 快速开始

### Step 1: 数据库初始化

```bash
cd /Users/jjl/llm-infra/HuggingFaceModelDownloader/Data-discover

# 激活 uv 环境
source download/bin/activate

# 运行一次 producer 来初始化表结构
python producer_lite.py --days 0
```

### Step 2: 手动添加一些任务（测试）

```bash
# 扫描最近 3 天，每天最多 100 个
python producer_lite.py --days 3 --limit 100

# 查看队列状态
./scripts/monitor.sh
```

### Step 3: 启动 Consumer

```bash
# 编译 consumer
cd /Users/jjl/llm-infra/HuggingFaceModelDownloader/Data-discover
go build -o consumer_lite consumer_lite.go

# 启动（使用 nohup 后台运行）
export HF_TOKEN=your_token_here
nohup ./consumer_lite --workers 2 --db datasets.db --output ./Datasets > logs/consumer.log 2>&1 &

# 查看日志
tail -f logs/consumer.log
```

### Step 4: 设置定时任务

```bash
# 编辑 crontab
crontab -e

# 添加以下行（每小时扫描一次）
0 * * * * cd /Users/jjl/llm-infra/HuggingFaceModelDownloader/Data-discover && source download/bin/activate && python producer_lite.py --days 1 >> logs/producer.log 2>&1
```

---

## 5. 日常运维

### 查看状态

```bash
./scripts/monitor.sh
./scripts/stats.sh
```

### 重置失败任务

```bash
./scripts/reset_failed.sh
```

### 手动添加特定数据集

```bash
sqlite3 datasets.db <<EOF
INSERT OR IGNORE INTO download_queue (dataset_id, priority, status)
VALUES ('your/dataset-name', 100, 'pending');
EOF
```

### 暂停/恢复下载

```bash
# 暂停（杀死 consumer 进程）
pkill -f consumer_lite

# 恢复（重新启动）
nohup ./consumer_lite --workers 2 > logs/consumer.log 2>&1 &
```

---

## 对比原方案

| 特性 | 原方案（Redis） | 轻量方案（SQLite） |
|------|----------------|-------------------|
| **依赖** | Redis + Python + Go | Python + Go + SQLite |
| **部署复杂度** | 需要 Redis 服务 | 无额外服务 |
| **资源占用** | Redis ~1-2GB | 几乎为 0 |
| **并发性能** | 高（Redis 专业） | 中（SQLite WAL 模式） |
| **任务持久化** | 需要 AOF 配置 | 原生持久化 |
| **监控** | 需要 Redis 命令 | 直接 SQL 查询 |
| **适用场景** | 高并发（>10 workers） | 中低并发（<10 workers） |

---

## 性能预估

- **Producer**: 每小时扫描 ~1000-5000 个数据集，写入 SQLite
- **Consumer** (2-3 workers):
  - 小数据集: ~50-100/day
  - 中数据集: ~20-30/day
  - 大数据集: ~5-10/day

**SQLite 性能瓶颈**：
- WAL 模式下，支持多读单写
- 3-5 个 workers 是合理范围
- 超过 10 个 workers 建议升级到 Redis 方案

---

## 总结

这个轻量方案：
- ✅ **5 个文件**：`producer_lite.py` + `consumer_lite.go` + 3 个 shell 脚本
- ✅ **零额外服务**：只需 SQLite
- ✅ **简单部署**：编译 + cron 即可
- ✅ **易于维护**：直接 SQL 查询状态
- ✅ **资源占用极低**：适合个人/小团队使用

需要我帮你生成完整的代码文件吗？
