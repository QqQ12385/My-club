# -*- coding: utf-8 -*-
"""docx_common.py — 初赛提交 Word 文档的公共样式工具
严格对照《初赛提交资料要求.docx》的格式要求：
  - 首页：项目名称(宋体加粗三号居中)/文档名称(宋体加粗四号居中)/队伍人员(宋体四号居中)/报名序号(宋体四号居中)
  - 第二页：目录(小四, 仅到二级标题, 1.5倍行距, 引用方式生成)
  - 第三页起正文，页码从第三页起为 1
  - 标题层级 1. / 1.1 / (1)，最多三级
  - 一级标题宋体小四加粗，二级宋体五号加粗，三级与正文宋体五号
  - 正文及标题 1.5 倍行距
  - 表格：标题居中，有表序号及表名在表正上方居中；图序号图名在图下方居中
"""
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.enum.section import WD_SECTION
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

SONG = "宋体"
HEI = "黑体"

PROJECT_NAME = "多平台连接器与统一消息管理"
TEAM = "【成员A姓名】　【成员B姓名】"
REG_NO = "【报名序号】"


def set_font(run, name=SONG, size=10.5, bold=False, color=None):
    """设置 run 字体：size 单位磅(pt)。五号=10.5pt，小四=12pt，四号=14pt，三号=16pt。"""
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)
    run.font.size = Pt(size)
    run.font.bold = bold
    if color:
        run.font.color.rgb = RGBColor(*color)


def set_para_15(p):
    """1.5 倍行距。"""
    pf = p.paragraph_format
    pf.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE


def add_para(doc, text="", size=10.5, bold=False, align=None, name=SONG,
             space_before=0, space_after=0, first_indent=None, line15=True):
    p = doc.add_paragraph()
    if line15:
        set_para_15(p)
    pf = p.paragraph_format
    if align is not None:
        p.alignment = align
    pf.space_before = Pt(space_before)
    pf.space_after = Pt(space_after)
    if first_indent is not None:
        pf.first_line_indent = Pt(first_indent)
    if text:
        r = p.add_run(text)
        set_font(r, name=name, size=size, bold=bold)
    return p


def add_heading1(doc, text):
    """一级标题：宋体小四(12pt)加粗，1.5 倍行距。"""
    return add_para(doc, text, size=12, bold=True, space_before=8, space_after=4)


def add_heading2(doc, text):
    """二级标题：宋体五号(10.5pt)加粗。"""
    return add_para(doc, text, size=10.5, bold=True, space_before=6, space_after=3)


def add_heading3(doc, text):
    """三级标题：宋体五号(10.5pt)。"""
    return add_para(doc, text, size=10.5, bold=False, space_before=3, space_after=2)


def add_body(doc, text, indent=True):
    """正文：宋体五号，1.5 倍行距，首行缩进 2 字符。"""
    return add_para(doc, text, size=10.5, first_indent=(21 if indent else None))


def _set_cell_border(cell):
    """给单元格加全边框（单线）。"""
    tcPr = cell._tc.get_or_add_tcPr()
    borders = OxmlElement("w:tcBorders")
    for edge in ("top", "left", "bottom", "right"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), "4")
        el.set(qn("w:color"), "000000")
        borders.append(el)
    tcPr.append(borders)


def _cell_text(cell, text, size=10.5, bold=False, align=WD_ALIGN_PARAGRAPH.CENTER, name=SONG):
    cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    p = cell.paragraphs[0]
    p.alignment = align
    set_para_15(p)
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(2)
    r = p.add_run(text)
    set_font(r, name=name, size=size, bold=bold)


