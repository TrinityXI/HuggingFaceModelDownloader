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
from datetime import datetime, timedelta
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
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
        
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
        with get_db_connection() as conn:
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
        
        with get_db_connection() as conn:
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
        with get_db_connection() as conn:
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
        
        with get_db_connection() as conn:
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
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE download_queue
                SET status = 'pending', retry_count = 0, last_error = NULL
                WHERE id = %s AND status = 'failed'
            """, (task_id,))
            
            conn.commit()
            
            if cursor.rowcount == 0:
                return jsonify({'error': 'Task not found or not in failed status'}), 404
        
        return jsonify({'message': 'Task retry scheduled', 'task_id': task_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/queue/<int:task_id>', methods=['DELETE'])
def delete_task(task_id):
    """删除任务"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                DELETE FROM download_queue
                WHERE id = %s
            """, (task_id,))
            
            conn.commit()
            
            if cursor.rowcount == 0:
                return jsonify({'error': 'Task not found'}), 404
        
        return jsonify({'message': 'Task deleted', 'task_id': task_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    host = os.getenv('MONITOR_HOST', '0.0.0.0')
    port = int(os.getenv('MONITOR_PORT', 8080))
    app.run(host=host, port=port, debug=False)
