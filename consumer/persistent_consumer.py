#!/usr/bin/env python3
"""
持久化消费者：长期运行的服务，避免频繁容器启动

优势：
- 避免 Docker 容器启动开销
- 支持连接复用和资源优化
- 更好的错误处理和重试机制
- 支持分布式部署

用法：
    python persistent_consumer.py                    # 使用默认配置
    python persistent_consumer.py --workers 3        # 使用 3 个并发 worker
    python persistent_consumer.py --redis-host redis # 连接到远程 Redis
"""

import argparse
import json
import os
import signal
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

try:
    import redis
except ImportError:
    print("请安装 redis 库: pip install redis")
    sys.exit(1)

# 假设我们有一个直接调用 Go 下载器的 Python 包装器
# 或者使用 subprocess 调用编译好的 Go 二进制文件


class PersistentConsumer:
    def __init__(self, config):
        self.config = config
        self.running = True

        # 初始化 Redis 连接
        self.redis_client = redis.Redis(
            host=config['redis_host'],
            port=config['redis_port'],
            db=config['redis_db'],
            password=config.get('redis_password'),
            decode_responses=True
        )

        self.queue_name = config['queue_name']
        self.dlq_name = config['dlq_name']
        self.max_retries = config['max_retries']

        # 确保输出目录存在
        self.output_dir = Path(config['output_dir'])
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # 初始化健康检查
        self.last_health_check = datetime.now()

        print(f"持久化消费者初始化完成")
        print(f"Redis: {config['redis_host']}:{config['redis_port']}")
        print(f"队列: {self.queue_name}")
        print(f"输出目录: {self.output_dir}")

    def signal_handler(self, sig, frame):
        """处理停止信号"""
        print("\n收到停止信号，正在安全退出...")
        self.running = False

    def download_dataset(self, dataset_id, output_path):
        """
        直接调用下载器下载数据集
        这里可以：
        1. 调用编译好的 Go 二进制文件
        2. 使用 Python 实现的下载器
        3. 调用 Go 下载器的 HTTP API（如果暴露）
        """
        # 方法 1: 调用 Go 二进制文件
        go_binary_path = self.config.get('go_binary_path', '/usr/local/bin/hfdownloader')

        cmd = [
            go_binary_path,
            'download',
            '--dataset',
            '--repo', dataset_id,
            '--output', str(output_path),
            '--endpoint', self.config.get('endpoint', 'https://huggingface.co')
        ]

        # 添加可选参数
        if self.config.get('token'):
            cmd.extend(['--token', self.config['token']])

        # Note: v2.0 CLI uses different parameter names
        # --workers is now --connections for concurrent connections
        # --max-active for maximum concurrent files
        if self.config.get('workers'):
            cmd.extend(['--connections', str(self.config['workers'])])
        
        # v2.0 uses --filters instead of --include/--exclude
        if self.config.get('include_pattern'):
            cmd.extend(['--filters', self.config['include_pattern']])

        try:
            import subprocess
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.config.get('timeout', 3600)
            )

            return {
                'success': result.returncode == 0,
                'stdout': result.stdout,
                'stderr': result.stderr,
                'returncode': result.returncode
            }

        except subprocess.TimeoutExpired:
            return {
                'success': False,
                'error': '下载超时'
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def process_task(self, task):
        """处理单个下载任务"""
        task_id = task['id']
        dataset_id = task['dataset_id']

        print(f"[{task_id}] 开始处理: {dataset_id}")

        # 构建输出路径
        safe_dataset_id = dataset_id.replace('/', '_')
        output_path = self.output_dir / safe_dataset_id

        # 检查是否已存在（避免重复下载）
        if output_path.exists() and output_path.is_dir():
            try:
                if any(output_path.iterdir()):
                    print(f"[{task_id}] ⚠️  输出目录已存在，跳过下载")
                    return True
            except Exception:
                pass  # 忽略检查错误，继续下载

        # 执行下载
        result = self.download_dataset(dataset_id, output_path)

        if result['success']:
            print(f"[{task_id}] ✅ 下载成功: {dataset_id}")
            return True
        else:
            error_msg = result.get('error') or result.get('stderr', '未知错误')
            print(f"[{task_id}] ❌ 下载失败: {dataset_id}")
            print(f"     错误: {error_msg[:200]}")
            return False

    def fetch_task(self):
        """从 Redis 队列获取任务"""
        try:
            # 使用 BRPOP 阻塞获取任务
            result = self.redis_client.brpop(self.queue_name, timeout=1)
            if result:
                _, task_json = result
                task = json.loads(task_json)
                return task
        except redis.exceptions.ConnectionError:
            print("Redis 连接错误，等待重连...")
            time.sleep(5)
        except Exception as e:
            print(f"获取任务时出错: {e}")

        return None

    def handle_task_failure(self, task, error_msg):
        """处理失败任务"""
        task['retry_count'] = task.get('retry_count', 0) + 1
        task['last_error'] = error_msg
        task['last_attempt'] = datetime.now().isoformat()

        if task['retry_count'] >= self.max_retries:
            # 移到死信队列
            self.redis_client.lpush(self.dlq_name, json.dumps(task))
            print(f"[{task['id']}] ❌ 任务失败，已移到死信队列")
        else:
            # 重新入队重试
            self.redis_client.lpush(self.queue_name, json.dumps(task))
            print(f"[{task['id']}] 🔄 重试任务 ({task['retry_count']}/{self.max_retries})")

    def health_check(self):
        """健康检查"""
        current_time = datetime.now()
        if (current_time - self.last_health_check).seconds > 300:  # 每 5 分钟
            try:
                queue_length = self.redis_client.llen(self.queue_name)
                dlq_length = self.redis_client.llen(self.dlq_name)

                print(f"[健康检查] 队列长度: {queue_length}, 死信队列: {dlq_length}")

                self.last_health_check = current_time
            except Exception as e:
                print(f"[健康检查] 错误: {e}")

    def worker(self, worker_id):
        """工作线程"""
        print(f"Worker {worker_id} 启动")

        while self.running:
            try:
                # 健康检查
                self.health_check()

                # 获取任务
                task = self.fetch_task()

                if task:
                    success = self.process_task(task)
                    if not success:
                        self.handle_task_failure(task, "下载失败")
                else:
                    # 没有任务，短暂休眠
                    time.sleep(0.1)

            except Exception as e:
                print(f"Worker {worker_id} 出错: {e}")
                time.sleep(5)  # 出错后等待一段时间

        print(f"Worker {worker_id} 停止")

    def run(self):
        """运行消费者服务"""
        print("=" * 60)
        print("持久化消费者服务启动")
        print(f"Redis: {self.config['redis_host']}:{self.config['redis_port']}")
        print(f"队列: {self.queue_name}")
        print(f"Worker 数量: {self.config['workers']}")
        print(f"最大重试次数: {self.max_retries}")
        print("=" * 60)

        # 注册信号处理
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

        # 启动多个 worker
        try:
            if self.config['workers'] > 1:
                import threading
                threads = []
                for i in range(self.config['workers']):
                    t = threading.Thread(
                        target=self.worker,
                        args=(i+1,),
                        daemon=True
                    )
                    t.start()
                    threads.append(t)

                # 等待所有线程
                for t in threads:
                    t.join()
            else:
                self.worker(1)

        except KeyboardInterrupt:
            self.running = False

        print("持久化消费者服务已停止")


def main():
    parser = argparse.ArgumentParser(description="持久化消费者服务")
    parser.add_argument("--redis-host", default="localhost", help="Redis 主机")
    parser.add_argument("--redis-port", type=int, default=6379, help="Redis 端口")
    parser.add_argument("--redis-db", type=int, default=0, help="Redis 数据库")
    parser.add_argument("--redis-password", help="Redis 密码")
    parser.add_argument("--queue-name", default="hf_download_queue", help="任务队列名称")
    parser.add_argument("--dlq-name", default="hf_download_dlq", help="死信队列名称")
    parser.add_argument("--output", default="./datasets", help="输出目录")
    parser.add_argument("--workers", type=int, default=1, help="Worker 数量")
    parser.add_argument("--max-retries", type=int, default=3, help="最大重试次数")
    parser.add_argument("--endpoint", default="https://hf-mirror.com", help="HF API 端点")
    parser.add_argument("--max-active", type=int, default=2, help="最大并发下载数")
    parser.add_argument("--connections", type=int, default=4, help="每个文件的连接数")
    parser.add_argument("--timeout", type=int, default=3600, help="下载超时（秒）")
    parser.add_argument("--token", help="HF Token")
    parser.add_argument("--mirror", help="HF 镜像站点")
    parser.add_argument("--use-mirror-on-failure", action="store_true", help="失败时使用镜像")
    parser.add_argument("--dry-run", action="store_true", help="仅测试，不实际下载")
    parser.add_argument("--go-binary-path", default="./hfdownloader", help="Go 下载器二进制路径")

    args = parser.parse_args()

    config = {
        'redis_host': args.redis_host,
        'redis_port': args.redis_port,
        'redis_db': args.redis_db,
        'redis_password': args.redis_password,
        'queue_name': args.queue_name,
        'dlq_name': args.dlq_name,
        'output_dir': args.output,
        'workers': args.workers,
        'max_retries': args.max_retries,
        'endpoint': args.endpoint,
        'max_active': args.max_active,
        'connections': args.connections,
        'timeout': args.timeout,
        'token': args.token,
        'mirror': args.mirror,
        'use_mirror_on_failure': args.use_mirror_on_failure,
        'dry_run': args.dry_run,
        'go_binary_path': args.go_binary_path
    }

    consumer = PersistentConsumer(config)
    consumer.run()


if __name__ == "__main__":
    main()