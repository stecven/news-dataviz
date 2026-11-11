# -*- coding: utf-8 -*-
"""生成导师汇报 PPT：out/demo/report.pptx（3 页，极简专业、字少图大）。

配色取自项目统一色板 loop/palette.py（暖橙系），不引入默认 Office 蓝。
图片严格按宽高比缩放，不拉伸、不遮挡文字。可重复运行（每次覆盖输出）。
"""
from __future__ import annotations

import os

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Inches, Pt

# ---------------------------------------------------------------------------
# 项目根与输出
# ---------------------------------------------------------------------------
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "out", "demo")
OUT_PPTX = os.path.join(OUT_DIR, "report.pptx")
IMAGE = os.path.join(OUT_DIR, "theme_match", "preview.png")

# ---------------------------------------------------------------------------
# 色板（与 loop/palette.py 一致，暖橙系）
# ---------------------------------------------------------------------------
PRIMARY = RGBColor(0xE8, 0xA0, 0x8C)        # 暖珊瑚：主角强调
SECONDARY = RGBColor(0xC2, 0x51, 0x2F)      # 深暖红：壁垒强调
ACCENT = RGBColor(0xE8, 0xB8, 0x5C)         # 暖金：次级强调
DARK = RGBColor(0x22, 0x22, 0x22)           # 文本深色
MID = RGBColor(0x7A, 0x80, 0x88)            # 中性中灰
LIGHT = RGBColor(0xD6, 0xDA, 0xDF)          # 中性淡灰
SURFACE = RGBColor(0xFF, 0xFF, 0xFF)        # 白底
SOFT = RGBColor(0xFB, 0xF0, 0xEA)           # 暖珊瑚淡底（卡片底）

# 画布 16:9
SLIDE_W = 13.333
SLIDE_H = 7.5
MARGIN = 0.7

# 中文字体（Windows 通用）
FONT = "Microsoft YaHei"


def _add_rect(slide, x, y, w, h, fill, line=None, line_w=None):
    """加一个矩形（可作卡片底 / 强调条）。"""
    from pptx.enum.shapes import MSO_SHAPE
    shp = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y),
                                 Inches(w), Inches(h))
    shp.fill.solid()
    shp.fill.fore_color.rgb = fill
    if line is None:
        shp.line.fill.background()
    else:
        shp.line.color.rgb = line
        shp.line.width = Pt(line_w or 0.75)
    shp.shadow.inherit = False
    return shp


def _add_text(slide, x, y, w, h, text, size, color=DARK, bold=False,
              align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, line_spacing=1.0):
    """加一个文本框，返回 text_frame。"""
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = 0
    tf.margin_right = 0
    tf.margin_top = 0
    tf.margin_bottom = 0
    p = tf.paragraphs[0]
    p.alignment = align
    p.line_spacing = line_spacing
    r = p.add_run()
    r.text = text
    r.font.size = Pt(size)
    r.font.bold = bold
    r.font.color.rgb = color
    r.font.name = FONT
    return tf


def _add_bullets(slide, x, y, w, h, items, size, color=DARK, gap=0.18,
                 bullet_color=None, line_spacing=1.0):
    """加一组带项目符号的文本（每项一行，可多行自动换行）。"""
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = 0
    tf.margin_right = 0
    tf.margin_top = 0
    tf.margin_bottom = 0
    first = True
    for it in items:
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.alignment = PP_ALIGN.LEFT
        p.line_spacing = line_spacing
        p.space_after = Pt(gap * 72)
        # 项目符号：用暖色圆点 + 文本
        r = p.add_run()
        r.text = "●  "
        r.font.size = Pt(size)
        r.font.color.rgb = bullet_color or PRIMARY
        r.font.name = FONT
        r2 = p.add_run()
        r2.text = it
        r2.font.size = Pt(size)
        r2.font.color.rgb = color
        r2.font.name = FONT
    return tf


def _add_page_number(slide, n):
    # 页码放右上角，与底部内容条完全无交集，避免任何边界框重叠。
    _add_text(slide, SLIDE_W - 0.9, 0.25, 0.5, 0.3, str(n),
              size=11, color=MID, align=PP_ALIGN.RIGHT)


