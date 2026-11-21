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

# 运行状态：线程引用 + 停止标志，供"应用连接"页真正启停长连接
_stream_thread: threading.Thread | None = None
_stop_event = threading.Event()
_running = False


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
    """部分 Windows 环境的应用控制策略会拦截 pycryptodome 的原生 .pyd
    （如 Crypto.Cipher._raw_aes*.pyd，WinError 4551），导致 `import lark_oapi`
    直接失败。SDK 仅在「加密回调」场景才真正用 AES，本项目走长连接、不使用
    加密回调，故无条件预注入完整的 Crypto 桩模块，覆盖 AES 及其底层 _raw_*
    依赖，保证 SDK 可导入。桩方法一旦被真正调用会立即报错，绝不静默出错。"""
    import sys, types

    # 已经注入过则跳过（避免重复覆盖真实模块）
    if getattr(_stub_pycryptodome, "_done", False):
        return

    def _mod(name):
        m = types.ModuleType(name)
        sys.modules[name] = m
        return m

    def _stub_cipher():
        raise RuntimeError("pycryptodome 被系统策略拦截，且本项目未使用加密回调，不应调用到此")

    try:
        crypto = _mod("Crypto")
        cipher = _mod("Crypto.Cipher")
        util = _mod("Crypto.Util")
        raw_api = _mod("Crypto.Util._raw_api")
        raw_aes = _mod("Crypto.Cipher._raw_aes")
        raw_aes_1 = _mod("Crypto.Cipher._raw_aes_1")
        hash_mod = _mod("Crypto.Hash")
        sha256 = _mod("Crypto.Hash._sha256")
        random_mod = _mod("Crypto.Random")
        osrng = _mod("Crypto.Random.OSRNG")

        class _AESStub:
            MODE_GCM = 12
            MODE_CBC = 2
            MODE_ECB = 1
            MODE_CTR = 6
            block_size = 16
            key_size = (16, 24, 32)

            @staticmethod
            def new(*args, **kwargs):
                _stub_cipher()

        aes_mod = _mod("Crypto.Cipher.AES")
        aes_mod.AES = _AESStub
        cipher.AES = _AESStub
        raw_aes.new = _stub_cipher
        raw_aes_1.new = _stub_cipher
        raw_api.create_cipher = _stub_cipher
        raw_api.create_mac = _stub_cipher
        sha256.new = _stub_cipher
        hash_mod.sha256 = _stub_cipher
        osrng.new = _stub_cipher
        random_mod.new = _stub_cipher

        crypto.Cipher = cipher
        crypto.Util = util
        crypto.Hash = hash_mod
        crypto.Random = random_mod

        _stub_pycryptodome._done = True
        log.warning("已注入完整 Crypto 桩模块（覆盖 _raw_aes 等被拦截的原生扩展，不影响长连接收发）")
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
    global _running
    client = _init_sdk()
    if not client:
        log.info("未配置飞书应用凭据或 SDK 未安装，跳过飞书长连接")
        _running = False
        return
    log.info("飞书长连接启动中（appId=%s）...", _APP_ID)
    _running = True
    try:
        # 独立线程跑 client.start()，主线程轮询 stop_event
        def _run():
            try:
                client.start()
            except Exception as e:
                log.info("飞书长连接结束: %s", e)
        worker = threading.Thread(target=_run, daemon=True, name="feishu-ws-worker")
        worker.start()
        while not _stop_event.is_set():
            if not worker.is_alive():
                if not _stop_event.is_set():
                    log.info("飞书长连接意外断开，1.5s 后重连")
                    _stop_event.wait(1.5)
                    worker = threading.Thread(target=_run, daemon=True, name="feishu-ws-worker")
                    worker.start()
                else:
                    break
            else:
                _stop_event.wait(0.5)
    finally:
        _running = False
        log.info("飞书长连接已停止")


def start_in_background():
    global _stream_thread, _stop_event
    _stop_event.clear()
    _stream_thread = threading.Thread(target=start_stream_forever, daemon=True, name="feishu-ws")
    _stream_thread.start()
    return _stream_thread


def stop():
    """真正停止飞书长连接：置停止标志 + 关 client，线程自然退出。"""
    global _client_ready, _ws_client, _running
    _stop_event.set()
    try:
        c = _ws_client
        if c is not None:
            close = getattr(c, "stop", None) or getattr(c, "close", None)
            if close:
                close()
    except Exception as e:
        log.warning("关闭飞书 client 异常: %s", e)
    _client_ready = False
    _ws_client = None
    _running = False
    log.info("已请求停止飞书长连接")


def is_running() -> bool:
    return _running and (_stream_thread is not None and _stream_thread.is_alive())


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
                log.error("资源下载失败 msg=%s key=%s type=%s HTTP=%s body=%s",
                          message_id, file_key, res_type, r.status_code, r.text[:300])
                return {"ok": False, "content": b"",
                        "reason": f"飞书资源下载失败: HTTP {r.status_code} {r.text[:120]}"}
            log.info("资源下载成功 msg=%s type=%s %d bytes", message_id, res_type, len(r.content))
            return {"ok": True, "content": r.content}
    except Exception as e:
        return {"ok": False, "content": b"", "reason": f"飞书资源下载异常: {e}"}


_user_name_cache: dict = {}


def _name_map() -> dict:
    """解析 FEISHU_NAME_MAP 配置（open_id=显示名，逗号分隔）。"""
    raw = settings.FEISHU_NAME_MAP or ""
    result = {}
    for part in raw.split(","):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, _, v = part.partition("=")
        if k.strip() and v.strip():
            result[k.strip()] = v.strip()
    return result


async def resolve_user_name(open_id: str) -> str:
    """解析飞书用户显示名：优先用 FEISHU_NAME_MAP 映射，否则实时查通讯录。
    这样用户改映射或改姓名后，下一条消息即用新名。"""
    if not open_id:
        return ""
    mapped = _name_map().get(open_id)
    if mapped:
        return mapped
    return await get_user_name(open_id)


async def get_user_name(open_id: str) -> str:
    """按 open_id 实时查用户姓名（不缓存，用户改姓名后下条消息即用新名）。"""
    if not (is_configured() and open_id):
        return ""
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
                log.info("查询用户姓名 open_id=%s -> %s", open_id, name)
            return name
    except Exception as e:
        log.warning("查询用户姓名失败 open_id=%s: %s", open_id, e)
        return ""
