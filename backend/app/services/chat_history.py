import json
import redis
import logging
from datetime import datetime
from typing import List, Dict, Optional, Any
from app.core.config import settings

# Try importing tiktoken for accurate token counting
try:
    import tiktoken
except ImportError:
    tiktoken = None

logger = logging.getLogger(__name__)


class ChatHistoryService:
    """聊天历史服务，使用Redis存储用户对话历史"""

    def __init__(self):
        self.redis_client = None
        self._init_redis()
        self.max_history_messages = 20  # 最大存储消息数（最近20条）
        self.key_prefix = "feishu:chat:history"
        # 历史消息优化配置
        self.enable_deduplication = True  # 是否启用去重
        self.enable_token_estimation = True  # 是否启用改进的token估算
        self.max_history_tokens = 4000  # 历史消息最大token数（默认值）
        self.compression_strategy = "recent_first"  # 压缩策略：recent_first（优先保留最近）, sliding_window（滑动窗口）

        # Initialize tiktoken encoder if available
        self.encoder = None
        if tiktoken:
            try:
                self.encoder = tiktoken.encoding_for_model(settings.LLM_MODEL or "gpt-4o")
            except Exception as e:
                logger.warning(f"Failed to initialize tiktoken: {e}")

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

    def _get_summary_key(self, user_id: str) -> str:
        """Get summary Redis key"""
        return f"{self.key_prefix}:summary:{user_id}"

    def _is_duplicate_message(self, user_id: str, role: str, content: str) -> bool:
        """检查消息是否与最新消息重复

        Args:
            user_id: 飞书用户ID
            role: 角色
            content: 消息内容

        Returns:
            是否重复
        """
        if not self.redis_client:
            return False

        try:
            key = self._get_user_key(user_id)
            # 获取最新的一条消息
            latest_msg_json = self.redis_client.lrange(key, 0, 0)
            if not latest_msg_json:
                return False

            latest_msg = json.loads(latest_msg_json[0])
            # 检查角色和内容是否相同
            return (latest_msg.get("role") == role and
                    latest_msg.get("content") == content)
        except Exception:
            # 如果出现任何异常，当作不重复处理
            return False

    def _estimate_tokens(self, text: str) -> int:
        """估算文本的token数量

        更准确的估算方法：
        1. 使用tiktoken（如果可用）
        2. 降级回启发式方法：
           - 中文字符：每个约2-3个token
           - 英文字符：每个约0.25-0.5个token（4个字符约1个token）

        Args:
            text: 文本内容

        Returns:
            估算的token数量
        """
        if not text:
            return 0

        # Use tiktoken if available
        if self.encoder:
            try:
                return len(self.encoder.encode(text))
            except Exception:
                pass

        # Fallback to heuristic
        # 统计中文字符数（CJK统一表意文字范围）
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        # 其他字符
        other_chars = len(text) - chinese_chars

        # 估算：中文字符每个2.5个token，其他字符每4个字符1个token
        estimated_tokens = int(chinese_chars * 2.5 + other_chars / 4)

        # 确保至少为1
        return max(1, estimated_tokens)

    async def _summarize_history(self, old_summary: str, new_messages: List[Dict]) -> str:
        """Summarize conversation history using LLMService"""
        try:
            from app.services.llm import LLMService
            llm_service = LLMService()
            
            summary_prompt = f"""请简要总结以下对话的历史背景。
原总结: {old_summary}
新对话内容: {json.dumps(new_messages, ensure_ascii=False)}
要求：保留关键信息，如用户意图、已执行的操作、提到的数据集ID等。总结应简洁。"""

            messages = [{"role": "user", "content": summary_prompt}]
            response = await llm_service.chat_completion(messages)
            return response.content
        except Exception as e:
            logger.error(f"Failed to summarize history: {e}")
            return old_summary

    async def save_and_optimize(self, user_id: str, user_input: str, ai_response: str, 
                               mode: str = "token", limit: int = 2000) -> bool:
        """Save conversation and optimize history (Token truncation or Summarization)

        Args:
            user_id: User ID
            user_input: User message
            ai_response: Assistant response
            mode: 'token' (truncate) or 'summary' (summarize)
            limit: Token limit or message count limit depending on mode

        Returns:
            Success status
        """
        if not self.redis_client:
            return False

        # Add new messages
        self.add_message(user_id, "user", user_input)
        self.add_message(user_id, "assistant", ai_response)

        key = self._get_user_key(user_id)
        
        try:
            # Get all messages
            msgs_json = self.redis_client.lrange(key, 0, -1)
            # Reverse to get chronological order [Old -> New] for processing
            msgs = [json.loads(m) for m in reversed(msgs_json)]

            if mode == "token":
                # Truncate based on token count
                current_tokens = sum(self._estimate_tokens(m["content"]) for m in msgs)
                
                if current_tokens > limit and len(msgs) > 2:
                    logger.info(f"History exceeds token limit ({current_tokens}/{limit}). Truncating...")
                    while current_tokens > limit and len(msgs) > 2:
                        removed = msgs.pop(0) # Remove oldest
                        current_tokens -= self._estimate_tokens(removed["content"])
                    
                    # Update Redis
                    self.redis_client.delete(key)
                    # Push back (Oldest -> Newest) using lpush results in [Newest, ..., Oldest] at Head
                    for m in msgs:
                         self.redis_client.lpush(key, json.dumps(m, ensure_ascii=False))
                         
            elif mode == "summary":
                # Summarize if message count exceeds limit
                if len(msgs) >= limit:
                    logger.info(f"History exceeds message count ({len(msgs)}/{limit}). Summarizing...")
                    sum_key = self._get_summary_key(user_id)
                    old_summary = self.redis_client.get(sum_key) or "无"
                    
                    # Generate new summary
                    new_summary = await self._summarize_history(old_summary, msgs)
                    
                    # Update summary and clear raw history (keep last few?)
                    # Keeping last 2 turns (4 messages) for immediate context
                    kept_msgs = msgs[-4:] if len(msgs) > 4 else msgs
                    
                    self.redis_client.set(sum_key, new_summary)
                    
                    self.redis_client.delete(key)
                    for m in kept_msgs:
                        self.redis_client.lpush(key, json.dumps(m, ensure_ascii=False))

            return True
        except Exception as e:
            logger.error(f"Error in save_and_optimize: {e}")
            return False

    def get_context(self, user_id: str) -> List[Dict]:
        """Get full context including summary and raw messages"""
        if not self.redis_client:
            return []
            
        context = []
        
        # Add summary if exists
        sum_key = self._get_summary_key(user_id)
        summary = self.redis_client.get(sum_key)
        if summary:
            context.append({"role": "system", "content": f"历史对话背景总结: {summary}"})
            
        # Add raw messages (chronological order)
        raw_msgs = self.get_user_messages(user_id, limit=50) # Get all available
        # get_user_messages returns [New -> Old] (based on lrange 0..N), but actually implementation
        # of get_user_messages iterates lrange result. 
        # Redis List: [Newest, ..., Oldest] (due to lpush)
        # lrange(0, limit) returns [Newest, ..., Oldest]
        # get_user_messages returns list of dicts.
        # We need chronological order [Old -> New] for context.
        
        if raw_msgs:
            context.extend(reversed(raw_msgs))
            
        return context

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

        # 检查是否与最新消息重复
        if self._is_duplicate_message(user_id, role, content):
            logger.debug(f"消息与最新消息重复，跳过保存: user_id={user_id}, role={role}, content_len={len(content)}")
            return True  # 返回True表示"成功"（因为跳过了重复）

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

        # 计算系统提示词和当前消息的token消耗
        system_tokens = self._estimate_tokens(system_prompt)
        current_message_tokens = self._estimate_tokens(current_message)

        # 为系统提示词、当前消息和部分预留空间预留token
        reserved_tokens = system_tokens + current_message_tokens + 500  # 500作为安全边际
        available_tokens = max_tokens - reserved_tokens

        if available_tokens < 0:
            # 如果系统提示词和当前消息已经超过最大限制，使用原始方法（可能会截断）
            available_tokens = max_tokens // 2  # 分配一半空间给历史
            logger.warning(f"系统提示词和当前消息占用过多token，压缩历史可用空间: {available_tokens}")

        # 构建消息列表
        messages = [{"role": "system", "content": system_prompt}]

        # 添加历史消息（需要反转，因为Redis存储是最新的在前）
        # 我们需要按时间顺序：旧 -> 新
        if history_messages:
            # 反转列表，使最旧的消息在前面
            reversed_history = list(reversed(history_messages))

            # 使用改进的token估算
            total_tokens = 0
            filtered_history = []
            last_role = None
            last_content = None

            for msg in reversed_history:
                content = msg.get("content", "")
                role = msg.get("role", "")

                # 检查是否与上一条消息连续重复（角色和内容都相同）
                if role == last_role and content == last_content:
                    logger.debug(f"跳过连续重复消息: role={role}, content_len={len(content)}")
                    continue

                estimated_tokens = self._estimate_tokens(content)

                if total_tokens + estimated_tokens > available_tokens:
                    break

                # 只保留role和content字段，过滤掉tool_calls和tool_response
                # 因为历史工具调用不应该影响新的LLM调用
                filtered_msg = {"role": role, "content": content}
                filtered_history.append(filtered_msg)
                total_tokens += estimated_tokens

                # 更新上一条消息信息用于重复检查
                last_role = role
                last_content = content

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