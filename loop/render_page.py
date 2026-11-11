"""整版渲染：把流式排版结果画成一张 PPT 页 + 一张 preview.png。

为什么不能直接复用单卡渲染器
----------------------------
整版是**混合卡片**的页面：温度计皮肤（ticks/outline）、半圆扇区（arc）、
占位图（image）、以及每张卡片自己的图框与标题带会同时出现在一份规格里。
现有三个适配器各只认一部分（``render_pptx`` 不认 ticks/outline/arc，
``render_thermo`` 不认 image）。所以这里写一个「全集」适配器：

* PPTX 用 ``render_thermo._add_basic`` + ``_add_skin``（已覆盖形状/扇区/皮肤）
  加一个 image 分支；
* 字号按**每张卡片各自的比例**（``flatten`` 写在 ``geometry._scale`` 上），
  不是整版比例——否则小卡片上的字会被大版面放大。
* preview 不复用 ``render_preview`` 画整版，改为**逐卡片渲染再贴回画布**：
  单卡预览已经处理了 ticks/outline/arc/image/frame/title_band 的全部细节，
  贴图能保证整版预览和单卡预览逐像素一致，也不会把卡片字号算错。
"""
import os

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt
from PIL import Image, ImageDraw

from loop import palette
from loop.layout import flatten
from loop.models import PageSpec
from loop.preview import PX_PER_IN, _render_order, render_preview

#: 正文颜色与单卡预览同源（都取自色板），避免整版文字比卡片文字深/浅。
_TEXT = "#" + palette.color("text")
from loop.render import resolve_image_path
from loop.render_thermo import _add_basic, _add_skin
from loop.text_style import FONT_NAME, apply_fill, apply_text_style


def _add_image(slide, el):
    """图片元素 → PICTURE；路径缺失/文件不在就抛，绝不静默跳过。"""
    if not el.image_path:
        raise ValueError(
            f"{el.id}: image element has no image_path "
            f"(type='image' requires the path of a file on disk)")
    path = resolve_image_path(el.image_path)
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"{el.id}: image file not found: {el.image_path} "
            f"(resolved to {path})")
    geo = el.geometry or {}
    rect = geo.get("image_rect")
    if rect:
        dx, dy, dw, dh = (float(v) for v in rect)
    else:
        dx, dy, dw, dh = 0.0, 0.0, el.w_in, el.h_in
    return slide.shapes.add_picture(path, Inches(el.x_in + dx),
                                    Inches(el.y_in + dy),
                                    Inches(dw), Inches(dh))


def _block_geometry(el):
    """拆出 (每栏行分组, 每栏净宽, 栏间距) —— 与排版层算高时同一份数据。"""
    geo = el.geometry or {}
    groups = geo.get("line_groups") or [list(geo.get("lines") or [el.text or ""])]
    groups = [list(g) for g in groups] or [[]]
    gutter = float(geo.get("column_gutter_in") or 0.0)
    inner = ((el.w_in - (len(groups) - 1) * gutter) / len(groups)
             if groups else el.w_in)
    return groups, inner, gutter


def _add_text_block(slide, el):
    """版面级文本块 → 一个 TextBox（块内分栏时每栏一个）。

    **不交给 PowerPoint 折行**：排版层已经折好行并写进
    ``geometry["lines"]``（高度就是按这个算的），这里关掉 ``word_wrap``
    并按行插入换行，保证「看到的行数」与「排版占的高度」永远一致。
    分栏正文同理：行已经分好组，这里只按栏位把每组装进自己的文本框。
    """
    from loop.text_flow import BLOCK_PAD_IN

    geo = el.geometry or {}
    groups, inner, gutter = _block_geometry(el)
    scale = float(geo.get("_scale", 1.0) or 1.0)
    align = {"left": PP_ALIGN.LEFT, "center": PP_ALIGN.CENTER,
             "right": PP_ALIGN.RIGHT}.get(geo.get("align", "left"),
                                          PP_ALIGN.LEFT)
    shape = None
    for k, lines in enumerate(groups):
        x = el.x_in + k * (inner + gutter)
        shp = slide.shapes.add_textbox(Inches(x), Inches(el.y_in),
                                       Inches(inner), Inches(el.h_in))
        tf = shp.text_frame
        tf.word_wrap = False
        tf.vertical_anchor = MSO_ANCHOR.TOP
        tf.margin_left = 0
        tf.margin_right = 0
        tf.margin_top = Inches(BLOCK_PAD_IN)
        tf.margin_bottom = 0
        for i, line in enumerate(lines):
            para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            para.alignment = align
            run = para.add_run()
            run.text = line
            run.font.size = Pt(palette.scaled_font_size(el.role, scale))
            run.font.name = FONT_NAME
            run.font.color.rgb = RGBColor.from_string(palette.color("text"))
        shape = shape or shp
    return shape


