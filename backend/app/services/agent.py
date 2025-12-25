import json
import logging
import asyncio
from typing import Dict, List, Any, Optional

from app.core.config import settings
from app.services.llm import LLMService
from app.services.tools import ToolRegistry

logger = logging.getLogger(__name__)


class FeishuAgentHandler:
    """飞书Agent处理器，协调LLM和工具调用"""

    def __init__(self):
        if not settings.AGENT_ENABLED:
            logger.warning("Agent功能已禁用，初始化跳过")
            self.enabled = False
            return

        try:
            self.llm_service = LLMService()
            self.tool_registry = ToolRegistry()
            self.enabled = True
            logger.info("FeishuAgentHandler初始化成功")
        except Exception as e:
            logger.error(f"FeishuAgentHandler初始化失败: {e}", exc_info=True)
            self.enabled = False

    def is_enabled(self) -> bool:
        """检查Agent是否启用"""
        return self.enabled and settings.AGENT_ENABLED

    async def process_message(self, user_message: str, user_id: str = "") -> Dict:
        """处理自然语言消息

        Args:
            user_message: 用户消息文本
            user_id: 用户ID（可选）

        Returns:
            处理结果字典
        """
        if not self.is_enabled():
            return {
                "success": False,
                "message": "Agent功能未启用",
                "fallback_recommended": True
            }

        try:
            # 构建系统提示词
            system_prompt = """你是一个HuggingFace数据集下载助手。你可以帮助用户：
1. 扫描和搜索数据集：使用 scan_dataset 工具
2. 查询数据集下载状态：使用 query_dataset 工具
3. 触发数据集下载：使用 download_dataset 工具
4. 压缩打包数据集：使用 tar_dataset 工具

请根据用户意图选择合适的工具。如果用户意图不明确，请询问澄清。

重要：保持回复简洁、专业，使用中文回复。"""

            # 获取可用工具
            tools = self.tool_registry.get_tools_schema()

            # 构建消息历史
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ]

            logger.info(f"处理用户消息: user_id={user_id}, message_length={len(user_message)}")

            # 调用LLM
            response = await self.llm_service.chat_completion(messages, tools)

            # 检查是否有工具调用
            tool_calls = self.llm_service.parse_tool_calls(response)

            if tool_calls:
                logger.info(f"检测到工具调用: {len(tool_calls)} 个")

                # 执行工具调用
                tool_results = []
                for tool_call in tool_calls:
                    tool_name = tool_call["function"]["name"]
                    tool_args = tool_call["function"]["arguments"]

                    logger.info(f"执行工具: {tool_name}, 参数: {tool_args}")

                    # 执行工具
                    result = await self.tool_registry.execute_tool(tool_name, tool_args)

                    # 构建工具响应消息
                    tool_response = self.llm_service.format_tool_response(
                        tool_call["id"],
                        result
                    )

                    tool_results.append({
                        "tool": tool_name,
                        "result": result,
                        "response_message": tool_response
                    })

                # 如果有工具调用结果，发送给LLM进行总结
                if tool_results:
                    # 添加LLM的初始响应（包含工具调用）
                    messages.append({
                        "role": "assistant",
                        "content": response.content if hasattr(response, 'content') and response.content else "",
                        "tool_calls": [
                            {
                                "id": tc["id"],
                                "type": tc["type"],
                                "function": {
                                    "name": tc["function"]["name"],
                                    "arguments": json.dumps(tc["function"]["arguments"]) if isinstance(tc["function"]["arguments"], dict) else tc["function"]["arguments"]
                                }
                            }
                            for tc in tool_calls
                        ]
                    })

                    # 添加工具执行结果
                    for tool_result in tool_results:
                        messages.append(tool_result["response_message"])

                    # 获取最终回复
                    final_response = await self.llm_service.chat_completion(messages)

                    # 汇总工具执行结果
                    successful_tools = []
                    failed_tools = []
                    for tr in tool_results:
                        if tr["result"].get("success", False):
                            successful_tools.append(tr["tool"])
                        else:
                            failed_tools.append(tr["tool"])

                    return {
                        "success": True,
                        "message": final_response.content if hasattr(final_response, 'content') else "操作完成",
                        "tool_calls": len(tool_calls),
                        "successful_tools": successful_tools,
                        "failed_tools": failed_tools,
                        "has_tool_results": True
                    }

            # 没有工具调用，直接返回LLM回复
            logger.info("无工具调用，直接返回LLM回复")
            return {
                "success": True,
                "message": response.content if hasattr(response, 'content') else "收到",
                "tool_calls": 0,
                "has_tool_results": False
            }

        except Exception as e:
            logger.error(f"Agent处理失败: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"Agent处理失败: {str(e)}",
                "error_details": str(e),
                "fallback_recommended": True
            }

    def process_message_sync(self, user_message: str, user_id: str = "") -> Dict:
        """同步版本的消息处理（用于集成到现有同步代码中）

        Args:
            user_message: 用户消息文本
            user_id: 用户ID（可选）

        Returns:
            处理结果字典
        """
        if not self.is_enabled():
            return {
                "success": False,
                "message": "Agent功能未启用",
                "fallback_recommended": True
            }

        try:
            # 使用 asyncio.run 自动管理事件循环生命周期
            return asyncio.run(self.process_message(user_message, user_id))

        except Exception as e:
            logger.error(f"同步Agent处理失败: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"Agent处理失败: {str(e)}",
                "fallback_recommended": True
            }