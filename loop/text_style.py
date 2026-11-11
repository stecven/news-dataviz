"""文本角色 → 字号 / 颜色的统一落地（用户 m04549）。

三个渲染适配器（render.py / render_arc.py / render_thermo.py）原本各自写
`Pt(10)` + `_TEXT_COLOR`，三份重复且无法分层。这里收成一处，三个适配器都
调它，避免出现「改了一个忘了另外两个」的经典漂移。

为什么不直接塞进 render.py 让另外两个 import：render_arc / render_thermo
是 `render.py` 的**平级**适配器（设计文档 E.1 ⑤），让它们反向依赖基础
适配器会把「平行」变成「继承」，后加第三个适配器时容易形成隐式层级。放
在独立小模块里，三者仍然是平的。
"""
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Pt

from loop import palette

#: 字体族。单一来源，与 palette 分开是因为字体名不是颜色也不是字号。
FONT_NAME = "微软雅黑"

#: 图框边框线宽（pt）。1.0 在 100 px/in 的预览上是 1.4 px，肉眼可见又不抢戏。
BORDER_PT = 1.0


def apply_text_style(shp, el, scale: float = 1.0) -> None:
    """给文本形状套上 role 决定的对齐 / 字号 / 颜色。

    ``el`` 是 ElementSpec；字号由 ``el.role`` 查 palette 的字号表再乘
    ``scale``（画布相对基准 10×6 的缩放比，见 ``palette.spec_scale``），
    颜色统一取 neutral_dark（正文类文本），不再各处硬编码。
    """
    tf = shp.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = el.text or ""
    # 对齐方式默认居中（图表内文字都要居中）；图框的标题带显式要求左对齐，
    # 通过 element.geometry["align"] 声明，不新增 PageSpec 字段。
    align = ((el.geometry or {}).get("align") or "center").lower()
    p.alignment = PP_ALIGN.LEFT if align == "left" else PP_ALIGN.CENTER

    size = Pt(palette.scaled_font_size(el.role, scale))
    rgb = RGBColor.from_string(palette.color("text"))
    for run in p.runs:
        run.font.size = size
        run.font.name = FONT_NAME
        run.font.color.rgb = rgb


def apply_fill(shp, el) -> None:
    """按 el.fill 上色。el.fill 是 hex 字符串（模板参数或求解器算出）。

    图框（role == "frame"）需要一圈可见的边框，颜色写在
    ``element.geometry["border"]`` 里；其余图元一律去描边（形状之间靠填色
    区分，描边会把相邻色块切成格子）。
    """
    if el.fill:
        shp.fill.solid()
        shp.fill.fore_color.rgb = RGBColor.from_string(el.fill)
        border = (el.geometry or {}).get("border")
        if border:
            shp.line.color.rgb = RGBColor.from_string(border)
            shp.line.width = Pt(BORDER_PT)
        else:
            shp.line.fill.background()