def _add_footer_bar(slide):
    """底部一条暖色细线，统一三页。"""
    _add_rect(slide, MARGIN, SLIDE_H - 0.42, SLIDE_W - 2 * MARGIN, 0.03,
              fill=PRIMARY)


def _slide_title(slide, text, subtitle=None):
    """页标题 + 可选副标题（第 2、3 页用）。宽度收窄，给右上角页码留位。"""
    _add_text(slide, MARGIN, 0.45, SLIDE_W - 2 * MARGIN - 0.9, 0.7, text,
              size=30, color=DARK, bold=True)
    if subtitle:
        _add_text(slide, MARGIN, 1.15, SLIDE_W - 2 * MARGIN - 0.9, 0.4, subtitle,
                  size=14, color=MID)


def _fit_image_rect(img_w, img_h, box_x, box_y, box_w, box_h):
    """在 box 内等比缩放图片，返回 (x, y, w, h)。"""
    scale = min(box_w / img_w, box_h / img_h)
    w = img_w * scale
    h = img_h * scale
    x = box_x + (box_w - w) / 2
    y = box_y + (box_h - h) / 2
    return x, y, w, h


# ---------------------------------------------------------------------------
# 第 1 页：封面 + 核心成果
# ---------------------------------------------------------------------------
def build_slide1(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])

    # 顶部暖色装饰条
    _add_rect(slide, 0, 0, SLIDE_W, 0.12, fill=PRIMARY)

    # 标题（顶部居中）
    _add_text(slide, MARGIN, 0.55, SLIDE_W - 2 * MARGIN, 0.9,
              "新闻可视化自动编排引擎", size=40, color=DARK, bold=True,
              align=PP_ALIGN.CENTER)
    # 副标题
    _add_text(slide, MARGIN, 1.45, SLIDE_W - 2 * MARGIN, 0.5,
              "从「纯文本 + 数据库」到「多栏图文混排整版」的跨越",
              size=17, color=SECONDARY, align=PP_ALIGN.CENTER)

    # 大图：竖版 2:3，铺满中下部
    from PIL import Image
    with Image.open(IMAGE) as im:
        img_w, img_h = im.size
    box_x, box_y = MARGIN + 1.2, 2.15
    box_w, box_h = SLIDE_W - 2 * (MARGIN + 1.2), SLIDE_H - 2.15 - 1.0
    x, y, w, h = _fit_image_rect(img_w, img_h, box_x, box_y, box_w, box_h)
    slide.shapes.add_picture(IMAGE, Inches(x), Inches(y), Inches(w), Inches(h))

    # 图注（底部）
    _add_text(slide, MARGIN, SLIDE_H - 0.95, SLIDE_W - 2 * MARGIN, 0.5,
              "输入一篇新闻稿 + 数据库，系统自动匹配图表与插图，生成此版面"
              "（所有元素可在 PPT 中直接编辑）",
              size=12, color=MID, align=PP_ALIGN.CENTER)

    _add_footer_bar(slide)
    _add_page_number(slide, 1)


