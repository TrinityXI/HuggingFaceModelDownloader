import os
from dotenv import load_dotenv

# Load .env file
# Try to find .env in various locations
base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
deploy_env = os.path.join(base_dir, 'deploy', '.env')
root_env = os.path.join(base_dir, '.env')

if os.path.exists(deploy_env):
    load_dotenv(deploy_env)
elif os.path.exists(root_env):
    load_dotenv(root_env)

class Config:
    # Service Config
    HOST = os.getenv('PRODUCER_HOST', '0.0.0.0')
    PORT = int(os.getenv('PRODUCER_PORT', 8000))
    LOG_DIR = '/app/logs'
    
    # MySQL
    MYSQL_HOST = os.getenv('MYSQL_HOST', 'localhost')
    MYSQL_PORT = int(os.getenv('MYSQL_PORT', 3306))
    MYSQL_USER = os.getenv('MYSQL_USER', 'root')
    MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', '')
    MYSQL_DATABASE = os.getenv('MYSQL_DATABASE', 'hf_datasets')
    
    # Redis
    REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
    REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
    REDIS_DB = int(os.getenv('REDIS_DB', 0))
    REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', None)
    REDIS_CONFIG_KEY = os.getenv('REDIS_CONFIG_KEY', 'hf_producer_config')
    REDIS_TRIGGER_KEY = 'hf_producer_trigger_scan'
    
    # RabbitMQ
    RABBITMQ_HOST = os.getenv('RABBITMQ_HOST', 'localhost')
    RABBITMQ_PORT = int(os.getenv('RABBITMQ_PORT', 5672))
    RABBITMQ_USER = os.getenv('RABBITMQ_USER', 'guest')
    RABBITMQ_PASSWORD = os.getenv('RABBITMQ_PASSWORD', 'guest')
    RABBITMQ_VHOST = os.getenv('RABBITMQ_VHOST', '/')
    RABBITMQ_QUEUE_NAME = os.getenv('RABBITMQ_QUEUE_NAME', 'hf_download_queue')
    RABBITMQ_DLQ_NAME = os.getenv('RABBITMQ_DLQ_NAME', 'hf_download_dlq')
    RABBITMQ_EVENT_EXCHANGE = os.getenv('RABBITMQ_EVENT_EXCHANGE', 'download_events')
    RABBITMQ_EVENT_QUEUE = os.getenv('RABBITMQ_EVENT_QUEUE', 'producer_events')
    
    # Hugging Face
    HF_ENDPOINT = os.getenv('HF_ENDPOINT', 'https://hf-mirror.com')
    HF_TOKEN = os.getenv('HF_TOKEN', '')
    
    # Feishu
    FEISHU_WEBHOOK_URL = os.getenv('FEISHU_WEBHOOK_URL', '')
    FEISHU_SECRET = os.getenv('FEISHU_SECRET', '')
    FEISHU_APP_ID = os.getenv('FEISHU_APP_ID', '')
    FEISHU_APP_SECRET = os.getenv('FEISHU_APP_SECRET', '')
    FEISHU_ENCRYPT_KEY = os.getenv('FEISHU_ENCRYPT_KEY', '')
    FEISHU_VERIFICATION_TOKEN = os.getenv('FEISHU_VERIFICATION_TOKEN', '')

    # LLM Agent Configuration
    LLM_MODEL = os.getenv('LLM_MODEL', 'gpt-4o')
    LLM_API_KEY = os.getenv('LLM_API_KEY', '')
    LLM_BASE_URL = os.getenv('LLM_BASE_URL', '')
    LLM_TEMPERATURE = float(os.getenv('LLM_TEMPERATURE', '0.1'))
    LLM_MAX_TOKENS = int(os.getenv('LLM_MAX_TOKENS', '2000'))
    AGENT_ENABLED = os.getenv('AGENT_ENABLED', 'true').lower() == 'true'

    # Defaults
    DEFAULT_PRODUCER_INTERVAL = int(os.getenv('PRODUCER_INTERVAL', 3600))
    DEFAULT_PRODUCER_DAYS = int(os.getenv('PRODUCER_DAYS', 7))
    DEFAULT_PRODUCER_LIMIT = int(os.getenv('PRODUCER_LIMIT', 50))
    DEFAULT_PRODUCER_TIMEZONE_OFFSET = int(os.getenv('PRODUCER_TIMEZONE_OFFSET', 8))
    DEFAULT_PRODUCER_USE_CREATED_AT = os.getenv('PRODUCER_USE_CREATED_AT', 'false').lower() == 'true'
    DEFAULT_PRODUCER_AUTO_LIMIT = os.getenv('PRODUCER_AUTO_LIMIT', 'true').lower() == 'true'

settings = Config()
