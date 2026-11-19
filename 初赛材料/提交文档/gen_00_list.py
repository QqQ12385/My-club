# -*- coding: utf-8 -*-
"""生成 00_提交清单.xlsx"""
import os
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "00_提交清单.xlsx")

wb = Workbook()
ws = wb.active
ws.title = "提交清单"

# 三列
headers = ["序号", "提交文档名", "内容简介"]
rows = [
    ["1", "00_提交清单", "本表，列出本次初赛提交的全部文档及其内容概要。"],
    ["2", "01_需求分析", "对赛题「多平台连接器与统一消息管理」的需求理解、题目要求对应的功能清单、新增功能清单、核心业务流程。"],
    ["3", "02_原型设计", "软件界面清单（一级/二级菜单与主要界面）、每个界面的展示内容与主要功能、主要界面设计图。"],
    ["4", "03_数据库设计", "数据表清单及关联关系、每个数据表的字段及含义、各表创建 SQL 语句。"],
    ["5", "04_接口设计", "接口清单（含 HTTP/REST、WebSocket、MQTT 预留）、每个接口的路由、请求参数与返回数据示例。"],
    ["6", "05_初步验证", "技术选型与难点、本次验证清单、验证结果截图及说明（含长连接、收发闭环、AI、稳定性等）。"],
    ["7", "06_其他", "代码仓库地址（操作演示视频为决赛阶段材料，初赛不要求提交）。"],
]

thin = Side(style="thin", color="000000")
border = Border(left=thin, right=thin, top=thin, bottom=thin)

# 标题行
for j, h in enumerate(headers, start=1):
    c = ws.cell(row=1, column=j, value=h)
    c.font = Font(name="宋体", size=11, bold=True)
    c.alignment = Alignment(horizontal="center", vertical="center")
    c.border = border

# 数据行
for i, row in enumerate(rows, start=2):
    for j, val in enumerate(row, start=1):
        c = ws.cell(row=i, column=j, value=val)
        c.font = Font(name="宋体", size=11)
        c.border = border
        if j == 1 or j == 2:  # 序号、提交文档名：居中
            c.alignment = Alignment(horizontal="center", vertical="center")
        else:  # 内容简介：两边对齐
            c.alignment = Alignment(horizontal="justify", vertical="center", wrap_text=True)

# 列宽
ws.column_dimensions["A"].width = 8
ws.column_dimensions["B"].width = 20
ws.column_dimensions["C"].width = 70

# 行高（内容简介换行，适当加高）
ws.row_dimensions[1].height = 22
for i in range(2, len(rows) + 2):
    ws.row_dimensions[i].height = 32

wb.save(OUT)
print("SAVED:", OUT)