def add_table(doc, headers, rows, col_aligns=None, col_widths=None):
    """加三线表风格（实际用全边框，符合"方框均加边框线"）。
    headers/rows 均为字符串列表。col_aligns: 每列对齐('c'居中/'l'两端)。"""
    table = doc.add_table(rows=1, cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    # 表头
    for j, h in enumerate(headers):
        c = table.rows[0].cells[j]
        _cell_text(c, h, size=10.5, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
        _set_cell_border(c)
    # 数据行
    for row in rows:
        cells = table.add_row().cells
        for j, val in enumerate(row):
            align = WD_ALIGN_PARAGRAPH.CENTER
            if col_aligns and col_aligns[j] == "l":
                align = WD_ALIGN_PARAGRAPH.JUSTIFY
            _cell_text(cells[j], str(val), size=10.5, bold=False, align=align)
            _set_cell_border(cells[j])
    # 列宽
    if col_widths:
        for j, w in enumerate(col_widths):
            for row in table.rows:
                row.cells[j].width = Cm(w)
    return table


def add_table_caption(doc, text):
    """表序号及表名，位于表正上方居中。"""
    return add_para(doc, text, size=10.5, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER,
                    space_before=6, space_after=2)


def add_fig_caption(doc, text):
    """图序号及图名，位于图下方居中。"""
    return add_para(doc, text, size=10.5, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER,
                    space_before=2, space_after=6)


def build_cover(doc, doc_name):
    """首页封面。"""
    # 顶部留白
    for _ in range(4):
        add_para(doc, "", line15=True)
    add_para(doc, PROJECT_NAME, size=16, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
    add_para(doc, "", line15=True)
    add_para(doc, doc_name, size=14, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
    add_para(doc, "", line15=True)
    add_para(doc, "", line15=True)
    add_para(doc, TEAM, size=14, bold=False, align=WD_ALIGN_PARAGRAPH.CENTER)
    add_para(doc, REG_NO, size=14, bold=False, align=WD_ALIGN_PARAGRAPH.CENTER)


def build_toc_page(doc):
    """第二页目录（自动域引用，仅到二级标题）。"""
    doc.add_page_break()
    p = add_para(doc, "目录", size=12, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER,
                 space_after=6)
    # 插入 TOC 域，级别 1-2
    para = doc.add_paragraph()
    run = para.add_run()
    fldChar = OxmlElement("w:fldChar")
    fldChar.set(qn("w:fldCharType"), "begin")
    run._r.append(fldChar)
    instrText = OxmlElement("w:instrText")
    instrText.set(qn("xml:space"), "preserve")
    instrText.text = 'TOC \\o "1-2" \\h \\z \\u'
    run._r.append(instrText)
    fldChar2 = OxmlElement("w:fldChar")
    fldChar2.set(qn("w:fldCharType"), "separate")
    run._r.append(fldChar2)
    # 占位
    run2 = para.add_run("（目录将在 Word 中右键“更新域”自动生成）")
    set_font(run2, size=12)
    fldChar3 = OxmlElement("w:fldChar")
    fldChar3.set(qn("w:fldCharType"), "end")
    run2._r.append(fldChar3)


def start_body(doc):
    """第三页开始正文，并从第三页起设页码 1。"""
    # 新分节，页码从 1 开始
    section = doc.add_section(WD_SECTION.NEW_PAGE)
    # 页码域放页脚，居中
    footer = section.footer
    footer.is_linked_to_previous = False
    p = footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run()
    fldChar1 = OxmlElement("w:fldChar")
    fldChar1.set(qn("w:fldCharType"), "begin")
    run._r.append(fldChar1)
    instrText = OxmlElement("w:instrText")
    instrText.set(qn("xml:space"), "preserve")
    instrText.text = "PAGE"
    run._r.append(instrText)
    fldChar2 = OxmlElement("w:fldChar")
    fldChar2.set(qn("w:fldCharType"), "end")
    run._r.append(fldChar2)
    set_font(run, size=10.5)
    # 页码从 1 重新计
    sectPr = section._sectPr
    pgNumType = OxmlElement("w:pgNumType")
    pgNumType.set(qn("w:start"), "1")
    sectPr.append(pgNumType)
    return section
