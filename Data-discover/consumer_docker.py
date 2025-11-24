#!/usr/bin/env python3
"""
Docker 消费者：从 SQLite 队列读取任务并调用 Docker 下载器

用法:
    python consumer_docker.py                    # 使用默认配置
    python consumer_docker.py --workers 3        # 使用 3 个并发 worker
    python consumer_docker.py --db datasets.db   # 指定数据库路径
"""

import argparse
import os
import sqlite3
import subprocess
import sys
import time
import signal
from pathlib import Path
from datetime import datetime


class DockerConsumer:
    def __init__(self, config):
        self.config = config
        self.db_path = config['db_path']
        self.running = True
        self._init_db()

    def _init_db(self):
        """确保数据库和表存在"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 确保表存在（如果 producer 还没运行过）
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
                completed_at TEXT
            )
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_queue_status_priority
            ON download_queue(status, priority DESC)
        """)
        
        conn.commit()
        conn.close()

    def fetch_task(self):
        """从队列获取一个待处理任务"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # 启用 WAL 模式（提高并发性能）
            cursor.execute("PRAGMA journal_mode=WAL")
            
            # 开始事务
            cursor.execute("BEGIN IMMEDIATE")
            
            # 查询优先级最高的待处理任务
            cursor.execute("""
                SELECT id, dataset_id, priority, retry_count
                FROM download_queue
                WHERE status = 'pending'
                ORDER BY priority DESC, id ASC
                LIMIT 1
            """)
            
            row = cursor.fetchone()
            if not row:
                conn.rollback()
                return None
            
            task_id, dataset_id, priority, retry_count = row
            
            # 标记为正在处理
            cursor.execute("""
                UPDATE download_queue
                SET status = 'downloading', started_at = ?
                WHERE id = ?
            """, (datetime.now().isoformat(), task_id))
            
            conn.commit()
            return {
                'id': task_id,
                'dataset_id': dataset_id,
                'priority': priority,
                'retry_count': retry_count
            }
            
        except sqlite3.Error as e:
            conn.rollback()
            print(f"数据库错误: {e}", file=sys.stderr)
            return None
        finally:
            conn.close()

    def process_task(self, task):
        """处理下载任务"""
        dataset_id = task['dataset_id']
        
        # 检查输出目录是否已存在（避免重复下载）
        output_path = Path(self.config['output_dir']) / dataset_id.replace('/', '_')
        if output_path.exists() and output_path.is_dir():
            # 检查目录是否非空（简单检查，Docker 下载器会做更详细的验证）
            try:
                if any(output_path.iterdir()):
                    print(f"[{task['id']}] ⚠️  输出目录已存在: {output_path}")
                    print(f"[{task['id']}]   将调用 Docker 下载器进行验证（如果文件完整会跳过）")
            except Exception:
                pass  # 忽略检查错误，继续下载流程
        
        # 构建 Docker 命令
        docker_cmd = [
            'docker', 'run', '--rm',
            '--dns', '8.8.8.8',
            '--dns', '114.114.114.114',
            '-v', f"{self.config['output_dir']}:/data",
            self.config['docker_image'],
            'download', dataset_id,
            '--dataset',
            '-o', f"/data/{dataset_id.replace('/', '_')}",
            '--endpoint', self.config['endpoint'],
            '--max-active', str(self.config['max_active']),
            '--connections', str(self.config['connections'])
        ]
        
        # 添加 dry-run 模式（如果启用）
        if self.config.get('dry_run'):
            docker_cmd.append('--dry-run')
        
        # 添加 token（如果提供）
        if self.config.get('token'):
            docker_cmd.extend(['-t', self.config['token']])
        
        # 添加镜像站点（如果提供）
        if self.config.get('mirror'):
            docker_cmd.extend(['--mirror', self.config['mirror']])
            if self.config.get('use_mirror_on_failure'):
                docker_cmd.append('--use-mirror-on-failure')
        
        print(f"[{task['id']}] 开始下载: {dataset_id}")
        print(f"  命令: {' '.join(docker_cmd[:10])}...")
        
        try:
            # 执行 Docker 命令
            result = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=self.config.get('timeout', 3600)  # 默认 1 小时超时
            )
            
            if result.returncode == 0:
                print(f"[{task['id']}] ✅ 下载成功: {dataset_id}")
                self.mark_success(task)
                return True
            else:
                error_msg = result.stderr[:500] if result.stderr else "未知错误"
                print(f"[{task['id']}] ❌ 下载失败: {dataset_id}")
                print(f"  错误: {error_msg}")
                self.mark_failure(task, error_msg)
                return False
                
        except subprocess.TimeoutExpired:
            error_msg = "下载超时"
            print(f"[{task['id']}] ⏱️  下载超时: {dataset_id}")
            self.mark_failure(task, error_msg)
            return False
        except Exception as e:
            error_msg = str(e)[:500]
            print(f"[{task['id']}] ❌ 执行错误: {dataset_id}")
            print(f"  错误: {error_msg}")
            self.mark_failure(task, error_msg)
            return False

    def mark_success(self, task):
        """标记任务为成功"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                UPDATE download_queue
                SET status = 'completed', completed_at = ?
                WHERE id = ?
            """, (datetime.now().isoformat(), task['id']))
            conn.commit()
        except sqlite3.Error as e:
            print(f"更新状态失败: {e}", file=sys.stderr)
        finally:
            conn.close()

    def mark_failure(self, task, error_msg):
        """标记任务为失败或重试"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            retry_count = task['retry_count'] + 1
            max_retries = self.config.get('max_retries', 3)
            
            if retry_count >= max_retries:
                # 超过最大重试次数，标记为失败
                cursor.execute("""
                    UPDATE download_queue
                    SET status = 'failed', last_error = ?
                    WHERE id = ?
                """, (error_msg[:1000], task['id']))
                print(f"[{task['id']}] 已达到最大重试次数，标记为失败")
            else:
                # 重置为 pending，允许重试
                cursor.execute("""
                    UPDATE download_queue
                    SET status = 'pending', retry_count = ?, last_error = ?
                    WHERE id = ?
                """, (retry_count, error_msg[:1000], task['id']))
                print(f"[{task['id']}] 将重试 (第 {retry_count}/{max_retries} 次)")
            
            conn.commit()
        except sqlite3.Error as e:
            print(f"更新状态失败: {e}", file=sys.stderr)
        finally:
            conn.close()

    def worker(self, worker_id):
        """工作线程"""
        print(f"Worker {worker_id} 启动")
        
        while self.running:
            task = self.fetch_task()
            
            if task:
                self.process_task(task)
            else:
                # 没有任务，休眠
                time.sleep(self.config['poll_interval'])
        
        print(f"Worker {worker_id} 停止")

    def run(self):
        """运行消费者"""
        print("="*60)
        print("Docker 消费者启动")
        print(f"数据库: {self.config['db_path']}")
        print(f"输出目录: {self.config['output_dir']}")
        print(f"Docker 镜像: {self.config['docker_image']}")
        print(f"Worker 数量: {self.config['workers']}")
        print(f"轮询间隔: {self.config['poll_interval']} 秒")
        if self.config.get('dry_run'):
            print("⚠️  DRY-RUN 模式：仅测试，不实际下载")
        print("="*60)
        
        # 注册信号处理
        def signal_handler(sig, frame):
            print("\n收到停止信号，正在安全退出...")
            self.running = False
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # 启动多个 worker（简单实现：顺序处理）
        # 注意：SQLite 的并发限制，多个 worker 可能不是最佳选择
        # 但可以通过 WAL 模式支持多读单写
        try:
            if self.config['workers'] > 1:
                import threading
                threads = []
                for i in range(self.config['workers']):
                    t = threading.Thread(target=self.worker, args=(i+1,), daemon=True)
                    t.start()
                    threads.append(t)
                
                # 等待所有线程
                for t in threads:
                    t.join()
            else:
                self.worker(1)
        except KeyboardInterrupt:
            self.running = False
        
        print("消费者已停止")


