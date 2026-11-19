"""feishu_stream_connector.py — 飞书企业自建应用（长连接，双向收发）

与 dingtalk_stream_connector.py 同架构：
  - 官方 lark-oapi SDK 的 ws.Client 建立 WebSocket 长连接（无需公网回调）
  - 群/单聊 @机器人 → 收到 im.message.receive_v1 事件 → 回调 on_message → 归一化入库
  - 页面回复飞书消息 → 调 im/v1/messages OpenAPI 真发回群/会话

凭据：FEISHU_APP_ID / FEISHU_APP_SECRET（开放平台「凭证与基础信息」）
事件订阅：im.message.receive_v1，订阅方式=长连接
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import threading

import httpx

from .config import settings

log = logging.getLogger("feishu-stream-connector")

_BASE = "https://open.feishu.cn/open-apis"

# 外部注入：收到飞书消息时的处理函数（main.py 在启动时设置）
_on_message = None

_ws_client = None
_client_ready = False
_APP_ID = ""
_APP_SECRET = ""


def is_configured() -> bool:
    return bool(settings.FEISHU_APP_ID and settings.FEISHU_APP_SECRET)


def set_message_handler(fn):
    global _on_message
    _on_message = fn


def _strip_mentions(text: str) -> str:
    """去掉飞书文本里的 @占位符（如 @_user_1）。"""
    return re.sub(r"@_user_\d+", "", text or "").strip()


def _extract_text(content: str) -> str:
    """从事件 content JSON 提取纯文本。"""
    try:
        data = json.loads(content or "{}")
    except Exception:
        return (content or "").strip()
    return _strip_mentions(data.get("text", ""))


def _build_event_handler():
    """构造 lark EventDispatcherHandler。回调在 ws 线程执行，转交给注入的 handler。"""
    import lark_oapi as lark

    def on_receive(data) -> None:
        try:
            event = data.event
            msg = event.message
            sender_open_id = (event.sender.sender_id.open_id if event.sender else "") or ""
            item = {
                "message_id": msg.message_id,
                "chat_id": msg.chat_id,
                "chat_type": msg.chat_type or "group",     # p2p | group
                "message_type": msg.message_type or "text",
                "content": msg.content or "{}",
                "open_id": sender_open_id,
                "mentions": [m.key for m in (msg.mentions or [])],
            }
            if _on_message:
                _on_message(item)
        except Exception as e:
            log.exception("处理飞书消息异常: %s", e)

    return (lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(on_receive)
            .build())


def _stub_pycryptodome():
    """部分 Windows 环境的应用控制策略会拦截 pycryptodome 的原生 .pyd，
    导致 `import lark_oapi` 直接失败。SDK 仅在「加密回调」场景才真正用 AES，
    本项目不使用该场景，故在 Crypto 不可用时注入桩模块，保证 SDK 可导入。"""
    try:
        import Crypto  # noqa: F401
        return
    except Exception:
        pass
    import sys, types
    try:
        crypto = types.ModuleType("Crypto")
        cipher = types.ModuleType("Crypto.Cipher")
        aes_mod = types.ModuleType("Crypto.Cipher.AES")

        class _AESStub:  # 占位：本项目不会真正调用
            MODE_GCM = 12
            MODE_CBC = 2

            @staticmethod
            def new(*args, **kwargs):
                raise RuntimeError("pycryptodome 被系统策略拦截，且未使用加密回调，不应调用到此")

        aes_mod.AES = _AESStub
        cipher.AES = aes_mod
        crypto.Cipher = cipher
        sys.modules["Crypto"] = crypto
        sys.modules["Crypto.Cipher"] = cipher
        sys.modules["Crypto.Cipher.AES"] = aes_mod
        log.warning("pycryptodome 不可用，已注入桩模块（不影响收发消息）")
    except Exception as e:
        log.warning("注入 Crypto 桩模块失败: %s", e)


def _init_sdk():
    global _ws_client, _client_ready, _APP_ID, _APP_SECRET
    if _client_ready:
        return _ws_client
    _APP_ID = settings.FEISHU_APP_ID
    _APP_SECRET = settings.FEISHU_APP_SECRET
    if not (_APP_ID and _APP_SECRET):
        _client_ready = True
        return None
    _stub_pycryptodome()
    try:
        import lark_oapi as lark
    except Exception as e:
        log.warning("lark-oapi SDK 未安装（pip install lark-oapi）：%s", e)
        _client_ready = True
        return None
    handler = _build_event_handler()
    _ws_client = lark.ws.Client(_APP_ID, _APP_SECRET,
                                event_handler=handler,
                                log_level=lark.LogLevel.INFO)
    _client_ready = True
    return _ws_client


def start_stream_forever():
    client = _init_sdk()
    if not client:
        log.info("未配置飞书应用凭据或 SDK 未安装，跳过飞书长连接")
        return
    log.info("飞书长连接启动中（appId=%s）...", _APP_ID)
    try:
        client.start()
    except Exception as e:
        log.exception("飞书长连接异常退出: %s", e)


def start_in_background():
    t = threading.Thread(target=start_stream_forever, daemon=True, name="feishu-ws")
    t.start()
    return t


# ---------------- REST：token / 发消息 / 传文件 / 下载 ----------------

_token_cache = {"token": "", "expire": 0.0}


async def _get_token() -> str:
    import time
    if _token_cache["token"] and time.time() < _token_cache["expire"]:
        return _token_cache["token"]
    if not (_APP_ID and _APP_SECRET):
        return ""
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(f"{_BASE}/auth/v3/tenant_access_token/internal",
                             json={"app_id": _APP_ID, "app_secret": _APP_SECRET})
            data = r.json()
            token = data.get("tenant_access_token")
            if not token:
                log.error("获取飞书 tenant_access_token 失败: %s", data)
                return ""
            _token_cache["token"] = token
            _token_cache["expire"] = time.time() + int(data.get("expire", 7200)) - 300
            return token
    except Exception as e:
        log.error("获取飞书 token 异常: %s", e)
        return ""


async def send_message(chat_id: str, text: str, reply_message_id: str = "") -> dict:
    """发文本到指定会话（chat_id）。带 reply_message_id 时走"回复消息"接口。
    返回 {"ok": bool, "reason": str}"""
    if not is_configured():
        return {"ok": False, "reason": "未配置飞书应用凭据"}
    token = await _get_token()
    if not token:
        return {"ok": False, "reason": "获取飞书 access_token 失败"}
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {"msg_type": "text", "content": json.dumps({"text": text}, ensure_ascii=False)}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            if reply_message_id:
                url = f"{_BASE}/im/v1/messages/{reply_message_id}/reply"
                r = await c.post(url, headers=headers,
                                 json={"content": body["content"], "msg_type": "text"})
            else:
                url = f"{_BASE}/im/v1/messages?receive_id_type=chat_id"
                r = await c.post(url, headers=headers,
                                 json={"receive_id": chat_id, **body})
            data = r.json()
            if data.get("code") != 0:
                return {"ok": False, "reason": f"飞书发送失败: {data.get('msg') or data}"}
            return {"ok": True}
    except Exception as e:
        return {"ok": False, "reason": f"飞书发送异常: {e}"}


async def upload_file(filename: str, content: bytes) -> dict:
    """上传文件到飞书，返回 {"ok": bool, "fileKey": str, "reason": str}。"""
    if not is_configured():
        return {"ok": False, "fileKey": "", "reason": "未配置飞书应用凭据"}
    token = await _get_token()
    if not token:
        return {"ok": False, "fileKey": "", "reason": "获取飞书 access_token 失败"}
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(f"{_BASE}/im/v1/files",
                             headers={"Authorization": f"Bearer {token}"},
                             data={"file_type": "stream", "file_name": filename},
                             files={"file": (filename, content)})
            data = r.json()
            key = (data.get("data") or {}).get("file_key")
            if data.get("code") != 0 or not key:
                return {"ok": False, "fileKey": "",
                        "reason": f"飞书文件上传失败: {data.get('msg') or data}"}
            return {"ok": True, "fileKey": key}
    except Exception as e:
        return {"ok": False, "fileKey": "", "reason": f"飞书文件上传异常: {e}"}


async def send_file(chat_id: str, file_key: str) -> dict:
    """发文件消息到指定会话。"""
    if not is_configured():
        return {"ok": False, "reason": "未配置飞书应用凭据"}
    token = await _get_token()
    if not token:
        return {"ok": False, "reason": "获取飞书 access_token 失败"}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(f"{_BASE}/im/v1/messages?receive_id_type=chat_id",
                             headers={"Authorization": f"Bearer {token}",
                                      "Content-Type": "application/json"},
                             json={"receive_id": chat_id, "msg_type": "file",
                                   "content": json.dumps({"file_key": file_key})})
            data = r.json()
            if data.get("code") != 0:
                return {"ok": False, "reason": f"飞书文件发送失败: {data.get('msg') or data}"}
            return {"ok": True}
    except Exception as e:
        return {"ok": False, "reason": f"飞书文件发送异常: {e}"}


async def download_resource(message_id: str, file_key: str, res_type: str = "file") -> dict:
    """下载收到的图片/文件资源。res_type: file | image。
    返回 {"ok": bool, "content": bytes, "reason": str}"""
    if not is_configured():
        return {"ok": False, "content": b"", "reason": "未配置飞书应用凭据"}
    token = await _get_token()
    if not token:
        return {"ok": False, "content": b"", "reason": "获取飞书 access_token 失败"}
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.get(f"{_BASE}/im/v1/messages/{message_id}/resources/{file_key}",
                            headers={"Authorization": f"Bearer {token}"},
                            params={"type": res_type})
            if r.status_code != 200:
                return {"ok": False, "content": b"",
                        "reason": f"飞书资源下载失败: HTTP {r.status_code}"}
            return {"ok": True, "content": r.content}
    except Exception as e:
        return {"ok": False, "content": b"", "reason": f"飞书资源下载异常: {e}"}


_user_name_cache: dict = {}


async def get_user_name(open_id: str) -> str:
    """按 open_id 查用户姓名（缓存，失败返回空）。"""
    if not (is_configured() and open_id):
        return ""
    if open_id in _user_name_cache:
        return _user_name_cache[open_id]
    token = await _get_token()
    if not token:
        return ""
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{_BASE}/contact/v3/users/{open_id}",
                            headers={"Authorization": f"Bearer {token}"},
                            params={"user_id_type": "open_id"})
            data = r.json()
            user = (data.get("data") or {}).get("user") or {}
            name = user.get("name") or ""
            if name:
                _user_name_cache[open_id] = name
            return name
    except Exception:
        return ""
