"""文本块：折行与高度计算（图文混排 0.1，用户 m06055）。

为什么折行要由排版层算、而不是交给渲染器
----------------------------------------
页面上文字与卡片共用一个纵向游标，**文字占多高**决定了后面所有元素的 y。
如果让 PowerPoint 自己折行，排版层就只能猜高度，猜错就是重叠或留白。
所以：排版层用与预览同一套字体度量（`fit._load_font`）折一次行，把折好的
行写进元素（`geometry["lines"]`），两个渲染器都照抄 —— PPTX 端关闭
`word_wrap` 并按行插换行，PNG 端逐行画。这样「排版高度」与「看到的行数」
永远一致。
"""
from loop import palette
from loop.fit import _load_font, _wrap_lines
from loop.preview import PX_PER_IN

#: 文本块上下各留一点呼吸位（英寸）。它算进块高，所以间距仍是 gutter。
BLOCK_PAD_IN = 0.05

#: 文本块允许的样式名 —— 就是色板字号表里那几个设计角色。
BLOCK_STYLES = ("title", "subtitle", "body", "label", "note")

ALIGNS = ("left", "center", "right")


def line_height_in(style: str, scale: float = 1.0) -> float:
    """一行占多少英寸（pt → in，含行距系数）。"""
    return palette.font_size(style) * scale * palette.LINE_HEIGHT_RATIO / 72.0


def wrap(text: str, style: str, width_in: float, scale: float = 1.0) -> list:
    """按盒宽逐字折行。显式 ``\\n`` 是硬换行，不被合并。"""
    if width_in <= 0:
        raise ValueError(f"text block width must be positive, got {width_in!r}")
    font = _load_font(style, scale)
    max_w_px = width_in * PX_PER_IN
    lines: list = []
    for para in text.split("\n"):
        if not para:
            lines.append("")
            continue
        lines.extend(_wrap_lines(para, font, max_w_px))
    return lines or [""]


def block_height_in(text: str, style: str, width_in: float,
                    scale: float = 1.0) -> float:
    """文本块高度 = 行数 × 行高 + 上下留白。"""
    return round(len(wrap(text, style, width_in, scale)) * line_height_in(style, scale)
                 + 2 * BLOCK_PAD_IN, 6)


def inner_column_width_in(width_in: float, columns: int,
                          column_gutter_in: float = 0.2) -> float:
    """块内分栏时每一栏的净宽。"""
    if columns < 1:
        raise ValueError(f"columns must be >= 1, got {columns!r}")
    inner = (width_in - (columns - 1) * column_gutter_in) / columns
    if inner <= 0:
        raise ValueError(
            f"{width_in:.4f} in 宽放不下 {columns} 栏（栏间距 {column_gutter_in:.4f}）")
    return inner


def balance_lines(lines: list, columns: int) -> list:
    """把折好的行按行数均分到 N 栏（报纸式均衡分栏）。

    第 0 栏拿前若干行、第 1 栏拿接着的若干行 —— 阅读顺序不被改动，只是折到
    下一栏继续。均分取上取整，所以最后一栏可能短一点，不会出现空栏。
    """
    if columns < 1:
        raise ValueError(f"columns must be >= 1, got {columns!r}")
    if columns == 1:
        return [list(lines)]
    per = -(-len(lines) // columns)
    groups = [list(lines[i * per:(i + 1) * per]) for i in range(columns)]
    return [g for g in groups if g] or [[]]


def wrap_columns(text: str, style: str, width_in: float, columns: int = 1,
                 scale: float = 1.0, column_gutter_in: float = 0.2) -> list:
    """块内分栏折行：返回**每栏的行列表**（``len(...) == columns``）。"""
    inner = inner_column_width_in(width_in, columns, column_gutter_in)
    return balance_lines(wrap(text, style, inner, scale), columns)


def columns_height_in(groups: list, style: str, scale: float = 1.0) -> float:
    """分栏块的高度 = **最长一栏**的行数 × 行高 + 上下留白。"""
    longest = max((len(g) for g in groups), default=0)
    return round(longest * line_height_in(style, scale) + 2 * BLOCK_PAD_IN, 6)
