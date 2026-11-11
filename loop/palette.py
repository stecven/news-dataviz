"""统一色板与文本角色字号表（用户 m04549）。

这是**单一来源**：渲染层（render.py / render_arc.py / render_thermo.py /
preview.py）与模板默认色都从这里取，改一处全流水线生效。

为什么单独一个模块而不是散在模板参数里：m04383 的端到端复盘发现三张图
配色零交集——温度计 E8A08C+FFFFFF+C9C9C9（暖珊瑚单色）、半圆
C01F2A+E07B39+F2C14E+7A9E7E+6C7A89（五色撞色）、占位图 7A8088+A8AEB6+
D6DADF（中性灰）。根因是每个模板各自带 `color_*` 默认值，彼此不知道对方
存在。色板把「一版用哪些颜色」抬到版本级，模板只声明「我用哪个角色」。

色板角色
--------
用户 m04549 原定 6 个：primary / secondary / neutral_dark / neutral_light /
accent_1 / accent_2。实现时发现两处不够用，均已向用户确认（回答见 m04607）：

1. **第 5 个扇区色**：半圆要 5 色分类，6 个角色里只有 4 个是彩色。
   用户裁定「补一个 accent_3」（石板灰，沿用原版报纸）。
2. **neutral 需要 4 档而不是 2 档**：文本深色、温度计划度/外圈（很淡的发
   丝线）、占位图主笔与虚框（中灰）是三种明确不同的用法，压成同色会让
   刻度线看不见或占位图"笔触"发虚。故拆成 dark / strong / mid / light /
   hairline 五档，每档都有唯一使用点。

cross-figure 的关键决策
-----------------------
`primary` 取 **E8A08C**，即温度计液柱的暖珊瑚色——这是从 m02007 起花了
多轮对齐《经济日报》原版得到的颜色。半圆图第 1 个扇区也用 primary，
于是两张图共享同一个"主角暖色"，这正是本轮要的"配色收敛"。若把 primary
改成更深的暖红，温度计就会偏离已验收的原版外观，得不偿失。

顺序约定
--------
`SECTOR_ROLES = ("primary", "secondary", "accent_1", "accent_2", "accent_3")`
是半圆图的**固定取色顺序**。不随机、不轮转、不按数值排序——同一份数据
每跑一次颜色一致，且相邻扇区色距经过校验（见 `check_separation`）。

字号
----
用户要求的 5 个设计角色 title / subtitle / body / label / note 全部定义
（subtitle、body 当前无使用点，为下一层版面预留）；现有 ElementSpec.role
通过 `ROLE_TO_FONT` 逐个映射进去。渲染层只读 `font_size(role)`，不出现
任何 pt 字面量。
"""
from __future__ import annotations

#: 色板：角色名 → 6 位十六进制（不带 #）。渲染层与模板共用。
PALETTE: dict[str, str] = {
    # --- 彩色（跨图统一的主角暖色 + 分类对比色）---
    "primary": "E8A08C",        # 暖珊瑚：温度计液柱/球泡、半圆第 1 扇区
    "secondary": "C2512F",      # 深暖红：次要强调、半圆第 2 扇区
    "accent_1": "E8B85C",       # 暖金：分类对比 1
    "accent_2": "7A9E7E",       # 灰绿：分类对比 2
    "accent_3": "6C7A89",       # 石板灰：分类对比 3（第 5 扇区）
    # --- 中性五档（各有唯一使用点）---
    "neutral_dark": "222222",   # 文本深色
    "neutral_strong": "7A8088", # 占位图主笔 / 深色空心点
    "neutral_mid": "A8AEB6",    # 占位图中间调
    "neutral_light": "D6DADF",  # 占位图淡色 / 虚框
    "neutral_hairline": "C9C9C9",  # 温度计划度线、外圈描边（发丝线）
    # --- 底 ---
    "surface": "FFFFFF",        # 画布 / 管身底
}

#: 半圆扇区固定取色顺序（第 i 个分项 → 第 i 个角色；> 5 项本轮不适用）。
SECTOR_ROLES: tuple[str, ...] = (
    "primary", "secondary", "accent_1", "accent_2", "accent_3")

#: 语义别名：写业务代码时按用途取色，比记 hex 更不容易错。
ROLE_ALIASES: dict[str, str] = {
    "liquid": "primary",              # 温度计液柱 / 球泡
    "track": "surface",               # 管身白底
    "outline": "neutral_hairline",    # 温度计外圈描边
    "ticks": "neutral_hairline",      # 管内刻度线
    "text": "neutral_dark",
    "placeholder_stroke": "neutral_strong",
    "placeholder_mid": "neutral_mid",
    "placeholder_light": "neutral_light",
    "canvas": "surface",
}


