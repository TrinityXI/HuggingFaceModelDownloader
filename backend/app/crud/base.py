import logging
import pymysql
from contextlib import contextmanager
from app.core.config import settings

logger = logging.getLogger(__name__)

class DBConnection:
    def __init__(self):
        self.config = {
            'host': settings.MYSQL_HOST,
            'port': settings.MYSQL_PORT,
            'user': settings.MYSQL_USER,
            'password': settings.MYSQL_PASSWORD,
            'database': settings.MYSQL_DATABASE,
            'charset': 'utf8mb4',
            'cursorclass': pymysql.cursors.DictCursor
        }

    @contextmanager
    def get_connection(self):
        """Get database connection context manager"""
        conn = pymysql.connect(**self.config)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_db(self):
        """Initialize database tables"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Create download queue table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS download_queue (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    dataset_id VARCHAR(255) UNIQUE NOT NULL,
                    priority INT DEFAULT 0,
                    status ENUM('pending', 'downloading', 'completed', 'failed') DEFAULT 'pending',
                    retry_count INT DEFAULT 0,
                    last_error TEXT,
                    storage_path VARCHAR(512),
                    progress_percentage DECIMAL(5,2) DEFAULT 0.00,
                    downloaded_bytes BIGINT DEFAULT 0,
                    total_bytes BIGINT DEFAULT 0,
                    total_files INT DEFAULT 0,
                    completed_files INT DEFAULT 0,
                    download_speed DECIMAL(15,2) DEFAULT 0.00,
                    progress_status VARCHAR(32) DEFAULT 'pending',
                    tar_enabled BOOLEAN DEFAULT FALSE,
                    tar_compress BOOLEAN DEFAULT TRUE,
                    tar_split_size VARCHAR(32) DEFAULT '50GiB',
                    tar_split_threshold VARCHAR(32) DEFAULT '100GiB',
                    tar_delete_source BOOLEAN DEFAULT FALSE,
                    repo_type ENUM('dataset', 'model') DEFAULT 'dataset',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    started_at TIMESTAMP NULL,
                    completed_at TIMESTAMP NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    INDEX idx_status_priority (status, priority DESC),
                    INDEX idx_status (status),
                    INDEX idx_dataset_id (dataset_id),
                    INDEX idx_created_at (created_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)

            # Migration: add repo_type column if it doesn't exist (for existing tables)
            # NOTE: MySQL 8.0 does NOT support ADD COLUMN IF NOT EXISTS (MariaDB only)
            cursor.execute("""
                SELECT COUNT(*) as cnt
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'download_queue'
                  AND COLUMN_NAME = 'repo_type'
            """)
            if cursor.fetchone()['cnt'] == 0:
                cursor.execute("""
                    ALTER TABLE download_queue
                    ADD COLUMN repo_type ENUM('dataset', 'model') DEFAULT 'dataset'
                """)
                logger.info("Migration: added repo_type column to download_queue")
            
            # Create download events table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS download_events (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    dataset_id VARCHAR(255) NOT NULL,
                    event_type ENUM('start', 'complete', 'fail', 'retry') NOT NULL,
                    message TEXT,
                    metadata JSON,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_dataset_id (dataset_id),
                    INDEX idx_event_type (event_type),
                    INDEX idx_created_at (created_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)

            # Create datasets metadata table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS datasets (
                    id VARCHAR(255) PRIMARY KEY,
                    author VARCHAR(255),
                    name VARCHAR(255),
                    downloads INT DEFAULT 0,
                    likes INT DEFAULT 0,
                    last_modified DATETIME,
                    created_at_hf DATETIME,
                    tags JSON,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    INDEX idx_downloads (downloads),
                    INDEX idx_likes (likes),
                    INDEX idx_last_modified (last_modified)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)

db = DBConnection()
