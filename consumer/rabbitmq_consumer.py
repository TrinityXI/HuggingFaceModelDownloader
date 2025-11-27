#!/usr/bin/env python3
"""
RabbitMQ 消费者服务
从 RabbitMQ 队列接收消息并处理下载任务
"""

import json
import time
import logging
import os
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import pika

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/app/logs/rabbitmq_consumer.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class RabbitMQConsumer:
    def __init__(self):
        self.rabbitmq_host = os.getenv('RABBITMQ_HOST', 'localhost')
        self.rabbitmq_port = int(os.getenv('RABBITMQ_PORT', 5672))
        self.rabbitmq_user = os.getenv('RABBITMQ_USER', 'admin')
        self.rabbitmq_password = os.getenv('RABBITMQ_PASSWORD', 'password123')
        self.rabbitmq_vhost = os.getenv('RABBITMQ_VHOST', '/')
        self.queue_name = os.getenv('RABBITMQ_QUEUE_NAME', 'hf_download_queue')
        self.dlq_name = os.getenv('RABBITMQ_DLQ_NAME', 'hf_download_dlq')

        # 消费者配置
        self.consumer_workers = int(os.getenv('CONSUMER_WORKERS', 4))
        self.consumer_max_retries = int(os.getenv('CONSUMER_MAX_RETRIES', 3))
        self.consumer_timeout = int(os.getenv('CONSUMER_TIMEOUT', 3600))

        # 下载器配置
        self.hf_endpoint = os.getenv('HF_ENDPOINT', 'https://huggingface.co')
        self.hf_token = os.getenv('HF_TOKEN', '')
        self.output_dir = os.getenv('OUTPUT_DIR', '/datasets')
        self.go_binary_path = os.getenv('GO_BINARY_PATH', '/app/hfdownloader')

        # RabbitMQ 连接
        self.connection = None
        self.channel = None
        self.running = False

        # 线程池
        self.executor = ThreadPoolExecutor(max_workers=self.consumer_workers)

    def connect_rabbitmq(self):
        """连接到 RabbitMQ"""
        try:
            credentials = pika.PlainCredentials(self.rabbitmq_user, self.rabbitmq_password)
            parameters = pika.ConnectionParameters(
                host=self.rabbitmq_host,
                port=self.rabbitmq_port,
                virtual_host=self.rabbitmq_vhost,
                credentials=credentials,
                heartbeat=600,
                blocked_connection_timeout=300
            )

            self.connection = pika.BlockingConnection(parameters)
            self.channel = self.connection.channel()

            # 设置 QoS，控制并发处理数量
            self.channel.basic_qos(prefetch_count=self.consumer_workers)

            # 声明队列
            self.channel.queue_declare(
                queue=self.queue_name,
                durable=True,
                arguments={
                    'x-dead-letter-exchange': '',
                    'x-dead-letter-routing-key': self.dlq_name
                }
            )

            self.channel.queue_declare(
                queue=self.dlq_name,
                durable=True
            )

            logger.info(f"成功连接到 RabbitMQ: {self.rabbitmq_host}:{self.rabbitmq_port}")
            return True

        except Exception as e:
            logger.error(f"连接 RabbitMQ 失败: {e}")
            return False

    def disconnect_rabbitmq(self):
        """断开 RabbitMQ 连接"""
        self.running = False
        try:
            if self.connection and not self.connection.is_closed:
                self.connection.close()
                logger.info("RabbitMQ 连接已关闭")
        except Exception as e:
            logger.error(f"关闭 RabbitMQ 连接时出错: {e}")

    def download_dataset(self, dataset_info):
        """下载数据集"""
        dataset_id = dataset_info.get('dataset_id', 'unknown')
        logger.info(f"开始下载数据集: {dataset_id}")

        try:
            # 构建输出路径
            safe_dataset_id = dataset_id.replace('/', '_')
            output_path = os.path.join(self.output_dir, safe_dataset_id)
            
            # 构建下载命令 (使用 hfdownloader v2.0 的新 CLI 参数)
            cmd = [
                self.go_binary_path,
                'download',
                '--dataset',
                '--repo', dataset_id,
                '--output', output_path,
                '--endpoint', self.hf_endpoint
            ]
            
            # 添加 token（如果有）
            if self.hf_token:
                cmd.extend(['--token', self.hf_token])
            
            # 打印命令用于调试
            logger.info(f"执行命令: {' '.join(cmd)}")

            # 执行下载
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.consumer_timeout
            )

            if result.returncode == 0:
                logger.info(f"下载成功: {dataset_id}")
                return True, "下载成功"
            else:
                error_msg = f"下载失败: {result.stderr}"
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

    def process_message(self, ch, method, properties, body):
        """处理单个消息"""
        try:
            # 解析消息
            message = json.loads(body)
            dataset_info = message

            dataset_id = dataset_info.get('dataset_id', 'unknown')
            logger.info(f"收到下载任务: {dataset_id}")

            # 执行下载
            success, message = self.download_dataset(dataset_info)

            if success:
                # 确认消息
                ch.basic_ack(delivery_tag=method.delivery_tag)
                logger.info(f"任务完成并确认: {dataset_id}")
            else:
                # 检查重试次数
                retry_count = dataset_info.get('retry_count', 0)
                if retry_count < self.consumer_max_retries:
                    # 重新入队进行重试
                    dataset_info['retry_count'] = retry_count + 1
                    dataset_info['last_error'] = message

                    ch.basic_publish(
                        exchange='',
                        routing_key=self.queue_name,
                        body=json.dumps(dataset_info),
                        properties=pika.BasicProperties(
                            delivery_mode=2,
                            content_type='application/json',
                            headers={
                                'x-retry-count': retry_count + 1
                            }
                        )
                    )
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                    logger.warning(f"任务重试 {retry_count + 1}/{self.consumer_max_retries}: {dataset_id}")
                else:
                    # 发送到死信队列
                    dataset_info['final_error'] = message
                    dataset_info['failed_at'] = time.time()

                    ch.basic_publish(
                        exchange='',
                        routing_key=self.dlq_name,
                        body=json.dumps(dataset_info),
                        properties=pika.BasicProperties(
                            delivery_mode=2,
                            content_type='application/json'
                        )
                    )
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                    logger.error(f"任务失败并进入死信队列: {dataset_id}")

        except json.JSONDecodeError:
            logger.error("消息格式错误，拒绝消息")
            ch.basic_reject(delivery_tag=method.delivery_tag, requeue=False)
        except Exception as e:
            logger.error(f"处理消息时出错: {e}")
            ch.basic_reject(delivery_tag=method.delivery_tag, requeue=True)

    def start_consuming(self):
        """开始消费消息"""
        try:
            # 设置消息处理回调
            self.channel.basic_consume(
                queue=self.queue_name,
                on_message_callback=self.process_message,
                auto_ack=False
            )

            logger.info(f"开始消费消息，工作线程数: {self.consumer_workers}")
            logger.info(f"按 Ctrl+C 停止消费")

            self.running = True
            self.channel.start_consuming()

        except Exception as e:
            logger.error(f"消费消息时出错: {e}")
            raise

    def stop_consuming(self):
        """停止消费消息"""
        self.running = False
        try:
            if self.channel and self.channel.is_open:
                self.channel.stop_consuming()
                logger.info("已停止消费消息")
        except Exception as e:
            logger.error(f"停止消费时出错: {e}")

    def run(self):
        """运行消费者"""
        logger.info("启动 RabbitMQ 消费者")

        # 连接 RabbitMQ
        if not self.connect_rabbitmq():
            logger.error("无法连接到 RabbitMQ，退出")
            return

        try:
            self.start_consuming()
        except KeyboardInterrupt:
            logger.info("收到中断信号，停止消费者")
        except Exception as e:
            logger.error(f"消费者运行出错: {e}")
        finally:
            self.stop_consuming()
            self.disconnect_rabbitmq()
            self.executor.shutdown(wait=True)

    def __del__(self):
        """析构函数，确保资源清理"""
        self.disconnect_rabbitmq()
        try:
            self.executor.shutdown(wait=False)
        except:
            pass

def main():
    """主函数"""
    consumer = RabbitMQConsumer()
    consumer.run()

if __name__ == '__main__':
    main()