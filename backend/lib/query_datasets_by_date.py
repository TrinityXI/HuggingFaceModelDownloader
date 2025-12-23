#!/usr/bin/env python3
"""
查询 Hugging Face 指定日期新上传的数据集

用法:
    python query_datasets_by_date.py --date 2024-01-15
    python query_datasets_by_date.py --date 2024-01-15 --limit 100
    python query_datasets_by_date.py --date 2024-01-15 --output datasets.json
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional
import requests
from urllib.parse import urlencode


class HuggingFaceDatasetQuery:
    """查询 Hugging Face 数据集的类"""
    
    def __init__(self, endpoint: str = "https://huggingface.co", token: Optional[str] = None):
        """
        初始化查询器
        
        Args:
            endpoint: Hugging Face API 端点，默认为 https://huggingface.co
            token: Hugging Face 访问令牌（可选，用于访问私有数据集）
        """
        self.endpoint = endpoint.rstrip('/')
        self.token = token
        self.session = requests.Session()
        if token:
            self.session.headers.update({"Authorization": f"Bearer {token}"})
    
    def list_datasets(
        self,
        search: Optional[str] = None,
        author: Optional[str] = None,
        filter_tag: Optional[str] = None,
        sort: str = "lastModified",
        direction: int = -1,
        limit: int = 100,
        full: bool = False
    ) -> List[Dict]:
        """
        获取数据集列表
        
        Args:
            search: 搜索关键词（数据集名称或作者）
            author: 作者筛选
            filter_tag: 标签筛选，例如 "task_categories:text-classification"
            sort: 排序字段，例如 "lastModified", "downloads", "author"
            direction: 排序方向，-1 为降序，1 为升序
            limit: 返回数量限制
            full: 是否获取完整信息（包括所有标签、文件等）
        
        Returns:
            数据集列表
        """
        url = f"{self.endpoint}/api/datasets"
        params = {
            "sort": sort,
            "direction": direction,
            "limit": limit,
            "full": "true" if full else "false"
        }
        
        if search:
            params["search"] = search
        if author:
            params["author"] = author
        if filter_tag:
            params["filter"] = filter_tag
        
        # Hugging Face API 支持 cursor 分页
        # 我们使用分页来获取更多数据，避免需要设置很大的 limit
        all_datasets = []
        cursor = None
        per_page = min(limit, 100)  # 每页最多 100 条（API 推荐值）
        
        while len(all_datasets) < limit:
            # 设置当前页的 limit
            current_limit = min(per_page, limit - len(all_datasets))
            params["limit"] = current_limit
            
            # 如果有 cursor，添加到参数中
            if cursor:
                params["cursor"] = cursor
            elif "cursor" in params:
                del params["cursor"]  # 第一次查询不需要 cursor
            
            try:
                response = self.session.get(url, params=params, timeout=30)
                
                # 处理速率限制
                if response.status_code == 429:
                    print(f"警告: API 速率限制，等待 60 秒后重试...", file=sys.stderr)
                    import time
                    time.sleep(60)
                    continue
                
                response.raise_for_status()
                data = response.json()
                
                if not data or len(data) == 0:
                    break
                
                all_datasets.extend(data)
                
                # 检查是否有下一页（通过 Link header）
                link_header = response.headers.get("Link", "")
                if "rel=\"next\"" in link_header:
                    # 从 Link header 中提取 cursor
                    import re
                    next_match = re.search(r'cursor=([^&>]+)', link_header)
                    if next_match:
                        cursor = next_match.group(1)
                    else:
                        break
                else:
                    # 没有下一页了
                    break
                
                # 如果返回的数据少于请求的数量，说明没有更多数据了
                if len(data) < current_limit:
                    break
                
            except requests.exceptions.RequestException as e:
                # 如果是速率限制，等待后重试
                if "429" in str(e):
                    print(f"警告: API 速率限制，等待 60 秒后重试...", file=sys.stderr)
                    import time
                    time.sleep(60)
                    continue
                print(f"请求错误: {e}", file=sys.stderr)
                break
        
        return all_datasets[:limit]
    
    def get_datasets_by_date(
        self,
        target_date: str,
        limit: int = 1000,
        timezone_offset: int = 0,
        use_created_at: bool = False,
        auto_limit: bool = False
    ) -> List[Dict]:
        """
        获取指定日期上传的数据集
        
        Args:
            target_date: 目标日期，格式为 "YYYY-MM-DD"
            limit: 最大查询数量（用于分页查询）。如果 auto_limit=True，会根据日期自动调整
            timezone_offset: 时区偏移（小时），默认为 0（UTC）
            use_created_at: 如果为 True，使用 createdAt 字段（创建时间）；否则使用 lastModified（最后修改时间）
            auto_limit: 如果为 True，根据目标日期自动调整 limit（历史日期需要查询更多数据）
        
        Returns:
            指定日期上传的数据集列表
        """
        # 解析目标日期
        try:
            date_obj = datetime.strptime(target_date, "%Y-%m-%d")
        except ValueError:
            raise ValueError(f"日期格式错误，应为 YYYY-MM-DD，例如: 2024-01-15")
        
        # 如果启用自动 limit，根据日期距离现在的天数调整 limit
        if auto_limit:
            today = datetime.now().date()
            target_date_obj = date_obj.date()
            days_ago = (today - target_date_obj).days
            
            if days_ago > 180:  # 半年前
                limit = max(limit, 10000)  # 至少查询 10000 条
            elif days_ago > 90:  # 3个月前
                limit = max(limit, 5000)   # 至少查询 5000 条
            elif days_ago > 30:  # 1个月前
                limit = max(limit, 2000)   # 至少查询 2000 条
            # 30 天内使用默认 limit
        
        # 计算日期范围（考虑时区）
        # 如果指定了时区偏移，需要将本地日期转换为 UTC
        # 例如：UTC+8 的 2024-01-15 00:00:00 对应 UTC 的 2024-01-14 16:00:00
        local_start = date_obj.replace(hour=0, minute=0, second=0, microsecond=0)
        # 将本地时间转换为 UTC（减去时区偏移）
        start_time = local_start - timedelta(hours=timezone_offset)
        end_time = start_time + timedelta(days=1)
        
        # 确保时区信息为 UTC
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=timezone.utc)
        
        date_field = "createdAt" if use_created_at else "lastModified"
        field_name = "创建时间" if use_created_at else "最后修改时间"
        
        print(f"查询日期范围: {start_time.isoformat()} 到 {end_time.isoformat()}")
        print(f"使用字段: {field_name} ({date_field})")
        print(f"正在获取数据集列表（最多 {limit} 条）...")
        
        # 获取数据集列表（按指定字段降序排列）
        sort_field = "createdAt" if use_created_at else "lastModified"
        datasets = self.list_datasets(
            sort=sort_field,
            direction=-1,
            limit=limit,
            full=False
        )
        return datasets


def format_dataset_name(dataset: Dict) -> str:
    """格式化数据集名称"""
    if "id" in dataset:
        return dataset["id"]
    elif "author" in dataset and "name" in dataset:
        return f"{dataset['author']}/{dataset['name']}"
    else:
        return "unknown"


def main():
    parser = argparse.ArgumentParser(
        description="查询 Hugging Face 指定日期新上传的数据集",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 查询 2024-01-15 新上传的数据集
  python query_datasets_by_date.py --date 2024-01-15
  
  # 查询并保存到 JSON 文件
  python query_datasets_by_date.py --date 2024-01-15 --output datasets.json
  
  # 使用自定义 API 端点
  python query_datasets_by_date.py --date 2024-01-15 --endpoint https://hf-mirror.com
  
  # 增加查询数量限制
  python query_datasets_by_date.py --date 2024-01-15 --limit 5000
        """
    )
    
    parser.add_argument(
        "--date",
        required=True,
        help="目标日期，格式: YYYY-MM-DD (例如: 2024-01-15)"
    )
    
    parser.add_argument(
        "--limit",
        type=int,
        default=1000,
        help="最大查询数量（默认: 1000）"
    )
    
    parser.add_argument(
        "--endpoint",
        default="https://huggingface.co",
        help="Hugging Face API 端点（默认: https://huggingface.co）"
    )
    
    parser.add_argument(
        "--token",
        help="Hugging Face 访问令牌（可选，也可通过 HF_TOKEN 环境变量设置）"
    )
    
    parser.add_argument(
        "--output",
        "-o",
        help="输出文件路径（JSON 格式），如果不指定则输出到标准输出"
    )
    
    parser.add_argument(
        "--timezone-offset",
        type=int,
        default=0,
        help="时区偏移（小时），默认为 0（UTC）。例如中国时区为 8"
    )
    
    parser.add_argument(
        "--names-only",
        action="store_true",
        help="仅输出数据集名称（每行一个）"
    )
    
    parser.add_argument(
        "--use-created-at",
        action="store_true",
        help="使用 createdAt（创建时间）而不是 lastModified（最后修改时间）来筛选数据集"
    )
    
    parser.add_argument(
        "--auto-limit",
        action="store_true",
        help="根据目标日期自动调整查询数量（历史日期需要查询更多数据）"
    )
    
    args = parser.parse_args()
    
    # 获取 token（优先使用命令行参数，其次使用环境变量）
    token = args.token or os.getenv("HF_TOKEN")
    
    # 创建查询器
    query = HuggingFaceDatasetQuery(endpoint=args.endpoint, token=token)
    
    try:
        # 查询数据集
        datasets = query.get_datasets_by_date(
            target_date=args.date,
            limit=args.limit,
            timezone_offset=args.timezone_offset,
            use_created_at=args.use_created_at,
            auto_limit=args.auto_limit
        )
        
        print(f"\n找到 {len(datasets)} 个在 {args.date} 上传的数据集:\n")
        
        if args.names_only:
            # 仅输出名称
            for dataset in datasets:
                print(format_dataset_name(dataset))
        else:
            # 输出详细信息
            for i, dataset in enumerate(datasets, 1):
                name = format_dataset_name(dataset)
                last_modified = dataset.get("lastModified", "unknown")
                downloads = dataset.get("downloads", 0)
                likes = dataset.get("likes", 0)
                print(f"{i}. {name}")
                print(f"   最后修改: {last_modified}")
                print(f"   下载次数: {downloads:,}")
                print(f"   点赞数: {likes:,}")
                if "tags" in dataset and dataset["tags"]:
                    print(f"   标签: {', '.join(dataset['tags'][:5])}")
                print()
        
        # 保存到文件
        if args.output:
            output_data = {
                "date": args.date,
                "count": len(datasets),
                "datasets": datasets
            }
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, ensure_ascii=False, indent=2)
            print(f"\n结果已保存到: {args.output}")
        elif not args.names_only:
            # 如果没有指定输出文件且不是仅名称模式，输出 JSON 到标准输出
            output_data = {
                "date": args.date,
                "count": len(datasets),
                "datasets": datasets
            }
            print("\n=== JSON 输出 ===")
            print(json.dumps(output_data, ensure_ascii=False, indent=2))
    
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

