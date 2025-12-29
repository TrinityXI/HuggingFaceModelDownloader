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
from app.services.chat_history import chat_history_service

logger = logging.getLogger(__name__)


class FeishuBot:
    _token_cache = {
        "token": None,
        "expire_at": 0
    }

    def __init__(self, webhook_url: Optional[str] = None, secret: Optional[str] = None, 
                 app_id: Optional[str] = None, app_secret: Optional[str] = None):
        self.webhook_url = webhook_url or settings.FEISHU_WEBHOOK_URL
        self.secret = secret or settings.FEISHU_SECRET
        self.app_id = app_id or settings.FEISHU_APP_ID
        self.app_secret = app_secret or settings.FEISHU_APP_SECRET
        
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

    def get_tenant_access_token(self) -> str:
        """获取飞书 Tenant Access Token (带缓存)"""
        now = time.time()
        if self._token_cache["token"] and self._token_cache["expire_at"] > now + 60:
            return self._token_cache["token"]

        if not self.app_id or not self.app_secret:
            logger.error("Feishu App ID or Secret not configured")
            return ""

        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        try:
            response = requests.post(url, json={
                "app_id": self.app_id,
                "app_secret": self.app_secret
            }, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get("code") == 0:
                token = data.get("tenant_access_token")
                expire = data.get("expire", 7200)
                self._token_cache["token"] = token
                self._token_cache["expire_at"] = now + expire
                return token
            else:
                logger.error(f"Failed to get tenant_access_token: {data}")
                return ""
        except Exception as e:
            logger.error(f"Error getting tenant_access_token: {e}")
            return ""

    def reply_message(self, message_id: str, content: str, msg_type: str = "text") -> bool:
        """回复指定消息"""
        logger.info(f"reply_message调用开始: message_id={message_id}, msg_type={msg_type}, content_length={len(content)}")
        token = self.get_tenant_access_token()
        if not token:
            logger.error("Cannot reply message: No tenant_access_token")
            return False

        url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reply"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8"
        }
        
        # 构造消息体
        if msg_type == "text":
            data = {
                "content": json.dumps({"text": content}),
                "msg_type": "text"
            }
        elif msg_type == "interactive":
             # 简化的卡片构造，如果 content 是 JSON 字符串则直接使用，否则构造简单卡片
            try:
                card_content = json.loads(content)
                data = {
                    "content": json.dumps(card_content),
                    "msg_type": "interactive"
                }
            except:
                # 构造简单卡片
                data = {
                    "content": json.dumps({
                        "header": {"title": {"tag": "plain_text", "content": "系统回复"}},
                        "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": content}}]
                    }),
                    "msg_type": "interactive"
                }
        else:
            data = {
                "content": content,
                "msg_type": msg_type
            }

        try:
            response = requests.post(url, headers=headers, json=data, timeout=10)
            result = response.json()
            if result.get("code") == 0:
                logger.info(f"Successfully replied to message {message_id}")
                return True
            else:
                logger.error(f"Failed to reply message: {result}")
                return False
        except Exception as e:
            logger.error(f"Error replying message: {e}")
            return False

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
        self.agent_handler = None  # 延迟初始化Agent处理器

    def _get_agent_handler(self):
        """获取Agent处理器实例（延迟初始化）"""
        if self.agent_handler is None:
            try:
                from app.services.agent import FeishuAgentHandler
                self.agent_handler = FeishuAgentHandler()
                logger.info("Agent处理器初始化成功")
            except ImportError as e:
                logger.error(f"导入Agent模块失败: {e}")
                self.agent_handler = None
            except Exception as e:
                logger.error(f"初始化Agent处理器失败: {e}")
                self.agent_handler = None
        return self.agent_handler

    def handle_command(self, command_text: str, user_id: str = "") -> Dict:
        """处理飞书命令，支持关键词命令和自然语言Agent处理"""

        # 空消息处理
        if not command_text.strip():
            response = self._create_response("请输入命令，输入 'help' 查看可用命令")
            # 保存助手回复
            try:
                if user_id and response.get("message"):
                    chat_history_service.add_message(user_id, "assistant", response["message"])
            except Exception as e:
                logger.warning(f"保存空消息回复失败: {e}")
            return response

        # 保存用户消息到历史
        try:
            if user_id and command_text.strip():
                chat_history_service.add_message(user_id, "user", command_text.strip())
        except Exception as e:
            logger.warning(f"保存用户消息失败: {e}")

        # 检查是否为关键词命令
        parts = command_text.strip().split()
        cmd = parts[0].lower()
        args = parts[1:] if len(parts) > 1 else []

        # 如果是已知的关键词命令，优先处理
        if cmd in self.commands:
            try:
                result = self.commands[cmd](args, user_id)
                # 保存助手回复
                try:
                    if user_id and result.get("message"):
                        chat_history_service.add_message(user_id, "assistant", result["message"])
                except Exception as e:
                    logger.warning(f"保存助手回复失败: {e}")
                return result
            except Exception as e:
                logger.error(f"Handle command failed {cmd}: {e}")
                error_response = self._create_response(f"处理命令时出错: {str(e)}", is_error=True)
                # 保存错误回复
                try:
                    if user_id and error_response.get("message"):
                        chat_history_service.add_message(user_id, "assistant", error_response["message"])
                except Exception as e2:
                    logger.warning(f"保存错误回复失败: {e2}")
                return error_response

        # 不是关键词命令，尝试Agent处理
        agent_handler = self._get_agent_handler()
        if agent_handler and agent_handler.is_enabled():
            try:
                # 使用同步版本处理（适配现有异步代码）
                result = agent_handler.process_message_sync(command_text, user_id)

                if result.get("success"):
                    response = self._create_response(result["message"])
                    # Agent已经在agent.py中保存了对话历史，这里不再重复保存以避免重复
                    # 注释掉重复保存的代码，只在agent.py中保存一次
                    # try:
                    #     if user_id and response.get("message"):
                    #         chat_history_service.add_message(user_id, "assistant", response["message"])
                    # except Exception as e:
                    #     logger.warning(f"保存Agent成功回复失败: {e}")
                    return response
                else:
                    # Agent处理失败
                    error_msg = result.get("message", "Agent处理失败")
                    if result.get("fallback_recommended"):
                        error_msg += f"\n\n你可以尝试使用关键词命令，输入 'help' 查看可用命令"
                    error_response = self._create_response(error_msg, is_error=True)
                    # 保存错误回复
                    try:
                        if user_id and error_response.get("message"):
                            chat_history_service.add_message(user_id, "assistant", error_response["message"])
                    except Exception as e:
                        logger.warning(f"保存Agent失败回复失败: {e}")
                    return error_response

            except Exception as e:
                logger.error(f"Agent处理失败: {e}", exc_info=True)
                error_response = self._create_response(
                    f"Agent处理失败: {str(e)}\n\n你可以尝试使用关键词命令，输入 'help' 查看可用命令",
                    is_error=True
                )
                # 保存错误回复
                try:
                    if user_id and error_response.get("message"):
                        chat_history_service.add_message(user_id, "assistant", error_response["message"])
                except Exception as e2:
                    logger.warning(f"保存Agent异常回复失败: {e2}")
                return error_response
        else:
            # Agent不可用，返回帮助信息
            error_response = self._create_response(
                f"未识别命令: {command_text}\n\n输入 'help' 查看可用关键词命令\n\n(Agent功能未启用或配置错误)",
                is_error=True
            )
            # 保存错误回复
            try:
                if user_id and error_response.get("message"):
                    chat_history_service.add_message(user_id, "assistant", error_response["message"])
            except Exception as e:
                logger.warning(f"保存Agent不可用回复失败: {e}")
            return error_response

    def _create_response(self, message: str, is_error: bool = False) -> Dict:
        return {
            "success": not is_error,
            "message": message,
            "timestamp": datetime.now().isoformat()
        }

    def _save_conversation_turn(self, user_id: str, user_message: str, assistant_message: str, is_error: bool = False) -> None:
        """保存对话回合

        Args:
            user_id: 飞书用户ID
            user_message: 用户消息
            assistant_message: 助手回复消息
            is_error: 是否为错误回复
        """
        if not user_id:
            logger.warning("没有用户ID，跳过保存对话历史")
            return

        try:
            # 保存用户消息
            if user_message and user_message.strip():
                chat_history_service.add_message(
                    user_id, "user", user_message.strip()
                )

            # 保存助手回复
            if assistant_message and assistant_message.strip():
                chat_history_service.add_message(
                    user_id, "assistant", assistant_message.strip()
                )

            logger.debug(f"已保存对话回合: user_id={user_id}, is_error={is_error}")
        except Exception as e:
            logger.error(f"保存对话回合失败: {e}", exc_info=True)

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
