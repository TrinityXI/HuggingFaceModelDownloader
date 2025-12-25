import json
import redis
import logging
from datetime import datetime
from typing import List, Dict, Optional
from app.core.config import settings

logger = logging.getLogger(__name__)


class ChatHistoryService:
    """聊天历史服务，使用Redis存储用户对话历史"""

    def __init__(self):
        self.redis_client = None
        self._init_redis()
        self.max_history_messages = 20  # 最大存储消息数（最近20条）
        self.key_prefix = "feishu:chat:history"

    def _init_redis(self):
        """初始化Redis连接"""
        try:
            self.redis_client = redis.Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                db=settings.REDIS_DB,
                password=settings.REDIS_PASSWORD,
                decode_responses=True
            )
            self.redis_client.ping()
            logger.info("ChatHistoryService Redis连接成功")
        except Exception as e:
            logger.warning(f"ChatHistoryService Redis连接失败: {e}")
            self.redis_client = None

    def _get_user_key(self, user_id: str) -> str:
        """获取用户Redis key"""
        return f"{self.key_prefix}:{user_id}"

    def add_message(self, user_id: str, role: str, content: str,
                   tool_calls: Optional[List[Dict]] = None,
                   tool_response: Optional[Dict] = None) -> bool:
        """添加消息到用户历史

        Args:
            user_id: 飞书用户ID
            role: 角色 ('user', 'assistant', 'system', 'tool')
            content: 消息内容
            tool_calls: 工具调用信息（可选）
            tool_response: 工具响应信息（可选）

        Returns:
            是否成功
        """
        if not self.redis_client:
            logger.warning("Redis连接不可用，跳过保存消息历史")
            return False

        # 验证用户ID
        if not user_id or not user_id.strip():
            logger.debug(f"无效的用户ID，跳过保存消息历史: user_id={repr(user_id)}")
            return False

        try:
            message = {
                "role": role,
                "content": content,
                "timestamp": datetime.now().isoformat()
            }

            if tool_calls:
                message["tool_calls"] = tool_calls
            if tool_response:
                message["tool_response"] = tool_response

            key = self._get_user_key(user_id)

            # 使用lpush添加到列表开头，然后trim保持最大长度
            self.redis_client.lpush(key, json.dumps(message, ensure_ascii=False))
            self.redis_client.ltrim(key, 0, self.max_history_messages - 1)

            # 设置过期时间（7天）
            self.redis_client.expire(key, 7 * 24 * 3600)

            logger.debug(f"添加消息到用户历史: user_id={user_id}, role={role}, content_len={len(content)}")
            return True

        except Exception as e:
            logger.error(f"添加消息历史失败: {e}")
            return False

    def get_user_messages(self, user_id: str, limit: int = 10) -> List[Dict]:
        """获取用户历史消息（按时间倒序，最新的在前面）

        Args:
            user_id: 飞书用户ID
            limit: 获取的消息数量限制

        Returns:
            消息列表，每个消息包含role和content
        """
        if not self.redis_client:
            logger.warning("Redis连接不可用，返回空历史")
            return []

        # 验证用户ID
        if not user_id or not user_id.strip():
            logger.debug(f"无效的用户ID，返回空历史: user_id={repr(user_id)}")
            return []

        try:
            key = self._get_user_key(user_id)

            # 获取最新的limit条消息
            messages_json = self.redis_client.lrange(key, 0, limit - 1)

            messages = []
            for msg_json in messages_json:
                try:
                    msg = json.loads(msg_json)
                    # 转换为OpenAI格式的消息对象
                    message_item = {"role": msg["role"], "content": msg["content"]}

                    # 如果包含tool_calls或tool_response，添加到消息中
                    if "tool_calls" in msg:
                        message_item["tool_calls"] = msg["tool_calls"]
                    if "tool_response" in msg:
                        message_item["tool_response"] = msg["tool_response"]

                    messages.append(message_item)
                except Exception as e:
                    logger.warning(f"解析消息JSON失败: {e}, content={msg_json}")

            logger.debug(f"获取用户历史消息: user_id={user_id}, count={len(messages)}")
            return messages

        except Exception as e:
            logger.error(f"获取消息历史失败: {e}")
            return []

    def clear_user_history(self, user_id: str) -> bool:
        """清除用户历史消息

        Args:
            user_id: 飞书用户ID

        Returns:
            是否成功
        """
        if not self.redis_client:
            return False

        try:
            key = self._get_user_key(user_id)
            self.redis_client.delete(key)
            logger.info(f"清除用户历史消息: user_id={user_id}")
            return True
        except Exception as e:
            logger.error(f"清除用户历史失败: {e}")
            return False

    def get_formatted_history(self, user_id: str, system_prompt: str,
                             current_message: str, max_tokens: int = 4000) -> List[Dict]:
        """获取格式化后的对话历史，用于LLM调用

        Args:
            user_id: 飞书用户ID
            system_prompt: 系统提示词
            current_message: 当前用户消息
            max_tokens: 最大token数限制（粗略估计）

        Returns:
            格式化后的消息列表，包含系统提示、历史消息和当前消息
        """
        # 获取历史消息
        history_messages = self.get_user_messages(user_id, limit=20)

        # 构建消息列表
        messages = [{"role": "system", "content": system_prompt}]

        # 添加历史消息（需要反转，因为Redis存储是最新的在前）
        # 我们需要按时间顺序：旧 -> 新
        if history_messages:
            # 反转列表，使最旧的消息在前面
            reversed_history = list(reversed(history_messages))

            # 简单的token估算（中文字符数 * 2作为token估算）
            total_chars = 0
            filtered_history = []

            for msg in reversed_history:
                content = msg.get("content", "")
                chars = len(content)
                # 粗略估算：中文字符每个约2-3个token，英文单词每个约1.3个token
                # 这里用字符数 * 2作为保守估计
                estimated_tokens = chars * 2

                if total_chars + estimated_tokens > max_tokens:
                    break

                # 只保留role和content字段，过滤掉tool_calls和tool_response
                # 因为历史工具调用不应该影响新的LLM调用
                filtered_msg = {"role": msg["role"], "content": content}
                filtered_history.append(filtered_msg)
                total_chars += estimated_tokens

            messages.extend(filtered_history)

        # 添加当前消息
        messages.append({"role": "user", "content": current_message})

        logger.debug(f"格式化历史消息: user_id={user_id}, 历史消息数={len(history_messages)}, 过滤后={len(messages)-2}")
        return messages

    def save_conversation_turn(self, user_id: str, user_message: str,
                              assistant_response: Dict) -> bool:
        """保存完整的对话回合（用户消息 + 助手回复）

        Args:
            user_id: 飞书用户ID
            user_message: 用户消息
            assistant_response: 助手回复（包含消息内容和可能的工具调用）

        Returns:
            是否成功
        """
        success = True

        # 保存用户消息
        if user_message:
            success = self.add_message(user_id, "user", user_message) and success

        # 保存助手回复
        if assistant_response:
            content = assistant_response.get("content", "")
            tool_calls = assistant_response.get("tool_calls")

            # 如果有工具调用，保存工具调用信息
            if tool_calls:
                success = self.add_message(
                    user_id, "assistant",
                    content if content else "工具调用执行中...",
                    tool_calls=tool_calls
                ) and success
            else:
                success = self.add_message(user_id, "assistant", content) and success

        return success


# 全局实例
chat_history_service = ChatHistoryService()