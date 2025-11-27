#!/usr/bin/env python3
"""
生产者服务：定期扫描 HF 数据集并添加到下载队列

可以作为长期运行的服务，定期执行扫描任务。

用法:
    python producer_service.py                    # 使用默认配置
    python producer_service.py --interval 3600    # 每 3600 秒（1小时）运行一次
    python producer_service.py --once             # 只运行一次后退出
"""

import argparse
import os
import signal
import sys
import time
from datetime import datetime

from producer_lite import LightweightProducer


class ProducerService:
    def __init__(self, config):
        self.config = config
        self.running = True
        
        # MySQL配置
        mysql_config = None
        if config.get('mysql_host') or os.getenv('MYSQL_HOST'):
            mysql_config = {
                'host': config.get('mysql_host') or os.getenv('MYSQL_HOST', 'localhost'),
                'port': config.get('mysql_port') or int(os.getenv('MYSQL_PORT', 3306)),
                'user': config.get('mysql_user') or os.getenv('MYSQL_USER', 'root'),
                'password': config.get('mysql_password') or os.getenv('MYSQL_PASSWORD', ''),
                'database': config.get('mysql_database') or os.getenv('MYSQL_DATABASE', 'hf_datasets'),
                'charset': 'utf8mb4'
            }
        
        # RabbitMQ配置
        rabbitmq_config = {} if config.get('enable_rabbitmq') else None
        
        self.producer = LightweightProducer(
            db_path=config['db_path'],
            endpoint=config['endpoint'],
            token=config.get('token'),
            mysql_config=mysql_config,
            rabbitmq_config=rabbitmq_config
        )
        
    def signal_handler(self, sig, frame):
        """处理停止信号"""
        print("\n收到停止信号，正在安全退出...")
        self.running = False
    
    def run_once(self):
        """执行一次扫描"""
        print(f"\n{'='*60}")
        print(f"开始扫描任务 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}")
        
        try:
            self.producer.scan_and_queue(
                days=self.config['days'],
                limit_per_day=self.config['limit'],
                min_downloads=self.config.get('min_downloads', 0),
                min_likes=self.config.get('min_likes', 0)
            )
            print(f"\n扫描完成 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            return True
        except Exception as e:
            print(f"\n扫描失败: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            return False
    
    def run(self):
        """运行服务（持续运行）"""
        # 注册信号处理
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        interval = self.config.get('interval', 3600)  # 默认 1 小时
        
        print("="*60)
        print("生产者服务启动")
        print(f"数据库: {self.config['db_path']}")
        print(f"扫描间隔: {interval} 秒 ({interval/3600:.1f} 小时)")
        print(f"每次扫描: 最近 {self.config['days']} 天，每天最多 {self.config['limit']} 个")
        print("="*60)
        
        # 立即执行一次
        self.run_once()
        
        # 循环执行
        while self.running:
            try:
                # 等待指定间隔
                print(f"\n等待 {interval} 秒后执行下次扫描...")
                print(f"下次扫描时间: {(datetime.now().timestamp() + interval):.0f}")
                
                # 分段等待，以便响应停止信号
                waited = 0
                while waited < interval and self.running:
                    time.sleep(min(10, interval - waited))  # 每 10 秒检查一次
                    waited += 10
                
                if self.running:
                    self.run_once()
                    
            except KeyboardInterrupt:
                self.running = False
                break
        
        print("\n生产者服务已停止")


def main():
    parser = argparse.ArgumentParser(description="生产者服务：定期扫描 HF 数据集")
    parser.add_argument("--db", default="datasets.db", help="SQLite数据库路径（用于dataset元数据）")
    parser.add_argument("--days", type=int, default=1, help="每次扫描最近 N 天")
    parser.add_argument("--limit", type=int, default=100, help="每天最多查询 N 个")
    parser.add_argument("--min-downloads", type=int, default=0, help="最小下载量过滤")
    parser.add_argument("--min-likes", type=int, default=0, help="最小点赞数过滤")
    parser.add_argument("--endpoint", default="https://huggingface.co", help="HF API 端点")
    parser.add_argument("--token", help="HF Token（或使用 HF_TOKEN 环境变量）")
    parser.add_argument("--interval", type=int, default=3600, help="扫描间隔（秒），默认 3600（1小时）")
    parser.add_argument("--once", action="store_true", help="只运行一次后退出（不持续运行）")
    parser.add_argument("--mysql-host", default=None, help="MySQL主机（默认从环境变量读取）")
    parser.add_argument("--mysql-port", type=int, default=3306, help="MySQL端口")
    parser.add_argument("--mysql-user", default=None, help="MySQL用户名")
    parser.add_argument("--mysql-password", default=None, help="MySQL密码")
    parser.add_argument("--mysql-database", default="hf_datasets", help="MySQL数据库名")
    parser.add_argument("--enable-rabbitmq", action="store_true", help="启用RabbitMQ任务发布")
    
    args = parser.parse_args()
    
    token = args.token or os.getenv("HF_TOKEN")
    
    config = {
        'db_path': args.db,
        'days': args.days,
        'limit': args.limit,
        'min_downloads': args.min_downloads,
        'min_likes': args.min_likes,
        'endpoint': args.endpoint,
        'token': token,
        'interval': args.interval,
        'mysql_host': args.mysql_host,
        'mysql_port': args.mysql_port,
        'mysql_user': args.mysql_user,
        'mysql_password': args.mysql_password,
        'mysql_database': args.mysql_database,
        'enable_rabbitmq': args.enable_rabbitmq or os.getenv('ENABLE_RABBITMQ', '').lower() in ('true', '1', 'yes')
    }
    
    service = ProducerService(config)
    
    try:
        if args.once:
            # 只运行一次
            service.run_once()
        else:
            # 持续运行
            service.run()
    finally:
        # 断开RabbitMQ连接
        if hasattr(service.producer, '_disconnect_rabbitmq'):
            service.producer._disconnect_rabbitmq()


if __name__ == "__main__":
    main()

