import json
import logging
import os
from flask import request
from flask_restx import Resource
from app.services.feishu import FeishuCommandHandler, verify_feishu_signature, FeishuBot
from app.core.config import settings

logger = logging.getLogger(__name__)

def register_routes(ns, models):
    feishu_webhook_model = models['feishu_webhook_model']
    feishu_webhook_response = models['feishu_webhook_response']
    feishu_notify_model = models['feishu_notify_model']
    feishu_notify_response = models['feishu_notify_response']

    @ns.route('/webhook')
    class FeishuWebhook(Resource):
        @ns.expect(feishu_webhook_model, validate=False)
        @ns.response(200, '成功', feishu_webhook_response)
        def post(self):
            try:
                # 打印请求头和请求体用于调试
                logger.info(f"收到飞书Webhook请求 - Headers: {dict(request.headers)}")
                request_body_raw = request.get_data(as_text=True)
                logger.info(f"收到飞书Webhook请求 - Body: {request_body_raw}")

                data = request.get_json(force=True, silent=True)
                if data is None:
                    # 尝试解析 text body (针对某些非标准 content-type)
                    try:
                        data = json.loads(request.get_data(as_text=True))
                    except:
                        logger.warning(f"无法解析JSON请求体")
                        return {'success': False, 'message': 'Invalid JSON body'}, 400

                # 1. 处理 URL Verification (标准飞书回调验证)
                if data.get('type') == 'url_verification':
                    return {'challenge': data.get('challenge', '')}

                # 2. 新接口格式: Header['sender'] + Body['message']
                sender_header = request.headers.get('sender')
                if sender_header:
                    message = data.get('message', '')
                    if message:
                        handler = FeishuCommandHandler()
                        result = handler.handle_command(message.strip(), sender_header)
                        response_text = result.get('message', '命令执行成功')
                        # 如果是错误，可能需要加上标识? 这里保持原样
                        if not result.get('success'):
                            response_text = f"❌ {response_text}"
                        
                        return {'success': result.get('success'), 'message': response_text}
                    return {'success': False, 'message': 'Message is empty'}, 400

                # 3. 标准飞书 Event 格式 (原有逻辑)
                timestamp = request.headers.get('X-Lark-Request-Timestamp', '')
                signature = request.headers.get('X-Lark-Request-Signature', '')
                request_body = request.get_data(as_text=True)
                secret = settings.FEISHU_SECRET
                
                if not verify_feishu_signature(timestamp, signature, request_body, secret):
                    logger.warning(f"飞书签名验证失败: timestamp={timestamp}")
                    return {'success': False, 'message': 'Invalid signature'}, 401
                
                event = data.get('event', {})
                if event.get('type') == 'message':
                    message_type = event.get('msg_type', '')
                    content = event.get('content', '')
                    if message_type == 'text':
                        try:
                            content_json = json.loads(content)
                            command_text = content_json.get('text', '').strip()
                            user_id = event.get('sender', {}).get('sender_id', {}).get('user_id', '')
                            if command_text:
                                handler = FeishuCommandHandler()
                                result = handler.handle_command(command_text, user_id)
                                response_text = result.get('message', '命令执行成功') if result.get('success') else f"❌ {result.get('message')}"
                                return {'msg_type': 'text', 'content': {'text': response_text}}
                        except json.JSONDecodeError:
                            logger.error(f"飞书消息解析失败: {content}")
                    return {'success': True, 'message': 'Message received'}
                return {'success': True, 'message': 'Event processed'}
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
