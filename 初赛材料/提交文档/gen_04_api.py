# -*- coding: utf-8 -*-
"""生成 04_接口设计.docx"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _docx_common import *
from docx import Document
from docx.shared import Pt, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "04_接口设计.docx")

doc = Document()
style = doc.styles["Normal"]
style.font.name = SONG
style._element.rPr.rFonts.set(qn("w:eastAsia"), SONG)
style.font.size = Pt(10.5)

build_cover(doc, "接口设计")
build_toc_page(doc)
start_body(doc)

# ============ 1 接口清单 ============
add_heading1(doc, "1. 接口清单")
add_body(doc, "系统接口以 HTTP REST 为主，WebSocket 用于服务端实时推送，另有 MQTT 主题（预留）与 RPA 采集 HTTP 触发接口。"
             "接口清单如下表所示（不含静态资源托管路由）。")

add_table_caption(doc, "表 1  接口清单")
add_table(doc,
    ["序号", "接口名称", "接口路由", "接口解释"],
    [
        ["1", "账号登录", "POST /api/auth/login", "账号密码登录，返回 token 与用户资料"],
        ["2", "用户注册", "POST /api/auth/register", "注册为普通用户并返回 token"],
        ["3", "退出登录", "POST /api/auth/logout", "退出当前会话"],
        ["4", "钉钉扫码URL", "GET /api/auth/dingtalk/url", "获取钉钉 OAuth 授权跳转地址"],
        ["5", "钉钉扫码回调", "GET /api/auth/dingtalk/callback", "授权码换 unionId，自动注册/绑定"],
        ["6", "扫码状态轮询", "GET /api/auth/dingtalk/state/{state}", "轮询扫码登录结果"],
        ["7", "个人资料", "GET / PATCH /api/me", "读取/修改当前用户个人资料"],
        ["8", "成员管理", "GET /api/users", "查看全部账号（仅管理员）"],
        ["9", "角色切换", "PATCH /api/users/{account}/role", "切换管理员/普通用户（仅管理员）"],
        ["10", "应用连接列表", "GET /api/apps", "各平台连接状态与运行状态"],
        ["11", "连接平台", "POST /api/apps/{key}/connect", "启动平台长连接并标记已连接"],
        ["12", "断开平台", "POST /api/apps/{key}/disconnect", "停止平台长连接并标记断开"],
        ["13", "测试连接", "POST /api/apps/{key}/test", "健康检查，返回延迟与真实运行状态"],
        ["14", "添加连接器", "POST /api/apps", "启用一个已实现收发逻辑的平台连接器"],
        ["15", "移除连接器", "DELETE /api/apps/{key}", "移除平台连接器"],
        ["16", "切主备通道", "PATCH /api/apps/{key}/channel", "切换主/备用通道"],
        ["17", "消息列表", "GET /api/messages", "按平台/状态/关键字筛选消息（账号隔离）"],
        ["18", "会话上下文", "GET /api/messages/{mid}/thread", "某消息的往来会话气泡"],
        ["19", "文件下载", "GET /api/files/{fid}", "下载/在线打开收发文件"],
        ["20", "删除会话气泡", "DELETE /api/thread/{tid}", "删除单条会话气泡"],
        ["21", "删除消息", "DELETE /api/messages/{mid}", "删除单条消息（级联清理）"],
        ["22", "撤回消息", "POST /api/messages/{mid}/recall", "撤回自己发送的消息（保留痕迹）"],
        ["23", "清空记录", "POST /api/messages/clear", "清空全部消息记录"],
        ["24", "回复消息", "POST /api/messages/{mid}/reply", "回复：选通道→转格式→发送→降级→回流"],
        ["25", "发送文件", "POST /api/messages/{mid}/send-file", "向会话发送文件（媒体上传 API）"],
        ["26", "主动发消息", "POST /api/contacts/send", "向联系人主动发起消息"],
        ["27", "好友清单", "GET /api/contacts/list", "聚合联系人 + 手动好友"],
        ["28", "用户目录", "GET /api/users/directory", "站内注册用户目录（加好友用）"],
        ["29", "添加好友", "POST /api/contacts/add", "手动添加好友"],
        ["30", "删除好友", "DELETE /api/contacts/{cid}", "删除好友"],
        ["31", "导出CSV", "GET /api/messages/export", "导出全部消息记录 CSV"],
        ["32", "自动回复开关", "GET/POST /api/ai/autoreply", "读取/设置 AI 自动回复开关"],
        ["33", "AI分类", "POST /api/ai/classify", "消息智能分类（text/todo/approval/notice）"],
        ["34", "回复建议", "GET /api/ai/suggest/{mid}", "基于上下文生成候选回复"],
        ["35", "每日摘要", "GET /api/ai/summary", "跨平台消息聚合摘要"],
        ["36", "归一化入站", "POST /api/collector/incoming", "平台回调/RPA采集统一入口（含去重）"],
        ["37", "纯文本入站", "POST /api/collector/plain", "纯文本消息快速入栈"],
        ["38", "手动同步", "POST /api/collector/sync", "手动同步平台消息（演示接收闭环）"],
        ["39", "健康检查", "GET /api/health", "服务健康状态"],
        ["40", "实时推送", "WS /ws", "new_message/status_update/msg_recalled/thread_update/channel_update"],
    ],
    col_aligns=["c", "c", "c", "l"],
    col_widths=[1.0, 2.6, 4.8, 6.4],
)

# ============ 2 接口详情 ============
add_heading1(doc, "2. 接口详情")

def api_detail(title, fields):
    add_table_caption(doc, title)
    add_table(doc,
        ["项", "内容"],
        fields,
        col_aligns=["c", "l"],
        col_widths=[3.0, 11.8],
    )

# 2.1 登录
add_heading2(doc, "2.1 账号登录")
api_detail("表 2  账号登录接口", [
    ["接口名称", "账号登录"],
    ["接口路由", "POST /api/auth/login"],
    ["请求方式", "POST"],
    ["涉及数据表", "users（查账号密码）、ops_log（记录登录）"],
    ["请求参数", 'JSON：{"account":"gary","password":"demo123"}'],
    ["返回数据示例", '{"token":"<24位随机>","user":{"name":"高远","role":"系统管理员","email":"gary",...}}'],
])

add_heading2(doc, "2.2 消息列表")
api_detail("表 3  消息列表接口", [
    ["接口名称", "消息列表"],
    ["接口路由", "GET /api/messages"],
    ["请求方式", "GET"],
    ["涉及数据表", "messages"],
    ["请求参数", "Query：platform（wechat/dingtalk/feishu/user）、status（received/.../unread/pending/done）、keyword；Header：Authorization"],
    ["返回数据示例", '{"messages":[{"id":"m...","platform":"dingtalk","sender":"张三","content":"...","status":"received","convId":"..."}]}'],
])

add_heading2(doc, "2.3 回复消息（核心闭环）")
api_detail("表 4  回复消息接口", [
    ["接口名称", "回复消息"],
    ["接口路由", "POST /api/messages/{mid}/reply"],
    ["请求方式", "POST"],
    ["涉及数据表", "messages、thread、traces、apps"],
    ["请求参数", '路径：mid；JSON：{"text":"回复内容","channel":"api|rpa|(空)","fault":false}；Header：Authorization'],
    ["返回数据示例", '{"ok":true,"channel":"api","status":"replied","messageId":"m..."} 或 {"ok":false,"channel":"api","reason":"..."}'],
])

add_heading2(doc, "2.4 归一化入站")
api_detail("表 5  归一化入站接口", [
    ["接口名称", "归一化入站（消息接收统一入口）"],
    ["接口路由", "POST /api/collector/incoming"],
    ["请求方式", "POST"],
    ["涉及数据表", "messages、thread、traces"],
    ["请求参数", 'JSON：{"platform":"dingtalk","sender":"张三","chat":"群名","content":"...","msg_key":"平台消息ID"}'],
    ["返回数据示例", '{"ok":true,"id":"m..."} 或 {"ok":true,"duplicated":true}'],
])

add_heading2(doc, "2.5 主动发消息")
api_detail("表 6  主动发消息接口", [
    ["接口名称", "向联系人主动发消息"],
    ["接口路由", "POST /api/contacts/send"],
    ["请求方式", "POST"],
    ["涉及数据表", "messages、thread、traces、contacts"],
    ["请求参数", 'JSON：{"platform":"dingtalk","sender":"张三","chat":"群名","conv_id":"openConversationId","text":"内容"}'],
    ["返回数据示例", '{"ok":true,"channel":"api","messageId":"m..."}'],
])

add_heading2(doc, "2.6 实时推送（WebSocket）")
api_detail("表 7  WebSocket 实时推送", [
    ["接口名称", "实时推送通道"],
    ["接口路由", "WS /ws"],
    ["请求方式", "WebSocket 长连接"],
    ["涉及数据表", "无（纯推送，按 owner 过滤）"],
    ["请求参数", "无（连接后即接收服务端广播）"],
    ["返回数据示例", '{"type":"new_message","data":{...统一消息格式}} / {"type":"status_update","data":{"id","status"}} / {"type":"channel_update","data":{"key","connected","running"}}'],
])

add_heading2(doc, "2.7 其他接口说明")
add_body(doc, "其余接口（注册、扫码登录、文件上传下载、好友管理、成员管理、AI 三件套、导出 CSV、健康检查等）均遵循同样的"
             "JSON 请求/响应约定：请求体为 JSON，响应统一为 JSON 对象；需要鉴权的接口在 Header 携带 Authorization: Bearer <token>；"
             "错误统一返回 HTTP 状态码（400/401/404/409）+ {\"detail\":\"错误说明\"}。")
add_body(doc, "接口协议不限于 HTTP：系统同时预留 MQTT 主题接入能力（若后续接入物联网设备消息，主题格式为 "
             "umc/{platform}/{deviceId}/in，消息体为统一 Message JSON），以及 RPA 采集的 HTTP 触发接口 "
             "（Power Automate 流通过 POST /api/collector/plain 上报桌面端采集的文本消息）。")

# ============ 3 其他 ============
add_heading1(doc, "3. 其他")
add_body(doc, "AI 专项对话链接：https://www.doubao.com/thread/xHUSWiR2dh9pkXq2l")
add_body(doc, "代码仓库地址：【待填写】")

doc.save(OUT)
print("SAVED:", OUT)
