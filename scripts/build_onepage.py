# -*- coding: utf-8 -*-
"""单页信息图复刻：《时令小家电换季热销》（经济日报 2026-11-03 第09版）
坐标一律按「原图像素 / 100 = 英寸」，版面比例与原图 1000x1417 一致。
图表全部 PowerPoint 原生（可点开改数据），图标来自 assets/icons，数据来自 db/assets.db。
"""

import os
import sqlite3

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Inches, Pt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "db", "assets.db")
ICONS = os.path.join(ROOT, "assets", "icons")
OUT = os.path.join(ROOT, "out", "时令小家电换季热销_单页复刻.pptx")

PW, PH = 10.0, 14.17
RED = RGBColor(0xC0, 0x1F, 0x2A)
DARK = RGBColor(0x22, 0x22, 0x22)
GRAY = RGBColor(0x66, 0x66, 0x66)
LGRAY = RGBColor(0xBB, 0xBB, 0xBB)
TRACK = RGBColor(0xF1, 0xF1, 0xF1)
FONT = "微软雅黑"


def I(px):
    return px / 100.0


# ---------------- 绘图工具 ----------------
def tb(s, x, y, w, h, text, size=8, bold=False, color=DARK,
       align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, spacing=1.0):
    box = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = 0
    tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    for i, line in enumerate(text.split("\n")):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = spacing
        r = p.add_run()
        r.text = line
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.name = FONT
        r.font.color.rgb = color
    return box


def shape(s, x, y, w, h, fill=None, line=None, kind=MSO_SHAPE.RECTANGLE, lw=0.75):
    sh = s.shapes.add_shape(kind, Inches(x), Inches(y), Inches(w), Inches(h))
    if fill is None:
        sh.fill.background()
    else:
        sh.fill.solid()
        sh.fill.fore_color.rgb = fill
    if line is None:
        sh.line.fill.background()
    else:
        sh.line.color.rgb = line
        sh.line.width = Pt(lw)
    sh.shadow.inherit = False
    return sh


def pic(s, name, x, y, size):
    path = os.path.join(ICONS, name + ".png")
    if not os.path.exists(path):
        return None
    return s.shapes.add_picture(path, Inches(x), Inches(y), Inches(size), Inches(size))


def pic_alpha(s, name, x, y, size, alpha=0.35, rot=0):
    """半透明图标，用来做背景装饰。"""
    p = pic(s, name, x, y, size)
    if p is None:
        return None
    if rot:
        p.rotation = rot
    from pptx.oxml.ns import qn
    srgb = p._element.blipFill.find(qn("a:srgbClr"))
    if srgb is not None:
        el = srgb.makeelement(qn("a:alpha"), {"val": str(int(alpha * 100000))})
        srgb.append(el)
    return p


