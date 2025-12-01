#!/usr/bin/env python3
"""
监控服务 Flask API 后端
提供下载队列和数据集监控的 REST API
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import pymysql
import pika
import os
import json
import requests
import time
import sys
from datetime import datetime, timedelta
from contextlib import contextmanager

# Import mysql_queue from current directory (copied by Docker)
from mysql_queue import MySQLQueueManager

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

# 创建 MySQL 队列管理器实例
queue_manager = MySQLQueueManager(MYSQL_CONFIG)

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

# 删除旧的数据库连接管理器，使用统一的 MySQLQueueManager

def get_rabbitmq_queue_stats():
    """获取 RabbitMQ 队列统计信息"""
    try:
        credentials = pika.PlainCredentials(RABBITMQ_CONFIG['user'], RABBITMQ_CONFIG['password'])
        parameters = pika.ConnectionParameters(
            host=RABBITMQ_CONFIG['host'],
            port=RABBITMQ_CONFIG['port'],
            virtual_host=RABBITMQ_CONFIG['vhost'],
            credentials=credentials
        )
        
        connection = pika.BlockingConnection(parameters)
        channel = connection.channel()
        
        # 获取主队列信息
        queue_info = channel.queue_declare(queue=RABBITMQ_CONFIG['queue_name'], passive=True, durable=True)
        queue_length = queue_info.method.message_count
        
        # 获取死信队列信息
        dlq_info = channel.queue_declare(queue=RABBITMQ_CONFIG['dlq_name'], passive=True, durable=True)
        dlq_length = dlq_info.method.message_count
        
        connection.close()
        
        return {
            'queue_length': queue_length,
            'dlq_length': dlq_length
        }
    except Exception as e:
        return {
            'queue_length': 0,
            'dlq_length': 0,
            'error': str(e)
        }

@app.route('/api/health')
def health_check():
    """健康检查端点"""
    try:
        # 使用队列管理器测试数据库连接
        with queue_manager.get_connection():
            pass

        rabbitmq_stats = get_rabbitmq_queue_stats()

        return jsonify({
            'status': 'healthy',
            'mysql': 'connected',
            'rabbitmq': 'connected' if 'error' not in rabbitmq_stats else 'error',
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

@app.route('/api/stats/overview')
def get_overview_stats():
    """获取总览统计数据"""
    try:
        with queue_manager.get_connection() as conn:
            cursor = conn.cursor()

            # 按状态统计任务数量
            cursor.execute("""
                SELECT status, COUNT(*) as count
                FROM download_queue
                GROUP BY status
            """)
            status_counts = {row['status']: row['count'] for row in cursor.fetchall()}

            # 获取今日新增任务数
            cursor.execute("""
                SELECT COUNT(*) as count
                FROM download_queue
                WHERE DATE(created_at) = CURDATE()
            """)
            today_added = cursor.fetchone()['count']

            # 获取今日完成任务数
            cursor.execute("""
                SELECT COUNT(*) as count
                FROM download_queue
                WHERE DATE(completed_at) = CURDATE() AND status = 'completed'
            """)
            today_completed = cursor.fetchone()['count']

            # 获取失败任务数
            cursor.execute("""
                SELECT COUNT(*) as count
                FROM download_queue
                WHERE status = 'failed'
            """)
            failed_count = cursor.fetchone()['count']

        rabbitmq_stats = get_rabbitmq_queue_stats()

        return jsonify({
            'status_counts': status_counts,
            'today_added': today_added,
            'today_completed': today_completed,
            'failed_count': failed_count,
            'rabbitmq_queue': rabbitmq_stats['queue_length'],
            'rabbitmq_dlq': rabbitmq_stats['dlq_length'],
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/queue/list')
def get_queue_list():
    """获取下载队列列表"""
    try:
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 20))
        status = request.args.get('status', None)

        offset = (page - 1) * per_page

        with queue_manager.get_connection() as conn:
            cursor = conn.cursor()

            # 构建查询
            where_clause = f"WHERE status = '{status}'" if status else ""

            # 获取总数
            cursor.execute(f"""
                SELECT COUNT(*) as total
                FROM download_queue
                {where_clause}
            """)
            total = cursor.fetchone()['total']

            # 获取数据
            cursor.execute(f"""
                SELECT id, dataset_id, priority, status, retry_count, last_error,
                       storage_path, created_at, started_at, completed_at, updated_at
                FROM download_queue
                {where_clause}
                ORDER BY
                    CASE
                        WHEN status = 'downloading' THEN 1
                        WHEN status = 'pending' THEN 2
                        WHEN status = 'failed' THEN 3
                        WHEN status = 'completed' THEN 4
                    END,
                    priority DESC,
                    created_at DESC
                LIMIT %s OFFSET %s
            """, (per_page, offset))

            tasks = cursor.fetchall()

            # 转换日期为 ISO 格式
            for task in tasks:
                for key in ['created_at', 'started_at', 'completed_at', 'updated_at']:
                    if task[key]:
                        task[key] = task[key].isoformat()

        return jsonify({
            'tasks': tasks,
            'total': total,
            'page': page,
            'per_page': per_page,
            'total_pages': (total + per_page - 1) // per_page
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/queue/<int:task_id>')
def get_task_detail(task_id):
    """获取任务详情"""
    try:
        with queue_manager.get_connection() as conn:
            cursor = conn.cursor()

            # 获取任务信息
            cursor.execute("""
                SELECT id, dataset_id, priority, status, retry_count, last_error,
                       storage_path, created_at, started_at, completed_at, updated_at
                FROM download_queue
                WHERE id = %s
            """, (task_id,))

            task = cursor.fetchone()
            if not task:
                return jsonify({'error': 'Task not found'}), 404

            # 转换日期
            for key in ['created_at', 'started_at', 'completed_at', 'updated_at']:
                if task[key]:
                    task[key] = task[key].isoformat()

            # 获取事件日志
            cursor.execute("""
                SELECT id, event_type, message, metadata, created_at
                FROM download_events
                WHERE dataset_id = %s
                ORDER BY created_at DESC
                LIMIT 50
            """, (task['dataset_id'],))

            events = cursor.fetchall()
            for event in events:
                if event['created_at']:
                    event['created_at'] = event['created_at'].isoformat()
                if event['metadata']:
                    event['metadata'] = json.loads(event['metadata']) if isinstance(event['metadata'], str) else event['metadata']

            task['events'] = events

        return jsonify(task)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/stats/timeline')
def get_timeline_stats():
    """获取时间线统计数据（最近7天）"""
    try:
        days = int(request.args.get('days', 7))

        with queue_manager.get_connection() as conn:
            cursor = conn.cursor()

            # 获取每日完成数量
            cursor.execute("""
                SELECT DATE(completed_at) as date, COUNT(*) as count
                FROM download_queue
                WHERE completed_at >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
                  AND status = 'completed'
                GROUP BY DATE(completed_at)
                ORDER BY date DESC
            """, (days,))

            completed_timeline = cursor.fetchall()

            # 获取每日新增数量
            cursor.execute("""
                SELECT DATE(created_at) as date, COUNT(*) as count
                FROM download_queue
                WHERE created_at >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
                GROUP BY DATE(created_at)
                ORDER BY date DESC
            """, (days,))

            created_timeline = cursor.fetchall()

            # 转换日期格式
            for item in completed_timeline + created_timeline:
                if item['date']:
                    item['date'] = item['date'].isoformat()

        return jsonify({
            'completed_timeline': completed_timeline,
            'created_timeline': created_timeline
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/queue/<int:task_id>/retry', methods=['POST'])
def retry_task(task_id):
    """重试失败的任务"""
    try:
        with queue_manager.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                UPDATE download_queue
                SET status = 'pending', retry_count = 0, last_error = NULL
                WHERE id = %s AND status = 'failed'
            """, (task_id,))

            if cursor.rowcount == 0:
                return jsonify({'error': 'Task not found or not in failed status'}), 404

        return jsonify({'message': 'Task retry scheduled', 'task_id': task_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/queue/<int:task_id>', methods=['DELETE'])
def delete_task(task_id):
    """删除任务"""
    try:
        with queue_manager.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                DELETE FROM download_queue
                WHERE id = %s
            """, (task_id,))

            if cursor.rowcount == 0:
                return jsonify({'error': 'Task not found'}), 404

        return jsonify({'message': 'Task deleted', 'task_id': task_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/datasets/search', methods=['GET'])
def search_datasets():
    """搜索 Hugging Face 数据集"""
    try:
        query = request.args.get('q', '')
        limit = int(request.args.get('limit', 20))

        if not query:
            return jsonify({'error': 'Query parameter q is required'}), 400

        # Hugging Face API 配置
        hf_endpoint = os.getenv('HF_ENDPOINT', 'https://hf-mirror.com')
        hf_token = os.getenv('HF_TOKEN', '')

        headers = {}
        if hf_token:
            headers['Authorization'] = f'Bearer {hf_token}'

        # 调用 Hugging Face API 搜索数据集
        search_url = f"{hf_endpoint}/api/datasets"
        params = {
            'search': query,
            'limit': limit,
            'full': 'true'
        }

        response = requests.get(search_url, headers=headers, params=params, timeout=30)
        response.raise_for_status()

        datasets = response.json()

        # 格式化返回数据
        formatted_datasets = []
        for dataset in datasets:
            formatted_datasets.append({
                'id': dataset.get('id', ''),
                'name': dataset.get('id', ''),
                'description': dataset.get('description', ''),
                'downloads': dataset.get('downloads', 0),
                'likes': dataset.get('likes', 0),
                'last_modified': dataset.get('lastModified', ''),
                'created_at': dataset.get('createdAt', ''),
                'tags': dataset.get('tags', []),
                'author': dataset.get('author', ''),
                'siblings': dataset.get('siblings', []),
                'card_data': dataset.get('cardData', {})
            })

        return jsonify({
            'datasets': formatted_datasets,
            'total': len(formatted_datasets),
            'query': query
        })

    except requests.RequestException as e:
        return jsonify({'error': f'Hugging Face API request failed: {str(e)}'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/queue/manual', methods=['POST'])
def create_manual_task():
    """手动创建下载任务"""
    try:
        data = request.get_json()

        if not data:
            return jsonify({'error': 'Request body is required'}), 400

        dataset_id = data.get('dataset_id')
        storage_path = data.get('storage_path', '')
        priority = data.get('priority', 0)

        if not dataset_id:
            return jsonify({'error': 'dataset_id is required'}), 400

        # 验证数据集是否存在
        hf_endpoint = os.getenv('HF_ENDPOINT', 'https://hf-mirror.com')
        hf_token = os.getenv('HF_TOKEN', '')

        headers = {}
        if hf_token:
            headers['Authorization'] = f'Bearer {hf_token}'

        dataset_url = f"{hf_endpoint}/api/datasets/{dataset_id}"
        response = requests.get(dataset_url, headers=headers, timeout=30)

        if response.status_code == 404:
            return jsonify({'error': f'Dataset {dataset_id} not found on Hugging Face'}), 404
        elif response.status_code != 200:
            return jsonify({'error': f'Hugging Face API error: {response.status_code}'}), 500

        # 添加任务到 MySQL 队列
        added = queue_manager.add_to_queue(dataset_id, priority, storage_path)

        if not added:
            # 检查任务状态
            existing_task = queue_manager.get_task_by_dataset_id(dataset_id)
            if existing_task:
                status = existing_task.get('status')
                if status in ('completed', 'downloading'):
                    return jsonify({'error': f'Dataset {dataset_id} is already in queue with status: {status}'}), 409
                else:
                    # 如果是 pending 或 failed，任务已更新
                    message = 'Task updated'
            else:
                return jsonify({'error': 'Failed to add task to queue'}), 500
        else:
            message = 'Task created'

        # 获取任务ID
        task = queue_manager.get_task_by_dataset_id(dataset_id)

        # 发送 RabbitMQ 消息通知消费者
        try:
            credentials = pika.PlainCredentials(RABBITMQ_CONFIG['user'], RABBITMQ_CONFIG['password'])
            parameters = pika.ConnectionParameters(
                host=RABBITMQ_CONFIG['host'],
                port=RABBITMQ_CONFIG['port'],
                virtual_host=RABBITMQ_CONFIG['vhost'],
                credentials=credentials
            )

            connection = pika.BlockingConnection(parameters)
            channel = connection.channel()

            # 确保队列存在
            channel.queue_declare(
                queue=RABBITMQ_CONFIG['queue_name'],
                durable=True,
                arguments={
                    'x-dead-letter-exchange': '',
                    'x-dead-letter-routing-key': RABBITMQ_CONFIG['dlq_name']
                }
            )

            # 发送消息
            message_body = {
                'dataset_id': dataset_id,
                'priority': priority,
                'storage_path': storage_path,
                'created_at': datetime.now().isoformat(),
                'manual': True
            }

            channel.basic_publish(
                exchange='',
                routing_key=RABBITMQ_CONFIG['queue_name'],
                body=json.dumps(message_body),
                properties=pika.BasicProperties(
                    delivery_mode=2,  # 持久化消息
                    content_type='application/json',
                    timestamp=int(time.time())
                )
            )

            connection.close()

        except Exception as e:
            # RabbitMQ 失败不影响任务创建，只是消费者不会立即处理
            print(f"Warning: Failed to send RabbitMQ message: {e}")

        return jsonify({
            'message': message,
            'task_id': task['id'] if task else None,
            'dataset_id': dataset_id
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    host = os.getenv('MONITOR_HOST', '0.0.0.0')
    port = int(os.getenv('MONITOR_PORT', 8080))
    app.run(host=host, port=port, debug=False)
