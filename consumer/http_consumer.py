#!/usr/bin/env python3
"""
HTTP Consumer 服务
通过 HTTP API 从 producer 拉取任务并处理下载
不依赖 RabbitMQ 和 Redis
"""

import json
import time
import logging
import os
import sys
import subprocess
import requests
from datetime import datetime

# 配置日志
handlers = [logging.StreamHandler(sys.stdout)]

try:
    log_dir = '/app/logs'
    if os.path.exists(log_dir) and os.access(log_dir, os.W_OK):
        handlers.append(logging.FileHandler('/app/logs/http_consumer.log'))
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=handlers,
    force=True
)
logger = logging.getLogger(__name__)

logger.info("="*60)
logger.info("HTTP Consumer 启动中...")
logger.info("="*60)


class DownloadProgressTracker:
    """下载进度跟踪器"""

    def __init__(self, dataset_id):
        self.dataset_id = dataset_id
        self.total_bytes = 0
        self.total_files = 0
        self.scanned_total_files = 0
        self.scan_total_bytes = 0  # 扫描完成时的总字节数（准确值）
        self.completed_files = 0
        self.skipped_files = 0
        self.file_progress = {}
        self.planned_files = set()
        self.completed_files_set = set()
        self.skipped_files_set = set()
        self.last_speed_check_time = time.time()
        self.last_speed_check_bytes = 0
        self.current_speed = 0
        self.last_publish_time = time.time()
        self.last_publish_percentage = 0.0
        self.publish_interval = 10
        self.publish_percentage_delta = 5.0
        self.start_time = time.time()
        self.speed_samples = []  # 存储最近的速度样本
        self.max_speed_samples = 5  # 最多保留5个样本用于平滑
        
        # 扫描阶段状态
        self.is_scanning = True
        self.scan_dirs = 0
        self.scan_files = 0
        self.scan_message = ''
        self.last_scan_publish_time = 0

    def process_event(self, event):
        """处理单个进度事件"""
        event_type = event.get('event', '')

        if event_type == 'scan_start':
            self.is_scanning = True
            self.scan_message = event.get('message', 'scanning repo')

        elif event_type == 'scan_progress':
            message = event.get('message', '')
            self.scan_message = message
            import re
            # 解析 dirs 和 files
            dirs_match = re.search(r'(\d+)\s+dirs', message)
            files_match = re.search(r'(\d+)\s+files', message)
            if dirs_match:
                self.scan_dirs = int(dirs_match.group(1))
            if files_match:
                self.scan_files = int(files_match.group(1))
                self.scanned_total_files = self.scan_files

        elif event_type == 'scan_complete':
            self.is_scanning = False
            # 扫描完成时，获取准确的文件总数和总字节数
            total_files = event.get('bytes', 0)  # Bytes 字段存储文件总数
            total_bytes = event.get('total', 0)  # Total 字段存储总字节数
            if total_files > 0:
                self.scanned_total_files = total_files
            if total_bytes > 0:
                # 使用扫描完成时的总字节数作为基准
                self.scan_total_bytes = total_bytes

        elif event_type == 'plan_item':
            path = event.get('path', '')
            total = event.get('total', 0)

            if path and path not in self.planned_files:
                self.planned_files.add(path)
                # 始终累加新的 plan_item
                self.total_files += 1
                self.total_bytes += total
                self.file_progress[path] = {'bytes': 0, 'total': total, 'skipped': False}

        elif event_type == 'file_start':
            # 文件开始下载时，确保文件已在跟踪器中
            path = event.get('path', '')
            if path and path not in self.file_progress:
                # 如果文件未通过 plan_item 添加，现在添加
                total = event.get('total', 0)
                self.planned_files.add(path)
                self.total_files += 1
                self.total_bytes += total
                self.file_progress[path] = {'bytes': 0, 'total': total, 'skipped': False}

        elif event_type == 'file_progress':
            path = event.get('path', '')
            bytes_done = event.get('bytes', 0)
            total = event.get('total', 0)

            if path:
                if path not in self.file_progress:
                    # 动态添加新发现的文件
                    self.planned_files.add(path)
                    self.total_files += 1
                    self.total_bytes += total
                    self.file_progress[path] = {'bytes': 0, 'total': total, 'skipped': False}
                
                self.file_progress[path]['bytes'] = bytes_done

                if bytes_done >= total and total > 0 and path not in self.completed_files_set:
                    self.completed_files_set.add(path)
                    self.completed_files += 1

        elif event_type == 'file_done':
            path = event.get('path', '')
            message = event.get('message', '')

            if path:
                # 确保文件在跟踪器中
                if path not in self.file_progress:
                    total = event.get('total', 0)
                    self.planned_files.add(path)
                    self.total_files += 1
                    self.total_bytes += total
                    self.file_progress[path] = {'bytes': 0, 'total': total, 'skipped': False}

                if path not in self.completed_files_set:
                    self.completed_files_set.add(path)
                    self.completed_files += 1

                is_skipped = 'skip' in message.lower()
                if is_skipped and path not in self.skipped_files_set:
                    self.skipped_files += 1
                    self.skipped_files_set.add(path)

                if path in self.file_progress:
                    total = self.file_progress[path]['total']
                    self.file_progress[path]['bytes'] = total
                    self.file_progress[path]['skipped'] = is_skipped

    def get_overall_progress(self):
        """计算总体进度（基于累计下载字节数和总字节数）"""
        # 使用实际累计的文件数
        display_total_files = self.total_files if self.total_files > 0 else len(self.planned_files)
        
        # 优先使用 scan_complete 事件提供的准确总字节数
        effective_total_bytes = self.scan_total_bytes if self.scan_total_bytes > 0 else self.total_bytes

        if effective_total_bytes == 0:
            return {
                'percentage': 0.0,
                'downloaded_bytes': 0,
                'total_bytes': 0,
                'total_files': display_total_files,
                'completed_files': self.completed_files,
                'skipped_files': self.skipped_files,
                'download_speed': 0
            }

        # 累计所有非跳过文件的已下载字节数
        downloaded_bytes = 0

        for path, fp in self.file_progress.items():
            is_skipped = path in self.skipped_files_set

            if not is_skipped:
                # 如果文件已完成，使用其总大小；否则使用当前进度
                if path in self.completed_files_set:
                    downloaded_bytes += fp['total']
                else:
                    downloaded_bytes += fp['bytes']

        # 使用准确的总字节数作为分母
        # 计算百分比，并确保不超过 100%
        percentage = (downloaded_bytes / effective_total_bytes * 100) if effective_total_bytes > 0 else 0.0
        percentage = min(percentage, 100.0)  # 限制最大值为 100%

        # 计算下载速度（使用移动平均平滑）
        current_time = time.time()
        time_delta = current_time - self.last_speed_check_time

        if time_delta >= 1.0:
            bytes_delta = downloaded_bytes - self.last_speed_check_bytes
            instant_speed = bytes_delta / time_delta if time_delta > 0 else 0

            # 添加到速度样本列表
            self.speed_samples.append(instant_speed)

            # 只保留最近的样本
            if len(self.speed_samples) > self.max_speed_samples:
                self.speed_samples.pop(0)

            # 计算平均速度
            self.current_speed = sum(self.speed_samples) / len(self.speed_samples) if self.speed_samples else 0

            self.last_speed_check_time = current_time
            self.last_speed_check_bytes = downloaded_bytes

        return {
            'percentage': round(percentage, 2),
            'downloaded_bytes': downloaded_bytes,
            'total_bytes': effective_total_bytes,
            'total_files': display_total_files,
            'completed_files': self.completed_files,
            'skipped_files': self.skipped_files,
            'download_speed': round(self.current_speed, 2),
            'progress_status': 'downloading'  # 下载状态
        }

    def should_publish_progress(self):
        """判断是否应该发布进度更新"""
        current_time = time.time()
        current_progress = self.get_overall_progress()
        current_percentage = current_progress['percentage']

        time_elapsed = current_time - self.last_publish_time >= self.publish_interval
        percentage_changed = abs(current_percentage - self.last_publish_percentage) >= self.publish_percentage_delta

        if time_elapsed or percentage_changed:
            self.last_publish_time = current_time
            self.last_publish_percentage = current_percentage
            return True

        return False

    def get_scan_progress(self):
        """获取扫描阶段的进度信息"""
        return {
            'percentage': 0.0,  # 扫描阶段百分比为0
            'downloaded_bytes': 0,
            'total_bytes': self.total_bytes,
            'total_files': self.scan_files,  # 扫描到的文件数
            'completed_files': 0,
            'skipped_files': 0,
            'download_speed': 0,
            'progress_status': 'scanning'  # 扫描状态
        }

    def should_publish_scan_progress(self):
        """判断是否应该发布扫描进度更新（每5秒一次）"""
        current_time = time.time()
        if current_time - self.last_scan_publish_time >= 5:
            self.last_scan_publish_time = current_time
            return True
        return False


