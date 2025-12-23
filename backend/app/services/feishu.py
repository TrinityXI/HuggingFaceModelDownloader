import os
import json
import logging
import hmac
import hashlib
import time
from typing import Dict, List, Optional
from datetime import datetime
import requests

from app.core.config import settings
from app.services.queue import queue_service
from app.services.scanner import scanner_service

logger = logging.getLogger(__name__)


class FeishuBot:
    def __init__(self, webhook_url: Optional[str] = None, secret: Optional[str] = None):
        self.webhook_url = webhook_url or settings.FEISHU_WEBHOOK_URL
        self.secret = secret or settings.FEISHU_SECRET
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'User-Agent': 'HuggingFaceModelDownloader/1.0'
        })

        if not self.webhook_url:
            logger.warning("Feishu Webhook URL not configured")
        else:
            logger.info(f"Feishu Bot initialized with webhook: {self.webhook_url[:50]}...")

    def _generate_signature(self, timestamp: str) -> str:
        if not self.secret:
            return ''
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
        if not self.webhook_url:
            return False

        try:
            timestamp = str(int(time.time()))
            signature = self._generate_signature(timestamp)

            if msg_type == "interactive":
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
                            "template": "blue"
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
                if at_all:
                    message["card"]["elements"].insert(0, {
                        "tag": "div",
                        "text": {"tag": "lark_md", "content": "<at id=all></at>"}
                    })
                elif at_users:
                    for user_id in at_users:
                        message["card"]["elements"].insert(0, {
                            "tag": "div",
                            "text": {"tag": "lark_md", "content": f"<at id={user_id}></at>"}
                        })
            else:
                message = {
                    "timestamp": timestamp,
                    "sign": signature,
                    "msg_type": "text",
                    "content": {
                        "text": f"**{title}**\n\n{content}"
                    }
                }
                if at_all:
                    message["content"]["text"] = "<at user_id=\"all\"></at>\n" + message["content"]["text"]
                elif at_users:
                    at_text = " ".join([f"<at user_id=\"{user_id}\"></at>" for user_id in at_users])
                    message["content"]["text"] = at_text + "\n" + message["content"]["text"]

            response = self.session.post(self.webhook_url, json=message, timeout=10)
            response.raise_for_status()

            result = response.json()
            if result.get("StatusCode") == 0 and result.get("code") == 0:
                logger.info(f"Feishu message sent: {title}")
                return True
            else:
                logger.error(f"Feishu message failed: {result}")
                return False

        except Exception as e:
            logger.error(f"Send Feishu message failed: {e}")
            return False

    def send_notification(self, event_type: str, dataset_id: str = "",
                         message: str = "", metadata: Dict = None) -> bool:
        event_configs = {
            "dataset_discovered": {"title": "📚 新数据集发现", "color": "blue"},
            "download_started": {"title": "⏬ 下载开始", "color": "wathet"},
            "download_completed": {"title": "✅ 下载完成", "color": "green"},
            "download_failed": {"title": "❌ 下载失败", "color": "red"},
            "system_alert": {"title": "⚠️ 系统告警", "color": "orange"},
            "queue_status": {"title": "📊 队列状态", "color": "purple"},
            "manual_trigger": {"title": "🔧 手动触发", "color": "turquoise"}
        }

        config = event_configs.get(event_type, {"title": "📢 系统通知", "color": "grey"})
        content_parts = []
        if dataset_id: content_parts.append(f"**数据集**: `{dataset_id}`")
        if message: content_parts.append(f"**详情**: {message}")
        if metadata:
            for key, value in metadata.items():
                if isinstance(value, (list, dict)):
                    value = json.dumps(value, ensure_ascii=False, indent=2)
                content_parts.append(f"**{key}**: `{value}`")
        content_parts.append(f"**时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        content = "\n\n".join(content_parts)
        return self.send_message(config["title"], content, msg_type="interactive")


class FeishuCommandHandler:
    def __init__(self):
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
        parts = command_text.strip().split()
        if not parts:
            return self._create_response("请输入命令，输入 'help' 查看可用命令")

        cmd = parts[0].lower()
        args = parts[1:] if len(parts) > 1 else []

        if cmd in self.commands:
            try:
                return self.commands[cmd](args, user_id)
            except Exception as e:
                logger.error(f"Handle command failed {cmd}: {e}")
                return self._create_response(f"处理命令时出错: {str(e)}", is_error=True)
        else:
            return self._create_response(f"未知命令: {cmd}\n输入 'help' 查看可用命令", is_error=True)

    def _create_response(self, message: str, is_error: bool = False) -> Dict:
        return {
            "success": not is_error,
            "message": message,
            "timestamp": datetime.now().isoformat()
        }

    def cmd_help(self, args: List[str], user_id: str) -> Dict:
        help_text = """**可用命令:**\n1. **help** - 显示此帮助信息\n2. **status** - 显示系统状态\n3. **queue** [stats|pending|downloading|completed|failed] - 查看队列状态\n4. **scan** [now] - 触发数据集扫描\n5. **stats** - 查看系统统计信息\n6. **tasks** [dataset_id] - 查看任务详情\n7. **reset** [interrupted] - 重置任务\n8. **config** - 查看当前配置"""
        return self._create_response(help_text)

    def cmd_status(self, args: List[str], user_id: str) -> Dict:
        stats = queue_service.get_overview_stats()
        config = scanner_service.get_config()
        status_text = f"""**系统状态报告**\n**队列状态:**\n- 待处理: {stats.get('pending', 0)}\n- 下载中: {stats.get('downloading', 0)}\n- 已完成: {stats.get('completed', 0)}\n- 已失败: {stats.get('failed', 0)}\n\n**当前配置:**\n- 扫描间隔: {config.get('producer_interval')}秒\n- 查询天数: {config.get('producer_days')}天\n"""
        return self._create_response(status_text)

    def cmd_queue(self, args: List[str], user_id: str) -> Dict:
        if not args or args[0] == "stats":
            stats = queue_service.get_overview_stats()
            response = f"""**队列统计:**\n- 待处理: {stats.get('pending', 0)}\n- 下载中: {stats.get('downloading', 0)}\n- 已完成: {stats.get('completed', 0)}\n- 已失败: {stats.get('failed', 0)}"""
            return self._create_response(response)
        elif args[0] == "pending":
            tasks = queue_service.fetch_tasks(worker_id="viewer", limit=10)
            if not tasks: return self._create_response("没有待处理任务")
            task_list = "\n".join([f"- `{task['dataset_id']}`" for task in tasks[:5]])
            return self._create_response(f"**待处理任务:**\n\n{task_list}")
        else:
            return self._create_response("可用子命令: stats, pending")

    def cmd_scan(self, args: List[str], user_id: str) -> Dict:
        if args and args[0] == "now":
            success, skipped = scanner_service.scan_and_enqueue()
            return self._create_response(f"扫描完成. 新增: {success}, 跳过: {skipped}")
        return self._create_response("使用 'scan now' 立即触发")

    def cmd_stats(self, args: List[str], user_id: str) -> Dict:
        stats = queue_service.get_overview_stats()
        total = sum([v for k,v in stats.items() if k in ['pending', 'downloading', 'completed', 'failed']])
        response = f"**任务统计:** 总任务: {total}, 成功: {stats.get('completed', 0)}"
        return self._create_response(response)

    def cmd_tasks(self, args: List[str], user_id: str) -> Dict:
        if args:
            dataset_id = args[0]
            # We don't have get_task_by_dataset_id exposed in queue_service public API explicitly but update_status uses it.
            # But queue_service has get_task_detail(id).
            # I should add get_task_by_dataset_id to queue_service or use task_crud directly?
            # Accessing task_crud from here is fine since it's a service/logic layer.
            # But let's use queue_service if possible.
            # QueueService doesn't expose get_by_dataset_id.
            # I'll use task_crud here for now or add it to queue_service.
            from app.crud.task import task_crud
            task = task_crud.get_by_dataset_id(dataset_id)
            if not task: return self._create_response(f"未找到数据集: {dataset_id}", is_error=True)
            response = f"**任务详情**: {task.get('dataset_id')} - {task.get('status')}"
            return self._create_response(response)
        return self._create_response("请指定数据集ID")

    def cmd_reset(self, args: List[str], user_id: str) -> Dict:
        if args and args[0] == "interrupted":
            count = queue_service.reset_interrupted_tasks()
            return self._create_response(f"已重置 {count} 个中断任务")
        return self._create_response("可用子命令: interrupted")

    def cmd_config(self, args: List[str], user_id: str) -> Dict:
        config = scanner_service.get_config()
        return self._create_response(str(config))

def verify_feishu_signature(timestamp: str, signature: str, body: str, secret: str) -> bool:
    if not secret: return True
    try:
        if abs(int(time.time()) - int(timestamp)) > 300: return False
        string_to_sign = f"{timestamp}\n{secret}"
        calculated = hmac.new(secret.encode('utf-8'), string_to_sign.encode('utf-8'), digestmod=hashlib.sha256).hexdigest()
        return hmac.compare_digest(calculated, signature)
    except: return False