def head(s, x, y, num, title, w=9.5):
    shape(s, x, y, 0.26, 0.26, fill=RED)
    tb(s, x, y, 0.26, 0.26, str(num), size=11, bold=True,
       color=RGBColor(0xFF, 0xFF, 0xFF), align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    tb(s, x + 0.33, y - 0.04, w - 0.33, 0.34, title, size=13, bold=True, color=RED)


def sub(s, x, y, w, text, size=6.2):
    tb(s, x, y, w, 0.2, text, size=size, bold=True, color=GRAY)


def _style_axes(ch, maxv, lab_size, horizontal):
    va = ch.value_axis
    va.maximum_scale = maxv
    va.minimum_scale = 0
    va.has_major_gridlines = False
    va.visible = False
    ca = ch.category_axis
    ca.has_major_gridlines = False
    ca.format.line.color.rgb = RGBColor(0xDD, 0xDD, 0xDD)
    ca.tick_labels.font.size = Pt(lab_size)
    ca.tick_labels.font.name = FONT
    ca.tick_labels.font.color.rgb = DARK


def _custom_labels(ch, texts):
    """给个别数据点换自定义标签文字（如「超10倍」）。"""
    if not texts:
        return
    pts = ch.plots[0].series[0].points
    for i, t in enumerate(texts):
        if t is None:
            continue
        try:
            dl = pts[i].data_label
            dl.has_text_frame = True
            dl.text_frame.text = t
            for p in dl.text_frame.paragraphs:
                for r in p.runs:
                    r.font.size = Pt(6.5)
                    r.font.bold = True
                    r.font.name = FONT
                    r.font.color.rgb = DARK
        except Exception:
            pass


def hbar(s, x, y, w, h, labels, values, color, maxv, texts=None,
         gap=55, lab_size=6.5, top_first=True, numfmt="0%"):
    """横向条形图。top_first=True 时第一条显示在最上面（图表默认自下而上）。"""
    if top_first:
        labels, values = list(reversed(labels)), list(reversed(values))
        texts = list(reversed(texts)) if texts else None
    cd = CategoryChartData()
    cd.categories = labels
    cd.add_series("s", values)
    ch = s.shapes.add_chart(XL_CHART_TYPE.BAR_CLUSTERED, Inches(x), Inches(y),
                            Inches(w), Inches(h), cd).chart
    ch.has_legend = False
    ch.has_title = False
    ch.font.size = Pt(lab_size)
    ch.font.name = FONT
    ch.font.color.rgb = DARK
    pl = ch.plots[0]
    pl.gap_width = gap
    pl.vary_by_categories = False
    pl.has_data_labels = True
    dl = pl.data_labels
    dl.font.size = Pt(lab_size)
    dl.font.bold = True
    dl.font.name = FONT
    dl.font.color.rgb = DARK
    dl.number_format = numfmt
    dl.number_format_is_linked = False
    dl.position = XL_LABEL_POSITION.OUTSIDE_END
    se = pl.series[0]
    se.format.fill.solid()
    se.format.fill.fore_color.rgb = color
    se.format.line.fill.background()
    _style_axes(ch, maxv, lab_size, True)
    _custom_labels(ch, texts)
    return ch


def vbar(s, x, y, w, h, labels, values, color, maxv, texts=None,
         gap=45, lab_size=6.2, numfmt="0%"):
    cd = CategoryChartData()
    cd.categories = labels
    cd.add_series("s", values)
    ch = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(x), Inches(y),
                            Inches(w), Inches(h), cd).chart
    ch.has_legend = False
    ch.has_title = False
    ch.font.size = Pt(lab_size)
    ch.font.name = FONT
    ch.font.color.rgb = DARK
    pl = ch.plots[0]
    pl.gap_width = gap
    pl.vary_by_categories = False
    pl.has_data_labels = True
    dl = pl.data_labels
    dl.font.size = Pt(lab_size)
    dl.font.bold = True
    dl.font.name = FONT
    dl.font.color.rgb = DARK
    dl.number_format = numfmt
    dl.number_format_is_linked = False
    dl.position = XL_LABEL_POSITION.OUTSIDE_END
    se = pl.series[0]
    se.format.fill.solid()
    se.format.fill.fore_color.rgb = color
    se.format.line.fill.background()
    _style_axes(ch, maxv, lab_size, False)
    _custom_labels(ch, texts)
    return ch


def pie(s, x, y, size, labels, values, colors, lab_size=6, show_pct=True, hole=0.0):
    cd = CategoryChartData()
    cd.categories = labels
    cd.add_series("s", values)
    kind = XL_CHART_TYPE.DOUGHNUT if hole else XL_CHART_TYPE.PIE
    ch = s.shapes.add_chart(kind, Inches(x), Inches(y),
                            Inches(size), Inches(size), cd).chart
    ch.has_legend = False
    ch.has_title = False
    ch.font.size = Pt(lab_size)
    ch.font.name = FONT
    pl = ch.plots[0]
    pl.vary_by_categories = True
    pl.has_data_labels = show_pct
    dl = pl.data_labels
    dl.show_percentage = show_pct
    dl.show_value = False
    dl.show_category_name = False
    dl.font.size = Pt(lab_size)
    dl.font.name = FONT
    dl.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    dl.number_format = "0%"
    dl.number_format_is_linked = False
    for i, c in enumerate(colors):
        pt = pl.series[0].points[i]
        pt.format.fill.solid()
        pt.format.fill.fore_color.rgb = c
        pt.format.line.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        pt.format.line.width = Pt(1)
    return ch


