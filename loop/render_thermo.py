"""温度计皮肤渲染适配器（E.1 ⑤ pptx_thermo）。

与 `loop/render.py` / `loop/render_arc.py` 平级、互不修改：基础图形仍按
`render_pptx()` 的口径渲染，只有 `ticks` / `outline` 两种新图元用
**PPT 原生 FREEFORM 形状**画出（可点开编辑顶点，不是位图）。

用户 m02273：「柱体右边加刻度，柱体与圆形交界面不够自然，以及外圈加一圈」。
形状点位全部来自 `loop.thermo_shape`，与 PNG 预览共用同一份几何。
"""
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Inches, Pt

from loop import palette
from loop.models import PageSpec
from loop.text_style import apply_fill, apply_text_style
from loop.thermo_shape import outline_polyline, tick_rects

_EMU_IN = 914400
_FILL_TYPES = ("ellipse", "arc", "")


def _add_basic(slide, el):
    if el.type == "text":
        shp = slide.shapes.add_textbox(
            Inches(el.x_in), Inches(el.y_in), Inches(el.w_in), Inches(el.h_in))
    elif el.type == "ellipse":
        shp = slide.shapes.add_shape(
            MSO_SHAPE.OVAL, Inches(el.x_in), Inches(el.y_in),
            Inches(el.w_in), Inches(el.h_in))
    elif el.type == "arc":
        shp = slide.shapes.add_shape(
            MSO_SHAPE.PIE, Inches(el.x_in), Inches(el.y_in),
            Inches(el.w_in), Inches(el.h_in))
        g = el.geometry or {}
        shp.adjustments[0] = float(g.get("start_angle", 180.0))
        shp.adjustments[1] = float(g.get("end_angle", 360.0))
    elif el.type == "rect" and el.role == "track":
        # 管身：顶部做成半圆顶（原版温度计的 U 形管口），adj=0.5 使圆角半径
        # 等于管宽的一半；底部圆角被球泡盖住，看不出差别。
        shp = slide.shapes.add_shape(
            MSO_SHAPE.ROUNDED_RECTANGLE, Inches(el.x_in), Inches(el.y_in),
            Inches(el.w_in), Inches(el.h_in))
        shp.adjustments[0] = 0.5
    else:  # rect / liquid
        shp = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, Inches(el.x_in), Inches(el.y_in),
            Inches(el.w_in), Inches(el.h_in))
    return shp


def _freeform_from(slide, contours):
    """把若干闭合点列（英寸）合成一个 freeform 形状。

    python-pptx 的 build_freeform 会先把局部坐标 Emu(int(round(x)))、再乘 scale，
    小数点会被抹平 → 这里直接给整数 EMU 且 scale=1.0（探针实测的唯一正确写法）。
    """
    first = contours[0]
    x0, y0 = int(first[0][0] * _EMU_IN), int(first[0][1] * _EMU_IN)
    b = slide.shapes.build_freeform(x0, y0, scale=1.0)
    for i, pts in enumerate(contours):
        emu = [(int(round(px * _EMU_IN)), int(round(py * _EMU_IN))) for px, py in pts]
        if i:
            b.move_to(*emu[0])
        b.add_line_segments(emu[1:], close=True)
    return b.convert_to_shape()


def _add_skin(slide, el):
    if el.type == "ticks":
        rects = tick_rects(el)
        contours = [[(x, y), (x + w, y), (x + w, y + h), (x, y + h)] for x, y, w, h in rects]
        return _freeform_from(slide, contours), True
    # outline：闭合轮廓**只描边不填充**。早先版本靠「填色 + 后续图元盖住内部」
    # 的取巧做法，会连带盖掉画在它之前的刻度线（PPTX 与 PNG 表现不一致）。
    return _freeform_from(slide, [outline_polyline(el)]), False


def render_pptx_thermo(spec: PageSpec, out_path: str) -> None:
    """渲染带皮肤图元的温度计规格为 PPTX（每次新建 Presentation，覆盖写）。"""
    prs = Presentation()
    prs.slide_width = Inches(spec.width_in)
    prs.slide_height = Inches(spec.height_in)
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    # 画布变大/变小后字号跟着走（用户 m05688），比例取自图框尺寸。
    scale = palette.spec_scale(spec)

    # z-order：形状先、文字最后（与 render_arc / preview 同口径）。
    from loop.preview import _render_order
    for el in _render_order(spec):
        if el.type in ("ticks", "outline"):
            shp, do_fill = _add_skin(slide, el)
            # 兜底色取色板（m04549）：模板总会给 fill，这里只是防御性默认。
            tick_hex = el.fill or palette.color("ticks")
            if do_fill:
                shp.fill.solid()
                shp.fill.fore_color.rgb = RGBColor.from_string(tick_hex)
                shp.line.fill.background()
            else:
                # 外圈是「一圈描边」，不是实心块：无填充 + 细线，线条排在最前。
                shp.fill.background()
                shp.line.color.rgb = RGBColor.from_string(tick_hex)
                shp.line.width = Pt(1.0)
        else:
            shp = _add_basic(slide, el)
            apply_fill(shp, el)
        shp.name = el.id

        if el.type == "text":
            # 字号按 el.role 查色板字号表（m04549）再乘画布缩放（m05688）。
            apply_text_style(shp, el, scale)

    prs.save(out_path)


def needs_thermo_renderer(spec: PageSpec) -> bool:
    """规格里出现温度计皮肤图元（或温度计模板）时改用本适配器。"""
    return (spec.layout.get("template") == "thermometer"
            or any(e.type in ("ticks", "outline") for e in spec.elements))
