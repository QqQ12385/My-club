"""dingtalk_stream_connector.py — 钉钉企业内部应用（Stream 长连接，双向收发）

与 connectors/__init__.py 里的 DingTalkConnector（自定义机器人 Webhook，只能发）互补：
  - 本连接器基于钉钉官方 dingtalk-stream SDK，建立长连接（无需公网回调）
  - 群/单聊里 @机器人 → 收到消息 → 回调 on_message → 归一化 + AI 分类 + WS 推送
  - 页面回复钉钉消息 → 主动调机器人发消息 OpenAPI → 真发回群里

凭据：DINGTALK_APP_KEY / DINGTALK_APP_SECRET（企业内部应用 Client ID / Secret）
"""
from __future__ import annotations

import asyncio
import json
import logging
import platform
import threading

import httpx

from .config import settings

log = logging.getLogger("dingtalk-stream-connector")

_APP_KEY = ""
_APP_SECRET = ""

# 懒加载 dingtalk_stream（装了 SDK 才 import，避免模拟/无凭据时崩）
_stream_client = None
_client_ready = False


def _init_sdk():
    """首次调用时 import SDK 并返回可用状态。未装 SDK 或未配凭据返回 None。"""
    global _stream_client, _client_ready, _APP_KEY, _APP_SECRET
    if _client_ready:
        return _stream_client
    _APP_KEY = settings.DINGTALK_APP_KEY
    _APP_SECRET = settings.DINGTALK_APP_SECRET
    if not (_APP_KEY and _APP_SECRET):
        _client_ready = True
        return None
    try:
        from dingtalk_stream import ChatbotHandler, ChatbotMessage
        from dingtalk_stream.credential import Credential
        from dingtalk_stream.stream import DingTalkStreamClient
        from dingtalk_stream.frames import AckMessage
    except Exception as e:  # SDK 未安装
        log.warning("dingtalk-stream SDK 未安装：%s", e)
        _client_ready = True
        return None

    handler = _build_handler(ChatbotHandler, ChatbotMessage, AckMessage)
    credential = Credential(_APP_KEY, _APP_SECRET)
    client = DingTalkStreamClient(credential)
    client.register_callback_handler('/v1.0/im/bot/messages/get', handler)
    _stream_client = client
    _client_ready = True
    return client


def _build_handler(ChatbotHandler, ChatbotMessage, AckMessage):
    """构造回调 handler。on_message 接收原始 dict，交给外部注入的处理函数。"""
    class _Handler(ChatbotHandler):
        async def process(self, message):
            try:
                data = message.data
                if isinstance(data, dict):
                    incoming = ChatbotMessage.from_dict(data)
                else:
                    incoming = data
                # 外部注入的业务处理（main.py 里设置）
                if _on_message:
                    _on_message(incoming)
            except Exception as e:
                log.exception("处理钉钉消息异常: %s", e)
            return AckMessage.STATUS_OK, 'OK'

    return _Handler()


# 外部注入：收到钉钉消息时的处理函数（main.py 在启动时设置）
_on_message = None


def set_message_handler(fn):
    global _on_message
    _on_message = fn


def start_stream_forever():
    """在后台线程里跑 Stream 长连接（阻塞式）。无凭据时直接返回。"""
    client = _init_sdk()
    if not client:
        log.info("未配置钉钉企业应用凭据，跳过 Stream 接收")
        return
    log.info("钉钉 Stream 长连接启动中（clientId=%s）...", _APP_KEY)
    try:
        client.start_forever()
    except Exception as e:
        log.exception("钉钉 Stream 异常退出: %s", e)


def start_in_background():
    """非阻塞：起一个守护线程跑 Stream。"""
    t = threading.Thread(target=start_stream_forever, daemon=True, name="dingtalk-stream")
    t.start()
    return t


