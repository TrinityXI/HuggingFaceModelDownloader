import json
import time
import logging
from datetime import datetime
from threading import Thread
import pika

from app.core.config import settings
from app.crud.task import task_crud
from app.crud.dataset import dataset_crud
from app.crud.event import event_crud

logger = logging.getLogger(__name__)

class RabbitMQService:
    def __init__(self):
        self.connection = None
        self.channel = None
        self.event_connection = None
        self.event_channel = None

    def connect(self):
        try:
            credentials = pika.PlainCredentials(settings.RABBITMQ_USER, settings.RABBITMQ_PASSWORD)
            parameters = pika.ConnectionParameters(
                host=settings.RABBITMQ_HOST,
                port=settings.RABBITMQ_PORT,
                virtual_host=settings.RABBITMQ_VHOST,
                credentials=credentials,
                heartbeat=600,
                blocked_connection_timeout=300
            )

            self.connection = pika.BlockingConnection(parameters)
            self.channel = self.connection.channel()
            self.channel.basic_qos(prefetch_count=2)

            self.channel.queue_declare(
                queue=settings.RABBITMQ_QUEUE_NAME,
                durable=True,
                arguments={
                    'x-dead-letter-exchange': '',
                    'x-dead-letter-routing-key': settings.RABBITMQ_DLQ_NAME
                }
            )

            self.channel.queue_declare(queue=settings.RABBITMQ_DLQ_NAME, durable=True)
            self.channel.exchange_declare(exchange=settings.RABBITMQ_EVENT_EXCHANGE, exchange_type='topic', durable=True)
            self.channel.queue_declare(queue=settings.RABBITMQ_EVENT_QUEUE, durable=True)
            self.channel.queue_bind(exchange=settings.RABBITMQ_EVENT_EXCHANGE, queue=settings.RABBITMQ_EVENT_QUEUE, routing_key='download.*')

            logger.info(f"Connected to RabbitMQ: {settings.RABBITMQ_HOST}:{settings.RABBITMQ_PORT}")
            return True

        except Exception as e:
            logger.error(f"Failed to connect to RabbitMQ: {e}")
            return False

    def disconnect(self):
        try:
            if self.connection and not self.connection.is_closed:
                self.connection.close()
                logger.info("RabbitMQ connection closed")
        except Exception as e:
            logger.error(f"Error closing RabbitMQ connection: {e}")

    def send_message(self, message):
        try:
            if not self.channel or self.channel.is_closed:
                if not self.connect():
                    return False

            self.channel.basic_publish(
                exchange='',
                routing_key=settings.RABBITMQ_QUEUE_NAME,
                body=json.dumps(message),
                properties=pika.BasicProperties(
                    delivery_mode=2,
                    content_type='application/json',
                    timestamp=int(time.time())
                )
            )
            logger.info(f"Message sent: {message.get('dataset_id', 'Unknown')}")
            return True
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            return False

    def get_queue_stats(self):
        try:
            if not self.channel or self.channel.is_closed:
                if not self.connect():
                    return {'error': 'Not connected'}

            queue_info = self.channel.queue_declare(queue=settings.RABBITMQ_QUEUE_NAME, passive=True, durable=True)
            queue_length = queue_info.method.message_count

            dlq_info = self.channel.queue_declare(queue=settings.RABBITMQ_DLQ_NAME, passive=True, durable=True)
            dlq_length = dlq_info.method.message_count

            return {
                'queue_length': queue_length,
                'dlq_length': dlq_length
            }
        except Exception as e:
            logger.error(f"Failed to get RabbitMQ stats: {e}")
            return {'error': str(e)}

    def dispatch_tasks(self):
        try:
            if not self.channel or self.channel.is_closed:
                if not self.connect():
                    return

            try:
                queue_state = self.channel.queue_declare(queue=settings.RABBITMQ_QUEUE_NAME, passive=True)
                message_count = queue_state.method.message_count
                consumer_count = queue_state.method.consumer_count
            except Exception as e:
                logger.warning(f"Failed to get queue state: {e}")
                return

            if consumer_count == 0:
                return

            prefetch_count = 2
            target_depth = consumer_count * prefetch_count
            needed = target_depth - message_count

            if needed <= 0:
                return

            batch_size = min(needed, 10)
            tasks = task_crud.fetch_tasks_batch(limit=batch_size)

            if not tasks:
                return

            logger.info(f"Dispatching tasks: Queue={message_count}, Consumers={consumer_count}, Needed={needed}, Fetched={len(tasks)}")

            sent_count = 0
            for task in tasks:
                dataset_info = {
                    'dataset_id': task['dataset_id'],
                    'storage_path': task.get('storage_path', ''),
                    'priority': task['priority'],
                    'retry_count': task['retry_count']
                }
                
                # Add tar config if enabled
                if task.get('tar_enabled'):
                    dataset_info['tar_config'] = {
                        'enabled': True,
                        'compress': task.get('tar_compress', True),
                        'split_size': task.get('tar_split_size', '50GiB'),
                        'split_threshold': task.get('tar_split_threshold', '100GiB'),
                        'delete_source': task.get('tar_delete_source', False)
                    }

                if self.send_message(dataset_info):
                    sent_count += 1
                else:
                    task_crud.update_status(task['id'], 'pending')
                    logger.error(f"Failed to send message, rolled back: {task['dataset_id']}")

            logger.info(f"Successfully dispatched {sent_count}/{len(tasks)} tasks")

        except Exception as e:
            logger.error(f"Error dispatching tasks: {e}")

    def handle_download_event(self, ch, method, properties, body):
        try:
            event = json.loads(body)
            event_type = event.get('event_type')
            dataset_id = event.get('dataset_id')
            message = event.get('message', '')
            metadata = event.get('metadata', {})

            logger.info(f"Received event: {event_type} - {dataset_id}")

            task = task_crud.get_by_dataset_id(dataset_id)
            if not task:
                logger.debug(f"Skipping event (task not found): {dataset_id}")
                ch.basic_ack(delivery_tag=method.delivery_tag)
                return

            if event_type == 'start':
                task_crud.update_status(task['id'], 'downloading')
                event_crud.log(dataset_id, 'start', message, metadata)

            elif event_type == 'complete':
                storage_path = metadata.get('storage_path', '')
                task_crud.update_status(task['id'], 'completed', storage_path=storage_path)
                event_crud.log(dataset_id, 'complete', message, metadata)
                self._create_dataset_record(dataset_id, metadata)

            elif event_type == 'fail':
                task_crud.update_status(task['id'], 'failed', message)
                event_crud.log(dataset_id, 'fail', message, metadata)

            elif event_type == 'retry':
                task_crud.increment_retry(task['id'], 10, message)
                event_crud.log(dataset_id, 'retry', message, metadata)

            ch.basic_ack(delivery_tag=method.delivery_tag)

        except Exception as e:
            logger.error(f"Failed to handle event: {e}")
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    def _create_dataset_record(self, dataset_id, metadata):
        try:
            author, name = dataset_id.split('/', 1) if '/' in dataset_id else ('', dataset_id)
            dataset = {
                'id': dataset_id,
                'author': author,
                'name': name,
                'createdAt': metadata.get('created_at'),
                'lastModified': metadata.get('last_modified', datetime.now().isoformat()),
                'downloads': metadata.get('downloads', 0),
                'likes': metadata.get('likes', 0),
                'tags': metadata.get('tags', []),
            }
            dataset_crud.upsert(dataset)
        except Exception as e:
            logger.error(f"Failed to create dataset record: {e}")

    def start_event_listener(self):
        def listener_thread():
            try:
                credentials = pika.PlainCredentials(settings.RABBITMQ_USER, settings.RABBITMQ_PASSWORD)
                parameters = pika.ConnectionParameters(
                    host=settings.RABBITMQ_HOST,
                    port=settings.RABBITMQ_PORT,
                    virtual_host=settings.RABBITMQ_VHOST,
                    credentials=credentials,
                    heartbeat=600,
                    blocked_connection_timeout=300
                )
                self.event_connection = pika.BlockingConnection(parameters)
                self.event_channel = self.event_connection.channel()
                self.event_channel.queue_declare(queue=settings.RABBITMQ_EVENT_QUEUE, durable=True)
                self.event_channel.basic_qos(prefetch_count=1)
                self.event_channel.basic_consume(
                    queue=settings.RABBITMQ_EVENT_QUEUE,
                    on_message_callback=self.handle_download_event,
                    auto_ack=False
                )
                logger.info(f"Event listener started on queue: {settings.RABBITMQ_EVENT_QUEUE}")
                self.event_channel.start_consuming()
            except KeyboardInterrupt:
                logger.info("Event listener received stop signal")
                if self.event_channel:
                    self.event_channel.stop_consuming()
            except Exception as e:
                logger.error(f"Event listener error: {e}")
            finally:
                if self.event_connection and not self.event_connection.is_closed:
                    try:
                        self.event_connection.close()
                    except:
                        pass
        
        listener = Thread(target=listener_thread, daemon=True)
        listener.start()
        logger.info("Event listener thread started")
        return listener

rabbitmq_service = RabbitMQService()