def legend_text(s, x, y, w, labels, values, size=5.6, spacing=1.4):
    tb(s, x, y, w, 1.3, "\n".join(f"{l} {int(round(v * 100))}%" for l, v in zip(labels, values)),
       size=size, color=DARK, spacing=spacing)


def thermometer_col(s, cx, base_y, height, width, color):
    r = width / 2
    shape(s, cx - r, base_y - height, width, height + r * 2,
          fill=color, kind=MSO_SHAPE.ROUNDED_RECTANGLE)
    shape(s, cx - width * 0.9, base_y - width * 0.9, width * 1.8, width * 1.8,
          fill=color, kind=MSO_SHAPE.OVAL)


# ---------------- 数据 ----------------
def load():
    con = sqlite3.connect(DB)
    pid = con.execute("SELECT id FROM pages ORDER BY id DESC LIMIT 1").fetchone()[0]
    row = con.execute("SELECT date, page, title FROM pages WHERE id=?", (pid,)).fetchone()
    paras = [r[0] for r in con.execute(
        "SELECT text FROM paragraphs WHERE page_id=? ORDER BY seq", (pid,))]
    charts = {}
    for k, lb, v in con.execute(
            "SELECT chart_key, label, value FROM chart_points WHERE page_id=? "
            "ORDER BY chart_key, seq", (pid,)):
        charts.setdefault(k, {"labels": [], "values": []})
        charts[k]["labels"].append(lb)
        charts[k]["values"].append(v)
    con.close()
    return row, paras, charts


