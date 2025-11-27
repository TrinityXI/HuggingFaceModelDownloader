#!/usr/bin/env python3
"""
监控服务：提供 Flask API 后端监控下载队列和数据集
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import pymysql
import pika
import os
import json
from datetime import datetime
from contextlib import contextmanager

app = Flask(__name__)
CORS(app)  # 允许 Next.js 前端跨域请求

# MySQL 配置
MYSQL_CONFIG = {
    'host': os.getenv('MYSQL_HOST', 'localhost'),
    'port': int(os.getenv('MYSQL_PORT', 3306)),
    'user': os.getenv('MYSQL_USER', 'root'),
    'password': os.getenv('MYSQL_PASSWORD', ''),
    'database': os.getenv('MYSQL_DATABASE', 'hf_datasets'),
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor
}

# RabbitMQ 配置
RABBITMQ_CONFIG = {
    'host': os.getenv('RABBITMQ_HOST', 'localhost'),
    'port': int(os.getenv('RABBITMQ_PORT', 5672)),
    'user': os.getenv('RABBITMQ_USER', 'admin'),
    'password': os.getenv('RABBITMQ_PASSWORD', 'password123'),
    'vhost': os.getenv('RABBITMQ_VHOST', '/'),
    'queue_name': os.getenv('RABBITMQ_QUEUE_NAME', 'hf_download_queue'),
    'dlq_name': os.getenv('RABBITMQ_DLQ_NAME', 'hf_download_dlq')
}

@contextmanager
def get_db_connection():
    """获取数据库连接的上下文管理器"""
    conn = pymysql.connect(**MYSQL_CONFIG)
    try:
        yield conn
    finally:
        conn.close()

def get_rabbitmq_queue_stats():
    """获取 RabbitMQ 队列统计信息"""
    try:
        credentials = pika.PlainCredentials(RABBITMQ_CONFIG['user'], RABBITMQ_CONFIG['password'])

@app.route('/health')
def health_check():
    """健康检查端点"""
    try:
        # 检查 Redis 连接
        redis_client.ping()

        # 检查磁盘空间
        disk_usage = psutil.disk_usage('/')
        disk_percent = disk_usage.percent

        # 检查内存使用
        memory = psutil.virtual_memory()

        # 检查队列状态
        queue_name = os.getenv('REDIS_QUEUE_NAME', 'hf_download_queue')
        dlq_name = os.getenv('REDIS_DLQ_NAME', 'hf_download_dlq')

        queue_length = redis_client.llen(queue_name)
        dlq_length = redis_client.llen(dlq_name)

        status = {
            'status': 'healthy',
            'redis': 'connected',
            'disk_usage_percent': disk_percent,
            'memory_usage_percent': memory.percent,
            'queue_length': queue_length,
            'dlq_length': dlq_length,
            'timestamp': datetime.now().isoformat()
        }

        # 如果磁盘使用率超过 90%，标记为警告
        if disk_percent > 90:
            status['status'] = 'warning'
            status['message'] = '磁盘空间不足'

        return jsonify(status)

    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

@app.route('/metrics')
def metrics():
    """Prometheus 格式的指标端点"""
    metrics_data = []

    try:
        # 队列指标
        queue_name = os.getenv('REDIS_QUEUE_NAME', 'hf_download_queue')
        dlq_name = os.getenv('REDIS_DLQ_NAME', 'hf_download_dlq')

        queue_length = redis_client.llen(queue_name)
        dlq_length = redis_client.llen(dlq_name)

        metrics_data.append(f'hf_queue_length {queue_length}')
        metrics_data.append(f'hf_dlq_length {dlq_length}')

        # 系统指标
        disk_usage = psutil.disk_usage('/')
        metrics_data.append(f'hf_disk_usage_percent {disk_usage.percent}')
        metrics_data.append(f'hf_disk_free_bytes {disk_usage.free}')

        memory = psutil.virtual_memory()
        metrics_data.append(f'hf_memory_usage_percent {memory.percent}')
        metrics_data.append(f'hf_memory_available_bytes {memory.available}')

        # CPU 使用率
        cpu_percent = psutil.cpu_percent(interval=1)
        metrics_data.append(f'hf_cpu_usage_percent {cpu_percent}')

        # 网络指标
        net_io = psutil.net_io_counters()
        metrics_data.append(f'hf_network_bytes_sent {net_io.bytes_sent}')
        metrics_data.append(f'hf_network_bytes_recv {net_io.bytes_recv}')

    except Exception as e:
        metrics_data.append(f'hf_monitor_errors 1')

    return '\n'.join(metrics_data), 200, {'Content-Type': 'text/plain'}

@app.route('/')
def index():
    """监控服务首页"""
    return jsonify({
        'service': 'HuggingFace Downloader Monitor',
        'version': '1.0.0',
        'endpoints': {
            '/health': '健康检查',
            '/metrics': 'Prometheus 指标',
            '/': '服务信息'
        }
    })

if __name__ == '__main__':
    host = os.getenv('MONITOR_HOST', '0.0.0.0')
    port = int(os.getenv('MONITOR_PORT', 8080))

    print(f"启动监控服务: {host}:{port}")
    print(f"健康检查: http://{host}:{port}/health")
    print(f"指标端点: http://{host}:{port}/metrics")

    app.run(host=host, port=port, debug=False)