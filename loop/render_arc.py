"""半圆图渲染适配器（E.1 ⑤ pptx_arc）。

与 `loop/render.py` 平级、互不修改：温度计继续走 `render_pptx()`，半圆图走
本模块的 `render_pptx_arc()`。扇区是 **PPT 原生 PIE 形状**（AUTO_SHAPE，可点开
改角度），不是位图；start/end angle 写进 `shape.adjustments`。

设计文档 E.1 ⑤：`semicircle` → 新增 arc 扇区适配器，不改 `render.py`。
"""
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Inches, Pt

from loop import palette
from loop.models import PageSpec
from loop.text_style import apply_fill, apply_text_style


def _add_shape(slide, el):
    """按元素类型建一个原生形状；arc 用 PIE 并写 start/end angle。"""
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
        # python-pptx 的 PIE adjustments = [start_angle, end_angle]（度）。
        # 缺省 0/162 改成求解器算出的扇角；α₀=180 → 半圆在下半平面。
        shp.adjustments[0] = float(g.get("start_angle", 180.0))
        shp.adjustments[1] = float(g.get("end_angle", 360.0))
    else:  # rect
        shp = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, Inches(el.x_in), Inches(el.y_in),
            Inches(el.w_in), Inches(el.h_in))
    return shp


def render_pptx_arc(spec: PageSpec, out_path: str) -> None:
    """渲染含 arc 扇区的 PageSpec 为 PPTX（每次新建 Presentation，覆盖写）。"""
    prs = Presentation()
    prs.slide_width = Inches(spec.width_in)
    prs.slide_height = Inches(spec.height_in)
    slide = prs.slides.add_slide(prs.slide_layouts[6])   # 空白版式
    # 画布变大/变小后字号跟着走（用户 m05688），比例取自图框尺寸。
    scale = palette.spec_scale(spec)

    # z-order：形状先入 tree、文字后入 tree（后者在上层，盖不住）。
    # 与 loop/preview.py 的 _render_order 同口径；半圆 PIE 楔形 bbox 会盖住
    # 中心数值与量程说明，故文字必须最后插入。温度计无 arc，顺序不变。
    from loop.preview import _render_order
    for el in _render_order(spec):
        shp = _add_shape(slide, el)
        shp.name = el.id                                  # 回读校验的主键

        apply_fill(shp, el)

        if el.type == "arc":
            # 扇区描边（用户 m05688）：14.4° 这种窄扇区没有描边就看不出边界，
            # 相邻同色系扇区也粘在一起。颜色仍取色板的中性色，不新造颜色。
            shp.line.color.rgb = RGBColor.from_string(
                palette.color(palette.SECTOR_STROKE_ROLE))
            shp.line.width = Pt(palette.SECTOR_STROKE_PT)

        if el.type == "text":
            # 字号按 el.role 查色板字号表（m04549）再乘画布缩放（m05688）。
            apply_text_style(shp, el, scale)

    prs.save(out_path)


def needs_arc_renderer(spec: PageSpec) -> bool:
    """规格里出现 arc 元素（或半圆模板）时改用本适配器。"""
    return (spec.layout.get("template") == "semicircle"
            or any(e.type == "arc" for e in spec.elements))
