import json
import logging
import os
from flask import request, make_response
from flask_restx import Resource
import lark_oapi as lark
from lark_oapi.adapter.flask import *
from lark_oapi.api.im.v1 import *

from app.services.feishu import FeishuCommandHandler, verify_feishu_signature, FeishuBot
from app.core.config import settings

logger = logging.getLogger(__name__)

# 1. 定义 Lark 事件处理回调
def do_p2_im_message_receive_v1(data: P2ImMessageReceiveV1) -> None:
    """处理接收到的消息"""
    try:
        # print(lark.JSON.marshal(data)) # Debug log
        event = data.event
        if not event or not event.message or not event.sender:
            return

        content = event.message.content
        msg_type = event.message.message_type
        user_id = event.sender.sender_id.user_id
        message_id = event.message.message_id
        
        # 只处理文本消息
        if msg_type == "text":
            try:
                content_json = json.loads(content)
                text = content_json.get("text", "").strip()
                
                if text:
                    logger.info(f"收到飞书消息: {text} from {user_id}")
                    # Handle Command
                    handler = FeishuCommandHandler()
                    result = handler.handle_command(text, user_id)
                    
                    # Construct Reply
                    response_text = result.get('message', '命令执行成功')
                    # 如果是错误，加上标识
                    if not result.get('success'):
                        if not response_text.startswith("❌"):
                            response_text = f"❌ {response_text}"

                    # Reply to the message
                    bot = FeishuBot()
                    # 使用 reply_message 接口
                    bot.reply_message(message_id, response_text, msg_type="text")
                    
            except json.JSONDecodeError:
                logger.error(f"Failed to parse message content: {content}")
            except Exception as e:
                logger.error(f"Error handling command: {e}")
                
    except Exception as e:
        logger.error(f"Error in do_p2_im_message_receive_v1: {e}")

def do_customized_event(data: lark.CustomizedEvent) -> None:
    """处理自定义事件"""
    logger.info(f"收到飞书自定义事件: {lark.JSON.marshal(data)}")

# 2. 构建 Lark Event Handler
# 优先使用 VERIFICATION_TOKEN, 如果没有则使用 SECRET (兼容旧配置)
verification_token = settings.FEISHU_VERIFICATION_TOKEN or settings.FEISHU_SECRET
encrypt_key = settings.FEISHU_ENCRYPT_KEY

event_handler = lark.EventDispatcherHandler.builder(
    encrypt_key, 
    verification_token, 
    lark.LogLevel.INFO
).register_p2_im_message_receive_v1(do_p2_im_message_receive_v1) \
 .register_p1_customized_event("message", do_customized_event) \
 .build()


def register_routes(ns, models):
    feishu_webhook_model = models['feishu_webhook_model']
    feishu_webhook_response = models['feishu_webhook_response']
    feishu_notify_model = models['feishu_notify_model']
    feishu_notify_response = models['feishu_notify_response']

    @ns.route('/webhook')
    class FeishuWebhook(Resource):
        @ns.expect(feishu_webhook_model, validate=False)
        # @ns.response(200, '成功', feishu_webhook_response) # Remove strict response model to allow Lark's response
        def post(self):
            try:
                # 兼容性检查: 如果是旧的自定义 Header 方式
                sender_header = request.headers.get('sender')
                if sender_header:
                    logger.info(f"收到飞书Webhook请求 (Legacy) - Sender: {sender_header}")
                    data = request.get_json(force=True, silent=True) or {}
                    message = data.get('message', '')
                    if message:
                        handler = FeishuCommandHandler()
                        result = handler.handle_command(message.strip(), sender_header)
                        response_text = result.get('message', '命令执行成功')
                        if not result.get('success'):
                            response_text = f"❌ {response_text}"
                        return {'success': result.get('success'), 'message': response_text}
                    return {'success': False, 'message': 'Message is empty'}, 400

                # 使用 Lark OAPI Event Handler 处理标准事件
                # parse_req() 会自动读取 Flask request 的 header 和 body
                resp = event_handler.do(parse_req())
                return parse_resp(resp)

            except Exception as e:
                logger.error(f"处理飞书webhook失败: {e}")
                return {'success': False, 'message': str(e)}, 500

    @ns.route('/notify')
    class FeishuNotify(Resource):
        @ns.expect(feishu_notify_model, validate=True)
        @ns.response(200, '成功', feishu_notify_response)
        def post(self):
            try:
                data = request.get_json()
                if not data: return {'success': False, 'message': 'Request body is required'}, 400
                
                bot = FeishuBot()
                success = bot.send_notification(
                    event_type=data.get('event_type'),
                    dataset_id=data.get('dataset_id', ''),
                    message=data.get('message', ''),
                    metadata=data.get('metadata', {})
                )
                return {'success': success, 'message': 'Notification sent' if success else 'Failed'}
            except Exception as e:
                logger.error(f"发送飞书通知失败: {e}")
                return {'success': False, 'message': str(e)}, 500

    @ns.route('/test')
    class FeishuTest(Resource):
        @ns.response(200, '成功', feishu_notify_response)
        def get(self):
            try:
                bot = FeishuBot()
                success = bot.send_message(
                    title="测试通知",
                    content="这是一条来自 HuggingFace Model Downloader 的测试消息\n\n系统运行正常！",
                    msg_type="interactive"
                )
                return {
                    'success': success,
                    'message': 'Test notification sent' if success else 'Test notification failed',
                    'webhook_configured': bool(settings.FEISHU_WEBHOOK_URL),
                    'secret_configured': bool(settings.FEISHU_SECRET)
                }
            except Exception as e:
                logger.error(f"飞书测试失败: {e}")
                return {'success': False, 'message': str(e)}, 500