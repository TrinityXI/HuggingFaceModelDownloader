import logging
import json
import requests
from datetime import datetime, timedelta
from typing import Dict, List

# Assuming running from backend root
from lib.query_datasets_by_date import HuggingFaceDatasetQuery
from app.crud.task import task_crud
from app.crud.dataset import dataset_crud
from app.core.config import settings

logger = logging.getLogger(__name__)

class ScannerService:
    def __init__(self):
        self.query = HuggingFaceDatasetQuery(endpoint=settings.HF_ENDPOINT, token=settings.HF_TOKEN)
        
        # Current config state
        self.config = {
            'producer_interval': settings.DEFAULT_PRODUCER_INTERVAL,
            'producer_days': settings.DEFAULT_PRODUCER_DAYS,
            'producer_limit': settings.DEFAULT_PRODUCER_LIMIT,
            'producer_timezone_offset': settings.DEFAULT_PRODUCER_TIMEZONE_OFFSET,
            'producer_use_created_at': settings.DEFAULT_PRODUCER_USE_CREATED_AT,
            'producer_auto_limit': settings.DEFAULT_PRODUCER_AUTO_LIMIT,
            'hf_endpoint': settings.HF_ENDPOINT
        }

    def update_config(self, new_config: Dict):
        self.config.update(new_config)
        # Update query endpoint if changed
        if new_config.get('hf_endpoint') and new_config['hf_endpoint'] != self.query.endpoint:
            self.query = HuggingFaceDatasetQuery(endpoint=new_config['hf_endpoint'], token=settings.HF_TOKEN)

    def get_config(self):
        return self.config

    def scan_datasets(self):
        try:
            days = self.config['producer_days']
            target_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            logger.info(f"Scanning datasets: Date {target_date}, Past {days} days")

            datasets = self.query.get_datasets_by_date(
                target_date=target_date,
                limit=self.config['producer_limit'],
                timezone_offset=self.config['producer_timezone_offset'],
                use_created_at=self.config['producer_use_created_at'],
                auto_limit=self.config['producer_auto_limit']
            )

            valid_datasets = []
            for dataset in datasets:
                if isinstance(dataset, dict):
                    dataset_info = {
                        'id': dataset.get('id', ''),
                        'dataset_id': dataset.get('id', ''),
                        'name': dataset.get('id', ''),
                        'description': dataset.get('description', ''),
                        'downloads': dataset.get('downloads', 0),
                        'likes': dataset.get('likes', 0),
                        'last_modified': dataset.get('lastModified', ''),
                        'created_at': dataset.get('createdAt', ''),
                        'tags': dataset.get('tags', []),
                        'author': dataset.get('author', ''),
                        'created_at_producer': datetime.now().isoformat(),
                        'priority': self._calculate_priority(dataset)
                    }

                    if dataset_info['downloads'] >= 0 and dataset_info['likes'] >= 0:
                        valid_datasets.append(dataset_info)

            logger.info(f"Scan complete, found {len(valid_datasets)} valid datasets")
            return valid_datasets

        except Exception as e:
            logger.error(f"Error scanning datasets: {e}")
            return []

    def _calculate_priority(self, dataset):
        priority = 0
        downloads = dataset.get('downloads', 0)
        if downloads > 10000: priority += 3
        elif downloads > 1000: priority += 2
        elif downloads > 100: priority += 1

        likes = dataset.get('likes', 0)
        if likes > 100: priority += 2
        elif likes > 10: priority += 1

        tags = dataset.get('tags', [])
        popular_tags = ['text-classification', 'text-generation', 'translation',
                       'question-answering', 'summarization', 'sentiment-analysis']
        for tag in tags:
            if tag in popular_tags:
                priority += 1
                break
        return priority

    def add_datasets_to_queue(self, datasets):
        success_count = 0
        skipped_count = 0

        for dataset in datasets:
            try:
                dataset_id = dataset.get('dataset_id')
                priority = dataset.get('priority', 0)

                # Check existing in queue
                existing = task_crud.get_by_dataset_id(dataset_id)
                if existing:
                    status = existing.get('status')
                    if status in ('completed', 'downloading', 'pending'):
                        skipped_count += 1
                        continue

                # Save metadata
                dataset_crud.upsert(dataset)

                # Add to queue
                added = task_crud.add_to_queue(dataset_id, priority)

                if added:
                    success_count += 1
                else:
                    skipped_count += 1

            except Exception as e:
                logger.error(f"Failed to process dataset {dataset.get('dataset_id')}: {e}")

        logger.info(f"Processing complete: Success {success_count}/{len(datasets)}, Skipped {skipped_count}")
        return success_count, skipped_count

    def scan_and_enqueue(self):
        datasets = self.scan_datasets()
        if not datasets:
            return 0, 0
        return self.add_datasets_to_queue(datasets)
    
    def search_remote_datasets(self, query, limit=20):
        headers = {}
        if settings.HF_TOKEN:
            headers['Authorization'] = f'Bearer {settings.HF_TOKEN}'

        search_url = f"{self.config['hf_endpoint']}/api/datasets"
        params = {
            'search': query,
            'limit': limit,
            'full': 'true'
        }

        response = requests.get(search_url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        datasets = response.json()

        formatted = []
        for d in datasets:
            formatted.append({
                'id': d.get('id', ''),
                'name': d.get('id', ''),
                'description': d.get('description', ''),
                'downloads': d.get('downloads', 0),
                'likes': d.get('likes', 0),
                'last_modified': d.get('lastModified', ''),
                'created_at': d.get('createdAt', ''),
                'tags': d.get('tags', []),
                'author': d.get('author', ''),
            })
        return formatted

scanner_service = ScannerService()
