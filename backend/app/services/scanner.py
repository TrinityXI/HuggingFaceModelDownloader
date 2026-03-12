import logging
import json
import math
import requests
from datetime import datetime, timedelta, timezone
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
            'producer_trend_sort': True,
            'producer_recency_half_life': 30,
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
                auto_limit=self.config['producer_auto_limit'],
                days=days,
                post_sort="trendingScore" if self.config.get('producer_trend_sort', True) else "downloads"
            )

            # 先按下载量降序，确保高热度数据集优先进入队列
            datasets.sort(key=lambda d: d.get('downloads') or 0, reverse=True)

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
                        'trending_score': dataset.get('trendingScore', 0),
                        'last_modified': dataset.get('lastModified', ''),
                        'created_at': dataset.get('createdAt', ''),
                        'tags': dataset.get('tags', []),
                        'author': dataset.get('author', ''),
                        'created_at_producer': datetime.now().isoformat(),
                        'priority': self._calculate_priority(dataset)
                    }

                    if dataset_info['downloads'] >= 0 and dataset_info['likes'] >= 0:
                        valid_datasets.append(dataset_info)

            # 热门度 + 时间衰减混合排序
            if self.config.get('producer_trend_sort', True) and valid_datasets:
                valid_datasets = self._apply_trend_sort(
                    valid_datasets,
                    recency_half_life=self.config.get('producer_recency_half_life', 30)
                )
                logger.info("Applied trend sort (popularity × recency)")

            logger.info(f"Scan complete, found {len(valid_datasets)} valid datasets")
            return valid_datasets

        except Exception as e:
            logger.error(f"Error scanning datasets: {e}")
            return []

    def _apply_trend_sort(self, datasets: List[Dict], recency_half_life: int = 30) -> List[Dict]:
        """排序优先级: 原生 trendingScore > 本地计算 popularity×recency

        如果数据中包含 HF 原生 trendingScore 字段（非零），直接按它降序排序。
        否则回落到本地公式:
            score = (log(1+downloads)*0.6 + log(1+likes)*0.4) * exp(-days_old/half_life)
        """
        # 如果大多数条目有原生 trendingScore 字段，直接用它
        has_native = sum(1 for d in datasets if (d.get('trending_score') or 0) > 0)
        if has_native > len(datasets) * 0.3:
            return sorted(datasets, key=lambda d: d.get('trending_score') or 0, reverse=True)

        # 回落本地计算
        now_utc = datetime.now(timezone.utc)

        def _score(ds: Dict) -> float:
            downloads = ds.get('downloads') or 0
            likes = ds.get('likes') or 0
            popularity = math.log1p(downloads) * 0.6 + math.log1p(likes) * 0.4
            time_str = ds.get('last_modified') or ds.get('created_at')
            if time_str:
                try:
                    mod_time = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
                    if mod_time.tzinfo is None:
                        mod_time = mod_time.replace(tzinfo=timezone.utc)
                    days_old = max(0.0, (now_utc - mod_time).total_seconds() / 86400)
                    recency = math.exp(-days_old / max(recency_half_life, 1))
                except Exception:
                    recency = 0.0
            else:
                recency = 0.0
            return popularity * recency

        return sorted(datasets, key=_score, reverse=True)

    def _calculate_priority(self, dataset):
        priority = 0

        # HF 原生 trendingScore 优先级权重（最高 +4）
        trending = dataset.get('trendingScore', 0) or 0
        if trending > 100: priority += 4
        elif trending > 50: priority += 3
        elif trending > 10: priority += 2
        elif trending > 0: priority += 1

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
                'trending_score': d.get('trendingScore', 0),
                'last_modified': d.get('lastModified', ''),
                'created_at': d.get('createdAt', ''),
                'tags': d.get('tags', []),
                'author': d.get('author', ''),
            })
        return formatted

    def search_remote_models(self, query, limit=20):
        headers = {}
        if settings.HF_TOKEN:
            headers['Authorization'] = f'Bearer {settings.HF_TOKEN}'

        search_url = f"{self.config['hf_endpoint']}/api/models"
        params = {
            'search': query,
            'limit': limit,
            'full': 'true'
        }

        response = requests.get(search_url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        models = response.json()

        formatted = []
        for m in models:
            formatted.append({
                'id': m.get('id', ''),
                'name': m.get('id', ''),
                'description': m.get('description', '') or m.get('cardData', {}).get('language', ''),
                'downloads': m.get('downloads', 0),
                'likes': m.get('likes', 0),
                'trending_score': m.get('trendingScore', 0),
                'last_modified': m.get('lastModified', ''),
                'created_at': m.get('createdAt', ''),
                'tags': m.get('tags', []),
                'author': m.get('author', ''),
            })
        return formatted

    def scan_dataset(self, query: str = None, limit: int = 10, days: int = 7,
                     min_downloads: int = 0, tags: List[str] = None,
                     sort_by: str = None) -> List[Dict]:
        """扫描数据集（支持复杂查询条件）

        Args:
            query: 搜索关键词，如果提供则进行关键词搜索
            limit: 返回结果数量限制
            days: 扫描过去多少天的数据集（仅当query为空时有效）
            min_downloads: 最小下载量过滤
            tags: 标签过滤列表
            sort_by: 排序字段，支持 'downloads'（下载量）、'likes'（点赞数）、None（默认顺序）

        Returns:
            数据集列表
        """
        try:
            datasets = []

            if query:
                # 关键词搜索模式
                logger.info(f"扫描数据集（关键词搜索）: query='{query}', limit={limit}")
                datasets = self.search_remote_datasets(query, limit)
            else:
                # 日期扫描模式
                logger.info(f"扫描数据集（日期扫描）: days={days}, limit={limit}")
                # 临时修改配置中的天数
                original_days = self.config['producer_days']
                try:
                    self.config['producer_days'] = days
                    datasets = self.scan_datasets()
                finally:
                    self.config['producer_days'] = original_days

            # 应用过滤条件
            filtered_datasets = []
            for dataset in datasets:
                # 下载量过滤
                if dataset.get('downloads', 0) < min_downloads:
                    continue

                # 标签过滤
                if tags and tags[0]:
                    dataset_tags = dataset.get('tags', [])
                    if not any(tag.lower() in [t.lower() for t in dataset_tags] for tag in tags):
                        continue

                filtered_datasets.append(dataset)

            # 按指定字段排序
            if sort_by == 'trend':
                filtered_datasets = self._apply_trend_sort(
                    filtered_datasets,
                    recency_half_life=self.config.get('producer_recency_half_life', 30)
                )
                logger.info("按热门度+时间衰减综合排序")
            elif sort_by == 'downloads':
                filtered_datasets.sort(key=lambda x: x.get('downloads', 0), reverse=True)
                logger.info(f"按下载量排序: 降序")
            elif sort_by == 'likes':
                filtered_datasets.sort(key=lambda x: x.get('likes', 0), reverse=True)
                logger.info(f"按点赞数排序: 降序")

            # 限制返回数量
            result_datasets = filtered_datasets[:limit]

            logger.info(f"扫描完成: 找到 {len(result_datasets)} 个数据集")
            return result_datasets

        except Exception as e:
            logger.error(f"扫描数据集失败: {e}")
            return []

scanner_service = ScannerService()