# ---------------- 主流程 ----------------
def main():
    (date, page_no, title), paras, C = load()
    prs = Presentation()
    prs.slide_width = Inches(PW)
    prs.slide_height = Inches(PH)
    s = prs.slides.add_slide(prs.slide_layouts[6])
    s.background.fill.solid()
    s.background.fill.fore_color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

    # ===== 页眉 =====
    shape(s, 0, 0, PW, 0.05, fill=RED)
    tb(s, I(18), I(6), 0.6, 0.6, "9", size=32, bold=True, color=DARK)
    tb(s, I(60), I(14), 0.8, 0.24, "数据", size=9.5, bold=True, color=DARK)
    tb(s, I(60), I(38), 1.8, 0.2, "2026年11月3日 星期二", size=6.2, color=GRAY)
    tb(s, I(740), I(10), 2.4, 0.34, "经济日报", size=15, bold=True, color=DARK,
       align=PP_ALIGN.RIGHT)
    shape(s, I(25), I(62), I(950), 0.01, fill=LGRAY)
    tb(s, I(25), I(68), 1.0, 0.2, "说数", size=8.5, bold=True, color=RED)
    tb(s, I(700), I(68), 2.75, 0.2, "在这里读懂中国消费 →", size=7.2, bold=True,
       color=RED, align=PP_ALIGN.RIGHT)

    # ===== 标题 =====
    tb(s, I(80), I(84), I(760), 0.56, title, size=27, bold=True, color=DARK,
       align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    tb(s, I(430), I(142), I(160), 0.2, "林　蔚", size=6.8, color=GRAY, align=PP_ALIGN.CENTER)

    # ===== 三栏正文（左） =====
    colw, gap = 1.84, 0.08
    body_y, body_h = 1.66, 3.05
    total = sum(len(p) for p in paras)
    per, cols, cur, acc = total / 3.0, [], [], 0
    for p in paras:
        cur.append(p)
        acc += len(p)
        if acc >= per and len(cols) < 2:
            cols.append("\n".join(cur))
            cur, acc = [], 0
    cols.append("\n".join(cur))
    for i, c in enumerate(cols):
        tb(s, I(20) + i * (colw + gap), body_y, colw, body_h, c,
           size=5.4, color=RGBColor(0x33, 0x33, 0x33), spacing=1.34)

    # ===== 1 取暖电器（右上） =====
    x1 = 5.98
    head(s, x1, 1.78, 1, "取暖电器消费情况", w=3.85)
    pic(s, "thermometer", 9.26, 1.74, 0.3)
    sub(s, x1, 2.12, 3.3, "取暖电器细分品类成交额环比增速TOP5")
    d = C["heat_ratio_top5"]
    for i, (lb, v) in enumerate(zip(d["labels"], d["values"])):
        yy = 2.40 + i * 0.44
        tb(s, x1, yy + 0.04, 0.98, 0.2, lb, size=6.6, color=DARK)
        tw = 1.5
        shape(s, x1 + 1.02, yy + 0.10, tw, 0.13, fill=TRACK, kind=MSO_SHAPE.ROUNDED_RECTANGLE)
        ratio = 1.0 if v >= 10 else v / 3.0
        shape(s, x1 + 1.02, yy + 0.10, max(0.09, tw * ratio), 0.13,
              fill=RGBColor(0xE8, 0x6B, 0x4A), kind=MSO_SHAPE.ROUNDED_RECTANGLE)
        tb(s, x1 + 2.6, yy + 0.03, 0.6, 0.2, "超10倍" if v >= 10 else f"超{int(v)}倍",
           size=6.6, bold=True, color=RED)
        pic(s, "thermometer_flat", x1 + 3.14, yy + 0.01, 0.2)

    # ===== 2 除湿烘干电器 =====
    y2 = 4.72
    head(s, I(25), y2, 2, "除湿烘干电器消费情况")
    pic(s, "snowflake", 9.26, y2 - 0.06, 0.3)
    pic(s, "droplet", 8.96, y2 - 0.02, 0.22)

    # 2-A 整体 TOP5
    sub(s, I(25), y2 + 0.34, 2.3, "除湿烘干电器细分品类成交额环比增速TOP5")
    d = C["dehum_ratio_top5"]
    hbar(s, I(8), y2 + 0.50, 2.45, 1.42, d["labels"], d["values"],
         RGBColor(0x9A, 0xA8, 0xC8), 2.35, gap=52, lab_size=6.2)

    # 2-B 江苏气泡
    bx, by = 2.58, y2 + 0.50
    sub(s, bx, y2 + 0.34, 2.45, "江苏除湿烘干电器细分品类成交额环比增速TOP5")
    d = C["js_dehum_ratio"]
    spots = [(0.16, 0.10, 0.64), (1.06, 0.02, 0.50), (0.02, 0.76, 0.42),
             (0.98, 0.72, 0.36), (1.56, 0.40, 0.32)]
    for (lb, v), (dx, dy, sz) in zip(zip(d["labels"], d["values"]), spots):
        shape(s, bx + dx, by + dy, sz, sz, fill=RGBColor(0xEB, 0xE6, 0xD8),
              line=RGBColor(0xB4, 0xAB, 0x93), kind=MSO_SHAPE.OVAL, lw=1)
        tb(s, bx + dx - 0.05, by + dy + sz / 2 - 0.15, sz + 0.1, 0.3,
           f"{int(round(v * 100))}%\n{lb}", size=5.2, bold=True,
           color=RGBColor(0x46, 0x3C, 0x26), align=PP_ALIGN.CENTER,
           anchor=MSO_ANCHOR.MIDDLE, spacing=0.95)

    # 2-C 除湿烘干省份
    cx = 5.28
    sub(s, cx, y2 + 0.34, 2.1, "除湿烘干电器成交额占比TOP5省份")
    d = C["dehum_share_prov"]
    hbar(s, cx - 0.14, y2 + 0.50, 2.05, 1.42, d["labels"], d["values"],
         RGBColor(0x7F, 0xB0, 0x9E), 0.17, gap=52, lab_size=6.2)

    # 2-D 除湿烘干年龄段
    dx0 = 7.42
    sub(s, dx0, y2 + 0.34, 2.3, "各年龄段消费者除湿烘干电器成交额占比", size=5.7)
    d = C["dehum_age"]
    pie(s, dx0 - 0.04, y2 + 0.50, 1.32, d["labels"], d["values"],
        [RGBColor(0xD3, 0xDD, 0xEA), RGBColor(0xA6, 0xB8, 0xD0), RGBColor(0x7B, 0x93, 0xB2),
         RGBColor(0xBC, 0xC8, 0xD8), RGBColor(0xE3, 0xE9, 0xF1)], lab_size=5.4)
    legend_text(s, dx0 + 1.30, y2 + 0.62, 1.05, d["labels"], d["values"], 5.0)

    # --- 第二排 ---
    y3 = y2 + 2.02
    # 贵州
    sub(s, I(25), y3, 2.2, "贵州取暖电器细分品类成交额占比TOP5")
    d = C["gz_heat_share"]
    pie(s, I(10), y3 + 0.18, 1.42, d["labels"], d["values"],
        [RGBColor(0xC0, 0x1F, 0x2A), RGBColor(0xD9, 0x6B, 0x3C), RGBColor(0xE8, 0xA0, 0x5C),
         RGBColor(0xF0, 0xC8, 0x9A), RGBColor(0xF7, 0xE4, 0xCE)], lab_size=5.4)
    legend_text(s, I(158), y3 + 0.34, 1.05, d["labels"], d["values"], 5.0)

    # 湖南
    hx = 2.82
    sub(s, hx, y3, 2.35, "湖南取暖电器细分品类成交额环比增速TOP5")
    d = C["hn_heat_ratio"]
    vals = [min(v, 2.85) for v in d["values"]]
    texts = ["超10倍" if v >= 10 else f"{int(round(v * 100))}%" for v in d["values"]]
    hbar(s, hx - 0.14, y3 + 0.18, 2.4, 1.4, d["labels"], vals,
         RGBColor(0xE0, 0x9A, 0x50), 2.85, texts=texts, gap=48, lab_size=5.8)

    # 取暖年龄段
    ax = 5.30
    sub(s, ax, y3, 2.0, "各年龄段消费者取暖电器成交额占比", size=5.7)
    d = C["heat_age"]
    pie(s, ax - 0.04, y3 + 0.18, 1.32, d["labels"], d["values"],
        [RGBColor(0xF6, 0xE2, 0xCB), RGBColor(0xEB, 0xAE, 0x7C), RGBColor(0xC4, 0x5E, 0x30),
         RGBColor(0x8E, 0x3B, 0x1C), RGBColor(0xDB, 0x92, 0x60)], lab_size=5.4)
    legend_text(s, ax + 1.30, y3 + 0.34, 1.0, d["labels"], d["values"], 5.0)

    # 取暖省份
    sx = 7.46
    sub(s, sx, y3, 2.1, "取暖电器成交额占比TOP5省份", size=5.7)
    d = C["heat_share_prov"]
    pie(s, sx - 0.04, y3 + 0.18, 1.32, d["labels"], d["values"],
        [RGBColor(0xE4, 0xE9, 0xF0), RGBColor(0xAF, 0xC1, 0xD8), RGBColor(0x82, 0x9B, 0xBB),
         RGBColor(0xC9, 0xD5, 0xE4), RGBColor(0x9E, 0xAE, 0xC4)], lab_size=5.4)
    legend_text(s, sx + 1.30, y3 + 0.34, 0.95, d["labels"], d["values"], 5.0)

    # ===== 中部装饰（原图那片大枫叶位置，用极淡图标补一点层次，不压住图表） =====
    pic(s, "leaf_soft", I(300), I(690), 1.9)
    pic(s, "leaf_soft", I(560), I(700), 1.5)
    tb(s, I(180), I(886), I(640), 0.24,
       "取暖 · 除湿烘干 · 加热　三类小家电在换季窗口同步走俏", size=7.2,
       bold=True, color=RGBColor(0xC0, 0x9A, 0x70), align=PP_ALIGN.CENTER)

    # ===== 3 加热电器 =====
    y4 = 9.62
    head(s, I(25), y4, 3, "加热电器消费情况")
    pic(s, "radiator", 9.28, y4 - 0.06, 0.3)
    pic(s, "flame", 8.98, y4 - 0.02, 0.22)

    # 3-A 温度计柱
    sub(s, I(25), y4 + 0.36, 2.7, "加热电器细分品类成交额环比增速TOP5")
    d = C["heat_ratio_top5_prov"]
    base_y = y4 + 2.28
    step = I(272) / len(d["labels"])
    for i, (lb, v) in enumerate(zip(d["labels"], d["values"])):
        cx0 = I(58) + i * step
        hh = max(0.16, v / 1.25 * 1.22)
        thermometer_col(s, cx0, base_y, hh, 0.13, RGBColor(0xE2, 0x5B, 0x30))
        tb(s, cx0 - 0.40, base_y - hh - 0.28, 0.80, 0.2, f"{int(round(v * 100))}%",
           size=6.6, bold=True, color=RED, align=PP_ALIGN.CENTER)
        tb(s, cx0 - 0.40, base_y + 0.12, 0.80, 0.46, lb, size=5.2, color=DARK,
           align=PP_ALIGN.CENTER, spacing=1.05)

    # 3-B 省份环比
    px = 3.22
    sub(s, px, y4 + 0.36, 2.45, "加热电器成交额环比增速TOP5省份")
    d = C["heat_prov_ratio"]
    vbar(s, px - 0.14, y4 + 0.52, 2.45, 2.1, d["labels"], d["values"],
         RGBColor(0xE8, 0x8C, 0x5A), 1.75, gap=42, lab_size=5.8)

    # 3-C 上海
    ex = 5.98
    sub(s, ex, y4 + 0.36, 3.6, "上海加热电器细分品类成交额环比增速TOP5")
    d = C["sh_heat_ratio"]
    vals = [min(v, 3.1) for v in d["values"]]
    texts = ["超3倍" if v >= 3 else f"{int(round(v * 100))}%" for v in d["values"]]
    hbar(s, ex - 0.14, y4 + 0.52, 3.66, 2.1, d["labels"], vals,
         RGBColor(0xC0, 0x7A, 0x50), 3.1, texts=texts, gap=46, lab_size=5.8)
    pic(s, "cup", 9.20, y4 + 2.30, 0.24)
    pic(s, "sock", 8.92, y4 + 2.34, 0.2)

    # ===== 页脚 =====
    fy = 12.92
    shape(s, I(25), fy, I(950), 0.01, fill=LGRAY)
    tb(s, I(25), fy + 0.10, 1.5, 0.6, "数据周期：\n2026年8月7日\n至10月8日",
       size=6.0, color=DARK, spacing=1.25)
    tb(s, I(590), fy + 0.12, I(385), 0.5,
       "数据来源：京东消费及产业发展研究院\n本版编辑　李　瞳", size=6.0, color=GRAY,
       align=PP_ALIGN.RIGHT, spacing=1.3)
    pic(s, "leaf", I(115), fy + 0.10, 0.2)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    prs.save(OUT)
    print("已生成", OUT, os.path.getsize(OUT), "字节")


if __name__ == "__main__":
    main()
