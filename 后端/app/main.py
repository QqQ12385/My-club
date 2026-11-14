"""main.py — FastAPI 入口：全部 REST 接口 + WebSocket 推送 + 发送路由（主备降级）

对接契约：前端 README 第四节（成员 B 交付）
  WS_URL   = ws://localhost:8080/ws
  API_BASE = http://localhost:8080/api
推送格式：{"type":"new_message","data":<Message>}
          {"type":"status_update","data":{"id","status"}}
"""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
import uuid

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query, Header, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from pathlib import Path

from . import db
from .ai import classify, suggest_reply, daily_summary
from .connectors import dingtalk, wechat_rpa, CONNECTORS, SendResult
from .config import settings
from .normalize import normalize_incoming   # 归一化层
from .send_router import route_reply        # 发送路由（主备降级）
from .ws import hub
from . import dingtalk_stream_connector as dt_stream   # 钉钉企业内部应用（Stream 双向收发）

app = FastAPI(title="统一消息管理后端", version="1.0.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

tokens: dict[str, str] = {}   # token -> account

APPS_SEED = [
    {"key": "wechat", "connected": 1, "account": "wxid_gary_1024",
     "org": "个人微信 · RPA接入", "last_sync": "", "success_rate": "98%",
     "since": "2024-05-10",
     "note": "Power Automate 桌面端采集" + ("（模拟模式）" if wechat_rpa.simulated else "")},
    {"key": "dingtalk", "connected": 1, "account": "gary@xingchen-tech.com",
     "org": "星辰科技 · 钉钉组织", "last_sync": "", "success_rate": "100%",
     "since": "2024-04-15",
     "note": "企业内部机器人 · Webhook回调" + ("（模拟模式）" if dingtalk.simulated else "")},
]

PROFILE_DEFAULT = {
    "id": "U1024", "name": "Gary", "cnName": "高远", "initial": "高",
    "role": "系统管理员", "dept": "信息化中心 · 协同办公组", "org": "星辰科技",
    "staffNo": "XC-1024", "email": "gary@xingchen-tech.com", "phone": "138****6620",
    "city": "深圳", "tz": "GMT+8 北京时间", "joinedAt": "2024-03-12",
    "loginType": "企业微信扫码", "twoFactor": True,
    "lastLogin": {"time": "", "device": "Windows · Chrome", "ip": "127.0.0.1"},
    "prefs": {"notify": True, "dnd": True, "dndRange": "22:00 - 08:00", "route": "api"},
    "actions": [],
}


def _on_dingtalk_message(incoming) -> None:
    """钉钉 Stream 收到消息的回调：归一化 + AI 分类 + WS 推送。
    用线程池调度，避免阻塞 Stream 的 ack 返回。"""
    try:
        text = incoming.get_text_list()
        content = (text[0] if text else "").strip()
        if not content:
            return
        sender = incoming.sender_nick or "钉钉成员"
        chat = incoming.conversation_title or ("群聊" if incoming.conversation_type == "2" else "单聊")
        msg_key = incoming.message_id
        raw = {
            "platform": "dingtalk",
            "sender": sender,
            "chat": chat,
            "content": content,
            "msg_key": msg_key,
            "conv_id": incoming.conversation_id or "",
        }
        asyncio.run_coroutine_threadsafe(_ingest(raw), _main_loop)
    except Exception as e:
        log_dt.exception("钉钉消息入站处理异常: %s", e)


def _start_dingtalk_stream():
    if not dt_stream.is_configured():
        return
    dt_stream.set_message_handler(_on_dingtalk_message)
    dt_stream.start_in_background()


_main_loop: asyncio.AbstractEventLoop = None
log_dt = logging.getLogger("dingtalk-ingest")


@app.on_event("startup")
def startup():
    global _main_loop
    _main_loop = asyncio.get_event_loop()
    db.init_db()
    _seed_admin()
    _start_dingtalk_stream()
    # 应用连接种子
    for a in APPS_SEED:
        db.execute(
            "INSERT OR IGNORE INTO apps(key,connected,account,org,last_sync,success_rate,since,note)"
            " VALUES(:key,:connected,:account,:org,:last_sync,:success_rate,:since,:note)", a)
    # 个人资料种子
    if not db.query("SELECT 1 FROM profile WHERE id=1"):
        db.execute("INSERT INTO profile(id, data) VALUES(1, ?)", (json.dumps(PROFILE_DEFAULT, ensure_ascii=False),))
    # 演示种子消息（与前端演示模式一致）
    if not db.query("SELECT 1 FROM messages LIMIT 1"):
        seed_demo_messages()


def seed_demo_messages():
    rows = [
        ("m001", "dingtalk", "张经理", "项目冲刺群", "09:02", "today", "text",
         "今天下午3点评审会别忘了，会议室B栋302", "received"),
        ("m002", "dingtalk", "HR-李姐", "全员通知群", "09:15", "today", "todo",
         "【待办】请今天18:00前在OA补填11月考勤异常，逾期锁定", "received"),
        ("m003", "dingtalk", "技术群-小陈", "研发协作群", "09:40", "today", "text",
         " Gary 线上环境那个接口报错你看到了吗", "received"),
        ("m004", "wechat", "客户-王总", "微信", "10:05", "today", "text",
         "合同扫描件发我一份，今天要用", "received"),
        ("m005", "dingtalk", "前端-阿珂", "项目群-钉钉", "10:22", "today", "text",
         "统一入口的筛选联动bug我修好了，下午提测", "received"),
        ("m006", "wechat", "老婆", "微信", "11:00", "today", "text",
         "晚上早点回来吃饭", "received"),
        ("m007", "dingtalk", "财务-周会计", "财务对接群", "昨天", "yesterday", "text",
         "10月差旅报销审批到你这了，麻烦处理下", "replied"),
        ("m008", "dingtalk", "IT值班", "运维告警群", "昨天", "yesterday", "notice",
         "通知：本周六 22:00 机房网络割接，预计中断30分钟", "synced"),
        ("m009", "wechat", "供应商-刘经理", "微信", "周一", "earlier", "text",
         "发票已经寄出，注意查收", "synced"),
    ]
    for r in rows:
        # 未读：仅 status=received 的消息算未读，其余（replied/synced）已处理过
        unread = 1 if r[8] == "received" else 0
        db.execute(
            "INSERT OR IGNORE INTO messages(id,platform,msg_key,sender,chat,time,day,type,"
            "content,status,unread,pinned,muted,dedup_key,created_at)"
            " VALUES(?,?,NULL,?,?,?,?,?,?,?,?,0,0,?,?)",
            (*r, unread, db.dedup_hash(r[1], r[2], r[4], r[7]), time.time()))
        db.execute(
            "INSERT INTO thread(msg_id,from_side,text,time,send_status,channel)"
            " VALUES(?,?,?,?,?,?)", (r[0], "them", r[7], r[4], None, None))
        db.add_trace(r[0], "已接收", f"来自{r[1]}（{r[2]}）")
    db.execute("INSERT OR IGNORE INTO thread(msg_id,from_side,text,time,send_status,channel)"
               " VALUES('m003','me','看到了，我马上看日志','09:45','synced','api')")
    db.execute("INSERT OR IGNORE INTO thread(msg_id,from_side,text,time,send_status,channel)"
               " VALUES('m007','me','已审批通过，请查收','16:20','synced','api')")


# ------------------------------------------------------------------ 认证
class LoginReq(BaseModel):
    account: str
    password: str


class RegisterReq(BaseModel):
    account: str
    password: str
    name: str


def _user_to_profile(u: dict) -> dict:
    """把 users 表记录映射为前端 profile（含角色），其余字段用默认资料补齐。"""
    prof = dict(PROFILE_DEFAULT)
    prof["id"] = f"U{u['id']}"
    prof["name"] = u["name"]
    prof["cnName"] = u["name"]
    prof["initial"] = u["name"][:1]
    prof["role"] = "系统管理员" if u["role"] == "admin" else "普通用户"
    prof["email"] = u["account"]
    prof["staffNo"] = f"XC-{u['id']:04d}"
    prof["loginType"] = "账号密码登录"
    prof["twoFactor"] = False
    return prof


def _seed_admin():
    """保证默认管理员 gary 存在（迁移旧库或首次启动时补齐）。"""
    if not db.get_user_by_account(settings.DEMO_ACCOUNT):
        db.create_user(settings.DEMO_ACCOUNT, "高远", settings.DEMO_PASSWORD, role="admin")


@app.post("/api/auth/login")
def login(req: LoginReq):
    acc = req.account.strip().lower()
    # 兼容旧演示别名（邮箱/工号）→ 归一为账号
    if acc == f"{settings.DEMO_ACCOUNT}@xingchen-tech.com" or acc == "xc-1024":
        acc = settings.DEMO_ACCOUNT
    user = db.verify_user(acc, req.password)
    if not user:
        raise HTTPException(401, "账号或密码错误")
    token = secrets.token_urlsafe(24)
    tokens[token] = acc
    prof = _user_to_profile(user)
    prof["lastLogin"]["time"] = time.strftime("今天 %H:%M")
    db.add_op(f"登录统一消息中心（{acc}）")
    return {"token": token, "user": prof}


@app.post("/api/auth/register")
def register(req: RegisterReq):
    acc = req.account.strip().lower()
    if not acc or not req.password or not req.name.strip():
        raise HTTPException(400, "账号、姓名、密码均不能为空")
    if len(req.password) < 6:
        raise HTTPException(400, "密码至少 6 位")
    # 邮箱/工号形式禁止（避免与管理员别名冲突）
    if "@" in acc:
        raise HTTPException(400, "账号请使用字母数字组合，不要用邮箱")
    user = db.create_user(acc, req.name, req.password, role="user")
    if not user:
        raise HTTPException(409, "该账号已被注册")
    token = secrets.token_urlsafe(24)
    tokens[token] = acc
    prof = _user_to_profile(user)
    prof["lastLogin"]["time"] = time.strftime("今天 %H:%M")
    db.add_op(f"新用户注册并登录（{acc}）")
    return {"token": token, "user": prof}


@app.post("/api/auth/logout")
def logout():
    return {"ok": True}


def get_profile() -> dict:
    row = db.query("SELECT data FROM profile WHERE id=1")[0]
    return json.loads(row["data"])


def auth(requester_token: str | None):
    if requester_token and requester_token in tokens:
        return
    # 初赛演示阶段：无 token 也放行，避免前端未改登录对接时被拦
    return


@app.get("/api/me")
def me(authorization: str | None = Header(None)):
    # 有 token 时返回该用户的真实角色；无 token 返回默认资料
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
        if token in tokens:
            u = db.get_user_by_account(tokens[token])
            if u:
                return _user_to_profile(u)
    return get_profile()


class ProfilePatch(BaseModel):
    cnName: str | None = None
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    city: str | None = None


@app.patch("/api/me")
def patch_me(p: ProfilePatch):
    prof = get_profile()
    for k, v in p.model_dump(exclude_none=True).items():
        prof[k] = v
    db.execute("UPDATE profile SET data=? WHERE id=1", (json.dumps(prof, ensure_ascii=False),))
    db.add_op("修改了个人资料")
    return prof


# ------------------------------------------------------------------ 应用连接
def app_row(r) -> dict:
    return {"key": r["key"], "connected": bool(r["connected"]), "account": r["account"],
            "org": r["org"], "last_sync": r["last_sync"], "success_rate": r["success_rate"],
            "since": r["since"], "note": r["note"]}


@app.get("/api/apps")
def list_apps():
    return [app_row(r) for r in db.query("SELECT * FROM apps")]


@app.post("/api/apps/{key}/connect")
async def connect_app(key: str):
    _require_app(key)
    hc = await CONNECTORS[key].health_check()
    t = time.strftime("%H:%M")
    db.execute("UPDATE apps SET connected=1, last_sync=? WHERE key=?", (t, key))
    db.add_op(f"重新连接平台 {key}")
    await hub.broadcast({"type": "channel_update",
                         "data": {"key": key, "connected": True,
                                  "simulated": hc.get("simulated", False)}})
    return app_row(db.query("SELECT * FROM apps WHERE key=?", (key,))[0])


@app.post("/api/apps/{key}/disconnect")
async def disconnect_app(key: str):
    _require_app(key)
    db.execute("UPDATE apps SET connected=0 WHERE key=?", (key,))
    db.add_op(f"断开平台 {key}")
    await hub.broadcast({"type": "channel_update", "data": {"key": key, "connected": False}})
    return app_row(db.query("SELECT * FROM apps WHERE key=?", (key,))[0])


@app.post("/api/apps/{key}/test")
async def test_app(key: str):
    _require_app(key)
    t0 = time.perf_counter()
    hc = await CONNECTORS[key].health_check()
    latency = round((time.perf_counter() - t0) * 1000)
    return {"ok": hc["ok"], "latencyMs": latency,
            **({"reason": hc["reason"]} if "reason" in hc and not hc["ok"] else {})}


class ChannelPatch(BaseModel):
    primary: str  # "api" | "rpa"


@app.patch("/api/apps/{key}/channel")
def patch_channel(key: str, p: ChannelPatch):
    _require_app(key)
    if p.primary not in ("api", "rpa"):
        raise HTTPException(400, "primary 只能为 api 或 rpa")
    backup = "rpa" if p.primary == "api" else "api"
    return {"primary": p.primary, "backup": backup}


def _require_app(key: str):
    if key not in CONNECTORS:
        raise HTTPException(404, f"未知平台 {key}")


# ------------------------------------------------------------------ 消息
@app.get("/api/messages")
def list_messages(platform: str = "", status: str = "", keyword: str = ""):
    sql, args = "SELECT * FROM messages WHERE 1=1", []
    if platform and platform != "all":
        sql += " AND platform=?"; args.append(platform)
    if status == "unread":
        sql += " AND unread=1"
    elif status == "pending":
        sql += " AND status IN ('received','processing')"
    elif status == "done":
        sql += " AND status IN ('replied','synced')"
    if keyword:
        sql += " AND (sender LIKE ? OR content LIKE ?)"; args += [f"%{keyword}%", f"%{keyword}%"]
    sql += " ORDER BY created_at DESC LIMIT 200"
    rows = db.query(sql, tuple(args))
    return {"messages": [db.msg_to_dict(r) for r in rows], "total": len(rows)}


@app.get("/api/messages/{mid}/thread")
def get_thread(mid: str):
    rows = db.query("SELECT * FROM thread WHERE msg_id=? ORDER BY id", (mid,))
    return [{"from": r["from_side"], "text": r["text"], "time": r["time"],
             "sendStatus": r["send_status"], "channel": r["channel"]} for r in rows]


class ReplyReq(BaseModel):
    text: str
    channel: str | None = None      # 指定通道（重试/切换备用时前端传入）
    fault: bool = False             # 故障演练开关


@app.post("/api/messages/{mid}/reply")
async def reply(mid: str, req: ReplyReq):
    row = db.query("SELECT * FROM messages WHERE id=?", (mid,))
    if not row:
        raise HTTPException(404, "消息不存在")
    msg = db.msg_to_dict(row[0])
    conn = db.query("SELECT connected FROM apps WHERE key=?", (msg["platform"],))
    if conn and not conn[0]["connected"]:
        reason = f"{msg['platform']}连接已断开，请到「应用连接」重新连接"
        db.execute("UPDATE messages SET status='failed' WHERE id=?", (mid,))
        db.add_trace(mid, "发送失败", reason)
        return {"ok": False, "channel": req.channel or "api", "reason": reason}

    result: SendResult = await route_reply(msg, req.text, req.channel, req.fault)
    now = time.strftime("%H:%M")

    if result.ok:
        db.execute("INSERT INTO thread(msg_id,from_side,text,time,send_status,channel)"
                   " VALUES(?,?,?,?,?,?)", (mid, "me", req.text, now, "synced", result.channel))
        db.execute("UPDATE messages SET status='replied', unread=0 WHERE id=?", (mid,))
        db.add_trace(mid, "已回复", f"{result.channel} 通道发送成功：{req.text}")
        await hub.broadcast({"type": "status_update", "data": {"id": mid, "status": "replied"}})
        # 状态回流：1.1s 后推送 synced
        asyncio.get_event_loop().call_later(1.1, lambda: _sync_later(mid, result.channel))
        return {"ok": True, "channel": result.channel, "status": "replied", "messageId": mid}
    else:
        db.execute("UPDATE messages SET status='failed' WHERE id=?", (mid,))
        db.add_trace(mid, "发送失败", f"{result.channel}：{result.reason}")
        await hub.broadcast({"type": "status_update", "data": {"id": mid, "status": "failed"}})
        return {"ok": False, "channel": result.channel, "reason": result.reason}


# ------------------------------------------------------------------ 文件发送（功能需求第3条：发送文件）
@app.post("/api/messages/{mid}/send-file")
async def send_file(mid: str, file: UploadFile = File(...)):
    """统一入口向指定平台发送文件。钉钉走机器人媒体上传+sampleFile 真实发送；
    微信无 API，走 RPA 通道（模拟）。状态流转与文本回复一致。"""
    row = db.query("SELECT * FROM messages WHERE id=?", (mid,))
    if not row:
        raise HTTPException(404, "消息不存在")
    msg = db.msg_to_dict(row[0])
    content = await file.read()
    filename = file.filename or "file.bin"
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(422, "文件超过 20MB（钉钉机器人媒体上传上限）")

    now = time.strftime("%H:%M")
    if msg["platform"] == "dingtalk":
        conv_id = msg.get("convId") or msg.get("conv_id")
        if not conv_id:
            result_ok, channel, reason = False, "api", "该消息无钉钉会话ID，无法真实回发文件"
        else:
            from . import dingtalk_stream_connector as dt
            up = await dt.upload_media(filename, content)
            if up["ok"]:
                sent = await dt.send_file(conv_id, up["mediaId"], filename)
                result_ok, channel = sent["ok"], "api"
                reason = sent.get("reason", "")
            else:
                result_ok, channel, reason = False, "api", up["reason"]
    else:
        # 微信：RPA 通道（个人号无 API，模拟粘贴文件）
        r = await wechat_rpa.send(msg.get("chat") or msg["sender"],
                                  f"（文件：{filename}）")
        result_ok, channel, reason = bool(r.ok), "rpa", r.reason

    if result_ok:
        db.execute("INSERT INTO thread(msg_id,from_side,text,time,send_status,channel)"
                   " VALUES(?,?,?,?,?,?)",
                   (mid, "me", f"📎 [文件] {filename}", now, "synced", channel))
        db.execute("UPDATE messages SET status='replied', unread=0 WHERE id=?", (mid,))
        db.add_trace(mid, "已回复", f"{channel} 通道发送文件成功：{filename}")
        await hub.broadcast({"type": "status_update", "data": {"id": mid, "status": "replied"}})
        asyncio.get_event_loop().call_later(1.1, lambda: _sync_later(mid, channel))
        return {"ok": True, "channel": channel, "status": "replied"}
    else:
        db.execute("UPDATE messages SET status='failed' WHERE id=?", (mid,))
        db.add_trace(mid, "发送失败", f"文件发送失败（{channel}）：{reason}")
        await hub.broadcast({"type": "status_update", "data": {"id": mid, "status": "failed"}})
        return {"ok": False, "channel": channel, "reason": reason or "文件发送失败"}


# ------------------------------------------------------------------ 消息记录导出（CSV）
@app.get("/api/messages/export")
def export_messages():
    """导出全部消息记录为 CSV（UTF-8 BOM，Excel 直接打开不乱码）。"""
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["ID", "平台", "发送人", "会话", "时间", "分组", "类型", "内容", "状态"])
    rows = db.query("SELECT * FROM messages ORDER BY created_at")
    for r in rows:
        m = db.msg_to_dict(r)
        w.writerow([m["id"], m["platform"], m["sender"], m.get("chat", ""),
                    m["time"], m["day"], m["type"], m["content"].replace("\n", " "),
                    m["status"]])
    data = "\ufeff" + buf.getvalue()
    return Response(
        content=data.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=messages_export.csv"})


def _sync_later(mid: str, channel: str):
    db.execute("UPDATE messages SET status='synced' WHERE id=?", (mid,))
    db.add_trace(mid, "已同步到平台", f"状态已回流（{channel} 回执）")
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(hub.broadcast({"type": "status_update",
                                        "data": {"id": mid, "status": "synced"}}))
    except RuntimeError:
        pass


# ------------------------------------------------------------------ AI 功能
class ClassifyReq(BaseModel):
    content: str


@app.post("/api/ai/classify")
async def ai_classify(req: ClassifyReq):
    return await classify(req.content)


@app.get("/api/ai/suggest/{mid}")
async def ai_suggest(mid: str):
    rows = db.query("SELECT from_side, text FROM thread WHERE msg_id=? ORDER BY id", (mid,))
    ctx = [{"from": r["from_side"], "text": r["text"]} for r in rows]
    return {"suggestions": await suggest_reply(ctx)}


@app.get("/api/ai/summary")
async def ai_summary():
    rows = db.query("SELECT * FROM messages WHERE day='today' ORDER BY created_at DESC")
    msgs = [db.msg_to_dict(r) for r in rows]
    return {"summary": await daily_summary(msgs)}


# ------------------------------------------------------------------ RPA 采集（归一化入口）
class IncomingReq(BaseModel):
    platform: str          # wechat | dingtalk
    sender: str
    chat: str = ""
    content: str
    msg_key: str | None = None    # RPA 无ID时不传，后端生成去重键


@app.post("/api/collector/incoming")
async def collector_incoming(req: IncomingReq):
    """归一化入口：钉钉事件订阅回调、Power Automate RPA 采集流都打到这。
    返回 {"ok":true,"duplicated":false,"id":"..."}；重复消息 duplicated=true。"""
    return await _ingest(req.model_dump())


@app.post("/api/collector/plain")
async def collector_plain(request: Request):
    """纯文本采集入口（Power Automate 免拼 JSON 专用）。
    Body 即消息内容（text/plain）；可选首行写 `发送人@会话名`，
    不写则默认发送人=微信-RPA采集、会话=微信。"""
    raw = await request.body()
    text = raw.decode("utf-8", errors="replace").strip()
    # Power Automate 会把中文 URL 编码成 %XX 形式，这里自动还原
    import urllib.parse
    if "%" in text:
        decoded = urllib.parse.unquote(text)
        if decoded != text:
            text = decoded.strip()
    if not text:
        raise HTTPException(422, "empty body")
    lines = text.splitlines()
    sender, chat = "微信-RPA采集", "微信"
    if len(lines) > 1 and "@" in lines[0] and len(lines[0]) < 40:
        head = lines[0].split("@", 1)
        sender, chat = head[0].strip() or sender, (head[1].strip() or chat)
        content = "\n".join(lines[1:]).strip()
    else:
        content = text
    return await _ingest({"platform": "wechat", "sender": sender,
                          "chat": chat, "content": content})


async def _ingest(raw: dict) -> dict:
    """归一化 + AI 分类 + WebSocket 推送（incoming 与手动同步共用）。"""
    result = normalize_incoming(raw)
    if result["duplicated"]:
        return {"ok": True, "duplicated": True, "id": result["id"]}
    cls = await classify(raw["content"])
    db.execute("UPDATE messages SET type=? WHERE id=? AND type='text'",
               ("todo" if cls["type"] == "todo" else cls["type"], result["id"]))
    await hub.broadcast({"type": "new_message", "data": result["message"]})
    await hub.broadcast({"type": "status_update", "data": {"id": result["id"], "status": "received"}})
    return {"ok": True, "duplicated": False, "id": result["id"], "classify": cls}


class SyncReq(BaseModel):
    platform: str = "dingtalk"   # 手动同步的平台（演示钉钉回调闭环）
    sender: str = ""
    chat: str = ""
    content: str = ""


@app.post("/api/collector/sync")
async def collector_sync(req: SyncReq):
    """手动同步一条平台消息（演示「平台 → 统一入口」接收闭环）。
    正式环境此链路由平台事件订阅回调触发（钉钉）或 RPA 采集（微信），
    本地 localhost 无法被钉钉公网回调触达，故提供本手动入口兜底演示。"""
    if not req.content.strip():
        raise HTTPException(400, "消息内容不能为空")
    raw = {
        "platform": req.platform if req.platform in CONNECTORS else "dingtalk",
        "sender": req.sender.strip() or "钉钉群-成员",
        "chat": req.chat.strip() or "钉钉群",
        "content": req.content.strip(),
    }
    return await _ingest(raw)


# ------------------------------------------------------------------ WebSocket
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await hub.connect(ws)
    try:
        while True:
            await ws.receive_text()   # 保活
    except WebSocketDisconnect:
        hub.disconnect(ws)


@app.get("/api/health")
def health():
    return {"ok": True, "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "dingtalk_simulated": dingtalk.simulated,
            "rpa_simulated": wechat_rpa.simulated, "deepseek": not (not settings.DEEPSEEK_API_KEY)}


# ------------------------------------------------------------------ 静态托管 UI
# 放在所有 /api 路由之后，避免 catch-all 抢匹配。让用户通过 http://localhost:8080/
# 访问 UI，消除 file:// 双击打开导致的跨域拦截（fetch 到 localhost 会被浏览器挡）。
_UI_DIR = Path(__file__).resolve().parent.parent.parent / "UI" / "unified-msg-ui"
if not _UI_DIR.exists():
    _UI_DIR = Path(__file__).resolve().parent.parent.parent / "决赛材料" / "ui"


@app.get("/")
def index():
    return FileResponse(_UI_DIR / "index.html", headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


@app.get("/{file_path:path}")
async def serve_static(file_path: str):
    if file_path.startswith(("api/", "ws")):
        raise HTTPException(404)
    target = (_UI_DIR / file_path).resolve()
    if not str(target).startswith(str(_UI_DIR.resolve())) or not target.is_file():
        raise HTTPException(404)
    return FileResponse(target, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=False)