def color(role: str) -> str:
    """取一个角色色（hex 字符串，不带 #）。未知角色直接抛。

    故意不设默认值：拼错角色名时应该立刻炸，而不是静默画成某个颜色。
    """
    if role in ROLE_ALIASES:
        role = ROLE_ALIASES[role]
    try:
        return PALETTE[role]
    except KeyError:
        raise KeyError(
            f"unknown palette role {role!r}; "
            f"known roles: {sorted(PALETTE)} (aliases: {sorted(ROLE_ALIASES)})"
        ) from None


def sector_colors(n: int | None = None) -> list[str]:
    """半圆扇区色序列（按 SECTOR_ROLES 顺序截取 n 个）。"""
    seq = [PALETTE[r] for r in SECTOR_ROLES]
    return seq if n is None else seq[:n]


# ---------------------------------------------------------------------------
# 文本角色字号表（pt）
# ---------------------------------------------------------------------------

#: 设计角色 → 字号（pt）。层级 20 / 14 / 11 / 9 / 8，逐档递减且无并列。
FONT_SIZES: dict[str, int] = {
    "title": 20,        # 版面大标题
    "subtitle": 14,     # 栏目 / 图表标题（暂无使用点，为下层预留）
    "body": 11,         # 正文（真值「118%」等）
    "label": 9,         # 图形标签（类别名、图例）
    "note": 8,          # 注释 / 量程说明 / 来源
}

#: 现有 ElementSpec.role → 设计角色。
#: 没列出的 role 落到 `DEFAULT_FONT_ROLE`，但更希望是显式映射——新增图形时
#: 若忘了登记，`tests/test_step19_palette.py` 会点名报出来。
ROLE_TO_FONT: dict[str, str] = {
    "title": "title",
    "scale_note": "note",
    "legend": "label",
    "label": "label",
    "value": "body",
    "center": "subtitle",
}

DEFAULT_FONT_ROLE = "note"

#: 基准画布（英寸）。字号表是按 10×6 定的；图框让画布变大/变小之后，字号
#: 必须跟着画布走，否则同一份报纸里「大卡片小字、小卡片大字」（用户 m05688）。
BASE_CANVAS_W_IN = 10.0
BASE_CANVAS_H_IN = 6.0

#: 缩放后的字号上下限（pt）：6 是读者可读下限，24 是单张卡片的显示上限。
MIN_FONT_PT = 6.0
MAX_FONT_PT = 24.0

#: 半圆扇区描边（用户 m05688）：14.4° 这类窄扇区必须靠描边才有边界，
#: 相邻扇区不靠颜色也得分得开。色值取自中性色板，不新造颜色。
SECTOR_STROKE_ROLE = "neutral_mid"
SECTOR_STROKE_PT = 0.5

#: 行高系数（预览层折行用）：行高 = 字号 × 该系数。PPTX 端自带行距，不用它。
LINE_HEIGHT_RATIO = 1.35


def font_size(role: str) -> int:
    """按 ElementSpec.role 取字号（pt）。

    两种入参都接受：流水线里的元素角色（``scale_note`` / ``value`` …）走
    ``ROLE_TO_FONT`` 映射；设计角色名（``subtitle`` / ``body`` …）直接命中
    ``FONT_SIZES``。**不能只走映射**——映射表里没有 ``subtitle`` / ``body``
    这两个键，只查映射会静默降级到 ``note``（8 pt），把 14 pt 的副标题
    画成 8 pt 而不报错。
    """
    key = ROLE_TO_FONT.get(role, role if role in FONT_SIZES else DEFAULT_FONT_ROLE)
    return FONT_SIZES[key]


def design_role(role: str) -> str:
    """按 ElementSpec.role 取它所属的设计角色（供调试与测试用）。"""
    return ROLE_TO_FONT.get(role, DEFAULT_FONT_ROLE)


def canvas_scale(width_in: float, height_in: float) -> float:
    """画布相对基准 10×6 的缩放比：``min(w/10, h/6)``。

    取小的那一维：只放大宽、或只放大高时，字号不能跟着放大到溢出另一维。
    """
    w, h = float(width_in or 0.0), float(height_in or 0.0)
    if w <= 0.0 or h <= 0.0:
        return 1.0
    return min(w / BASE_CANVAS_W_IN, h / BASE_CANVAS_H_IN)


def spec_scale(spec) -> float:
    """按规格的**图框尺寸**取缩放比；没有图框时退回画布尺寸。

    用 ``frame_bbox``（用户 m04888 要求同时记录内容尺寸与图框尺寸的那个字段）
    而不是 ``width_in``，是为了让「按框缩放」这件事有唯一出处：以后版式层改
    成按内容缩放时，只改这里一处。
    """
    box = getattr(spec, "frame_bbox", None)
    if box and len(box) >= 4 and box[2] and box[3]:
        return canvas_scale(box[2], box[3])
    return canvas_scale(getattr(spec, "width_in", BASE_CANVAS_W_IN),
                        getattr(spec, "height_in", BASE_CANVAS_H_IN))