async def upload_media(filename: str, content: bytes) -> dict:
    """上传媒体文件到钉钉，返回 {"ok": bool, "mediaId": str, "reason": str}。
    走机器人媒体上传 OpenAPI（文件≤20MB）。"""
    if not (_APP_KEY and _APP_SECRET):
        return {"ok": False, "mediaId": "", "reason": "未配置钉钉企业应用凭据"}
    token = await _get_token()
    if not token:
        return {"ok": False, "mediaId": "", "reason": "获取钉钉 access_token 失败"}
    url = "https://api.dingtalk.com/v1.0/robot/media/upload"
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(url,
                             params={"robotCode": _APP_KEY},
                             headers={"x-acs-dingtalk-access-token": token},
                             files={"media": (filename, content)})
            data = r.json()
            media_id = data.get("mediaId")
            if r.status_code != 200 or not media_id:
                return {"ok": False, "mediaId": "",
                        "reason": f"钉钉媒体上传失败: {data.get('message') or data}"}
            return {"ok": True, "mediaId": media_id}
    except Exception as e:
        return {"ok": False, "mediaId": "", "reason": f"钉钉媒体上传异常: {e}"}


async def send_file(open_conversation_id: str, media_id: str, filename: str) -> dict:
    """通过机器人发送文件消息到指定群/会话（msgKey=sampleFile）。"""
    if not (_APP_KEY and _APP_SECRET):
        return {"ok": False, "reason": "未配置钉钉企业应用凭据"}
    token = await _get_token()
    if not token:
        return {"ok": False, "reason": "获取钉钉 access_token 失败"}
    url = "https://api.dingtalk.com/v1.0/robot/oToMessages/batchSend"
    headers = {
        "Content-Type": "application/json",
        "x-acs-dingtalk-access-token": token,
    }
    body = {
        "robotCode": _APP_KEY,
        "openConversationId": open_conversation_id,
        "msgKey": "sampleFile",
        "msgParam": json.dumps({"mediaId": media_id, "fileName": filename},
                               ensure_ascii=False),
    }
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(url, headers=headers, json=body)
            data = r.json()
            if r.status_code != 200 or data.get("processQueryKey") is None:
                return {"ok": False, "reason": f"钉钉文件发送失败: {data.get('message') or data}"}
            return {"ok": True}
    except Exception as e:
        return {"ok": False, "reason": f"钉钉文件发送异常: {e}"}


async def send_message(open_conversation_id: str, text: str, at_user_id: str = "") -> dict:
    """通过机器人主动发消息到指定群/会话（页面回复钉钉消息走这里）。

    走 OpenAPI 机器人发消息（非 session_webhook，可脱离会话上下文主动发）。
    返回 {"ok": bool, "reason": str}
    """
    if not (_APP_KEY and _APP_SECRET):
        return {"ok": False, "reason": "未配置钉钉企业应用凭据"}
    token = await _get_token()
    if not token:
        return {"ok": False, "reason": "获取钉钉 access_token 失败"}
    url = "https://api.dingtalk.com/v1.0/robot/oToMessages/batchSend"
    headers = {
        "Content-Type": "application/json",
        "x-acs-dingtalk-access-token": token,
    }
    body = {
        "robotCode": _APP_KEY,
        "openConversationId": open_conversation_id,
        "msgKey": "sampleText",
        "msgParam": json.dumps({"content": text}, ensure_ascii=False),
    }
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(url, headers=headers, json=body)
            data = r.json()
            if r.status_code != 200 or data.get("processQueryKey") is None:
                return {"ok": False, "reason": f"钉钉发送失败: {data.get('message') or data}"}
            return {"ok": True}
    except Exception as e:
        return {"ok": False, "reason": f"钉钉发送异常: {e}"}


_token_cache = {"token": "", "expire": 0.0}


async def _get_token() -> str:
    import time
    if _token_cache["token"] and time.time() < _token_cache["expire"]:
        return _token_cache["token"]
    url = "https://api.dingtalk.com/v1.0/oauth2/accessToken"
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(url, json={"appKey": _APP_KEY, "appSecret": _APP_SECRET})
            data = r.json()
            token = data.get("accessToken")
            if not token:
                log.error("获取钉钉 token 失败: %s", data)
                return ""
            _token_cache["token"] = token
            _token_cache["expire"] = time.time() + int(data.get("expireIn", 7200)) - 300
            return token
    except Exception as e:
        log.error("获取钉钉 token 异常: %s", e)
        return ""


def is_configured() -> bool:
    return bool(settings.DINGTALK_APP_KEY and settings.DINGTALK_APP_SECRET)
