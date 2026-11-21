"""send_router.py — 发送路由：按 CHANNEL_PLAN 选主通道 → 格式转换 → 发送 → 失败降级备用"""
from __future__ import annotations

from .connectors import dingtalk, wechat_rpa, SendResult
from .format_adapter import to_platform_format
from .config import settings
from . import db

# 主通道计划（与前端 config.js 的 CHANNEL_PLAN 保持一致，可在 DB 层覆盖）
DEFAULT_PLAN = {
    "wechat":   {"primary": "rpa",   "backup": "api"},
    "dingtalk": {"primary": "api",   "backup": "rpa"},
    "feishu":   {"primary": "api",   "backup": "rpa"},
}

FAULT_INJECT = False   # 故障演练：置 True 后下一次发送必定失败


async def route_reply(msg: dict, text: str, channel_hint: str | None, fault: bool) -> SendResult:
    """发送一条回复。channel_hint 非空时用指定通道（重试/切换备用）。
    主通道失败 → 自动切备用通道重发一次 → 仍失败才返回失败。"""
    plan = DEFAULT_PLAN.get(msg["platform"], {"primary": "api", "backup": "rpa"})
    order = ([channel_hint] if channel_hint
             else [plan["primary"], plan["backup"]])

    last_reason = ""
    for ch in order:
        # 故障注入：仅注入主通道（模拟真实故障演示）
        if fault and ch == plan["primary"]:
            return SendResult(False, reason="平台接口返回 429，调用频率超限" if ch == "api"
                              else "RPA 页面元素定位超时，未找到输入框", channel=ch)
        r = await _send_via(ch, msg, text)
        if r.ok:
            r.channel = ch
            return r
        last_reason = r.reason
    return SendResult(False, reason=last_reason,
                      channel=order[0] if order else "api")


async def _send_via(channel: str, msg: dict, text: str) -> SendResult:
    payload = to_platform_format(msg["platform"], text)
    if channel == "api":
        if msg["platform"] == "dingtalk":
            # 优先走企业内部应用机器人真实发消息（有 openConversationId 时）
            conv_id = msg.get("convId") or msg.get("conv_id")
            if conv_id:
                from . import dingtalk_stream_connector as dt
                r = await dt.send_message(conv_id, _prefix_reply_to(text, msg.get("sender"), msg.get("chat")))
                if r["ok"]:
                    return SendResult(True)
                # 机器人发送失败 → 降级到 Webhook（若配置了）
                if settings.DINGTALK_WEBHOOK:
                    return await dingtalk.send(payload, reply_to=msg.get("sender"), chat=msg.get("chat"))
                return SendResult(False, r["reason"])
            # 无 conv_id（种子消息/老消息）→ 走 Webhook
            return await dingtalk.send(payload, reply_to=msg.get("sender"), chat=msg.get("chat"))
        if msg["platform"] == "feishu":
            # 飞书：企业自建应用 OpenAPI 真发（chat_id 存在 conv_id）
            conv_id = msg.get("convId") or msg.get("conv_id")
            if conv_id:
                from . import feishu_stream_connector as fs
                r = await fs.send_message(conv_id, _prefix_reply_to(text, msg.get("sender"), msg.get("chat")))
                if r["ok"]:
                    return SendResult(True)
                return SendResult(False, r["reason"])
            return SendResult(False, "该消息无飞书会话ID（chat_id），无法真实回发")
        # 微信 API 通道：个人号无接口，直接失败（触发降级）
        return SendResult(False, "微信个人号无开放API，请走RPA通道")
    else:  # rpa
        # RPA 也带上“回给谁”，让微信侧粘贴出的文本同样可辨对象
        rpa_text = _prefix_reply_to(text, msg.get("sender"), msg.get("chat"))
        return await wechat_rpa.send(msg.get("chat") or msg["sender"], rpa_text)


def _prefix_reply_to(text: str, sender: str, chat: str) -> str:
    """给回复文本加“回给谁”标注，让目标平台侧也能看清回复对象。
    注意：单聊（私聊）本身就是一对一，不需要 @ 对方，直接发原文；
    只有群聊才加“@发送人（群名）”前缀，用来在群里点明回复对象。"""
    if not sender:
        return text
    # 单聊判定：chat 为空，或 chat 明确标注为“单聊”，都不加 @
    if not chat or "单聊" in chat:
        return text
    label = f"@{sender}（{chat}）"
    return f"{label} {text}"
