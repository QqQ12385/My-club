"""connectors/ — 各平台连接器（接收 / 发送 / 健康检查 三方法，新增平台照此实现）

双通道设计（对应 CHANNEL_PLAN）：
  API 通道：钉钉机器人 Webhook —— 有真实凭据时调真实接口，
            无凭据时自动进入模拟模式（simulated=True，闭环照样跑通）
  RPA 通道：simulated 模式模拟采集与发送；power_automate 模式通过 HTTP
            触发本机 Power Automate 流，由流完成桌面端的复制粘贴动作
"""
from __future__ import annotations

import hmac
import hashlib
import base64
import time
import urllib.parse
import json
import os
import httpx

from ..config import settings


class SendResult:
    def __init__(self, ok: bool, reason: str = "", channel: str = ""):
        self.ok = ok
        self.reason = reason
        self.channel = channel


# ---------------------------------------------------------------- 钉钉 API（机器人 Webhook）
class DingTalkConnector:
    key = "dingtalk"

    @property
    def simulated(self) -> bool:
        return not settings.DINGTALK_WEBHOOK

    @staticmethod
    def _sign(secret: str) -> tuple[str, str]:
        ts = str(round(time.time() * 1000))
        string_to_sign = f"{ts}\n{secret}"
        sign = base64.b64encode(
            hmac.new(secret.encode(), string_to_sign.encode(), hashlib.sha256).digest()
        )
        return ts, urllib.parse.quote_plus(sign)

    async def health_check(self) -> dict:
        if self.simulated:
            return {"ok": True, "simulated": True, "reason": "未配置Webhook，模拟模式"}
        return {"ok": True, "simulated": False}

    async def send(self, content: str, reply_to: str = "", chat: str = "") -> SendResult:
        if self.simulated:
            return SendResult(True, "simulated")
        # 钉钉 Webhook 纯文本：把“回给谁”拼进消息体，让群里也能看清回复对象
        text = content
        if reply_to:
            text = f"@{reply_to}（{chat}） {content}" if chat else f"@{reply_to} {content}"
        url = settings.DINGTALK_WEBHOOK
        if settings.DINGTALK_SECRET:
            ts, sign = self._sign(settings.DINGTALK_SECRET)
            url += f"&timestamp={ts}&sign={sign}"
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.post(url, json={"msgtype": "text", "text": {"content": text}})
                data = r.json()
                if data.get("errcode") != 0:
                    return SendResult(False, f"钉钉Webhook错误: {data.get('errmsg')}")
                return SendResult(True)
        except Exception as e:
            return SendResult(False, f"钉钉发送异常: {e}")


# ---------------------------------------------------------------- 微信 RPA 通道
class WeChatRPAConnector:
    """个人微信无开放接口 → RPA 为主通道。
    power_automate 模式：HTTP 触发 Power Automate 流（流内完成桌面端
    定位窗口 → 粘贴到输入框 → 发送 的鼠标键盘模拟）。
    simulated 模式：延迟 0.9s 后返回成功，闭环可演示。"""
    key = "wechat"

    @property
    def simulated(self) -> bool:
        return settings.RPA_MODE != "power_automate" or not settings.RPA_FLOW_URL

    async def health_check(self) -> dict:
        if self.simulated:
            return {"ok": True, "simulated": True, "reason": "RPA模拟模式"}
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.post(settings.RPA_FLOW_URL, json={"action": "health"})
                r.raise_for_status()
                return {"ok": True, "simulated": False}
        except Exception as e:
            return {"ok": False, "reason": str(e)}

    async def send(self, contact: str, content: str) -> SendResult:
        if self.simulated:
            import asyncio
            await asyncio.sleep(0.3)
            return SendResult(True, "simulated")
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.post(settings.RPA_FLOW_URL, json={
                    "action": "send", "contact": contact, "content": content,
                })
                data = r.json()
                if not data.get("ok", False):
                    return SendResult(False, data.get("reason", "RPA执行失败"))
                return SendResult(True)
        except httpx.TimeoutException:
            return SendResult(False, "RPA 页面元素定位超时，未找到输入框")
        except Exception as e:
            return SendResult(False, f"RPA发送异常: {e}")


dingtalk = DingTalkConnector()
wechat_rpa = WeChatRPAConnector()

CONNECTORS = {c.key: c for c in (dingtalk, wechat_rpa)}
