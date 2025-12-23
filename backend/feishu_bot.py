#!/usr/bin/env python3
"""
飞书机器人集成模块

功能：
1. 发送通知到飞书群
2. 处理飞书机器人webhook命令
3. 验证飞书请求签名

飞书机器人文档：https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot
"""

import os
import json
import logging
import hmac
import hashlib
import time
from typing import Dict, List, Optional, Any
from datetime import datetime
import requests

logger = logging.getLogger(__name__)


class FeishuBot:
    """飞书机器人客户端"""

    def __init__(self, webhook_url: Optional[str] = None, secret: Optional[str] = None):
        """
        初始化飞书机器人

        Args:
            webhook_url: 飞书机器人webhook URL（从环境变量 FEISHU_WEBHOOK_URL 读取）
            secret: 飞书机器人签名密钥（从环境变量 FEISHU_SECRET 读取）
        """
        self.webhook_url = webhook_url or os.getenv('FEISHU_WEBHOOK_URL', '')
        self.secret = secret or os.getenv('FEISHU_SECRET', '')
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'User-Agent': 'HuggingFaceModelDownloader/1.0'
        })

        # 检查配置
        if not self.webhook_url:
            logger.warning("飞书机器人webhook URL未配置，通知功能将不可用")
        else:
            logger.info(f"飞书机器人已初始化，webhook URL: {self.webhook_url[:50]}...")

    def _generate_signature(self, timestamp: str) -> str:
        """
        生成飞书请求签名

        Args:
            timestamp: 时间戳字符串

        Returns:
            签名字符串
        """
        if not self.secret:
            return ''

        # 飞书签名算法：timestamp + "\n" + secret
        string_to_sign = f"{timestamp}\n{self.secret}"
        hmac_code = hmac.new(
            self.secret.encode('utf-8'),
            string_to_sign.encode('utf-8'),
            digestmod=hashlib.sha256
        ).hexdigest()

        return hmac_code

    def send_message(self, title: str, content: str,
                    msg_type: str = "interactive",
                    at_all: bool = False,
                    at_users: List[str] = None) -> bool:
        """
        发送消息到飞书群

        Args:
            title: 消息标题
            content: 消息内容（支持markdown）
            msg_type: 消息类型，支持 "text", "post", "interactive"（卡片）
            at_all: 是否@所有人
            at_users: 要@的用户open_id列表

        Returns:
            是否发送成功
        """
        if not self.webhook_url:
            logger.warning("无法发送飞书消息：webhook URL未配置")
            return False

        try:
            timestamp = str(int(time.time()))
            signature = self._generate_signature(timestamp)

            if msg_type == "interactive":
                # 卡片消息
                message = {
                    "timestamp": timestamp,
                    "sign": signature,
                    "msg_type": "interactive",
                    "card": {
                        "config": {
                            "wide_screen_mode": True,
                            "enable_forward": True
                        },
                        "header": {
                            "title": {
                                "tag": "plain_text",
                                "content": title
                            },
                            "template": "blue"  # 蓝色主题
                        },
                        "elements": [
                            {
                                "tag": "div",
                                "text": {
                                    "tag": "lark_md",
                                    "content": content
                                }
                            }
                        ]
                    }
                }

                # 添加@所有人或@特定用户
                if at_all:
                    message["card"]["elements"].insert(0, {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": "<at id=all></at>"
                        }
                    })
                elif at_users:
                    for user_id in at_users:
                        message["card"]["elements"].insert(0, {
                            "tag": "div",
                            "text": {
                                "tag": "lark_md",
                                "content": f"<at id={user_id}></at>"
                            }
                        })
            else:
                # 文本消息
                message = {
                    "timestamp": timestamp,
                    "sign": signature,
                    "msg_type": "text",
                    "content": {
                        "text": f"**{title}**\n\n{content}"
                    }
                }

                # 添加@所有人或@特定用户
                if at_all:
                    message["content"]["text"] = "<at user_id=\"all\"></at>\n" + message["content"]["text"]
                elif at_users:
                    at_text = " ".join([f"<at user_id=\"{user_id}\"></at>" for user_id in at_users])
                    message["content"]["text"] = at_text + "\n" + message["content"]["text"]

            response = self.session.post(self.webhook_url, json=message, timeout=10)
            response.raise_for_status()

            result = response.json()
            if result.get("StatusCode") == 0 and result.get("code") == 0:
                logger.info(f"飞书消息发送成功: {title}")
                return True
            else:
                logger.error(f"飞书消息发送失败: {result}")
                return False

        except Exception as e:
            logger.error(f"发送飞书消息失败: {e}")
            return False

    def send_notification(self, event_type: str, dataset_id: str = "",
                         message: str = "", metadata: Dict = None) -> bool:
        """
        发送系统事件通知

        Args:
            event_type: 事件类型，如 "dataset_discovered", "download_started",
                       "download_completed", "download_failed", "system_alert"
            dataset_id: 数据集ID（可选）
            message: 详细消息
            metadata: 附加元数据

        Returns:
            是否发送成功
        """
        # 事件类型映射到标题和颜色
        event_configs = {
            "dataset_discovered": {
                "title": "📚 新数据集发现",
                "color": "blue"
            },
            "download_started": {
                "title": "⏬ 下载开始",
                "color": "wathet"  # 浅蓝色
            },
            "download_completed": {
                "title": "✅ 下载完成",
                "color": "green"
            },
            "download_failed": {
                "title": "❌ 下载失败",
                "color": "red"
            },
            "system_alert": {
                "title": "⚠️ 系统告警",
                "color": "orange"
            },
            "queue_status": {
                "title": "📊 队列状态",
                "color": "purple"
            },
            "manual_trigger": {
                "title": "🔧 手动触发",
                "color": "turquoise"
            }
        }

        config = event_configs.get(event_type, {
            "title": "📢 系统通知",
            "color": "grey"
        })

        # 构建消息内容
        content_parts = []

        if dataset_id:
            content_parts.append(f"**数据集**: `{dataset_id}`")

        if message:
            content_parts.append(f"**详情**: {message}")

        if metadata:
            for key, value in metadata.items():
                if isinstance(value, (list, dict)):
                    value = json.dumps(value, ensure_ascii=False, indent=2)
                content_parts.append(f"**{key}**: `{value}`")

        content_parts.append(f"**时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        content = "\n\n".join(content_parts)

        # 发送卡片消息
        return self.send_message(config["title"], content, msg_type="interactive")


class FeishuCommandHandler:
    """飞书命令处理器"""

    def __init__(self, producer_core):
        """
        初始化命令处理器

        Args:
            producer_core: ProducerCore实例
        """
        self.core = producer_core
        self.commands = {
            "help": self.cmd_help,
            "status": self.cmd_status,
            "queue": self.cmd_queue,
            "scan": self.cmd_scan,
            "stats": self.cmd_stats,
            "tasks": self.cmd_tasks,
            "reset": self.cmd_reset,
            "config": self.cmd_config
        }

    def handle_command(self, command_text: str, user_id: str = "") -> Dict:
        """
        处理飞书命令

        Args:
            command_text: 命令文本，如 "status" 或 "queue stats"
            user_id: 用户ID（用于个性化响应）

        Returns:
            响应字典，包含处理结果
        """
        parts = command_text.strip().split()
        if not parts:
            return self._create_response("请输入命令，输入 'help' 查看可用命令")

        cmd = parts[0].lower()
        args = parts[1:] if len(parts) > 1 else []

        if cmd in self.commands:
            try:
                return self.commands[cmd](args, user_id)
            except Exception as e:
                logger.error(f"处理命令失败 {cmd}: {e}")
                return self._create_response(f"处理命令时出错: {str(e)}", is_error=True)
        else:
            return self._create_response(f"未知命令: {cmd}\n输入 'help' 查看可用命令", is_error=True)

    def _create_response(self, message: str, is_error: bool = False) -> Dict:
        """创建标准响应格式"""
        return {
            "success": not is_error,
            "message": message,
            "timestamp": datetime.now().isoformat()
        }

    def cmd_help(self, args: List[str], user_id: str) -> Dict:
        """显示帮助信息"""
        help_text = """**可用命令:**

1. **help** - 显示此帮助信息
2. **status** - 显示系统状态
3. **queue** [stats|pending|downloading|completed|failed] - 查看队列状态
   - `queue stats` - 查看统计信息
   - `queue pending` - 查看待处理任务
   - `queue downloading` - 查看正在下载的任务
4. **scan** [now] - 触发数据集扫描
   - `scan now` - 立即触发扫描
5. **stats** - 查看系统统计信息
6. **tasks** [dataset_id] - 查看任务详情
   - `tasks` - 查看最近任务
   - `tasks <dataset_id>` - 查看特定数据集任务
7. **reset** [failed|interrupted] - 重置任务
   - `reset failed` - 重置所有失败任务
   - `reset interrupted` - 重置所有中断的任务
8. **config** - 查看当前配置

**示例:**
- `status`
- `queue stats`
- `scan now`
- `tasks facebook/bart-large`
"""
        return self._create_response(help_text)

    def cmd_status(self, args: List[str], user_id: str) -> Dict:
        """显示系统状态"""
        try:
            # 获取队列统计
            stats = self.core.queue_manager.get_queue_stats()

            # 获取当前配置
            config = self.core.get_config()

            status_text = f"""**系统状态报告**

**队列状态:**
- 待处理: {stats.get('pending', 0)}
- 下载中: {stats.get('downloading', 0)}
- 已完成: {stats.get('completed', 0)}
- 已失败: {stats.get('failed', 0)}

**当前配置:**
- 扫描间隔: {config.get('producer_interval', 3600)}秒
- 查询天数: {config.get('producer_days', 7)}天
- 查询限制: {config.get('producer_limit', 50)}条
- 时区偏移: UTC+{config.get('producer_timezone_offset', 8)}
- HF端点: {config.get('hf_endpoint', 'https://hf-mirror.com')}

**时间:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
            return self._create_response(status_text)
        except Exception as e:
            logger.error(f"获取状态失败: {e}")
            return self._create_response(f"获取状态失败: {str(e)}", is_error=True)

    def cmd_queue(self, args: List[str], user_id: str) -> Dict:
        """查看队列状态"""
        try:
            if not args or args[0] == "stats":
                stats = self.core.queue_manager.get_queue_stats()
                response = f"""**队列统计:**

- 待处理: {stats.get('pending', 0)}
- 下载中: {stats.get('downloading', 0)}
- 已完成: {stats.get('completed', 0)}
- 已失败: {stats.get('failed', 0)}
- 总计: {sum(stats.values())}

**时间:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
                return self._create_response(response)

            elif args[0] == "pending":
                # 获取待处理任务
                tasks = self.core.queue_manager.fetch_tasks_batch(limit=10)
                if not tasks:
                    return self._create_response("没有待处理任务")

                task_list = "\n".join([f"- `{task['dataset_id']}` (优先级: {task['priority']})"
                                      for task in tasks[:5]])  # 只显示前5个
                if len(tasks) > 5:
                    task_list += f"\n... 还有 {len(tasks) - 5} 个任务"

                return self._create_response(f"**待处理任务 (共 {len(tasks)} 个):**\n\n{task_list}")

            else:
                return self._create_response("可用子命令: stats, pending, downloading, completed, failed")

        except Exception as e:
            logger.error(f"查询队列失败: {e}")
            return self._create_response(f"查询队列失败: {str(e)}", is_error=True)

    def cmd_scan(self, args: List[str], user_id: str) -> Dict:
        """触发数据集扫描"""
        try:
            if args and args[0] == "now":
                # 触发扫描
                success_count, skipped_count = self.core.scan_and_enqueue()

                if success_count == 0 and skipped_count == 0:
                    return self._create_response("扫描完成，但未找到新数据集")

                response = f"""**扫描完成**

- 新发现数据集: {success_count}个
- 已跳过数据集: {skipped_count}个
- 总计处理: {success_count + skipped_count}个

**时间:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
                return self._create_response(response)
            else:
                return self._create_response("使用 'scan now' 立即触发扫描")

        except Exception as e:
            logger.error(f"触发扫描失败: {e}")
            return self._create_response(f"触发扫描失败: {str(e)}", is_error=True)

    def cmd_stats(self, args: List[str], user_id: str) -> Dict:
        """查看系统统计信息"""
        try:
            # 这里可以添加更多统计信息
            stats = self.core.queue_manager.get_queue_stats()
            total_tasks = sum(stats.values())

            response = f"""**系统统计信息**

**任务统计:**
- 总任务数: {total_tasks}
- 成功完成: {stats.get('completed', 0)}
- 失败任务: {stats.get('failed', 0)}
- 成功率: {(stats.get('completed', 0) / total_tasks * 100):.1f}% (基于总任务数)

**数据库:**
- SQLite元数据数据库: {'已启用' if self.core.dataset_db else '未启用'}

**时间:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
            return self._create_response(response)
        except Exception as e:
            logger.error(f"获取统计信息失败: {e}")
            return self._create_response(f"获取统计信息失败: {str(e)}", is_error=True)

    def cmd_tasks(self, args: List[str], user_id: str) -> Dict:
        """查看任务详情"""
        try:
            if args:
                # 查看特定数据集
                dataset_id = args[0]
                task = self.core.queue_manager.get_task_by_dataset_id(dataset_id)
                if not task:
                    return self._create_response(f"未找到数据集: {dataset_id}", is_error=True)

                response = f"""**任务详情**

- **数据集ID**: {task.get('dataset_id')}
- **状态**: {task.get('status')}
- **优先级**: {task.get('priority')}
- **重试次数**: {task.get('retry_count')}
- **创建时间**: {task.get('created_at')}
- **开始时间**: {task.get('started_at') or '未开始'}
- **完成时间**: {task.get('completed_at') or '未完成'}
- **最后错误**: {task.get('last_error') or '无'}

**时间:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
                return self._create_response(response)
            else:
                # 查看最近任务
                # 这里简化处理，实际可以查询最近的任务
                return self._create_response("请指定数据集ID，例如: `tasks facebook/bart-large`")

        except Exception as e:
            logger.error(f"查询任务失败: {e}")
            return self._create_response(f"查询任务失败: {str(e)}", is_error=True)

    def cmd_reset(self, args: List[str], user_id: str) -> Dict:
        """重置任务"""
        try:
            if not args:
                return self._create_response("可用子命令: failed, interrupted")

            if args[0] == "failed":
                # 重置失败任务（这里需要实现重置逻辑）
                return self._create_response("重置失败任务功能待实现")

            elif args[0] == "interrupted":
                # 重置中断任务
                count = self.core.queue_manager.reset_interrupted_tasks()
                return self._create_response(f"已重置 {count} 个中断的下载任务")

            else:
                return self._create_response("可用子命令: failed, interrupted")

        except Exception as e:
            logger.error(f"重置任务失败: {e}")
            return self._create_response(f"重置任务失败: {str(e)}", is_error=True)

    def cmd_config(self, args: List[str], user_id: str) -> Dict:
        """查看当前配置"""
        try:
            config = self.core.get_config()

            config_text = "**当前配置:**\n\n"
            for key, value in config.items():
                config_text += f"- **{key}**: `{value}`\n"

            config_text += f"\n**时间:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

            return self._create_response(config_text)
        except Exception as e:
            logger.error(f"获取配置失败: {e}")
            return self._create_response(f"获取配置失败: {str(e)}", is_error=True)


def verify_feishu_signature(timestamp: str, signature: str, body: str, secret: str) -> bool:
    """
    验证飞书webhook请求签名

    Args:
        timestamp: 请求头中的时间戳
        signature: 请求头中的签名
        body: 请求体原始内容
        secret: 飞书机器人密钥

    Returns:
        签名是否有效
    """
    if not secret:
        logger.warning("飞书机器人密钥未配置，跳过签名验证")
        return True

    try:
        # 验证时间戳（防止重放攻击）
        current_time = int(time.time())
        request_time = int(timestamp)

        # 允许5分钟的时间差
        if abs(current_time - request_time) > 300:
            logger.warning(f"请求时间戳过期: {request_time}, 当前时间: {current_time}")
            return False

        # 计算签名
        string_to_sign = f"{timestamp}\n{secret}"
        calculated_signature = hmac.new(
            secret.encode('utf-8'),
            string_to_sign.encode('utf-8'),
            digestmod=hashlib.sha256
        ).hexdigest()

        # 比较签名
        return hmac.compare_digest(calculated_signature, signature)

    except Exception as e:
        logger.error(f"验证飞书签名失败: {e}")
        return False