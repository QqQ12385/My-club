"""db.py — SQLite 持久化（标准消息模型 / 会话 / 应用连接 / 状态流转 / 操作日志）"""
import json
import sqlite3
import threading
import time
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "unified_msg.db"
_lock = threading.Lock()


def conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


_conn = conn()


def init_db():
    with _lock, _conn:
        _conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                platform TEXT NOT NULL,          -- wechat | dingtalk
                msg_key TEXT,                    -- 平台原始消息ID（去重键）
                sender TEXT NOT NULL,
                chat TEXT NOT NULL,              -- 会话/群名
                time TEXT NOT NULL,
                day TEXT NOT NULL,               -- today | yesterday | earlier
                type TEXT NOT NULL DEFAULT 'text',   -- text | todo
                content TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'received',
                unread INTEGER DEFAULT 1,
                pinned INTEGER DEFAULT 0,
                muted INTEGER DEFAULT 0,
                dedup_key TEXT UNIQUE,           -- RPA无ID时: sender+time+content哈希
                conv_id TEXT,                   -- 钉钉 openConversationId（回发消息用）
                created_at REAL
            );
            CREATE TABLE IF NOT EXISTS thread (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                msg_id TEXT NOT NULL,
                from_side TEXT NOT NULL,         -- them | me
                text TEXT NOT NULL,
                time TEXT NOT NULL,
                send_status TEXT,
                channel TEXT
            );
            CREATE TABLE IF NOT EXISTS traces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                msg_id TEXT NOT NULL,
                action TEXT NOT NULL,
                detail TEXT NOT NULL,
                ts REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            CREATE TABLE IF NOT EXISTS apps (
                key TEXT PRIMARY KEY,
                connected INTEGER DEFAULT 0,
                account TEXT, org TEXT, last_sync TEXT,
                success_rate TEXT, since TEXT, note TEXT
            );
            CREATE TABLE IF NOT EXISTS profile (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                data TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ops_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                time TEXT, text TEXT
            );
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account TEXT UNIQUE NOT NULL,      -- 登录账号（小写）
                name TEXT NOT NULL,                -- 显示姓名
                password_hash TEXT NOT NULL,       -- sha256 加盐哈希
                role TEXT NOT NULL DEFAULT 'user', -- admin | user
                created_at REAL NOT NULL
            );
            """
        )
        # 迁移：老库补 conv_id 列（钉钉 openConversationId）
        cols = [r[1] for r in _conn.execute("PRAGMA table_info(messages)").fetchall()]
        if "conv_id" not in cols:
            _conn.execute("ALTER TABLE messages ADD COLUMN conv_id TEXT")


def query(sql: str, args: tuple = ()) -> list:
    with _lock:
        return _conn.execute(sql, args).fetchall()


def execute(sql: str, args: tuple = ()) -> None:
    with _lock, _conn:
        _conn.execute(sql, args)


def executemany(sql: str, rows: list) -> None:
    with _lock, _conn:
        _conn.executemany(sql, rows)


def msg_to_dict(r) -> dict:
    return {
        "id": r["id"],
        "platform": r["platform"],
        "sender": r["sender"],
        "chat": r["chat"],
        "time": r["time"],
        "day": r["day"],
        "type": r["type"],
        "content": r["content"],
        "status": r["status"],
        "unread": bool(r["unread"]),
        "pinned": bool(r["pinned"]),
        "muted": bool(r["muted"]),
        "convId": r["conv_id"] if "conv_id" in r.keys() else "",
    }


def add_trace(msg_id: str, action: str, detail: str):
    execute("INSERT INTO traces(msg_id, action, detail, ts) VALUES(?,?,?,?)",
            (msg_id, action, detail, time.time()))


def add_op(text: str):
    execute("INSERT INTO ops_log(time, text) VALUES(?,?)",
            (time.strftime("今天 %H:%M"), text))


def dedup_hash(platform: str, sender: str, t: str, content: str) -> str:
    import hashlib
    raw = f"{platform}|{sender}|{t}|{content.strip()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


# ---------------- 用户认证辅助 ----------------
def hash_password(password: str, salt: str = "umc-salt-2026") -> str:
    """sha256(密码+盐) 十六进制哈希。演示级安全，真实环境建议 bcrypt。"""
    import hashlib
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


def create_user(account: str, name: str, password: str, role: str = "user") -> dict | None:
    """创建用户。账号已存在返回 None。返回用户字典。"""
    acc = account.strip().lower()
    exists = query("SELECT 1 FROM users WHERE account=?", (acc,))
    if exists:
        return None
    execute(
        "INSERT INTO users(account, name, password_hash, role, created_at) VALUES(?,?,?,?,?)",
        (acc, name.strip(), hash_password(password), role, time.time()))
    return get_user_by_account(acc)


def get_user_by_account(account: str) -> dict | None:
    rows = query("SELECT * FROM users WHERE account=?", (account.strip().lower(),))
    return dict(rows[0]) if rows else None


def verify_user(account: str, password: str) -> dict | None:
    """校验账号密码，成功返回用户字典（不含哈希），失败返回 None。"""
    u = get_user_by_account(account)
    if not u:
        return None
    if u["password_hash"] != hash_password(password):
        return None
    return {k: v for k, v in u.items() if k != "password_hash"}
