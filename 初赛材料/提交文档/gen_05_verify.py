# -*- coding: utf-8 -*-
"""生成 05_初步验证.docx"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _docx_common import *
from docx import Document
from docx.shared import Pt, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH

BASE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(BASE, "..", "..", "docs", "assets")
OUT = os.path.join(BASE, "05_初步验证.docx")

doc = Document()
style = doc.styles["Normal"]
style.font.name = SONG
style._element.rPr.rFonts.set(qn("w:eastAsia"), SONG)
style.font.size = Pt(10.5)

build_cover(doc, "初步验证")
build_toc_page(doc)
start_body(doc)

# ============ 1 技术选择 ============
add_heading1(doc, "1. 技术选择")
add_body(doc, "本系统采用前后端分离架构，围绕「多平台消息接入 → 统一展示 → 处理 → 发送反馈」闭环进行技术选型，"
             "重点解决多平台协议差异、长连接实时性、消息去重与数据隔离、发送可靠性等技术难点。")

add_heading2(doc, "1.1 前端技术")
add_body(doc, "前端采用原生 HTML + CSS + JavaScript 单页应用，不依赖框架，通过 Fetch 调用 REST 接口、WebSocket 接收实时推送。"
             "界面为三栏布局（平台筛选 + 消息列表 + 会话面板），支持图片/文件气泡预览下载、语音输入、消息撤回同步等交互。"
             "技术难点在于多平台消息的归一化展示与状态回流渲染，需保证气泡、缩略图、状态标签在多端实时一致。")

add_heading2(doc, "1.2 后端技术")
add_body(doc, "后端采用 Python FastAPI + Uvicorn，异步处理高并发消息入站与推送。核心难点有三：其一，多平台长连接接入——"
             "钉钉走 dingtalk-stream SDK 的 Stream 长连接，飞书走 lark-oapi 的 WebSocket 长连接，均无需公网回调地址，"
             "个人自建组织即可稳定收发；其二，发送主备降级——按平台通道计划选择主通道，失败自动切备用通道重发；"
             "其三，消息去重与数据隔离——以平台消息ID或内容哈希去重，以 owner 字段隔离多用户数据。")

add_heading2(doc, "1.3 数据库技术")
add_body(doc, "数据层采用 SQLite（WAL 模式），轻量零运维，满足演示与初赛场景。设计了 messages、thread、traces、files、"
             "contacts、users、apps 等 10 张表，支撑消息存储、会话上下文、状态流转回溯、文件留档、账号与好友体系。"
             "技术难点在于老库平滑迁移（启动时 PRAGMA 检查列并自动 ALTER TABLE 补列）。")

add_heading2(doc, "1.4 接口技术")
add_body(doc, "接口以 HTTP REST 为主（/api/*），WebSocket（/ws）负责实时推送，另预留 MQTT 主题接入与 RPA 采集的 HTTP 触发接口。"
             "技术难点在于跨平台消息格式归一化——各平台原始消息结构差异大（钉钉 content 为 JSON、飞书事件含 mentions、"
             "微信 RPA 为纯文本），统一归一化为标准 Message 结构后再入库与推送。")

add_heading2(doc, "1.5 AI 技术")
add_body(doc, "AI 能力接入 DeepSeek 大模型，实现消息智能分类（text/todo/approval/notice）、回复建议、每日摘要三大功能。"
             "技术难点在于无 API Key 时的优雅降级——自动切换为规则引擎分类，保证闭环不因 AI 不可用而中断；"
             "同时支持 AI 自动回复开关，新消息到达时按配置自动生成回复并回发平台。")

# ============ 2 验证清单 ============
add_heading1(doc, "2. 验证清单")
add_body(doc, "本次初步验证覆盖技术选型中的五大维度，验证内容与前面需求分析、原型设计、数据库设计、接口设计逐项对应，"
             "确保「设计与验证一致」。验证清单如下表所示。")

add_table_caption(doc, "表 1  验证清单")
add_table(doc,
    ["序号", "验证内容", "对应设计", "验证方式", "备注"],
    [
        ["1", "验证接口：钉钉 Stream 长连接建立", "接口设计 2.7 / 技术选择 1.2", "启动后端，观察日志输出 CONNECT_OK/TOKEN_OK", "真实凭据（企业内部应用）"],
        ["2", "验证接口：消息接收（钉钉→统一入口）", "接口设计 2.4 归一化入站", "钉钉群发消息，观察网页实时新增", "Stream 推送 + WebSocket"],
        ["3", "验证接口：消息发送（统一入口→钉钉）", "接口设计 2.3 回复消息", "网页回复，观察钉钉群收到机器人消息", "机器人 OpenAPI 真实回发"],
        ["4", "验证接口：飞书长连接收发", "接口设计 2.4 / 技术选择 1.2", "飞书单聊机器人发文字/图片/文件", "lark-oapi WebSocket 长连接"],
        ["5", "验证功能：状态回流与时间线", "数据库设计 traces 表", "处理消息后查看状态流转时间线", "received→replied→synced"],
        ["6", "验证功能：AI 自动回复闭环", "技术选择 1.5 AI 技术", "飞书群 @机器人，观察自动回复", "DeepSeek + 规则降级"],
        ["7", "验证数据库：消息持久化与去重", "数据库设计 messages 表", "重复消息只入库一次", "msg_key / dedup_key 去重"],
        ["8", "验证功能：多用户数据隔离", "数据库设计 owner 字段", "普通用户只见自己名下消息", "管理员可见全部"],
        ["9", "验证功能：文件收发留档", "数据库设计 files 表", "收发图片/文件可预览下载", "磁盘留档 + fileId 关联"],
        ["10", "稳定性：长连接断线重连", "技术选择 1.2 后端", "停启连接器，观察接收状态切换", "连接器真正启停"],
    ],
    col_aligns=["c", "l", "c", "l", "l"],
    col_widths=[1.0, 3.4, 3.0, 4.2, 3.2],
)

# ============ 3 验证结果 ============
add_heading1(doc, "3. 验证结果")

def verify_item(fig_no, fig_name, img_file, desc):
    add_heading2(doc, fig_name)
    # 插图
    path = os.path.join(ASSETS, img_file)
    if os.path.exists(path):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run()
        run.add_picture(path, width=Cm(14.5))
    else:
        add_para(doc, f"（截图缺失：{img_file}）", align=WD_ALIGN_PARAGRAPH.CENTER)
    add_fig_caption(doc, f"图 {fig_no}  {fig_name}")
    add_body(doc, desc)

verify_item("1", "钉钉 Stream 长连接建立",
    "验证-01-钉钉Stream连接成功.png",
    "启动后端后，命令行输出 CONNECT_OK 与 TOKEN_OK，表明钉钉 Stream 长连接已成功建立并获得有效期 7200 秒的访问令牌。"
    "该验证对应接口设计的实时推送通道与后端技术选型中的钉钉 Stream 长连接接入，证明无需公网回调即可建立双向通道。")

verify_item("2", "钉钉消息接收进统一入口",
    "验证-02-钉钉收消息进页面.png",
    "在钉钉群内发送消息后，网页消息列表实时新增一条消息，状态为「已接收」。该验证对应归一化入站接口（POST /api/collector/incoming），"
    "证明「平台→统一入口」的接收闭环可用，消息经归一化、去重、落库后经 WebSocket 实时推送至前端。")

verify_item("3", "统一入口回复回发到钉钉群",
    "验证-03-页面回复回群.png",
    "在网页打开会话并回复后，钉钉群内收到机器人消息（带 @对方 与群名标注），网页消息状态流转为「已回复→已同步到平台」。"
    "该验证对应回复消息接口（POST /api/messages/{mid}/reply），证明「统一入口→平台」的发送闭环可用，发送路由与状态回流均正常。")

verify_item("4", "状态回流时间线",
    "验证-05-状态回流时间线.png",
    "打开任意已处理消息的状态流转时间线，可看到「已接收→已回复→已同步到平台」完整链路，每步带时间戳。"
    "该验证对应数据库设计中的 traces 表，证明消息处理全过程可回溯，满足「状态回流」的闭环要求。")

verify_item("5", "飞书单聊收发文字/图片/文件",
    "验证-06-飞书单聊收文字图片文件.png",
    "飞书单聊机器人依次发送文字、图片、PDF 文件（23.2MB 大文件），网页飞书会话实时新增对应气泡：文字消息、图片缩略图（可点击大图预览）、"
    "文件气泡（可下载）。该验证覆盖飞书长连接接收、图片/文件资源下载留档，证明飞书企业自建应用长连接接入可用。")

verify_item("6", "飞书群聊发送与 AI 自动回复",
    "验证-09-飞书群聊发送与AI自动回复.png",
    "在飞书群内 @机器人发送消息后，消息实时进入网页；AI 自动回复（如「挺好的，谢谢关心」）同时写入本地气泡并回发到飞书群，"
    "状态标注「已同步到飞书 · API」。该验证覆盖飞书群聊收发与 AI 自动回复闭环，对应技术选择中的 AI 技术维度。")

add_heading2(doc, "验证补充说明")
add_body(doc, "除上述截图验证外，还完成了以下验证：①消息持久化与去重——同一平台消息重复上报只入库一次（msg_key/dedup_key 去重）；"
             "②多用户数据隔离——普通用户仅见自己名下消息，管理员可见全部并拥有成员管理权限；③稳定性——长连接断线自动重连，"
             "连接器可在「应用连接」页真正停止/启动，停止后不再接收新消息。上述功能均与设计文档一致。")

# ============ 4 其他 ============
add_heading1(doc, "4. 其他")
add_body(doc, "AI 专项对话链接：【待填写】")
add_body(doc, "代码仓库地址：【待填写】")

doc.save(OUT)
print("SAVED:", OUT)
