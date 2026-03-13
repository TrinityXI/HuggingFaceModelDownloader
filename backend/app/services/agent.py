import json
import logging
import asyncio
from typing import Dict, List, Any, Optional

from app.core.config import settings
from app.services.llm import LLMService
from app.services.tools import ToolRegistry
from app.services.chat_history import chat_history_service

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

    def _save_conversation(self, user_id: str, user_message: str, assistant_response: Dict) -> None:
        """保存对话历史

        Args:
            user_id: 飞书用户ID
            user_message: 用户消息
            assistant_response: 助手回复字典
        """
        if not user_id:
            logger.debug("没有用户ID，跳过保存对话历史")
            return

        if not user_id.strip():
            logger.warning(f"用户ID为空字符串，跳过保存对话历史。user_message: {user_message[:50] if user_message else 'None'}")
            return

        try:
            # 用户消息已经在feishu.py的handle_command中保存，这里不再重复保存
            # 只保存助手回复
            # if user_message and user_message.strip():
            #     chat_history_service.add_message(
            #         user_id, "user", user_message.strip()
            #     )

            # 保存助手回复
            if assistant_response:
                message = assistant_response.get("message", "")
                if message and message.strip():
                    chat_history_service.add_message(
                        user_id, "assistant", message.strip()
                    )
                logger.debug(f"已保存对话历史: user_id={user_id}")
        except Exception as e:
            logger.error(f"保存对话历史失败: {e}", exc_info=True)

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
            system_prompt = """你是一个 Hugging Face 资源下载助手，支持帮助用户管理数据集（dataset）和模型（model）的搜索、下载、状态查询和打包操作。

你的可用工具如下：
1. scan_dataset：扫描和搜索 Hugging Face 数据集 (支持关键词、时间、下载量、标签过滤、按下载量/点赞数排序)
2. search_model：搜索 Hugging Face 模型 (支持关键词、按下载量/点赞数排序)
3. query_dataset：查询单个指定数据集或模型的下载状态 (支持进度和事件日志)
4. list_queue_datasets：列出下载队列中的任务列表 (支持按状态过滤如"正在下载"、按优先级/进度/下载速度排序、返回top N)
5. download_dataset：触发指定数据集或模型的下载 (需传 repo_type='dataset' 或 repo_type='model'，支持优先级和强制重试)
6. tar_dataset：对已下载完成的数据集进行压缩打包 (支持压缩、分片、删除源文件)

请根据用户输入精准判断意图，并优先选择最合适的工具执行操作。

操作原则：
- 用户提到"模型"、"model"时，搜索用 search_model，下载用 download_dataset 并传 repo_type='model'
- 用户提到"数据集"、"dataset"时，搜索用 scan_dataset，下载用 download_dataset 并传 repo_type='dataset'
- 如果用户问"正在下载的top2任务"、"优先级最高的待下载任务"等，使用 list_queue_datasets 工具
- 如果用户明确表达了搜索、查询状态、触发下载或打包的需求，直接调用对应工具并返回结果。
- 如果用户意图不明确或信息不足（如缺少名称、ID 等关键信息），请礼貌地引导用户补充必要细节，而不是直接回复"请澄清"。
  - 示例引导方式：
    - "请告诉我您想搜索或下载的数据集/模型名称或 ID，我可以帮您查找或触发下载。"
    - "您想查询哪个数据集或模型的下载进度？请提供完整名称或路径。"
    - "您希望下载哪个模型？请提供 Hugging Face 上的模型标识（如 Qwen/Qwen2.5-7B）。"
- 所有回复必须简洁、专业，使用中文。
- 只在必要时才询问，不要反复确认已明确的信息。
- 执行工具后，基于工具返回结果给出清晰易懂的反馈。"""

            # 获取可用工具
            tools = self.tool_registry.get_tools_schema()

            # 构建消息历史（包含历史对话）
            messages = chat_history_service.get_formatted_history(
                user_id, system_prompt, user_message, max_tokens=4000
            )

            logger.info(f"处理用户消息: user_id={user_id}, message_length={len(user_message)}, 历史消息数={len(messages)-2}")

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

                    result = {
                        "success": True,
                        "message": final_response.content if hasattr(final_response, 'content') else "操作完成",
                        "tool_calls": len(tool_calls),
                        "successful_tools": successful_tools,
                        "failed_tools": failed_tools,
                        "has_tool_results": True
                    }

                    # 保存对话历史
                    self._save_conversation(user_id, user_message, result)

                    return result

            # 没有工具调用，直接返回LLM回复
            logger.info("无工具调用，直接返回LLM回复")
            result = {
                "success": True,
                "message": response.content if hasattr(response, 'content') else "收到",
                "tool_calls": 0,
                "has_tool_results": False
            }

            # 保存对话历史
            self._save_conversation(user_id, user_message, result)

            return result

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