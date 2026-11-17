"""normalize.py — 归一化层：各平台原始消息 → 内部统一 Message → 去重 → 落库"""
from __future__ import annotations

import time
import uuid

from . import db


def normalize_incoming(raw: dict) -> dict:
    """
    raw: {platform, sender, chat, content, msg_key?}
    归一化为前端契约的 Message 结构并落库。
    去重规则：
      有 msg_key → 键 "platform:msg_key"
      RPA 无 ID  → 键 "platform:sender+time+content哈希"（README 第4.6节约定）
    """
    platform = raw["platform"]
    t = time.strftime("%H:%M")
    now_day = "today"
    dedup = (f"{platform}:{raw['msg_key']}" if raw.get("msg_key")
             else f"{platform}:{db.dedup_hash(platform, raw['sender'], t, raw['content'])}")

    dup = db.query("SELECT id FROM messages WHERE dedup_key=?", (dedup,))
    if dup:
        return {"duplicated": True, "id": dup[0]["id"]}

    mid = f"m{uuid.uuid4().hex[:8]}"
    content = raw["content"]
    mtype = "todo" if "【待办】" in content else "text"
    owner = raw.get("owner") or "gary"   # 消息归属账号（默认管理员 gary）

    db.execute(
        "INSERT INTO messages(id,platform,msg_key,sender,chat,time,day,type,content,"
        "status,unread,pinned,muted,dedup_key,conv_id,owner,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?, 'received',1,0,0,?,?,?,?)",
        (mid, platform, raw.get("msg_key"), raw["sender"], raw.get("chat") or platform,
         t, now_day, mtype, content, dedup, raw.get("conv_id"), owner, time.time()))
    db.execute("INSERT INTO thread(msg_id,from_side,text,time,send_status,channel)"
               " VALUES(?,?,?,?,?,?)", (mid, "them", content, t, None, None))
    db.add_trace(mid, "已接收", f"来自{platform}（{raw['sender']}）")

    message = {
        "id": mid, "platform": platform, "sender": raw["sender"],
        "chat": raw.get("chat") or platform, "time": t, "day": now_day,
        "type": mtype, "content": content, "status": "received", "owner": owner,
    }
    return {"duplicated": False, "id": mid, "message": message}
