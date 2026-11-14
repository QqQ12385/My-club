"""ai.py — DeepSeek AI 功能（创新与AI应用加分项）
1. 消息智能分类：text / todo / approval / notice（辅助归一化层打标）
2. 每日摘要：多平台消息聚合摘要
3. 回复建议：根据会话上下文生成 3 条候选回复
无 API Key 时自动降级为规则版，保证闭环不中断。"""
from __future__ import annotations

import json
import httpx

from .config import settings

SYSTEM_CLASSIFY = (
    "你是消息分类器。把用户消息分类为 text(普通) / todo(待办) / approval(审批) / "
    "notice(通知)，只输出JSON：{\"type\":\"...\",\"summary\":\"一句话摘要(20字内)\"}"
)
SYSTEM_SUGGEST = (
    "你是消息回复助手。根据会话上下文给出3条简短得体的中文回复建议，"
    "只输出JSON数组：[\"...\",\"...\",\"...\"]"
)


def _simulated() -> bool:
    return not settings.DEEPSEEK_API_KEY


async def _chat(system: str, user: str) -> str:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(
            f"{settings.DEEPSEEK_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}"},
            json={
                "model": settings.DEEPSEEK_MODEL,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}],
                "temperature": 0.3,
                "max_tokens": 300,
            },
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


async def classify(content: str) -> dict:
    """智能分类 + 摘要。规则兜底：含【待办】→todo，含审批→approval，含通知→notice。"""
    if _simulated():
        low = content.lower()
        if "【待办】" in content or "尽快" in content or "deadline" in low:
            t = "todo"
        elif "审批" in content or "请示" in content:
            t = "approval"
        elif "通知" in content or "会议" in content:
            t = "notice"
        else:
            t = "text"
        return {"type": t, "summary": content[:20], "engine": "rule"}
    try:
        out = await _chat(SYSTEM_CLASSIFY, content)
        data = json.loads(out.strip().removeprefix("```json").removesuffix("```").strip())
        data["engine"] = "deepseek"
        return data
    except Exception:
        return {"type": "text", "summary": content[:20], "engine": "rule"}


async def suggest_reply(context: list[dict]) -> list[str]:
    """根据上下文生成回复建议。context: [{from, text}]"""
    if _simulated():
        last = context[-1]["text"] if context else ""
        if "？" in last or "?" in last:
            return ["好的，我确认一下再答复你", "这个问题我来处理，稍后同步", "收到，我先查下相关资料"]
        return ["收到，马上处理", "好的，我看下回复你", "已安排，稍后同步结果"]
    try:
        transcript = "\n".join(f"{m['from']}: {m['text']}" for m in context[-10:])
        out = await _chat(SYSTEM_SUGGEST, transcript)
        arr = json.loads(out.strip().removeprefix("```json").removesuffix("```").strip())
        return arr if isinstance(arr, list) else [str(arr)]
    except Exception:
        return ["收到，马上处理", "好的，我看下回复你", "已安排，稍后同步结果"]


async def daily_summary(messages: list[dict]) -> str:
    """多平台消息聚合摘要。"""
    if not messages:
        return "今日暂无消息。"
    if _simulated():
        by_plat: dict[str, int] = {}
        for m in messages:
            by_plat[m["platform"]] = by_plat.get(m["platform"], 0) + 1
        parts = [f"{k} {v}条" for k, v in by_plat.items()]
        todos = [m for m in messages if m.get("type") == "todo"]
        s = f"今日共收到 {len(messages)} 条消息（{'、'.join(parts)}）。"
        if todos:
            s += "待办：" + "；".join(t["content"][:30] for t in todos[:3])
        return s
    try:
        lines = "\n".join(f"[{m['platform']}] {m['sender']}: {m['content'][:80]}"
                          for m in messages[:40])
        return await _chat(
            "把多平台消息整理为一段不超过120字的中文工作摘要，突出待办事项，直接输出摘要正文。",
            lines)
    except Exception:
        return "摘要生成失败（AI服务异常），请稍后重试。"
