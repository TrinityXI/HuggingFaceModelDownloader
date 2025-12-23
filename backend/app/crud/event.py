import json
from typing import Dict, Optional
from app.crud.base import db

class EventCRUD:
    def log(self, dataset_id: str, event_type: str, message: str = "", metadata: Optional[Dict] = None):
        with db.get_connection() as conn:
            cursor = conn.cursor()
            metadata_json = json.dumps(metadata) if metadata else None
            cursor.execute("""
                INSERT INTO download_events (dataset_id, event_type, message, metadata)
                VALUES (%s, %s, %s, %s)
            """, (dataset_id, event_type, message, metadata_json))

    def get_by_dataset(self, dataset_id: str, limit: int = 50):
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, event_type, message, metadata, created_at
                FROM download_events
                WHERE dataset_id = %s
                ORDER BY created_at DESC
                LIMIT %s
            """, (dataset_id, limit))
            return cursor.fetchall()

event_crud = EventCRUD()
