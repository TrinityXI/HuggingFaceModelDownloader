import asyncio
import json
import logging
from typing import Dict, List, Any, Optional

import litellm
from litellm import acompletion

from app.core.config import settings

logger = logging.getLogger(__name__)


class LLMService:
    """LLM服务，集成litellm支持多模型调用"""

    def __init__(self):
        self.model = settings.LLM_MODEL or "gemini/gemini-1.5-pro"
        self.api_key = settings.LLM_API_KEY
        self.base_url = settings.LLM_BASE_URL
        self.temperature = settings.LLM_TEMPERATURE or 0.1
        self.max_tokens = settings.LLM_MAX_TOKENS or 2000

        # 配置litellm
        if self.api_key:
            litellm.api_key = self.api_key
        if self.base_url:
            litellm.api_base = self.base_url

        # 禁用代理以避免httpx版本兼容性问题
        litellm.drop_params = True

        logger.info(f"LLMService initialized with model: {self.model}, temperature: {self.temperature}")

    async def chat_completion(self, messages: List[Dict], tools: List[Dict] = None) -> Dict:
        """调用LLM进行对话

        Args:
            messages: 消息列表，格式 [{"role": "system/user/assistant", "content": "..."}, ...]
            tools: 可选，工具定义列表

        Returns:
            LLM响应消息字典
        """
        max_retries = 3
        retry_delay = 1  # 秒

        for attempt in range(max_retries):
            try:
                # 准备调用参数
                kwargs = {
                    "model": self.model,
                    "messages": messages,
                    "temperature": self.temperature,
                    "max_tokens": self.max_tokens,
                    "timeout": 30,  # 30秒超时
                }

                if tools:
                    kwargs["tools"] = tools
                    kwargs["tool_choice"] = "auto"

                logger.debug(f"Calling LLM (attempt {attempt + 1}/{max_retries}): model={self.model}, messages={len(messages)}")

                # 调用litellm
                response = await acompletion(**kwargs)

                # 提取消息内容
                message = response.choices[0].message

                logger.debug(f"LLM response received with tool_calls: {hasattr(message, 'tool_calls')}")

                return message

            except Exception as e:
                error_msg = str(e).lower()
                is_retryable = any(keyword in error_msg for keyword in [
                    "timeout", "connection", "network", "rate limit", "quota", "busy", "temporarily"
                ])

                if attempt < max_retries - 1 and is_retryable:
                    logger.warning(f"LLM调用失败 (可重试), 尝试 {attempt + 1}/{max_retries}: {e}")
                    await asyncio.sleep(retry_delay * (attempt + 1))  # 递增延迟
                    continue
                else:
                    logger.error(f"LLM调用失败 (最终): {e}", exc_info=True)
                    raise

    def parse_tool_calls(self, message: Dict) -> List[Dict]:
        """解析工具调用结果

        Args:
            message: LLM响应消息

        Returns:
            工具调用列表
        """
        tool_calls = []

        # 检查是否有tool_calls属性
        if hasattr(message, 'tool_calls') and message.tool_calls:
            for tool_call in message.tool_calls:
                try:
                    # 解析参数
                    arguments = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse tool call arguments: {tool_call.function.arguments}")
                    arguments = {}

                tool_calls.append({
                    "id": tool_call.id,
                    "type": tool_call.type,
                    "function": {
                        "name": tool_call.function.name,
                        "arguments": arguments  # 已解析为字典
                    }
                })

        return tool_calls

    def format_tool_response(self, tool_call_id: str, content: Any) -> Dict:
        """格式化工具响应供LLM使用

        Args:
            tool_call_id: 工具调用ID
            content: 工具执行结果

        Returns:
            格式化后的工具响应消息
        """
        if isinstance(content, (dict, list)):
            content_str = json.dumps(content, ensure_ascii=False)
        else:
            content_str = str(content)

        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content_str
        }