class HTTPConsumer:
    """HTTP Consumer - 通过 HTTP API 与 producer 交互"""

    def __init__(self):
        # Producer HTTP API 配置
        self.producer_endpoint = os.getenv('PRODUCER_ENDPOINT', 'http://localhost:8000')
        self.worker_id = os.getenv('WORKER_ID', f'http-consumer-{os.getpid()}')

        # Consumer 配置
        self.consumer_workers = int(os.getenv('CONSUMER_WORKERS', 1))
        self.consumer_max_retries = int(os.getenv('CONSUMER_MAX_RETRIES', 3))
        self.consumer_timeout = int(os.getenv('CONSUMER_TIMEOUT', 3600))
        self.poll_interval = int(os.getenv('POLL_INTERVAL', 30))  # 轮询间隔
        
        # 任务恢复配置
        self.recovery_enabled = os.getenv('RECOVERY_ENABLED', 'true').lower() == 'true'
        self.recovery_timeout_minutes = int(os.getenv('RECOVERY_TIMEOUT_MINUTES', 30))

        # 下载器配置
        self.hf_endpoint = os.getenv('HF_ENDPOINT', 'https://huggingface.co')
        self.hf_token = os.getenv('HF_TOKEN', '')
        self.output_dir = os.getenv('OUTPUT_DIR', '/datasets')
        self.go_binary_path = os.getenv('GO_BINARY_PATH', '/app/hfdownloader-optimized')

        # HTTP 客户端配置
        self.session = requests.Session()
        self.session.headers.update({'Content-Type': 'application/json'})

        self.running = False

        logger.info(f"Worker ID: {self.worker_id}")
        logger.info(f"Producer Endpoint: {self.producer_endpoint}")
        logger.info(f"Poll Interval: {self.poll_interval} seconds")
        logger.info(f"Recovery Enabled: {self.recovery_enabled}")
        logger.info(f"Recovery Timeout: {self.recovery_timeout_minutes} minutes")

    def fetch_tasks(self, limit=1):
        """从 producer 拉取任务"""
        try:
            url = f"{self.producer_endpoint}/api/consumer/fetch-tasks"
            payload = {
                'worker_id': self.worker_id,
                'limit': limit
            }

            response = self.session.post(url, json=payload, timeout=10)
            response.raise_for_status()

            data = response.json()
            tasks = data.get('tasks', [])

            if tasks:
                logger.info(f"拉取到 {len(tasks)} 个任务")

            return tasks

        except requests.RequestException as e:
            logger.error(f"拉取任务失败: {e}")
            return []
        except Exception as e:
            logger.error(f"拉取任务异常: {e}")
            return []

    def fetch_interrupted_tasks(self, limit=1):
        """从 producer 拉取中断的任务（恢复机制）"""
        try:
            url = f"{self.producer_endpoint}/api/consumer/fetch-interrupted-tasks"
            payload = {
                'worker_id': self.worker_id,
                'limit': limit,
                'timeout_minutes': self.recovery_timeout_minutes
            }

            response = self.session.post(url, json=payload, timeout=10)
            response.raise_for_status()

            data = response.json()
            tasks = data.get('tasks', [])

            if tasks:
                logger.info(f"发现 {len(tasks)} 个中断的任务需要恢复")
                for task in tasks:
                    prev = task.get('previous_progress', {})
                    logger.info(
                        f"  - {task['dataset_id']}: 之前进度 {prev.get('percentage', 0):.1f}%"
                    )

            return tasks

        except requests.RequestException as e:
            logger.error(f"拉取中断任务失败: {e}")
            return []
        except Exception as e:
            logger.error(f"拉取中断任务异常: {e}")
            return []

    def update_status(self, dataset_id, status, message='', storage_path=''):
        """更新任务状态"""
        try:
            url = f"{self.producer_endpoint}/api/consumer/update-status"
            payload = {
                'dataset_id': dataset_id,
                'status': status,
                'message': message,
                'storage_path': storage_path
            }

            response = self.session.post(url, json=payload, timeout=10)
            response.raise_for_status()

            logger.debug(f"状态已更新: {dataset_id} -> {status}")
            return True

        except requests.RequestException as e:
            logger.error(f"更新状态失败: {e}")
            return False
        except Exception as e:
            logger.error(f"更新状态异常: {e}")
            return False

    def update_progress(self, dataset_id, progress_data):
        """更新下载进度"""
        try:
            url = f"{self.producer_endpoint}/api/consumer/update-progress"
            payload = {
                'dataset_id': dataset_id,
                **progress_data
            }

            response = self.session.post(url, json=payload, timeout=10)
            response.raise_for_status()

            return True

        except requests.RequestException as e:
            logger.error(f"更新进度失败: {e}")
            return False
        except Exception as e:
            logger.error(f"更新进度异常: {e}")
            return False

    def log_event(self, dataset_id, event_type, message='', metadata=None):
        """记录事件"""
        try:
            url = f"{self.producer_endpoint}/api/consumer/log-event"
            payload = {
                'dataset_id': dataset_id,
                'event_type': event_type,
                'message': message,
                'metadata': metadata or {}
            }

            response = self.session.post(url, json=payload, timeout=10)
            response.raise_for_status()

            return True

        except requests.RequestException as e:
            logger.error(f"记录事件失败: {e}")
            return False
        except Exception as e:
            logger.error(f"记录事件异常: {e}")
            return False

    def download_dataset(self, task_info):
        """下载数据集"""
        dataset_id = task_info.get('dataset_id', 'unknown')
        logger.info(f"开始下载数据集: {dataset_id}")

        # 更新状态为 downloading
        self.update_status(dataset_id, 'downloading', '开始下载任务')
        self.log_event(dataset_id, 'start', '开始下载任务')

        # 初始化进度跟踪器
        progress_tracker = DownloadProgressTracker(dataset_id)

        try:
            safe_dataset_id = dataset_id.replace('/', '_')
            storage_subpath = task_info.get('storage_path')

            if storage_subpath:
                if storage_subpath.startswith('/'):
                    storage_subpath = storage_subpath.lstrip('/')
                output_path = os.path.join(self.output_dir, storage_subpath)
                output_path = os.path.join(output_path, safe_dataset_id)
            else:
                output_path = os.path.join(self.output_dir, safe_dataset_id)

            # 构建下载命令
            cmd = [
                self.go_binary_path,
                'download',
                '--dataset',
                '--repo', dataset_id,
                '--output', output_path,
                '--endpoint', self.hf_endpoint,
                '--max-active', '2',
                '--connections', '4',
                '--json'
            ]

            if self.hf_token:
                cmd.extend(['--token', self.hf_token])

            # 处理 tar 配置
            tar_config = task_info.get('tar_config', {})
            if tar_config and tar_config.get('enabled'):
                cmd.append('--tar')
                logger.info(f"启用 tar 压缩: {dataset_id}")
                
                if tar_config.get('compress', True):
                    cmd.append('--tar-gz')
                    logger.info(f"启用 gzip 压缩")
                
                split_size = tar_config.get('split_size', '50GiB')
                if split_size:
                    cmd.extend(['--tar-split-size', split_size])
                    logger.info(f"分片大小: {split_size}")
                
                split_threshold = tar_config.get('split_threshold', '100GiB')
                if split_threshold:
                    cmd.extend(['--tar-split-threshold', split_threshold])
                    logger.info(f"分片阈值: {split_threshold}")
                
                if tar_config.get('delete_source', False):
                    cmd.append('--tar-delete-source')
                    logger.info(f"打包后删除源文件")
                
                # tar 模式：默认使用 auto（自动根据大小选择）
                # auto: < 50GB 用 default, 50-100GB 用 local, >= 100GB 用 stream
                tar_mode = tar_config.get('mode', 'auto')
                cmd.extend(['--tar-mode', tar_mode])
                logger.info(f"Tar 模式: {tar_mode}")
                
                # 本地缓存目录（用于 local 模式）
                cache_dir = tar_config.get('cache_dir', '')
                if cache_dir:
                    cmd.extend(['--tar-cache-dir', cache_dir])
                    logger.info(f"本地缓存目录: {cache_dir}")
                
                # buffer 大小
                buffer_size = tar_config.get('buffer_size', 0)
                if buffer_size and buffer_size > 0:
                    cmd.extend(['--tar-buffer-size', str(buffer_size)])
                    logger.info(f"Buffer 大小: {buffer_size}")
                
                # 压缩级别
                compress_level = tar_config.get('compress_level', 0)
                if compress_level and 1 <= compress_level <= 9:
                    cmd.extend(['--tar-compress-level', str(compress_level)])
                    logger.info(f"压缩级别: {compress_level}")

            logger.info(f"执行命令: {' '.join(cmd)}")

            # 执行下载
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )

            # 实时读取进度
            output_lines = []
            for line in process.stdout:
                line = line.strip()
                if line:
                    output_lines.append(line)

                    try:
                        event = json.loads(line)
                        event_type = event.get('event', '')
                        message = event.get('message', '')

                        # 在处理事件前记录文件是否已完成
                        path = event.get('path', 'unknown')
                        was_completed = path in progress_tracker.completed_files_set

                        # 更新进度跟踪器
                        progress_tracker.process_event(event)
                        overall_progress = progress_tracker.get_overall_progress()

                        if event_type == 'scan_start':
                            logger.info(f"开始扫描: {message}")
                        elif event_type == 'scan_progress':
                            logger.info(f"扫描进度: {message}")
                            # 发布扫描进度到服务器
                            if progress_tracker.should_publish_scan_progress():
                                scan_progress = progress_tracker.get_scan_progress()
                                self.update_progress(dataset_id, scan_progress)
                        elif event_type == 'scan_complete':
                            logger.info(f"扫描完成: {message}")
                            # 发布扫描完成状态
                            overall_progress = progress_tracker.get_overall_progress()
                            self.update_progress(dataset_id, overall_progress)
                        elif event_type == 'plan_item':
                            logger.debug(f"计划项: {path}")
                        elif event_type == 'file_start':
                            logger.info(f"开始下载: {path}")
                        elif event_type == 'file_progress':
                            bytes_done = event.get('bytes', 0)
                            total = event.get('total', 1)
                            percent = (bytes_done / total * 100) if total > 0 else 0

                            # 如果文件之前未完成，现在也未完成，则显示进度
                            is_now_completed = path in progress_tracker.completed_files_set

                            if not was_completed and not is_now_completed:
                                logger.info(
                                    f"文件进度: {path} - {percent:.1f}% | "
                                    f"总体: {overall_progress['percentage']:.1f}% "
                                    f"({overall_progress['completed_files']}/{overall_progress['total_files']} 文件)"
                                )

                            # 发布进度更新
                            if progress_tracker.should_publish_progress():
                                self.update_progress(dataset_id, overall_progress)

                        elif event_type == 'file_done':
                            logger.info(
                                f"文件完成: {event.get('path', 'unknown')} | "
                                f"总体: {overall_progress['percentage']:.1f}% "
                                f"({overall_progress['completed_files']}/{overall_progress['total_files']} 文件)"
                            )
                        elif event_type == 'done':
                            logger.info(f"下载完成: {message}")
                            # 发布最终进度
                            self.update_progress(dataset_id, overall_progress)
                        elif event_type == 'error':
                            logger.error(f"下载错误: {message}")
                        else:
                            logger.debug(f"进度事件: {event_type} - {message}")

                    except json.JSONDecodeError:
                        logger.info(f"输出: {line}")

            # 等待进程完成
            process.wait()

            if process.returncode == 0:
                logger.info(f"下载成功: {dataset_id}")
                # 更新状态为 completed
                self.update_status(dataset_id, 'completed', '下载完成', output_path)
                self.log_event(dataset_id, 'complete', '下载完成', {'storage_path': output_path})
                return True, "下载成功"
            else:
                error_msg = f"下载失败，返回码: {process.returncode}"
                logger.error(f"{error_msg} - {dataset_id}")
                return False, error_msg

        except subprocess.TimeoutExpired:
            error_msg = f"下载超时: {dataset_id}"
            logger.error(error_msg)
            return False, error_msg
        except Exception as e:
            error_msg = f"下载异常: {str(e)}"
            logger.error(f"{error_msg} - {dataset_id}")
            return False, error_msg

    def process_task(self, task_info):
        """处理单个任务"""
        dataset_id = task_info.get('dataset_id', 'unknown')
        retry_count = task_info.get('retry_count', 0)

        logger.info(f"处理任务: {dataset_id} (重试次数: {retry_count})")

        # 执行下载
        success, msg = self.download_dataset(task_info)

        if not success:
            # 下载失败
            if retry_count < self.consumer_max_retries:
                # 更新状态为 pending 以便重试
                self.update_status(dataset_id, 'pending', msg)
                self.log_event(dataset_id, 'retry', msg, {'retry_count': retry_count + 1})
                logger.warning(f"任务将重试: {dataset_id} ({retry_count + 1}/{self.consumer_max_retries})")
            else:
                # 达到最大重试次数，标记为失败
                self.update_status(dataset_id, 'failed', msg)
                self.log_event(dataset_id, 'fail', msg, {'retry_count': retry_count + 1})
                logger.error(f"任务失败: {dataset_id}")

    def recover_interrupted_tasks(self):
        """
        恢复中断的下载任务
        在 Consumer 启动时调用，处理因重启而中断的任务
        """
        if not self.recovery_enabled:
            logger.info("任务恢复功能已禁用")
            return
        
        logger.info("="*60)
        logger.info("检查是否有中断的下载任务需要恢复...")
        logger.info("="*60)
        
        try:
            # 循环处理所有中断的任务
            total_recovered = 0
            while self.running:
                tasks = self.fetch_interrupted_tasks(limit=1)
                
                if not tasks:
                    break
                
                for task in tasks:
                    if not self.running:
                        break
                    
                    dataset_id = task.get('dataset_id', 'unknown')
                    logger.info(f"正在恢复中断的任务: {dataset_id}")
                    
                    # 记录恢复事件
                    self.log_event(dataset_id, 'retry', '任务因 Consumer 重启而中断，正在恢复', {
                        'worker_id': self.worker_id,
                        'recovery': True,
                        'previous_progress': task.get('previous_progress', {})
                    })
                    
                    # 处理任务（重新下载）
                    self.process_task(task)
                    total_recovered += 1
            
            if total_recovered > 0:
                logger.info(f"已恢复并处理 {total_recovered} 个中断的任务")
            else:
                logger.info("没有需要恢复的中断任务")
        
        except Exception as e:
            logger.error(f"恢复中断任务时出错: {e}")

    def run(self):
        """运行消费者"""
        logger.info("启动 HTTP Consumer")
        self.running = True
        
        # 启动时先恢复中断的任务
        self.recover_interrupted_tasks()

        while self.running:
            try:
                # 先检查是否有中断的任务需要恢复
                interrupted_tasks = self.fetch_interrupted_tasks(limit=1)
                if interrupted_tasks:
                    for task in interrupted_tasks:
                        if not self.running:
                            break
                        logger.info(f"发现中断任务，优先恢复: {task.get('dataset_id')}")
                        self.process_task(task)
                    continue  # 继续检查是否还有中断任务
                
                # 拉取新任务
                tasks = self.fetch_tasks(limit=self.consumer_workers)

                if tasks:
                    # 处理任务
                    for task in tasks:
                        if not self.running:
                            break
                        self.process_task(task)
                else:
                    # 没有任务，等待一段时间后再次拉取
                    logger.debug(f"无可用任务，等待 {self.poll_interval} 秒...")
                    time.sleep(self.poll_interval)

            except KeyboardInterrupt:
                logger.info("收到中断信号，停止消费者")
                self.running = False
                break
            except Exception as e:
                logger.error(f"消费者运行出错: {e}")
                time.sleep(60)

        logger.info("HTTP Consumer 已停止")

    def stop(self):
        """停止消费者"""
        self.running = False


def main():
    """主函数"""
    consumer = HTTPConsumer()

    try:
        consumer.run()
    except KeyboardInterrupt:
        logger.info("程序被用户中断")
    finally:
        consumer.stop()


if __name__ == '__main__':
    main()
