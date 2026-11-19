# -*- coding: utf-8 -*-
"""生成 03_数据库设计.docx"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _docx_common import *
from docx import Document
from docx.shared import Pt, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "03_数据库设计.docx")

doc = Document()
# 默认正文样式
style = doc.styles["Normal"]
style.font.name = SONG
style._element.rPr.rFonts.set(qn("w:eastAsia"), SONG)
style.font.size = Pt(10.5)

build_cover(doc, "数据库设计")
build_toc_page(doc)
start_body(doc)

# ============ 1 数据表清单 ============
add_heading1(doc, "1. 数据表清单")
add_body(doc, "统一消息管理系统的数据层采用 SQLite 持久化，围绕「消息接收 → 统一展示 → 处理 → 发送反馈」的业务闭环，"
             "设计了 10 张核心数据表。各表职责与关联关系如下表所示。")

add_table_caption(doc, "表 1  数据表清单及关联关系")
add_table(doc,
    ["序号", "数据表名", "作用", "与其他表关系"],
    [
        ["1", "messages", "消息主表：各平台归一化后的消息记录，含状态、去重键、归属账号", "关联 thread/traces/files（1:N，msg_id）；owner 关联 users.account"],
        ["2", "thread", "会话上下文：某条消息下的往来气泡（我方/对方）", "关联 messages（N:1，msg_id）；file_id 关联 files.id"],
        ["3", "traces", "状态流转时间线：记录消息从接收→回复→同步的每一步", "关联 messages（N:1，msg_id）"],
        ["4", "files", "收发文件留档：文件ID、磁盘路径、大小", "关联 messages（N:1，msg_id）；thread.file_id 指向本表 id"],
        ["5", "contacts", "好友清单：平台联系人聚合 + 手动添加好友", "owner 关联 users.account"],
        ["6", "users", "账号体系：登录账号、角色、钉钉扫码绑定", "被 messages.owner / contacts.owner 引用"],
        ["7", "apps", "平台连接状态：各平台接入账号、是否连接、成功率", "独立（配置类）"],
        ["8", "profile", "个人资料：管理员个人信息 JSON 存储", "id 固定为 1（单行）"],
        ["9", "ops_log", "操作日志：登录、连接、修改等审计记录", "独立（审计类）"],
        ["10", "settings", "键值配置：扩展配置项", "独立（配置类）"],
    ],
    col_aligns=["c", "c", "l", "l"],
    col_widths=[1.2, 2.6, 6.0, 5.0],
)

# ============ 2 数据表内容 ============
add_heading1(doc, "2. 数据表内容")

def field_table(title, fields):
    """每个表一个表格：表名 + 序号/字段英文名/字段类型/字段中文名/字段解释。"""
    add_table_caption(doc, title)
    add_table(doc,
        ["序号", "字段英文名", "字段类型", "字段中文名", "字段解释"],
        fields,
        col_aligns=["c", "c", "c", "c", "l"],
        col_widths=[1.0, 3.2, 2.4, 2.2, 6.0],
    )

add_heading2(doc, "2.1 messages（消息主表）")
field_table("表 2  messages 表", [
    ["1", "id", "TEXT", "消息ID", "主键，全局唯一消息标识"],
    ["2", "platform", "TEXT", "平台", "来源平台：wechat / dingtalk / feishu / user"],
    ["3", "msg_key", "TEXT", "平台消息ID", "平台原始消息ID（去重键之一，可空）"],
    ["4", "sender", "TEXT", "发送人", "消息发送人姓名/昵称"],
    ["5", "chat", "TEXT", "会话/群名", "消息所在会话或群名"],
    ["6", "time", "TEXT", "时间", "消息时间（HH:MM 显示用）"],
    ["7", "day", "TEXT", "日期分组", "today / yesterday / earlier"],
    ["8", "type", "TEXT", "消息类型", "text / todo / recall 等"],
    ["9", "content", "TEXT", "消息内容", "归一化后的文本内容"],
    ["10", "status", "TEXT", "状态", "received→processing→sending→replied→synced / failed"],
    ["11", "unread", "INTEGER", "未读", "1 未读 / 0 已读"],
    ["12", "pinned", "INTEGER", "置顶", "1 置顶 / 0 否"],
    ["13", "muted", "INTEGER", "免打扰", "1 免打扰 / 0 否"],
    ["14", "dedup_key", "TEXT", "去重键", "sender+time+content 哈希（UNIQUE，RPA 无ID场景去重）"],
    ["15", "conv_id", "TEXT", "会话ID", "钉钉 openConversationId / 飞书 chat_id（回发用）"],
    ["16", "owner", "TEXT", "归属账号", "消息归属登录账号（多用户数据隔离）"],
    ["17", "created_at", "REAL", "创建时间", "落库时间戳"],
])

add_heading2(doc, "2.2 thread（会话上下文）")
field_table("表 3  thread 表", [
    ["1", "id", "INTEGER", "主键", "自增主键"],
    ["2", "msg_id", "TEXT", "消息ID", "归属消息（关联 messages.id）"],
    ["3", "from_side", "TEXT", "发送方", "them（对方）/ me（我方）"],
    ["4", "text", "TEXT", "内容", "气泡文本"],
    ["5", "time", "TEXT", "时间", "气泡时间"],
    ["6", "send_status", "TEXT", "发送状态", "发送结果（synced 等）"],
    ["7", "channel", "TEXT", "通道", "实际发送通道 api / rpa"],
    ["8", "file_id", "TEXT", "文件ID", "关联 files.id（文件气泡可下载）"],
])

add_heading2(doc, "2.3 traces（状态流转时间线）")
field_table("表 4  traces 表", [
    ["1", "id", "INTEGER", "主键", "自增主键"],
    ["2", "msg_id", "TEXT", "消息ID", "归属消息"],
    ["3", "action", "TEXT", "动作", "已接收 / 已回复 / 发送失败 等"],
    ["4", "detail", "TEXT", "详情", "该步骤的补充说明"],
    ["5", "ts", "REAL", "时间戳", "动作发生时间"],
])

add_heading2(doc, "2.4 files（文件留档）")
field_table("表 5  files 表", [
    ["1", "id", "TEXT", "文件ID", "主键，下载用"],
    ["2", "msg_id", "TEXT", "消息ID", "归属消息"],
    ["3", "filename", "TEXT", "文件名", "原始文件名"],
    ["4", "size", "INTEGER", "大小", "字节数"],
    ["5", "path", "TEXT", "磁盘路径", "本地存储路径"],
    ["6", "created_at", "REAL", "创建时间", "落库时间戳"],
])

add_heading2(doc, "2.5 contacts（好友清单）")
field_table("表 6  contacts 表", [
    ["1", "id", "INTEGER", "主键", "自增主键"],
    ["2", "platform", "TEXT", "平台", "dingtalk / wechat / user"],
    ["3", "name", "TEXT", "好友名", "好友显示名"],
    ["4", "chat", "TEXT", "会话/群名", "所属会话或群"],
    ["5", "owner", "TEXT", "归属账号", "归属登录账号"],
    ["6", "created_at", "REAL", "创建时间", "添加时间"],
])

add_heading2(doc, "2.6 users（账号体系）")
field_table("表 7  users 表", [
    ["1", "id", "INTEGER", "主键", "自增主键"],
    ["2", "account", "TEXT", "账号", "登录账号（小写，UNIQUE）"],
    ["3", "name", "TEXT", "姓名", "显示姓名"],
    ["4", "password_hash", "TEXT", "密码哈希", "sha256(盐+密码) 十六进制"],
    ["5", "role", "TEXT", "角色", "admin（管理员）/ user（普通用户）"],
    ["6", "dingtalk_unionid", "TEXT", "钉钉unionId", "钉钉扫码登录绑定（可空）"],
    ["7", "created_at", "REAL", "创建时间", "注册时间"],
])

add_heading2(doc, "2.7 apps（平台连接状态）")
field_table("表 8  apps 表", [
    ["1", "key", "TEXT", "平台键", "主键：wechat / dingtalk / feishu"],
    ["2", "connected", "INTEGER", "是否连接", "1 连接 / 0 断开"],
    ["3", "account", "TEXT", "接入账号", "平台侧账号标识"],
    ["4", "org", "TEXT", "组织", "所属组织"],
    ["5", "last_sync", "TEXT", "上次同步", "最近同步时间"],
    ["6", "success_rate", "TEXT", "成功率", "近 7 日成功率"],
    ["7", "since", "TEXT", "接入时间", "接入日期"],
    ["8", "note", "TEXT", "备注", "接入说明"],
])

add_heading2(doc, "2.8 其他表")
field_table("表 9  profile / ops_log / settings 表", [
    ["1", "profile.id", "INTEGER", "主键", "固定为 1（单行管理员资料）"],
    ["2", "profile.data", "TEXT", "资料JSON", "个人资料 JSON 序列化存储"],
    ["3", "ops_log.id", "INTEGER", "主键", "自增主键"],
    ["4", "ops_log.time / text", "TEXT", "时间/内容", "操作审计记录"],
    ["5", "settings.key / value", "TEXT", "键/值", "扩展配置键值对"],
])

# ============ 3 SQL 语句 ============
add_heading1(doc, "3. SQL 语句")

sqls = {
    "messages": """CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    msg_key TEXT,
    sender TEXT NOT NULL,
    chat TEXT NOT NULL,
    time TEXT NOT NULL,
    day TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'text',
    content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'received',
    unread INTEGER DEFAULT 1,
    pinned INTEGER DEFAULT 0,
    muted INTEGER DEFAULT 0,
    dedup_key TEXT UNIQUE,
    conv_id TEXT,
    owner TEXT NOT NULL DEFAULT 'gary',
    created_at REAL
);""",
    "thread": """CREATE TABLE IF NOT EXISTS thread (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    msg_id TEXT NOT NULL,
    from_side TEXT NOT NULL,
    text TEXT NOT NULL,
    time TEXT NOT NULL,
    send_status TEXT,
    channel TEXT,
    file_id TEXT
);""",
    "traces": """CREATE TABLE IF NOT EXISTS traces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    msg_id TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT NOT NULL,
    ts REAL NOT NULL
);""",
    "files": """CREATE TABLE IF NOT EXISTS files (
    id TEXT PRIMARY KEY,
    msg_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    size INTEGER DEFAULT 0,
    path TEXT NOT NULL,
    created_at REAL NOT NULL
);""",
    "contacts": """CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    name TEXT NOT NULL,
    chat TEXT,
    owner TEXT NOT NULL DEFAULT 'gary',
    created_at REAL NOT NULL
);""",
    "users": """CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    dingtalk_unionid TEXT,
    created_at REAL NOT NULL
);""",
    "apps": """CREATE TABLE IF NOT EXISTS apps (
    key TEXT PRIMARY KEY,
    connected INTEGER DEFAULT 0,
    account TEXT, org TEXT, last_sync TEXT,
    success_rate TEXT, since TEXT, note TEXT
);""",
    "profile": """CREATE TABLE IF NOT EXISTS profile (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    data TEXT NOT NULL
);""",
    "ops_log": """CREATE TABLE IF NOT EXISTS ops_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    time TEXT, text TEXT
);""",
    "settings": """CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);""",
}

sql_names = [
    ("messages", "messages（消息主表）"),
    ("thread", "thread（会话上下文）"),
    ("traces", "traces（状态流转时间线）"),
    ("files", "files（文件留档）"),
    ("contacts", "contacts（好友清单）"),
    ("users", "users（账号体系）"),
    ("apps", "apps（平台连接状态）"),
    ("profile", "profile（个人资料）"),
    ("ops_log", "ops_log（操作日志）"),
    ("settings", "settings（键值配置）"),
]

for key, label in sql_names:
    add_heading2(doc, f"3.{sql_names.index((key, label))+1} {label}")
    # SQL 用等宽字体（Courier New），宋体小五，不设首行缩进
    p = doc.add_paragraph()
    set_para_15(p)
    p.paragraph_format.left_indent = Pt(12)
    r = p.add_run(sqls[key])
    r.font.name = "Consolas"
    r._element.rPr.rFonts.set(qn("w:eastAsia"), SONG)
    r.font.size = Pt(9)

# ============ 4 其他 ============
add_heading1(doc, "4. 其他")
add_body(doc, "本项目的数据库迁移策略：启动时通过 PRAGMA table_info 检查列是否存在，对老库自动执行 ALTER TABLE 补列"
             "（如 conv_id、owner、dingtalk_unionid、file_id），保证历史数据库平滑升级，不丢失已有消息数据。")
add_body(doc, "AI 专项对话链接：【待填写】")

doc.save(OUT)
print("SAVED:", OUT)