def render_pptx_page(spec: PageSpec, out_path: str) -> str:
    prs = Presentation()
    prs.slide_width = Inches(spec.width_in)
    prs.slide_height = Inches(spec.height_in)
    slide = prs.slides.add_slide(prs.slide_layouts[6])

    page_scale = palette.spec_scale(spec)
    for el in _render_order(spec):
        el_scale = float((el.geometry or {}).get("_scale", page_scale) or page_scale)
        if el.type == "text" and (el.geometry or {}).get("block"):
            shp = _add_text_block(slide, el)
            shp.name = el.id
            continue
        if el.type == "image":
            shp = _add_image(slide, el)
        elif el.type in ("ticks", "outline"):
            shp, do_fill = _add_skin(slide, el)
            hex_ = el.fill or palette.color("ticks")
            if do_fill:
                shp.fill.solid()
                shp.fill.fore_color.rgb = RGBColor.from_string(hex_)
                shp.line.fill.background()
            else:
                shp.fill.background()
                shp.line.color.rgb = RGBColor.from_string(hex_)
                shp.line.width = Pt(1.0)
        else:
            shp = _add_basic(slide, el)
            apply_fill(shp, el)
        shp.name = el.id
        if el.type == "text":
            apply_text_style(shp, el, el_scale)
    prs.save(out_path)
    return out_path


def compose_preview(page, out_path: str, card_dir: str) -> str:
    """逐卡片渲染 preview.png 再按外部坐标贴到整版画布上。"""
    os.makedirs(card_dir, exist_ok=True)
    canvas = Image.new("RGB",
                       (int(round(page.width_in * PX_PER_IN)),
                        int(round(page.height_in * PX_PER_IN))),
                       "#" + palette.color("surface"))
    for i, c in enumerate(page.cards):
        card_png = os.path.join(card_dir, f"card_{i:02d}_{c.name}.png")
        render_preview(c.spec, card_png)
        with Image.open(card_png) as pic:
            canvas.paste(pic.convert("RGB"),
                         (int(round(c.x_in * PX_PER_IN)),
                          int(round(c.y_in * PX_PER_IN))))

    draw = ImageDraw.Draw(canvas)
    for b in page.blocks:
        _draw_block(draw, b)
    for im in page.images:
        _paste_illustration(canvas, im)
    canvas.save(out_path)
    return out_path


def _paste_illustration(canvas, placed) -> None:
    """把一张版面插图按**盒内绘制矩形**贴到画布上（永不变形）。

    绘制的矩形由排版层算好写进 ``rect``（相对外盒左上角），这里只负责缩放
    与贴图：两处渲染都读同一份矩形，不会出现「PPTX 里对、PNG 里错位」。
    """
    dx, dy, dw, dh = (float(v) for v in placed.rect)
    path = resolve_image_path(placed.block.path)
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"{placed.name}: image file not found: {placed.block.path} "
            f"(resolved to {path})")
    px_w = max(1, int(round(dw * PX_PER_IN)))
    px_h = max(1, int(round(dh * PX_PER_IN)))
    with Image.open(path) as pic:
        target = pic.convert("RGBA").resize((px_w, px_h), Image.LANCZOS)
    canvas.paste(target,
                 (int(round((placed.x_in + dx) * PX_PER_IN)),
                  int(round((placed.y_in + dy) * PX_PER_IN))), target)


def _draw_block(draw, placed) -> None:
    """画一个版面文本块：逐行落地，行高与排版层算高度时用的是同一个。

    块内分栏时按 ``line_groups`` 左中右依次画，每栏的 x 由栏间距推。
    """
    from loop.fit import _load_font
    from loop.text_flow import BLOCK_PAD_IN

    style = placed.block.style
    font = _load_font(style, placed.scale)
    line_h = palette.line_height_px(style, scale=placed.scale)
    groups = [list(g) for g in (placed.line_groups or [placed.lines])]
    gutter = float(placed.column_gutter_in or 0.0)
    inner = ((placed.w_in - (len(groups) - 1) * gutter) / len(groups)
             if groups else placed.w_in)
    align = placed.block.align
    for k, lines in enumerate(groups):
        x0 = int(round((placed.x_in + k * (inner + gutter)) * PX_PER_IN))
        x1 = int(round((placed.x_in + k * (inner + gutter) + inner) * PX_PER_IN))
        y = int(round((placed.y_in + BLOCK_PAD_IN) * PX_PER_IN))
        for line in lines:
            if line:
                w = draw.textlength(line, font=font)
                if align == "center":
                    x = x0 + max(0, (x1 - x0 - w) / 2)
                elif align == "right":
                    x = x1 - w
                else:
                    x = x0
                draw.text((x, y), line, font=font, fill=_TEXT)
            y += line_h


def render_layout(page, out_dir: str, card_dir: str | None = None) -> dict:
    """把整版规格渲染成 ``page.pptx`` + ``preview.png``。"""
    os.makedirs(out_dir, exist_ok=True)
    card_dir = card_dir or os.path.join(out_dir, "_cards")
    spec = flatten(page)
    pptx = os.path.join(out_dir, "page.pptx")
    png = os.path.join(out_dir, "preview.png")
    render_pptx_page(spec, pptx)
    compose_preview(page, png, card_dir)
    return {"pptx": pptx, "preview": png, "flat_spec": spec,
            "card_dir": card_dir}


def needs_page_renderer(spec: PageSpec) -> bool:
    return spec.layout.get("kind") == "flow"


__all__ = ["render_pptx_page", "compose_preview", "render_layout",
           "needs_page_renderer", "MSO_SHAPE"]