# ---------------------------------------------------------------------------
# 第 2 页：核心能力与工程壁垒
# ---------------------------------------------------------------------------
def build_slide2(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _slide_title(slide, "核心能力与工程壁垒")

    col_gap = 0.5
    col_w = (SLIDE_W - 2 * MARGIN - col_gap) / 2
    left_x = MARGIN
    right_x = MARGIN + col_w + col_gap
    top = 1.75
    card_h = 4.0

    # ---- 左栏：四大能力 ----
    _add_rect(slide, left_x, top, col_w, card_h, fill=SOFT)
    _add_text(slide, left_x + 0.3, top + 0.25, col_w - 0.6, 0.5,
              "四大能力", size=20, color=DARK, bold=True)
    abilities = [
        "自动拆解与匹配：文本提主题，数据配图表",
        "多栏流式排版：图文混排，等高拉伸",
        "语义化配图：词表提取，同页避重",
        "全要素可编辑：原生 PPT 形状，无图片死图",
    ]
    _add_bullets(slide, left_x + 0.3, top + 0.95, col_w - 0.6, card_h - 1.2,
                 abilities, size=15, color=DARK, gap=0.28, bullet_color=PRIMARY,
                 line_spacing=1.15)

    # ---- 右栏：两大壁垒 ----
    _add_rect(slide, right_x, top, col_w, card_h, fill=SOFT)
    _add_text(slide, right_x + 0.3, top + 0.25, col_w - 0.6, 0.5,
              "两大工程壁垒", size=20, color=DARK, bold=True)
    walls = [
        ("零大模型依赖",
         "纯规则与约束求解，毫秒级生成，零 AI 幻觉"),
        ("防御性排版引擎",
         "空间不足时自动缩放 / 降级 / 报错，绝不静默重叠"),
    ]
    yy = top + 0.95
    for title, desc in walls:
        _add_rect(slide, right_x + 0.3, yy, 0.06, 0.5, fill=SECONDARY)
        _add_text(slide, right_x + 0.5, yy, col_w - 0.8, 0.5,
                  title, size=17, color=SECONDARY, bold=True)
        _add_text(slide, right_x + 0.5, yy + 0.55, col_w - 0.8, 0.8,
                  desc, size=14, color=DARK, line_spacing=1.15)
        yy += 1.55

    # ---- 底部数据条 ----
    bar_y = SLIDE_H - 1.05
    _add_rect(slide, MARGIN, bar_y, SLIDE_W - 2 * MARGIN, 0.6, fill=DARK)
    _add_text(slide, MARGIN, bar_y, SLIDE_W - 2 * MARGIN, 0.6,
              "676 项自动化测试全绿", size=18, color=SURFACE, bold=True,
              align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)

    _add_footer_bar(slide)
    _add_page_number(slide, 2)


# ---------------------------------------------------------------------------
# 第 3 页：当前局限与后续规划
# ---------------------------------------------------------------------------
def build_slide3(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _slide_title(slide, "当前局限与后续规划")

    col_gap = 0.5
    col_w = (SLIDE_W - 2 * MARGIN - col_gap) / 2
    left_x = MARGIN
    right_x = MARGIN + col_w + col_gap
    top = 1.75
    card_h = 4.6

    # ---- 左栏：已知局限 ----
    _add_rect(slide, left_x, top, col_w, card_h, fill=SOFT)
    _add_text(slide, left_x + 0.3, top + 0.25, col_w - 0.6, 0.5,
              "已知局限", size=20, color=DARK, bold=True)
    limits = [
        "语义提取暂用词表最长匹配，未引入深度 NLP",
        "暂不支持「文字环绕卡片」的两侧排版",
    ]
    _add_bullets(slide, left_x + 0.3, top + 0.95, col_w - 0.6, card_h - 1.2,
                 limits, size=15, color=DARK, gap=0.3, bullet_color=MID,
                 line_spacing=1.2)

    # ---- 右栏：下一步计划 ----
    _add_rect(slide, right_x, top, col_w, card_h, fill=SOFT)
    _add_text(slide, right_x + 0.3, top + 0.25, col_w - 0.6, 0.5,
              "下一步计划", size=20, color=DARK, bold=True)
    plans = [
        "网格排版进阶：支持跨行跨列、图文同行",
        "AI 辅助增强：在极少数模糊场景引入轻量 NLP 消歧",
        "真实业务对接：跑通更多长文本，目标 5 秒生成报纸初稿",
    ]
    _add_bullets(slide, right_x + 0.3, top + 0.95, col_w - 0.6, card_h - 1.2,
                 plans, size=15, color=DARK, gap=0.3, bullet_color=ACCENT,
                 line_spacing=1.2)

    _add_footer_bar(slide)
    _add_page_number(slide, 3)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    if not os.path.exists(IMAGE):
        raise FileNotFoundError(f"缺少封面图：{IMAGE}")

    prs = Presentation()
    prs.slide_width = Inches(SLIDE_W)
    prs.slide_height = Inches(SLIDE_H)

    build_slide1(prs)
    build_slide2(prs)
    build_slide3(prs)

    prs.save(OUT_PPTX)
    print(f"[OK] 已生成 {OUT_PPTX}（{len(prs.slides.__iter__.__self__._sldIdLst)} 页）")


if __name__ == "__main__":
    main()