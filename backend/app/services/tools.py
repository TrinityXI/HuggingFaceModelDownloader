import asyncio
import json
import logging
import os
import subprocess
import shutil
from typing import Dict, List, Any, Callable, Optional

from app.services.scanner import scanner_service
from app.services.queue import queue_service
from app.crud.task import task_crud
from app.crud.dataset import dataset_crud
from app.crud.event import event_crud

logger = logging.getLogger(__name__)


class ToolRegistry:
    """工具注册和执行管理器"""

    def __init__(self):
        self.tools = {}
        self._register_tools()

    def _register_tools(self):
        """注册所有可用工具"""
        # scan_dataset工具
        self.register_tool(
            name="scan_dataset",
            description="扫描和搜索HuggingFace数据集。支持关键词搜索、日期范围扫描、按下载量/点赞数排序。",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词，如 'text classification' 或 'bert'。不提供则按日期扫描"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回结果数量",
                        "default": 10
                    },
                    "days": {
                        "type": "integer",
                        "description": "扫描过去多少天的数据集（仅在query为空时有效）。days=1 表示今天",
                        "default": 7
                    },
                    "min_downloads": {
                        "type": "integer",
                        "description": "最小下载量过滤",
                        "default": 0
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "标签过滤，如 ['text-classification', 'nlp']"
                    },
                    "sort_by": {
                        "type": "string",
                        "description": "排序字段：'downloads'按下载量排序（用于查询top热门），'likes'按点赞数排序，不提供则使用默认顺序",
                        "enum": ["downloads", "likes"]
                    }
                },
                "required": []
            },
            func=self.scan_dataset
        )

        # query_dataset工具
        self.register_tool(
            name="query_dataset",
            description="查询单个数据集信息和下载状态",
            parameters={
                "type": "object",
                "properties": {
                    "dataset_id": {
                        "type": "string",
                        "description": "数据集ID，格式如 'username/dataset-name'"
                    },
                    "include_progress": {
                        "type": "boolean",
                        "description": "是否包含下载进度信息",
                        "default": True
                    },
                    "include_events": {
                        "type": "boolean",
                        "description": "是否包含事件日志",
                        "default": False
                    },
                    "include_metadata": {
                        "type": "boolean",
                        "description": "是否包含数据集元数据",
                        "default": True
                    }
                },
                "required": ["dataset_id"]
            },
            func=self.query_dataset
        )

        # list_queue_datasets工具
        self.register_tool(
            name="list_queue_datasets",
            description="列出下载队列中的数据集列表（支持按状态过滤和排序）。用于查询如'正在下载的top2数据集'、'优先级最高的待下载数据集'等。",
            parameters={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "状态过滤：'pending'(待下载)、'downloading'(下载中)、'completed'(已完成)、'failed'(失败)",
                        "enum": ["pending", "downloading", "completed", "failed"]
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回数量限制，如 top2 则设为 2",
                        "default": 10
                    },
                    "sort_by": {
                        "type": "string",
                        "description": "排序字段：'priority'(优先级)、'progress_percentage'(下载进度)、'downloaded_bytes'(已下载字节)、'download_speed'(下载速度)",
                        "enum": ["priority", "progress_percentage", "downloaded_bytes", "created_at", "updated_at", "download_speed"]
                    },
                    "sort_order": {
                        "type": "string",
                        "description": "排序方向：'desc'(降序，从高到低)、'asc'(升序，从低到高)",
                        "enum": ["desc", "asc"],
                        "default": "desc"
                    }
                },
                "required": []
            },
            func=self.list_queue_datasets
        )

        # search_model工具
        self.register_tool(
            name="search_model",
            description="搜索 Hugging Face 模型。支持关键词搜索，按下载量/点赞数排序。",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词，如 'llama' 或 'qwen'"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回结果数量",
                        "default": 10
                    },
                    "sort_by": {
                        "type": "string",
                        "description": "排序字段：'downloads'按下载量排序，'likes'按点赞数排序",
                        "enum": ["downloads", "likes"]
                    }
                },
                "required": ["query"]
            },
            func=self.search_model
        )

        # download_dataset工具
        self.register_tool(
            name="download_dataset",
            description="下载指定数据集或模型。repo_type='dataset' 表示数据集，repo_type='model' 表示模型。",
            parameters={
                "type": "object",
                "properties": {
                    "dataset_id": {
                        "type": "string",
                        "description": "数据集或模型 ID，格式如 'username/repo-name'"
                    },
                    "repo_type": {
                        "type": "string",
                        "description": "仓库类型：'dataset'（数据集）或 'model'（模型）",
                        "enum": ["dataset", "model"],
                        "default": "dataset"
                    },
                    "priority": {
                        "type": "integer",
                        "description": "下载优先级（0-10，越高越优先）",
                        "default": 0
                    },
                    "storage_path": {
                        "type": "string",
                        "description": "自定义存储路径"
                    },
                    "force": {
                        "type": "boolean",
                        "description": "强制重新下载，即使已存在",
                        "default": False
                    }
                },
                "required": ["dataset_id"]
            },
            func=self.download_dataset
        )

        # tar_dataset工具
        self.register_tool(
            name="tar_dataset",
            description="压缩打包已下载的数据集",
            parameters={
                "type": "object",
                "properties": {
                    "dataset_id": {
                        "type": "string",
                        "description": "数据集ID，格式如 'username/dataset-name'"
                    },
                    "compress": {
                        "type": "boolean",
                        "description": "是否启用压缩",
                        "default": True
                    },
                    "split_size": {
                        "type": "string",
                        "description": "分片大小，如 '50GiB' 或 '10GB'",
                        "default": "50GiB"
                    },
                    "delete_source": {
                        "type": "boolean",
                        "description": "打包后是否删除源文件",
                        "default": False
                    }
                },
                "required": ["dataset_id"]
            },
            func=self.tar_dataset
        )

    def register_tool(self, name: str, description: str, parameters: Dict, func: Callable):
        """注册工具到注册表

        Args:
            name: 工具名称
            description: 工具描述
            parameters: 工具参数schema
            func: 工具执行函数
        """
        self.tools[name] = {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters
            },
            "func": func
        }
        logger.debug(f"Registered tool: {name}")

    def get_tools_schema(self) -> List[Dict]:
        """获取所有工具的schema供LLM使用

        Returns:
            工具schema列表
        """
        return [{
            "type": tool["type"],
            "function": tool["function"]
        } for tool in self.tools.values()]

    async def execute_tool(self, name: str, arguments: Dict) -> Dict:
        """执行工具调用

        Args:
            name: 工具名称
            arguments: 工具参数

        Returns:
            工具执行结果
        """
        if name not in self.tools:
            logger.error(f"工具不存在: {name}")
            return {"error": f"工具不存在: {name}"}

        logger.info(f"执行工具: {name}, 参数: {arguments}")

        try:
            tool = self.tools[name]
            # 调用工具函数
            result = await tool["func"](**arguments)

            logger.info(f"工具执行成功: {name}")

            return {
                "success": True,
                "data": result
            }

        except Exception as e:
            logger.error(f"工具执行失败 {name}: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    # ========== 工具实现方法 ==========

    async def scan_dataset(self, query: str = None, limit: int = 10, days: int = 7,
                           min_downloads: int = 0, tags: List[str] = None,
                           sort_by: str = None) -> Dict:
        """扫描数据集工具实现

        支持两种模式：
        1. 关键词搜索模式（当query不为空时）
        2. 日期扫描模式（当query为空时）
        """
        try:
            datasets = scanner_service.scan_dataset(
                query=query,
                limit=limit,
                days=days,
                min_downloads=min_downloads,
                tags=tags,
                sort_by=sort_by
            )

            return {
                "count": len(datasets),
                "datasets": datasets,
                "filters_applied": {
                    "min_downloads": min_downloads,
                    "tags": tags or []
                }
            }

        except Exception as e:
            logger.error(f"scan_dataset工具执行失败: {e}", exc_info=True)
            raise

    async def query_dataset(self, dataset_id: str, include_progress: bool = True,
                           include_events: bool = False, include_metadata: bool = True) -> Dict:
        """查询数据集工具实现"""
        try:
            return queue_service.query_dataset(
                dataset_id=dataset_id,
                include_progress=include_progress,
                include_events=include_events
            )

        except Exception as e:
            logger.error(f"query_dataset工具执行失败: {e}", exc_info=True)
            raise

    async def list_queue_datasets(self, status: str = None, limit: int = 10,
                                  sort_by: str = None, sort_order: str = 'desc') -> Dict:
        """列出队列数据集工具实现"""
        try:
            return queue_service.list_queue_datasets(
                status=status,
                limit=limit,
                sort_by=sort_by,
                sort_order=sort_order
            )

        except Exception as e:
            logger.error(f"list_queue_datasets工具执行失败: {e}", exc_info=True)
            raise

    async def search_model(self, query: str, limit: int = 10, sort_by: str = None) -> Dict:
        """搜索模型工具实现"""
        try:
            models = scanner_service.search_remote_models(query, limit)
            if sort_by == 'downloads':
                models.sort(key=lambda m: m.get('downloads', 0), reverse=True)
            elif sort_by == 'likes':
                models.sort(key=lambda m: m.get('likes', 0), reverse=True)
            return {
                "count": len(models),
                "models": models,
                "query": query
            }
        except Exception as e:
            logger.error(f"search_model工具执行失败: {e}", exc_info=True)
            raise

    async def download_dataset(self, dataset_id: str, repo_type: str = 'dataset',
                              priority: int = 0,
                              storage_path: str = None, force: bool = False) -> Dict:
        """下载数据集或模型工具实现"""
        try:
            if repo_type not in ('dataset', 'model'):
                repo_type = 'dataset'
            # 调用QueueService创建手动任务
            task, message = queue_service.create_manual_task(
                dataset_id=dataset_id,
                priority=priority,
                storage_path=storage_path,
                force=force,
                tar_config=None,
                repo_type=repo_type
            )

            return {
                "success": True,
                "task_id": task['id'],
                "dataset_id": dataset_id,
                "repo_type": repo_type,
                "message": message,
                "status": task['status'],
                "priority": priority
            }

        except ValueError as e:
            # 处理已知的业务错误，如数据集已存在
            logger.warning(f"下载数据集业务错误: {e}")
            return {
                "success": False,
                "error": str(e)
            }
        except Exception as e:
            logger.error(f"download_dataset工具执行失败: {e}", exc_info=True)
            raise

    async def tar_dataset(self, dataset_id: str, compress: bool = True,
                         split_size: str = "50GiB", delete_source: bool = False) -> Dict:
        """压缩打包工具实现

        通过调用Go CLI的tar功能实现
        """
        try:
            # 检查数据集是否已下载完成
            task = task_crud.get_by_dataset_id(dataset_id)
            if not task:
                return {
                    "success": False,
                    "error": f"数据集 {dataset_id} 未找到"
                }

            if task['status'] != 'completed':
                return {
                    "success": False,
                    "error": f"数据集 {dataset_id} 状态为 {task['status']}，需要先下载完成"
                }

            # 获取存储路径
            storage_path = task.get('storage_path')
            if not storage_path:
                return {
                    "success": False,
                    "error": f"数据集 {dataset_id} 的存储路径未设置"
                }

            # 检查Go CLI是否可用
            go_cli_path = shutil.which("hfdownloader")
            if not go_cli_path:
                # 尝试默认路径
                default_paths = [
                    "/app/go_cli/hfdownloader",
                    "/usr/local/bin/hfdownloader",
                    "./hfdownloader"
                ]
                for path in default_paths:
                    if os.path.exists(path):
                        go_cli_path = path
                        break

            if not go_cli_path:
                logger.warning("Go CLI (hfdownloader) 未找到，返回占位信息")
                return {
                    "success": True,
                    "message": "tar功能已请求，但Go CLI未找到",
                    "dataset_id": dataset_id,
                    "config": {
                        "compress": compress,
                        "split_size": split_size,
                        "delete_source": delete_source
                    },
                    "note": "请确保hfdownloader已安装并在PATH中"
                }

            # 构建tar命令
            # 假设命令格式: hfdownloader tar --source <path> --output <path> [--compress] [--split-size]
            cmd = [go_cli_path, "tar", "--source", storage_path]

            # 添加输出路径（在源目录同级创建tar文件）
            output_dir = os.path.dirname(storage_path)
            output_base = f"{dataset_id.replace('/', '_')}.tar"
            if compress:
                output_base += ".gz"
            output_path = os.path.join(output_dir, output_base)
            cmd.extend(["--output", output_path])

            if compress:
                cmd.append("--compress")

            if split_size and split_size != "50GiB":
                cmd.extend(["--split-size", split_size])

            if delete_source:
                cmd.append("--delete-source")

            logger.info(f"执行tar命令: {' '.join(cmd)}")

            # 执行命令（异步）
            try:
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )

                stdout, stderr = await process.communicate()

                if process.returncode == 0:
                    # 解析输出（假设是JSON格式）
                    output = stdout.decode('utf-8').strip()
                    result_data = {}
                    if output:
                        try:
                            result_data = json.loads(output)
                        except json.JSONDecodeError:
                            result_data = {"raw_output": output}

                    return {
                        "success": True,
                        "message": f"数据集 {dataset_id} 打包完成",
                        "dataset_id": dataset_id,
                        "output_path": output_path,
                        "command": cmd,
                        "result": result_data
                    }
                else:
                    error_msg = stderr.decode('utf-8').strip()
                    logger.error(f"tar命令失败: {error_msg}")
                    return {
                        "success": False,
                        "error": f"打包失败: {error_msg}",
                        "returncode": process.returncode,
                        "stderr": error_msg
                    }

            except FileNotFoundError:
                logger.error(f"Go CLI未找到: {go_cli_path}")
                return {
                    "success": False,
                    "error": f"Go CLI未找到: {go_cli_path}"
                }
            except Exception as e:
                logger.error(f"执行tar命令异常: {e}")
                return {
                    "success": False,
                    "error": f"执行tar命令异常: {str(e)}"
                }

        except Exception as e:
            logger.error(f"tar_dataset工具执行失败: {e}", exc_info=True)
            raise