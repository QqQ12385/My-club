"""format_adapter.py — 消息格式统一转换（内部统一格式 ↔ 各平台格式）
与前端 js/core/format-adapter.js 保持同一套映射规则，答辩时两栏 JSON 对照演示。"""
from __future__ import annotations

import json


def to_platform_format(platform: str, text: str) -> str:
    """内部统一文本 → 平台原始格式（返回平台 API 所需的 content 字符串）"""
    if platform == "dingtalk":
        # 钉钉 text 消息；@人在 webhooks 中由 at 字段处理
        return text
    if platform == "wechat":
        # RPA 直接往输入框粘贴纯文本
        return text
    return text


def from_platform_format(platform: str, raw: dict) -> str:
    """平台原始消息 → 内部统一文本（归一化层用）"""
    if platform == "dingtalk":
        return raw.get("content", {}).get("text", "")
    return str(raw.get("text", raw))