def main():
    parser = argparse.ArgumentParser(description="Docker 消费者：从队列读取任务并下载")
    parser.add_argument("--db", default="datasets.db", help="SQLite 数据库路径")
    parser.add_argument("--output", default="./Datasets", help="输出目录")
    parser.add_argument("--docker-image", default="huggingface-downloader:latest", help="Docker 镜像名称")
    parser.add_argument("--endpoint", default="https://hf-mirror.com", help="HF API 端点")
    parser.add_argument("--mirror", help="HF 镜像站点")
    parser.add_argument("--use-mirror-on-failure", action="store_true", help="失败时使用镜像")
    parser.add_argument("--workers", type=int, default=1, help="Worker 数量（建议 1-3）")
    parser.add_argument("--poll-interval", type=int, default=10, help="轮询间隔（秒）")
    parser.add_argument("--max-retries", type=int, default=3, help="最大重试次数")
    parser.add_argument("--max-active", type=int, default=2, help="最大并发下载数")
    parser.add_argument("--connections", type=int, default=4, help="每个文件的连接数")
    parser.add_argument("--timeout", type=int, default=3600, help="下载超时（秒）")
    parser.add_argument("--token", help="HF Token（或使用 HF_TOKEN 环境变量）")
    parser.add_argument("--dry-run", action="store_true", help="仅测试，不实际下载（dry-run 模式）")
    
    args = parser.parse_args()
    
    # 获取 token
    token = args.token or os.getenv("HF_TOKEN")
    
    # 确保输出目录存在
    output_dir = Path(args.output).absolute()
    output_dir.mkdir(parents=True, exist_ok=True)
    
    config = {
        'db_path': args.db,
        'output_dir': str(output_dir),
        'docker_image': args.docker_image,
        'endpoint': args.endpoint,
        'mirror': args.mirror,
        'use_mirror_on_failure': args.use_mirror_on_failure,
        'workers': args.workers,
        'poll_interval': args.poll_interval,
        'max_retries': args.max_retries,
        'max_active': args.max_active,
        'connections': args.connections,
        'timeout': args.timeout,
        'token': token,
        'dry_run': args.dry_run
    }
    
    consumer = DockerConsumer(config)
    consumer.run()


if __name__ == "__main__":
    main()