def scaled_font_size(role: str, scale: float = 1.0) -> float:
    """role 字号 × 画布缩放，最后截断到 [MIN_FONT_PT, MAX_FONT_PT]。

    结果保留两位小数：``8/10`` 与 ``4.8/6`` 这类比值会有 1e-16 级尾差，
    不修掉的话 ``Pt()`` 按百分之一磅截断，16.0 会落成 15.99。
    """
    value = round(font_size(role) * float(scale), 2)
    return max(MIN_FONT_PT, min(MAX_FONT_PT, value))


def line_height_px(role: str, px_per_pt: float = 100.0 / 72.0,
                   scale: float = 1.0) -> int:
    """预览层行高（像素）：缩放后的 pt → px 后乘行高系数。"""
    return int(round(scaled_font_size(role, scale) * px_per_pt
                     * LINE_HEIGHT_RATIO))


# ---------------------------------------------------------------------------
# 对比度自检
#
# 用户 m04549 的闸口：「相邻扇区可区分；文本与背景对比度足够」。把两条判据
# 写成函数，供测试直接断言，也供后续换色时先跑一遍再改。
# ---------------------------------------------------------------------------

def _srgb_to_lab(hex6: str) -> tuple[float, float, float]:
    r, g, b = (int(hex6[i:i + 2], 16) / 255.0 for i in (0, 2, 4))

    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = lin(r), lin(g), lin(b)
    x = r * 0.4124 + g * 0.3576 + b * 0.1805
    y = r * 0.2126 + g * 0.7152 + b * 0.0722
    z = r * 0.0193 + g * 0.1192 + b * 0.9505
    xn, yn, zn = 0.95047, 1.0, 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = f(x / xn), f(y / yn), f(z / zn)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def delta_e(hex_a: str, hex_b: str) -> float:
    """CIE76 色差（够用来判「肉眼能否区分」，不需要 CIEDE2000 那套精度）。"""
    la, lb = _srgb_to_lab(hex_a), _srgb_to_lab(hex_b)
    return sum((p - q) ** 2 for p, q in zip(la, lb)) ** 0.5


def _relative_luminance(hex6: str) -> float:
    def f(c: int) -> float:
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hex6[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast_ratio(hex_a: str, hex_b: str) -> float:
    """WCAG 对比度。正文 ≥ 4.5、大字号 ≥ 3.0 是通行门槛。"""
    la, lb = _relative_luminance(hex_a), _relative_luminance(hex_b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


#: 相邻扇区的最小可分辨色差（CIE76）。经验上 ΔE > 20 就能一眼分开。
MIN_ADJACENT_DELTA_E = 20.0
#: 文本对背景的最小对比度（WCAG AA 正文门槛）。
MIN_TEXT_CONTRAST = 4.5


def check_separation() -> list[str]:
    """自检色板是否满足两条闸口；返回问题列表（空 = 通过）。"""
    problems: list[str] = []
    seq = sector_colors()
    for i, a in enumerate(seq):
        b = seq[(i + 1) % len(seq)]
        d = delta_e(a, b)
        if d < MIN_ADJACENT_DELTA_E:
            problems.append(
                f"adjacent sector colours {SECTOR_ROLES[i]}={a} and "
                f"{SECTOR_ROLES[(i+1) % len(seq)]}={b} too close: "
                f"ΔE={d:.1f} < {MIN_ADJACENT_DELTA_E}")
    for bg in ("surface", "neutral_light"):
        r = contrast_ratio(PALETTE["neutral_dark"], PALETTE[bg])
        if r < MIN_TEXT_CONTRAST:
            problems.append(
                f"text {PALETTE['neutral_dark']} on {bg} "
                f"{PALETTE[bg]} contrast {r:.2f} < {MIN_TEXT_CONTRAST}")
    return problems


def summary() -> dict:
    """给文档 / 汇报用的结构化摘要。"""
    return {
        "palette": dict(PALETTE),
        "sector_order": list(SECTOR_ROLES),
        "font_sizes": dict(FONT_SIZES),
        "base_canvas_in": [BASE_CANVAS_W_IN, BASE_CANVAS_H_IN],
        "font_pt_clamp": [MIN_FONT_PT, MAX_FONT_PT],
        "sector_stroke": {"color_role": SECTOR_STROKE_ROLE,
                          "pt": SECTOR_STROKE_PT},
        "role_to_font": dict(ROLE_TO_FONT),
        "min_adjacent_delta_e": MIN_ADJACENT_DELTA_E,
        "min_text_contrast": MIN_TEXT_CONTRAST,
        "problems": check_separation(),
    }
