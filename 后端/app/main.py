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
from fastapi.responses import FileResponse, Response, HTMLResponse
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
from . import feishu_stream_connector as fs_stream     # 飞书企业自建应用（长连接双向收发）
from . import dingtalk_oauth as dt_oauth                # 钉钉扫码登录（OAuth 授权登录）

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
    {"key": "feishu", "connected": 1, "account": "飞书自建应用",
     "org": "飞书组织 · 长连接接入", "last_sync": "", "success_rate": "100%",
     "since": "2024-05-20",
     "note": "企业自建应用 · WebSocket长连接" + ("（已配置）" if fs_stream.is_configured() else "（待配置AppID/Secret）")},
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
    用线程池调度，避免阻塞 Stream 的 ack 返回。
    文件/图片消息：走异步下载流程（机器人 messageFiles/download 换URL后拉取字节）。"""
    try:
        mtype = getattr(incoming, "message_type", "") or ""
        if mtype in ("file", "picture"):
            asyncio.run_coroutine_threadsafe(_ingest_dingtalk_file(incoming, mtype), _main_loop)
            return
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


async def _ingest_dingtalk_file(incoming, mtype: str) -> None:
    """接收钉钉文件/图片消息：换下载URL → 拉字节 → 本地留档 → 归一化入库（可点击下载）。"""
    from . import dingtalk_stream_connector as dt
    try:
        content_dict = (getattr(incoming, "extensions", {}) or {}).get("content") or {}
        filename = content_dict.get("fileName") or f"图片-{time.strftime('%H%M%S')}.png"
        download_code = content_dict.get("downloadCode") or ""
        if not download_code:
            log_dt.warning("钉钉文件消息缺少 downloadCode: %s", content_dict)
            return
        dl = await dt.download_robot_file(download_code)
        if not dl["ok"]:
            log_dt.error("钉钉文件下载失败：%s", dl["reason"])
            raw = {"platform": "dingtalk",
                   "sender": incoming.sender_nick or "钉钉成员",
                   "chat": incoming.conversation_title or ("群聊" if incoming.conversation_type == "2" else "单聊"),
                   "content": f"📎 [文件] {filename}（下载失败：{dl['reason']}）",
                   "msg_key": incoming.message_id,
                   "conv_id": incoming.conversation_id or ""}
            await _ingest(raw)
            return
        content = dl["content"]
        raw = {"platform": "dingtalk",
               "sender": incoming.sender_nick or "钉钉成员",
               "chat": incoming.conversation_title or ("群聊" if incoming.conversation_type == "2" else "单聊"),
               "content": f"📎 [文件] {filename}",
               "msg_key": incoming.message_id,
               "conv_id": incoming.conversation_id or ""}
        result = await _ingest(raw)
        mid = result.get("id")
        if not mid:
            return
        # 本地留档 + 会话气泡关联 fileId（网页可直接点开/下载）
        fid = uuid.uuid4().hex[:12]
        updir = Path(__file__).resolve().parent / "uploads"
        updir.mkdir(exist_ok=True)
        stored = updir / f"{fid}_{filename}"
        stored.write_bytes(content)
        db.execute("INSERT INTO files(id, msg_id, filename, size, path, created_at) VALUES(?,?,?,?,?,?)",
                   (fid, mid, filename, len(content), str(stored), time.time()))
        db.execute("UPDATE thread SET file_id=? WHERE id=(SELECT id FROM thread "
                   "WHERE msg_id=? AND from_side='them' ORDER BY id DESC LIMIT 1)",
                   (fid, mid))
        db.add_trace(mid, "已接收文件", f"来自钉钉的文件已留档：{filename}（{len(content)//1024}KB）")
        await hub.broadcast({"type": "thread_update", "data": {"id": mid}})
    except Exception as e:
        log_dt.exception("钉钉文件消息处理异常: %s", e)


def _on_dingtalk_recall(data: dict) -> None:
    """钉钉撤回事件回调：把对应消息在本地标记为「已撤回」并 WS 推送。
    事件字段以钉钉实际推送为准，兼容多种常见字段名（messageId/msgId/openMessageId）。"""
    try:
        info = data.get("recallInfo") or data.get("RecallInfo") or {}
        msg_id = (data.get("messageId") or data.get("message_id") or data.get("msgId")
                  or info.get("messageId") or info.get("msgId") or "")
        if not msg_id:
            log_dt.warning("钉钉撤回事件缺少消息ID字段，原始数据: %s", data)
            return
        msg_id = str(msg_id)
        row = db.query("SELECT id FROM messages WHERE msg_key=?", (msg_id,))
        if not row:
            # 钉钉撤回事件的 messageId 可能带前缀（如 cid 前的完整编码），宽松匹配一次
            row = db.query("SELECT id FROM messages WHERE msg_key LIKE ?", ("%" + msg_id[-32:],))
        if not row:
            log_dt.info("撤回的消息不在本地库中（可能非机器人可见消息）: %s", msg_id)
            return
        mid = row[0]["id"]
        db.execute("UPDATE messages SET type='recall', content=?, unread=0 WHERE id=?",
                   ("（对方在钉钉撤回了一条消息）", mid))
        db.add_trace(mid, "已撤回", "发送方在钉钉撤回了该消息，本地同步标记")
        try:
            asyncio.run_coroutine_threadsafe(
                hub.broadcast({"type": "msg_recalled", "data": {"id": mid}}), _main_loop)
        except RuntimeError:
            pass
        log_dt.info("钉钉撤回已同步：%s", mid)
    except Exception as e:
        log_dt.exception("钉钉撤回事件处理异常: %s", e)


def _start_dingtalk_stream():
    if not dt_stream.is_configured():
        return
    dt_stream.set_message_handler(_on_dingtalk_message)
    dt_stream.set_recall_handler(_on_dingtalk_recall)
    dt_stream.start_in_background()


# ---------------- 飞书：入站消息处理 ----------------
log_fs = logging.getLogger("feishu-ingest")


def _on_feishu_message(item: dict) -> None:
    """飞书长连接收到 im.message.receive_v1 事件：归一化入库 + WS 推送。
    文本消息直接入库；图片/文件消息先拉取字节留档再入库（可预览/下载）。"""
    try:
        async def _run():
            mtype = item.get("message_type", "text")
            if mtype == "text":
                text = fs_stream._extract_text(item.get("content", ""))
                if not text:
                    return
                open_id = item.get("open_id") or ""
                sender_name = item.get("sender_name") or ""
                if not sender_name and open_id:
                    sender_name = await fs_stream.get_user_name(open_id)
                    if sender_name:
                        # 姓名解析成功后，修正历史消息里以 open_id 落库的发送人名
                        db.execute("UPDATE messages SET sender=? WHERE platform='feishu' AND sender=?",
                                   (sender_name, open_id))
                raw = {"platform": "feishu",
                       "sender": sender_name or open_id or "飞书用户",
                       "chat": "飞书群聊" if item.get("chat_type") == "group" else "飞书单聊",
                       "content": text,
                       "msg_key": item.get("message_id"),
                       "conv_id": item.get("chat_id") or ""}
                await _ingest(raw)
            elif mtype in ("image", "file", "audio", "media"):
                await _ingest_feishu_file(item)
            else:
                log_fs.info("暂不处理的飞书消息类型: %s", mtype)
        asyncio.run_coroutine_threadsafe(_run(), _main_loop)
    except Exception as e:
        log_fs.exception("飞书消息入站处理异常: %s", e)


async def _ingest_feishu_file(item: dict) -> None:
    """接收飞书图片/文件消息：下载资源 → 本地留档 → 归一化入库（气泡可预览/下载）。"""
    import json as _json
    try:
        content = item.get("content", "{}")
        try:
            cdata = _json.loads(content) if isinstance(content, str) else content
        except Exception:
            cdata = {}
        msg_id = item.get("message_id") or ""
        if item.get("message_type") == "image":
            file_key = (cdata.get("image") or {}).get("image_key") or ""
            filename = f"飞书图片-{time.strftime('%H%M%S')}.png"
            res_type = "image"
        else:
            fnode = cdata.get("file") or cdata.get("audio") or cdata.get("media") or {}
            file_key = fnode.get("file_key") or ""
            filename = fnode.get("file_name") or f"飞书文件-{time.strftime('%H%M%S')}.bin"
            res_type = "file"
        if not (msg_id and file_key):
            log_fs.warning("飞书文件消息缺少 message_id/file_key: %s", item)
            return
        dl = await fs_stream.download_resource(msg_id, file_key, res_type)
        if not dl["ok"]:
            log_fs.error("飞书文件下载失败：%s", dl["reason"])
            raw = {"platform": "feishu", "sender": item.get("sender_name") or "飞书用户",
                   "chat": "飞书群聊" if item.get("chat_type") == "group" else "飞书单聊",
                   "content": f"📎 [文件] {filename}（下载失败：{dl['reason']}）",
                   "msg_key": msg_id, "conv_id": item.get("chat_id") or ""}
            await _ingest(raw)
            return
        sender = item.get("sender_name")
        if not sender and item.get("open_id"):
            sender = await fs_stream.get_user_name(item["open_id"]) or f"飞书用户{item['open_id'][-6:]}"
        raw = {"platform": "feishu", "sender": sender or "飞书用户",
               "chat": "飞书群聊" if item.get("chat_type") == "group" else "飞书单聊",
               "content": f"📎 [文件] {filename}",
               "msg_key": msg_id, "conv_id": item.get("chat_id") or ""}
        result = await _ingest(raw)
        mid = result.get("id")
        if not mid:
            return
        fid = uuid.uuid4().hex[:12]
        updir = Path(__file__).resolve().parent / "uploads"
        updir.mkdir(exist_ok=True)
        stored = updir / f"{fid}_{filename}"
        stored.write_bytes(dl["content"])
        db.execute("INSERT INTO files(id, msg_id, filename, size, path, created_at) VALUES(?,?,?,?,?,?)",
                   (fid, mid, filename, len(dl["content"]), str(stored), time.time()))
        db.execute("UPDATE thread SET file_id=? WHERE id=(SELECT id FROM thread "
                   "WHERE msg_id=? AND from_side='them' ORDER BY id DESC LIMIT 1)",
                   (fid, mid))
        db.add_trace(mid, "已接收文件", f"来自飞书的文件已留档：{filename}（{len(dl['content'])//1024}KB）")
        await hub.broadcast({"type": "thread_update", "data": {"id": mid}})
    except Exception as e:
        log_fs.exception("飞书文件消息处理异常: %s", e)


def _start_feishu_stream():
    if not fs_stream.is_configured():
        log_fs.info("未配置 FEISHU_APP_ID/SECRET，跳过飞书长连接")
        return
    fs_stream.set_message_handler(_on_feishu_message)
    fs_stream.start_in_background()


_main_loop: asyncio.AbstractEventLoop = None
log_dt = logging.getLogger("dingtalk-ingest")


@app.on_event("startup")
def startup():
    global _main_loop
    _main_loop = asyncio.get_event_loop()
    db.init_db()
    _seed_admin()
    _start_dingtalk_stream()
    _start_feishu_stream()
    # 应用连接种子
    for a in APPS_SEED:
        db.execute(
            "INSERT OR IGNORE INTO apps(key,connected,account,org,last_sync,success_rate,since,note)"
            " VALUES(:key,:connected,:account,:org,:last_sync,:success_rate,:since,:note)", a)
    # 个人资料种子
    if not db.query("SELECT 1 FROM profile WHERE id=1"):
        db.execute("INSERT INTO profile(id, data) VALUES(1, ?)", (json.dumps(PROFILE_DEFAULT, ensure_ascii=False),))
    # 演示种子消息：初赛评审反馈改为纯真实数据——不再注入，且清理老库残留
    _cleanup_demo_messages()


def _cleanup_demo_messages():
    """清理初始化注入的演示消息（m001~m009 及其会话/流转记录），保证导出全为真实数据。"""
    demo_ids = [r[0] for r in db.query(
        "SELECT id FROM messages WHERE id IN ('m001','m002','m003','m004','m005',"
        "'m006','m007','m008','m009')")]
    for mid in demo_ids:
        db.execute("DELETE FROM thread WHERE msg_id=?", (mid,))
        db.execute("DELETE FROM traces WHERE msg_id=?", (mid,))
        db.execute("DELETE FROM messages WHERE id=?", (mid,))
    if demo_ids:
        logging.getLogger("uvicorn.error").info("已清理 %s 条演示种子消息", len(demo_ids))


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


# ------------------------------------------------------------------ 钉钉扫码登录（OAuth）
_oauth_states: dict[str, str] = {}   # state -> 随机串（防 CSRF）

# 前端轮询/回跳落地页：拿到 token 后前端用它换本系统 token
@app.get("/api/auth/dingtalk/url")
def dingtalk_login_url():
    """返回钉钉扫码登录授权 URL + state。前端跳转该 URL。"""
    if not dt_oauth.is_configured():
        raise HTTPException(503, "未配置钉钉扫码登录（需 DINGTALK_CORP_ID/APP_KEY/SECRET）")
    state = dt_oauth.make_state()
    _oauth_states[state] = "pending"
    return {"url": dt_oauth.build_authorize_url(state), "state": state}


@app.get("/api/auth/dingtalk/callback")
async def dingtalk_login_callback(code: str = Query(None), state: str = Query(None),
                                  request: Request = None):
    """钉钉扫码登录回跳：用 code 换用户信息 → 映射/注册本地账号 → 签发 token。
    前端用 window.opener.postMessage 或轮询拿到 token。"""
    if not code:
        return HTMLResponse("<h3>登录失败：未收到授权码</h3>")
    userinfo = await dt_oauth.exchange_user(code)
    if not userinfo or not userinfo.get("unionId"):
        return HTMLResponse("<h3>登录失败：钉钉返回的用户信息无效</h3>")
    unionid = userinfo["unionId"]
    nick = userinfo.get("nick") or "钉钉用户"

    user = db.get_user_by_unionid(unionid)
    if not user:
        user = db.create_user_by_unionid(unionid, nick)
    if not user:
        return HTMLResponse("<h3>登录失败：无法创建本地账号</h3>")

    token = secrets.token_urlsafe(24)
    tokens[token] = user["account"]
    prof = _user_to_profile(user)
    prof["loginType"] = "钉钉扫码登录"
    prof["lastLogin"]["time"] = time.strftime("今天 %H:%M")
    db.add_op(f"钉钉扫码登录（{nick} / {user['account']}）")

    # 通过 state 关联的临时落地页把 token 交给前端；简单起见直接内嵌脚本回传
    return HTMLResponse(f"""
    <!doctype html><meta charset="utf-8"><title>钉钉登录成功</title>
    <script>
      const payload = {{
        token: {json.dumps(token)},
        user: {json.dumps(prof, ensure_ascii=False)}
      }};
      if (window.opener && !window.opener.closed) {{
        window.opener.postMessage({{ type: 'dingtalk-login', ...payload }}, '*');
      }}
      window.close();
    </script>
    <body style="font-family:sans-serif;text-align:center;padding-top:60px;">
      钉钉扫码登录成功，正在返回…<br>
      <small>若未自动返回，请回到原页面点击「钉钉扫码登录」重试。</small>
    </body>""")


@app.get("/api/auth/dingtalk/state/{state}")
def dingtalk_login_state(state: str):
    """前端轮询：state 未完成时用 postMessage 通道即可，这里作为兜底。"""
    return {"ready": False}


def get_profile() -> dict:
    row = db.query("SELECT data FROM profile WHERE id=1")[0]
    return json.loads(row["data"])


def auth(requester_token: str | None):
    if requester_token and requester_token in tokens:
        return
    # 初赛演示阶段：无 token 也放行，避免前端未改登录对接时被拦
    return


def _current_account(authorization: str | None) -> str | None:
    """从 Authorization header 解析当前登录账号。
    返回 None 表示管理员/未登录（可见全部消息），返回账号字符串表示该普通用户。
    管理员(gary)也返回 None（可见全部）。"""
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
        if token in tokens:
            acc = tokens[token]
            u = db.get_user_by_account(acc)
            if u and u.get("role") != "admin":
                return acc
    return None


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


# ---------------- 成员管理（仅管理员） ----------------
def _current_user(authorization: str | None) -> dict | None:
    """返回当前登录用户的完整记录（区别于 _current_account：管理员也有记录）。"""
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
        if token in tokens:
            return db.get_user_by_account(tokens[token])
    return None


def _require_admin(authorization: str | None) -> dict:
    u = _current_user(authorization)
    if not u or u["role"] != "admin":
        raise HTTPException(403, "需要管理员权限")
    return u


@app.get("/api/users")
def list_users(authorization: str | None = Header(None)):
    _require_admin(authorization)
    rows = db.query("SELECT id, account, name, role, created_at FROM users ORDER BY id")
    return [{"id": r["id"], "account": r["account"], "name": r["name"],
             "role": r["role"],
             "createdAt": time.strftime("%Y-%m-%d %H:%M", time.localtime(r["created_at"]))}
            for r in rows]


class RoleReq(BaseModel):
    role: str  # admin | user


@app.patch("/api/users/{account}/role")
def set_user_role(account: str, req: RoleReq, authorization: str | None = Header(None)):
    """管理员设置成员角色（admin=系统管理员 / user=普通用户）。不能改自己。"""
    me_u = _require_admin(authorization)
    if me_u["account"] == account:
        raise HTTPException(422, "不能修改自己的角色")
    if req.role not in ("admin", "user"):
        raise HTTPException(422, "角色只能是 admin 或 user")
    u = db.get_user_by_account(account)
    if not u:
        raise HTTPException(404, "用户不存在")
    db.execute("UPDATE users SET role=? WHERE account=?", (req.role, account))
    db.add_op(f"设置成员 {u['name']}({account}) 角色为 {req.role}（by {me_u['name']}）")
    return {"ok": True, "account": account, "role": req.role}


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
def list_messages(platform: str = "", status: str = "", keyword: str = "",
                  authorization: str | None = Header(None)):
    sql, args = "SELECT * FROM messages WHERE 1=1", []
    # 多用户数据隔离：普通用户只看自己名下的消息，管理员/未登录看全部
    owner = _current_account(authorization)
    if owner:
        sql += " AND owner=?"; args.append(owner)
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
def get_thread(mid: str, authorization: str | None = Header(None)):
    rows = db.query("SELECT * FROM thread WHERE msg_id=? ORDER BY id", (mid,))
    out = []
    for r in rows:
        item = {"id": r["id"], "from": r["from_side"], "text": r["text"], "time": r["time"],
                "sendStatus": r["send_status"], "channel": r["channel"]}
        if r["file_id"]:
            item["fileId"] = r["file_id"]
        out.append(item)
    return out


@app.get("/api/files/{fid}")
def download_file(fid: str, download: int = 0):
    """下载/在线预览统一入口发过的文件（磁盘持久化存储）。
    图片默认内联返回（网页气泡可直接显示缩略图、点击看大图）；
    其他文件或 ?download=1 时按附件下载。"""
    rows = db.query("SELECT * FROM files WHERE id=?", (fid,))
    if not rows:
        raise HTTPException(404, "文件不存在")
    f = rows[0]
    p = Path(f["path"])
    if not p.is_file():
        raise HTTPException(404, "文件已丢失")
    name = (f["filename"] or "").lower()
    if download or not name.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg")):
        return FileResponse(p, filename=f["filename"])
    import mimetypes
    mt = mimetypes.guess_type(f["filename"])[0] or "application/octet-stream"
    return FileResponse(p, media_type=mt, headers={"Cache-Control": "max-age=3600"})


@app.delete("/api/thread/{tid}")
def delete_thread_item(tid: int):
    """删除单条会话记录（聊天气泡级删除）。"""
    db.execute("DELETE FROM thread WHERE id=?", (tid,))
    return {"ok": True}


def _delete_message_cascade(mid: str):
    # 磁盘文件一并清理
    for f in db.query("SELECT path FROM files WHERE msg_id=?", (mid,)):
        try:
            Path(f["path"]).unlink(missing_ok=True)
        except Exception:
            pass
    db.execute("DELETE FROM files WHERE msg_id=?", (mid,))
    db.execute("DELETE FROM thread WHERE msg_id=?", (mid,))
    db.execute("DELETE FROM traces WHERE msg_id=?", (mid,))
    db.execute("DELETE FROM messages WHERE id=?", (mid,))


@app.delete("/api/messages/{mid}")
def delete_message(mid: str):
    """删除单条消息（连同会话上下文与状态流转记录）。"""
    _delete_message_cascade(mid)
    return {"ok": True}


@app.post("/api/messages/{mid}/recall")
def recall_message(mid: str, authorization: str | None = Header(None)):
    """撤回消息：本地记录标记为「已撤回」（不删除，保留痕迹，微信/钉钉撤回同款体验）。

    注意：机器人无法替别人撤回其在钉钉里发的消息（平台限制），此撤回只作用于
    本平台的记录展示；钉钉侧撤回会通过 Stream 撤回事件自动同步到这里。"""
    row = db.query("SELECT * FROM messages WHERE id=?", (mid,))
    if not row:
        raise HTTPException(404, "消息不存在")
    m = db.msg_to_dict(row[0])
    if m["type"] == "recall":
        return {"ok": True, "already": True}
    db.execute("UPDATE messages SET type='recall', content=?, unread=0 WHERE id=?",
               ("（已撤回一条消息）", mid))
    db.add_trace(mid, "已撤回", "在本平台撤回，记录保留（时间线可见「已撤回」）")
    owner = _current_account(authorization)
    db.add_op(f"撤回消息 {mid}（{m['sender']}）" + (f" by {owner}" if owner else ""))
    return {"ok": True}


@app.post("/api/messages/clear")
def clear_messages(authorization: str | None = Header(None)):
    """清空聊天记录：删除当前账号名下的全部消息（管理员清空全部）。"""
    owner = _current_account(authorization)
    if owner:
        mids = [r["id"] for r in db.query("SELECT id FROM messages WHERE owner=?", (owner,))]
    else:
        mids = [r["id"] for r in db.query("SELECT id FROM messages")]
    for mid in mids:
        _delete_message_cascade(mid)
    db.add_op(f"清空聊天记录（{len(mids)} 条）")
    return {"ok": True, "deleted": len(mids)}


@app.post("/api/messages/delete-contact")
def delete_contact_messages(req: SyncReq, authorization: str | None = Header(None)):
    """删除某联系人的全部消息（会话级删除：按平台+发送人匹配）。"""
    owner = _current_account(authorization)
    sql, args = "SELECT id FROM messages WHERE platform=? AND sender=?", (req.platform, req.sender)
    if owner:
        sql += " AND owner=?"; args += (owner,)
    mids = [r["id"] for r in db.query(sql, tuple(args))]
    for mid in mids:
        _delete_message_cascade(mid)
    db.add_op(f"删除与 {req.sender} 的会话（{len(mids)} 条消息）")
    return {"ok": True, "deleted": len(mids)}


class ReplyReq(BaseModel):
    text: str
    channel: str | None = None      # 指定通道（重试/切换备用时前端传入）
    fault: bool = False             # 故障演练开关


async def _reply_internal(mid: str, msg: dict, text: str, authorization: str | None) -> dict:
    """站内好友回复：收件人落一条「收到」消息（owner=对方），我侧追加 me 气泡，WS 推送双方。"""
    text = (text or "").strip()
    if not text:
        raise HTTPException(400, "消息内容不能为空")
    owner = _current_account(authorization) or "gary"
    # 收件人 = 会话里的对方账号（conv_id=user:账号）
    to_account = (msg.get("convId") or msg.get("conv_id") or "").split(":")[-1].strip()
    if not to_account or to_account == owner:
        crow = db.query("SELECT chat FROM contacts WHERE platform='user' AND name=? AND owner=?",
                        (msg["sender"], owner))
        to_account = crow[0]["chat"] if crow else ""
    to_user = db.get_user_by_account(to_account)
    if not to_user or to_user["account"] == owner:
        raise HTTPException(404, "未能确定站内好友账号，请先添加好友后重试")
    me_user = db.get_user_by_account(owner)
    my_name = me_user["name"] if me_user else owner
    now = time.strftime("%H:%M")

    # 收件人视角：一条「收到的新消息」
    mid_in = f"m{uuid.uuid4().hex[:8]}"
    db.execute(
        "INSERT INTO messages(id,platform,msg_key,sender,chat,time,day,type,content,"
        "status,unread,pinned,muted,dedup_key,conv_id,owner,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (mid_in, "user", None, my_name, "站内消息", now, "today", "text", text,
         "received", 1, 0, 0, db.dedup_hash("user", my_name, now, text),
         f"user:{to_account}", to_account, time.time()))
    db.execute("INSERT INTO thread(msg_id,from_side,text,time,send_status,channel)"
               " VALUES(?,?,?,?,?,?)", (mid_in, "them", text, now, None, None))
    db.add_trace(mid_in, "已接收", f"站内信来自 {my_name}({owner})")
    await hub.broadcast({"type": "new_message",
                         "data": db.msg_to_dict(db.query("SELECT * FROM messages WHERE id=?", (mid_in,))[0])})

    # 我侧：追加 me 气泡 + 状态回流
    db.execute("INSERT INTO thread(msg_id,from_side,text,time,send_status,channel)"
               " VALUES(?,?,?,?,?,?)", (mid, "me", text, now, "synced", "internal"))
    db.execute("UPDATE messages SET status='replied', unread=0 WHERE id=?", (mid,))
    db.add_trace(mid, "已回复", f"站内信发给 {to_user['name']}({to_account})：{text}")
    await hub.broadcast({"type": "thread_update", "data": {"id": mid}})
    await hub.broadcast({"type": "status_update", "data": {"id": mid, "status": "replied"}})
    return {"ok": True, "channel": "internal", "status": "replied", "messageId": mid}


@app.post("/api/messages/{mid}/reply")
async def reply(mid: str, req: ReplyReq, authorization: str | None = Header(None)):
    row = db.query("SELECT * FROM messages WHERE id=?", (mid,))
    if not row:
        raise HTTPException(404, "消息不存在")
    msg = db.msg_to_dict(row[0])

    # 站内好友（platform=user）：回复走站内信双写，不经外部平台
    if msg["platform"] == "user":
        return await _reply_internal(mid, msg, req.text, authorization)

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


# ------------------------------------------------------------------ 主动发消息（联系人清单发起，个体间互发）
class ContactSendReq(BaseModel):
    platform: str                      # dingtalk | wechat
    sender: str                        # 目标联系人姓名
    chat: str = ""                     # 会话/群名
    conv_id: str = ""                  # 钉钉 openConversationId（真实回发用）
    text: str                          # 要发送的内容


@app.post("/api/contacts/send")
async def contact_send(req: ContactSendReq, authorization: str | None = Header(None)):
    """从联系人清单主动发起消息（个体间互发，老师点评新增）。
    钉钉：有 conv_id 走机器人 OpenAPI 真实 @该人 发到群；无 conv_id 降级 Webhook。
    微信：走 RPA 通道。发送后落一条「我发出的」会话记录并回流状态。"""
    if not req.text.strip():
        raise HTTPException(400, "消息内容不能为空")
    platform = req.platform if req.platform in CONNECTORS else "dingtalk"
    owner = _current_account(authorization) or "gary"

    # 站内信：platform=user 时直接落两条记录（发件人一份、收件人一份），不走外部平台
    if req.platform == "user":
        to_account = req.chat.strip()
        to_user = db.get_user_by_account(to_account)
        if not to_user:
            raise HTTPException(404, "站内好友的账号不存在")
        me_user = db.get_user_by_account(owner)
        my_name = me_user["name"] if me_user else owner
        now = time.strftime("%H:%M")
        text = req.text.strip()

        # 收件人视角：一条「收到的新消息」
        mid_in = f"m{uuid.uuid4().hex[:8]}"
        db.execute(
            "INSERT INTO messages(id,platform,msg_key,sender,chat,time,day,type,content,"
            "status,unread,pinned,muted,dedup_key,conv_id,owner,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (mid_in, "user", None, my_name, "站内消息", now, "today", "text", text,
             "received", 1, 0, 0, db.dedup_hash("user", my_name, now, text),
             f"user:{to_account}", to_account, time.time()))
        db.execute("INSERT INTO thread(msg_id,from_side,text,time,send_status,channel)"
                   " VALUES(?,?,?,?,?,?)", (mid_in, "them", text, now, None, None))
        db.add_trace(mid_in, "已接收", f"站内信来自 {my_name}({owner})")
        await hub.broadcast({"type": "new_message",
                             "data": db.msg_to_dict(db.query("SELECT * FROM messages WHERE id=?", (mid_in,))[0])})

        # 发件人视角：一条「我发出的」记录
        mid_out = f"m{uuid.uuid4().hex[:8]}"
        db.execute(
            "INSERT INTO messages(id,platform,msg_key,sender,chat,time,day,type,content,"
            "status,unread,pinned,muted,dedup_key,conv_id,owner,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (mid_out, "user", None, to_user["name"], "站内消息", now, "today", "text", text,
             "replied", 0, 0, 0, db.dedup_hash("user", to_user["name"], now, text + "out"),
             f"user:{to_account}", owner, time.time()))
        db.execute("INSERT INTO thread(msg_id,from_side,text,time,send_status,channel)"
                   " VALUES(?,?,?,?,?,?)", (mid_out, "me", text, now, "synced", "internal"))
        db.add_trace(mid_out, "已发送", f"站内信发给 {to_user['name']}({to_account})")
        await hub.broadcast({"type": "new_message",
                             "data": db.msg_to_dict(db.query("SELECT * FROM messages WHERE id=?", (mid_out,))[0])})
        return {"ok": True, "channel": "internal", "messageId": mid_out}

    # 构造一个临时的消息体走统一发送路由（复用主备降级与格式转换）
    pseudo = {
        "platform": platform,
        "sender": req.sender.strip() or "联系人",
        "chat": req.chat.strip() or "",
        "convId": req.conv_id.strip() or "",
        "conv_id": req.conv_id.strip() or "",
    }
    result: SendResult = await route_reply(pseudo, req.text.strip(), None, False)

    now = time.strftime("%H:%M")
    if result.ok:
        # 主动发起的消息：落一条记录（type=text，status=replied，owner=当前账号）
        mid = f"m{uuid.uuid4().hex[:8]}"
        dedup = db.dedup_hash(platform, req.sender, now, req.text)
        db.execute(
            "INSERT INTO messages(id,platform,msg_key,sender,chat,time,day,type,content,"
            "status,unread,pinned,muted,dedup_key,conv_id,owner,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (mid, platform, None, req.sender.strip(), req.chat.strip() or platform, now, "today",
             "text", req.text.strip(), "replied", 0, 0, 0, dedup,
             req.conv_id.strip(), owner, time.time()))
        db.execute("INSERT INTO thread(msg_id,from_side,text,time,send_status,channel)"
                   " VALUES(?,?,?,?,?,?)", (mid, "me", req.text.strip(), now, "synced", result.channel))
        db.add_trace(mid, "已回复", f"主动发消息：{result.channel} 通道发送成功 → {req.sender}")
        await hub.broadcast({"type": "new_message",
                             "data": db.msg_to_dict(db.query("SELECT * FROM messages WHERE id=?", (mid,))[0])})
        await hub.broadcast({"type": "status_update", "data": {"id": mid, "status": "replied"}})
        asyncio.get_event_loop().call_later(1.1, lambda: _sync_later(mid, result.channel))
        return {"ok": True, "channel": result.channel, "messageId": mid}
    return {"ok": False, "channel": result.channel, "reason": result.reason}


# ------------------------------------------------------------------ 好友（手动添加联系人）
class FriendAddReq(BaseModel):
    name: str
    platform: str = "dingtalk"
    chat: str = ""

@app.get("/api/contacts/list")
def friend_list(authorization: str | None = Header(None)):
    """好友清单：手动添加的联系人（与消息自动聚合的联系人合并展示）。"""
    owner = _current_account(authorization)  # None=管理员看全部
    if owner:
        rows = db.query("SELECT * FROM contacts WHERE owner=?", (owner,))
    else:
        rows = db.query("SELECT * FROM contacts")
    return [{"id": r["id"], "platform": r["platform"], "name": r["name"],
             "chat": r["chat"] or ""} for r in rows]

@app.get("/api/users/directory")
def users_directory(authorization: str | None = Header(None)):
    """注册用户目录（所有登录用户可读）：添加平台好友时选人用。"""
    if not (_current_user(authorization) or _current_account(authorization) is None):
        # 未登录也放行（初赛演示阶段），但正常登录用户一定能用
        pass
    rows = db.query("SELECT account, name, role FROM users ORDER BY id")
    return [{"account": r["account"], "name": r["name"], "role": r["role"]} for r in rows]


@app.post("/api/contacts/add")
async def friend_add(req: FriendAddReq, authorization: str | None = Header(None)):
    """添加好友：记录到联系人表（平台 + 显示名 + 会话名）。
    platform=user 表示站内好友：chat 字段存对方账号，发消息走站内信。"""
    if not req.name.strip():
        raise HTTPException(400, "好友名称不能为空")
    owner = _current_account(authorization) or "gary"
    plat = req.platform if (req.platform in CONNECTORS or req.platform == "user") else "dingtalk"
    if plat == "user":
        # 站内好友：校验账号存在，显示名取注册姓名，chat 存账号
        u = db.get_user_by_account(req.chat.strip() or req.name.strip())
        if not u:
            raise HTTPException(404, "该账号不存在，请从用户目录中选择")
        if u["account"] == owner:
            raise HTTPException(422, "不能添加自己为好友")
        name, chat = u["name"], u["account"]
    else:
        name, chat = req.name.strip(), req.chat.strip()
    db.execute("INSERT INTO contacts(platform,name,chat,owner,created_at) VALUES(?,?,?,?,?)",
               (plat, name, chat, owner, time.time()))
    db.add_op(f"添加好友 {name}（{'站内' if plat=='user' else plat}）")
    await hub.broadcast({"type": "contacts_update"})
    return {"ok": True}

@app.delete("/api/contacts/{cid}")
async def friend_delete(cid: int):
    db.execute("DELETE FROM contacts WHERE id=?", (cid,))
    await hub.broadcast({"type": "contacts_update"})
    return {"ok": True}


# ------------------------------------------------------------------ 文件发送（功能需求第3条：发送文件）
@app.post("/api/messages/{mid}/send-file")
async def send_file(mid: str, file: UploadFile = File(...), authorization: str | None = Header(None)):
    """统一入口向指定平台发送文件。钉钉走机器人媒体上传+sampleFile 真实发送；
    微信无 API，走 RPA 通道（模拟）。状态流转与文本回复一致。"""
    row = db.query("SELECT * FROM messages WHERE id=?", (mid,))
    if not row:
        raise HTTPException(404, "消息不存在")
    msg = db.msg_to_dict(row[0])
    content = await file.read()
    filename = file.filename or "file.bin"
    platform = msg["platform"]
    # 各平台媒体上传上限：飞书 30MB、钉钉 20MB，统一取较小值校验，提示按平台区分
    limit_mb = 30 if platform == "feishu" else 20
    if len(content) > limit_mb * 1024 * 1024:
        raise HTTPException(422, f"文件超过 {limit_mb}MB（{'飞书' if platform == 'feishu' else '钉钉机器人'}媒体上传上限）")

    # 本地持久化：统一入口留档，网页端可随时下载/打开（下载走 /api/files/{fid}）
    fid = uuid.uuid4().hex[:12]
    updir = Path(__file__).resolve().parent / "uploads"
    updir.mkdir(exist_ok=True)
    stored = updir / f"{fid}_{filename}"
    stored.write_bytes(content)
    db.execute("INSERT INTO files(id, msg_id, filename, size, path, created_at) VALUES(?,?,?,?,?,?)",
               (fid, mid, filename, len(content), str(stored), time.time()))

    now = time.strftime("%H:%M")
    if msg["platform"] == "user":
        # 站内好友发文件：走站内信双写（收件人视角 them + 发件人视角 me），同一 file_id 两边可下载
        # 站内好友发文件：收件人 = 会话里的对方（conv_id=user:账号 或联系人表），不能用消息归属人（那是自己）
        to_account = (msg.get("convId") or msg.get("conv_id") or "").split(":")[-1].strip()
        if not to_account or to_account == _current_account(authorization):
            # 回退：按平台+发送人名在联系人表里找
            crow = db.query("SELECT chat FROM contacts WHERE platform='user' AND name=? AND owner=?",
                            (msg["sender"], _current_account(authorization) or "gary"))
            to_account = crow[0]["chat"] if crow else ""
        me_account = _current_account(authorization) or "gary"
        to_user = db.get_user_by_account(to_account)
        if not to_user or to_user["account"] == me_account:
            raise HTTPException(404, "未能确定站内好友账号，请先通过联系人添加好友后重试")
        me_user = db.get_user_by_account(me_account)
        my_name = me_user["name"] if me_user else "我"
        # 对方收到：在对方名下落一条「收到文件」消息
        mid_in = f"m{uuid.uuid4().hex[:8]}"
        db.execute(
            "INSERT INTO messages(id,platform,msg_key,sender,chat,time,day,type,content,"
            "status,unread,pinned,muted,dedup_key,conv_id,owner,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (mid_in, "user", None, my_name, "站内消息", now, "today", "file",
             f"📎 [文件] {filename}", "received", 1, 0, 0,
             db.dedup_hash("user", my_name, now, filename), f"user:{to_account}",
             to_account, time.time()))
        db.execute("INSERT INTO thread(msg_id,from_side,text,time,send_status,channel,file_id)"
                   " VALUES(?,?,?,?,?,?,?)",
                   (mid_in, "them", f"📎 [文件] {filename}", now, "synced", "internal", fid))
        await hub.broadcast({"type": "new_message",
                             "data": db.msg_to_dict(db.query("SELECT * FROM messages WHERE id=?", (mid_in,))[0])})
        # 我这边：当前会话追加 me 气泡
        db.execute("INSERT INTO thread(msg_id,from_side,text,time,send_status,channel,file_id)"
                   " VALUES(?,?,?,?,?,?,?)",
                   (mid, "me", f"📎 [文件] {filename}", now, "synced", "internal", fid))
        db.execute("UPDATE messages SET status='replied', unread=0 WHERE id=?", (mid,))
        db.add_trace(mid, "已回复", f"站内发送文件成功：{filename}")
        await hub.broadcast({"type": "thread_update", "data": {"id": mid}})
        return {"ok": True, "channel": "internal", "status": "replied"}

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
    elif msg["platform"] == "feishu":
        conv_id = msg.get("convId") or msg.get("conv_id")
        if not conv_id:
            result_ok, channel, reason = False, "api", "该消息无飞书chat_id，无法真实回发文件"
        else:
            up = await fs_stream.upload_file(filename, content)
            if up["ok"]:
                sent = await fs_stream.send_file(conv_id, up["fileKey"])
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
        db.execute("INSERT INTO thread(msg_id,from_side,text,time,send_status,channel,file_id)"
                   " VALUES(?,?,?,?,?,?,?)",
                   (mid, "me", f"📎 [文件] {filename}", now, "synced", channel, fid))
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


# ---------- AI 自动回复（老师点评新增）----------
def _get_setting(key: str, default: str = "") -> str:
    rows = db.query("SELECT value FROM settings WHERE key=?", (key,))
    return rows[0]["value"] if rows else default


def _set_setting(key: str, value: str):
    db.execute("INSERT INTO settings(key,value) VALUES(?,?) "
               "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


@app.get("/api/ai/autoreply")
def get_autoreply():
    return {"enabled": _get_setting("autoreply", "0") == "1"}


class AutoReplyReq(BaseModel):
    enabled: bool


@app.post("/api/ai/autoreply")
async def set_autoreply(req: AutoReplyReq):
    """AI 自动回复开关：开启后新消息进来由 AI 生成回复并经发送路由自动发出。"""
    _set_setting("autoreply", "1" if req.enabled else "0")
    await hub.broadcast({"type": "autoreply_update", "data": {"enabled": req.enabled}})
    return {"ok": True, "enabled": req.enabled}


async def _auto_reply(mid: str, content: str):
    """自动回复：AI 生成回复 → 走发送路由真实发出 → 状态回流。"""
    try:
        rows = db.query("SELECT from_side, text FROM thread WHERE msg_id=? ORDER BY id", (mid,))
        ctx = [{"from": r["from_side"], "text": r["text"]} for r in rows] or \
              [{"from": "them", "text": content}]
        replies = await suggest_reply(ctx)
        text = (replies or ["收到，稍后回复你"])[0]
        row = db.query("SELECT * FROM messages WHERE id=?", (mid,))
        if not row:
            return
        msg = db.msg_to_dict(row[0])
        result: SendResult = await route_reply(msg, f"[AI自动回复] {text}", None, False)
        now = time.strftime("%H:%M")
        if result.ok:
            db.execute("INSERT INTO thread(msg_id,from_side,text,time,send_status,channel)"
                       " VALUES(?,?,?,?,?,?)",
                       (mid, "me", f"[AI自动回复] {text}", now, "synced", result.channel))
            db.execute("UPDATE messages SET status='replied', unread=0 WHERE id=?", (mid,))
            db.add_trace(mid, "AI自动回复", f"{result.channel} 通道自动发送：{text}")
            await hub.broadcast({"type": "status_update", "data": {"id": mid, "status": "replied"}})
            await hub.broadcast({"type": "thread_update", "data": {"id": mid}})  # 让网页实时补上 AI 气泡
            asyncio.get_event_loop().call_later(1.1, lambda: _sync_later(mid, result.channel))
        else:
            db.add_trace(mid, "AI自动回复失败", f"{result.channel}：{result.reason}")
    except Exception as e:
        logging.getLogger("autoreply").exception("AI 自动回复异常: %s", e)


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
async def collector_incoming(req: IncomingReq, authorization: str | None = Header(None)):
    """归一化入口：钉钉事件订阅回调、Power Automate RPA 采集流都打到这。
    返回 {"ok":true,"duplicated":false,"id":"..."}；重复消息 duplicated=true。"""
    raw = req.model_dump()
    # 多用户隔离：普通用户采集的消息归属自己（管理员/无 token 归 gary）
    owner = _current_account(authorization)
    if owner:
        raw["owner"] = owner
    return await _ingest(raw)


@app.post("/api/collector/plain")
async def collector_plain(request: Request, authorization: str | None = Header(None)):
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
    owner = _current_account(authorization)
    return await _ingest({"platform": "wechat", "sender": sender,
                          "chat": chat, "content": content,
                          **({"owner": owner} if owner else {})})


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
    # AI 自动回复：开关开启时，新消息进来 AI 生成回复并经发送路由自动发出
    if _get_setting("autoreply", "0") == "1":
        loop = asyncio.get_event_loop()
        loop.create_task(_auto_reply(result["id"], raw["content"]))
    return {"ok": True, "duplicated": False, "id": result["id"], "classify": cls}


class SyncReq(BaseModel):
    platform: str = "dingtalk"   # 手动同步的平台（演示钉钉回调闭环）
    sender: str = ""
    chat: str = ""
    content: str = ""


@app.post("/api/collector/sync")
async def collector_sync(req: SyncReq, authorization: str | None = Header(None)):
    """手动同步一条平台消息（演示「平台 → 统一入口」接收闭环）。
    正式环境此链路由平台事件订阅回调触发（钉钉）或 RPA 采集（微信），
    本地 localhost 无法被钉钉公网回调触达，故提供本手动入口兜底演示。"""
    if not req.content.strip():
        raise HTTPException(400, "消息内容不能为空")
    owner = _current_account(authorization)
    raw = {
        "platform": req.platform if req.platform in CONNECTORS else "dingtalk",
        "sender": req.sender.strip() or "钉钉群-成员",
        "chat": req.chat.strip() or "钉钉群",
        "content": req.content.strip(),
    }
    if owner:
        raw["owner"] = owner
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
