#!/bin/bash
# 监控队列状态

DB_PATH="${1:-datasets.db}"

if [ ! -f "$DB_PATH" ]; then
    echo "错误: 数据库文件不存在: $DB_PATH"
    exit 1
fi

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

echo ""
echo "=== Downloading Tasks ==="
sqlite3 "$DB_PATH" <<EOF
.mode column
.headers on

SELECT
    dataset_id,
    started_at
FROM download_queue
WHERE status = 'downloading'
ORDER BY started_at DESC;

EOF

