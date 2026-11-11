"""单卡片适配外部边界（用户 m05768）：把一张卡片塞进给定的格子里。

背景
----
第 20 步之前是「内容决定画布」——内容多大，图框就多大，画布跟着长大。
自由布局要求反过来：**外部给定边界，内部自适应重排**。本轮只做这一层：
``build_pagespec(target_width_in=..., target_height_in=...)`` 时，整张卡片
（图框 + 标题带 + 图形 + 说明）必须严格装进这个边界。

机制：等比缩放设计参数 + 约束重解
--------------------------------
不是搬动已经解出来的坐标，而是**把设计参数整体乘一个比例 s 再重解**：

1. 目标格子减去 chrome（内边距、标题带、说明行）得到可用内容盒；
2. 以可用内容盒为画布跑 ``solve()``，参数取「默认值 × s」；
3. s 从 1.0 向下二分，直到解得出来、且内容外接盒不越界；
4. 文本行高/宽有**下限**——字号被 6 pt 下限兜住之后，行高不能跟着 s
   一路缩到装不下一行。下限让内容不再严格等比，所以第 3 步用二分而不是
   闭式解；
5. 完全装不下（连最小 s 都解不出来）时抛 :class:`BoundaryError`，并给出
   最小可行尺寸——不允许静默撑破格子。

为什么复用 solve() 而不是另写一套缩放器
--------------------------------------
约束求解器本来就吃「画布多大」：温度计的 ``d = max(gap_min,
(W-2m-w_track)/(n-1))`` 会用掉可用宽度，``H_track`` 会被可用高度压住，
半圆的 ``R`` 是画布的函数。参数等比缩小之后这一整套自适应直接成立，
不用另写「压缩算法」，也就不会和 C1–C8 打架。
"""
from __future__ import annotations

from dataclasses import replace

from loop import frame as frame_mod
from loop import palette
from loop.frame import (BAND_GAP_IN, BAND_H_IN, CHROME_ROLES,
                        NOTE_GAP_IN, NOTE_H_IN, PAD_IN)
from loop.models import PageSpec
from loop.preview import PX_PER_IN
from loop.solve import SolveError

#: 缩放下界。再小就没有可读性可言，继续缩只会让 BoundaryError 来得更晚。
S_FLOOR = 0.02
#: 搜索「最大的可用 s」：先粗扫再细修。可行区间不是单侧区间——s 太小文本
#: 装不下（字被 6 pt 兜住）、s 太大行列互相压——所以不能用二分。
COARSE_STEP = 0.05
FINE_STEP = 0.01
#: 求最小可行尺寸时，单轴搜索的上界（in）。
MAX_AXIS_IN = 14.0
#: 行高下限的迭代轮数。折行结果稳定下来通常两轮内就收敛。
_ROW_FLOOR_ROUNDS = 4
#: 标题与说明在卡片模式下已经由 chrome 提供，求解画布不再为它们留位置。
CHROME_OWNED_PARAMS = ("h_title", "gap_title", "h_note", "gap_note")

#: 跟着 s 等比缩的设计参数（长度，单位 in）。字号（pt）、角度、计数、颜色
#: 一律不缩——字号走 m05688 的画布缩放，角度是几何不是尺寸。
LENGTH_PARAMS = (
    "margin", "h_title", "gap_title", "h_note", "gap_note", "bottom_margin",
    "w_track", "H_track", "gap_min", "bulb_d", "h_label", "h_value",
    "gap_label", "gap_value", "w_label", "liquid_w",
    "tick_len", "tick_thick", "outline_pad", "bulb_ring_pad", "neck_h",
    "h_legend", "h_center", "gap_center", "gap_legend", "w_legend")

#: 文本行高 / 行宽必须有下限：字被 6 pt 兜住后，盒子不能缩到装不下一行。
#: key = 参数名，value = 该参数承载的文本 role。
TEXT_ROW_PARAMS = {
    "thermometer": {"h_label": "label", "h_value": "value"},
    "semicircle": {"h_legend": "legend", "h_center": "center"},
}
#: 行宽**不做**参数下限：把 w_label 钉死会让内容宽度不再等比，反而撑破格子
#: （C1 会直接拒绝）。宽度够不够交给 :func:`text_problems` 实测——装不下就
#: 报 BoundaryError，而不是偷偷把图撑大。


class BoundaryError(Exception):
    """目标格子装不下这张卡片，且不允许静默溢出。

    ``min_size`` 是「最小可行尺寸」的估算（in）；连最小设计参数都装不下时
    为 ``None``。
    """

    def __init__(self, target, problems, min_size=None, template=None):
        self.target = (float(target[0]), float(target[1]))
        self.problems = list(problems)
        self.min_size = None if min_size is None else (float(min_size[0]),
                                                      float(min_size[1]))
        bits = [f"卡片 {self.target[0]:g}×{self.target[1]:g} in 装不下这张图"]
        if template:
            bits.append(f"模板 {template}")
        if self.min_size is not None:
            bits.append(f"最小可行尺寸约 "
                        f"{self.min_size[0]:g}×{self.min_size[1]:g} in")
        else:
            bits.append("把设计参数压到最小仍然装不下（元素太多）")
        if problems:
            bits.append("；".join(problems))
        super().__init__("：".join(bits))


# ---------------------------------------------------------------------------
# 盒子代数
# ---------------------------------------------------------------------------
def chrome_height_in() -> float:
    """一张卡片的 chrome 总高：上下内边距 + 标题带 + 说明行及其间隙。"""
    return (2 * PAD_IN + BAND_H_IN + BAND_GAP_IN
            + NOTE_H_IN + NOTE_GAP_IN)


def content_top_in() -> float:
    """内容盒顶边在卡片里的 y（标题带与说明之下）。"""
    return PAD_IN + BAND_H_IN + BAND_GAP_IN + NOTE_H_IN + NOTE_GAP_IN


def available_box(target_w: float, target_h: float) -> tuple[float, float]:
    """目标格子能留给内容（数据图形）的宽高。"""
    return (float(target_w) - 2 * PAD_IN,
            float(target_h) - chrome_height_in())


# ---------------------------------------------------------------------------
# 参数缩放 + 文本下限
# ---------------------------------------------------------------------------
def scaled_overrides(template, s: float, *, base_overrides=None,
                     floors=None) -> dict:
    """把模板里的长度参数整体乘 ``s``，再抬到文本下限。

    ``base_overrides`` 是调用方原本要传的参数（优先于模板默认值），
    其余键原样透传。
    """
    base_overrides = dict(base_overrides or {})
    out = {}
    for key in LENGTH_PARAMS:
        if key not in template.params:
            continue
        base = float(base_overrides.get(key, template.params[key]["default"]))
        out[key] = round(base * s, 6)
    for key in CHROME_OWNED_PARAMS:
        if key in out:
            out[key] = 0.0
    for key, value in (floors or {}).items():
        if key in out:
            out[key] = max(out[key], round(float(value), 6))
    for key, value in base_overrides.items():
        if key not in out:
            out[key] = value
    return out


def one_line_height_in(role: str, font_scale: float) -> float:
    """某 role 在该字号下装下一行所需的高度（in）。"""
    pt = palette.scaled_font_size(role, font_scale)
    return pt / 72.0 * 1.4


def text_floors(template, font_scale: float) -> dict:
    """文本行的**行高**下限（in）。

    字被 6 pt 下限兜住之后，行高不能跟着 s 一路缩到装不下一行：那一行就得
    溢出去压到邻居。宽度不设下限（见上）。
    """
    floors: dict[str, float] = {}
    for key, role in TEXT_ROW_PARAMS.get(template.name, {}).items():
        if key in template.params:
            floors[key] = round(one_line_height_in(role, font_scale), 6)
    return floors


def _load_font(role: str, font_scale: float):
    from PIL import ImageFont
    from loop.preview import _FONT_PATH
    px = max(1, int(round(palette.scaled_font_size(role, font_scale)
                           * PX_PER_IN / 72.0)))
    try:
        return ImageFont.truetype(_FONT_PATH, px)
    except (OSError, FileNotFoundError):
        return ImageFont.load_default()


# ---------------------------------------------------------------------------
# 文本体检
# ---------------------------------------------------------------------------
def _wrap_lines(text: str, font, max_w_px: float) -> list[str]:
    """与 ``preview._draw_text`` 同口径的逐字折行。"""
    lines: list[str] = []
    cur = ""
    for ch in text:
        trial = cur + ch
        if cur and font.getlength(trial) > max_w_px:
            lines.append(cur)
            cur = ch
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def _overlap(a, b) -> bool:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return (min(ax1, bx1) - max(ax0, bx0) > 1e-6
            and min(ay1, by1) - max(ay0, by0) > 1e-6)


def text_problems(spec: PageSpec, font_scale: float,
                  skip: tuple = ()) -> list[str]:
    """文本体检：能不能装进自己的盒子、互相压不压。

    与预览层同一套折行与行高口径（``preview._draw_text``）。PPTX 端
    ``word_wrap=True`` 且不自动缩排——溢出就是溢出，所以必须提前拦住。
    """
    problems: list[str] = []
    px = PX_PER_IN
    texts = [e for e in spec.elements
             if e.type == "text" and e.role not in skip]
    boxes = []
    for e in texts:
        font = _load_font(e.role, font_scale)
        max_w = max(1.0, e.w_in * px)
        lines = _wrap_lines(e.text or "", font, max_w)
        line_h = palette.line_height_px(e.role, scale=font_scale)
        need_h = line_h * max(1, len(lines))
        if need_h > e.h_in * px + 0.5:
            problems.append(
                f"{e.id}: 「{e.text}」需要 {need_h:.1f}px 高，盒子只有 "
                f"{e.h_in * px:.1f}px")
        widest = max((font.getlength(ln) for ln in lines), default=0.0)
        if widest > max_w + 0.5:
            problems.append(
                f"{e.id}: 「{e.text}」最宽 {widest:.1f}px，盒子只有 "
                f"{max_w:.1f}px")
        boxes.append((e.id, (e.x_in, e.y_in, e.x_in + e.w_in,
                             e.y_in + e.h_in)))
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            if _overlap(boxes[i][1], boxes[j][1]):
                problems.append(f"{boxes[i][0]} 与 {boxes[j][0]} 文本框重叠")
    return problems


def _required_height_in(text: str, width_in: float, role: str,
                        font_scale: float) -> float:
    """这段文字在这个宽度下至少要多高（in）。"""
    font = _load_font(role, font_scale)
    px = PX_PER_IN
    lines = _wrap_lines(text or "", font, max(1.0, width_in * px))
    return palette.line_height_px(role, scale=font_scale) * max(1, len(lines)) / px


#: 按宽度抬下限的表：role -> 那个决定盒子宽度的参数。表格类的宽度不是
#: 独立参数（是画布减去半径剩出来的），所以要动的是「给图例留多宽」。
WIDTH_PARAMS = {
    "semicircle": {"legend": "w_legend"},
}


def _widest_line_in(text: str, role: str, font_scale: float) -> float:
    """这段文字最宽的一行有多宽（in）；不折行，量的是整行。"""
    font = _load_font(role, font_scale)
    widest = max((font.getlength(ln) for ln in (text or "").split("\n")),
                 default=0.0)
    return widest / PX_PER_IN


#: ``text_floors`` 的返回值是「参数名 -> 最小 in」。这个反向表把
#: ``TEXT_ROW_PARAMS`` 的 role 映射翻过来，好按 role 抬下限。
def _row_params_for(template) -> dict:
    return {role: param
            for param, role in TEXT_ROW_PARAMS.get(template.name, {}).items()}


def required_row_floors(spec: PageSpec, template, font_scale: float,
                        floors: dict | None = None) -> dict:
    """按**实测文本**把行高下限抬到位。

    一行高的下限只在文字真的只占一行时够用：半圆的图例是「标签 数值」，
    格子一窄就折成两行，而 ``h_legend`` 的下限还停在一行，于是盒子比字矮。
    这里拿解出来的盒子宽度量一次真实折行，把下限抬到实需高度；下一轮搜索
    会用更高的盒子重解。
    """
    out = dict(floors or {})
    invert = _row_params_for(template)
    for e in spec.elements:
        if e.type != "text" or e.role in CHROME_ROLES:
            continue
        param = invert.get(e.role)
        if param is None:
            continue
        need = _required_height_in(e.text or "", e.w_in, e.role, font_scale)
        if need > out.get(param, 0.0) + 1e-9:
            out[param] = round(need, 6)

    # 宽度：盒子窄到一行都放不下时，把「留多宽」的参数抬上去。半圆的图例列
    # 宽度由 C7 从画布里留出来，抬这个参数就等于抬盒子本身。
    for e in spec.elements:
        if e.type != "text" or e.role in CHROME_ROLES:
            continue
        wparam = WIDTH_PARAMS.get(template.name, {}).get(e.role)
        if wparam is None:
            continue
        widest = _widest_line_in(e.text or "", e.role, font_scale)
        if widest > e.w_in + 1e-6:
            grown = out.get(wparam, 0.0) + (widest - e.w_in) + 0.02
            out[wparam] = round(min(grown, MAX_AXIS_IN), 6)
    return out


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def fit_to_target(solve_at, *, template, target_width_in, target_height_in,
                  natural: PageSpec | None = None,
                  note_text: str | None = None,
                  subtitle_text: str | None = None,
                  probe: bool = False) -> PageSpec:
    """把一张卡片装进 ``target_width_in × target_height_in`` 的格子。

    ``solve_at(param_overrides, width_in, height_in) -> PageSpec`` 由调用方
    提供（它是唯一知道怎么建骨架、怎么求解的人），本函数只负责「缩到多大、
    装不装得下、装不下怎么报错」。

    ``probe=True`` 时不在失败路径上估算最小可行尺寸——那一步要反复试不同的
    格子，否则会和 :func:`minimum_target` 互相调用成环。
    """
    tw, th = float(target_width_in), float(target_height_in)
    if tw <= 0 or th <= 0:
        raise BoundaryError((tw, th), ["目标尺寸必须为正"],
                            template=template.name)
    avail_w, avail_h = available_box(tw, th)
    font_scale = palette.canvas_scale(tw, th)
    floors = text_floors(template, font_scale)

    def solve_only(s: float, floors: dict = None) -> PageSpec | None:
        """只问求解器：几何装得下吗（不看文字）。"""
        overrides = scaled_overrides(template, s, floors=floors or _floors)
        try:
            return solve_at(overrides, avail_w, avail_h)
        except SolveError:
            return None

    def attempt(s: float, floors: dict = None) -> PageSpec | None:
        """按 s 缩放参数重解，并顺手体检一次文本。

        解不出来（C1 越界 / H_track ≤ 0）就是装不下；解出来但标签互相压，
        也算装不下——求解器只保证元素在画布内，不保证相邻标签不重叠
        （``d`` 的公式里没有 ``w_label``）。文本体检要跳过会被 chrome 替换掉
        的 role，否则量的是那个马上要被丢掉的小盒子。
        """
        spec = solve_only(s, floors)
        if spec is None:
            return None
        if text_problems(spec, font_scale, skip=CHROME_ROLES):
            return None
        return spec

    if avail_w <= 0.2 or avail_h <= 0.2:
        raise BoundaryError(
            (tw, th), ["chrome 就占满了格子"],
            None if probe else _min_size(solve_at, template, tw, th),
            template=template.name)

    # 行高下限要迭代到位：先按「一行高」，解出来再拿实测折行把下限抬高，
    # 直到文字真的装得下。半圆的图例在窄格里会折成两行，一轮不够。
    _floors = floors
    best, s = None, None
    for _ in range(_ROW_FLOOR_ROUNDS):
        # 两路并进：一路要求文字也过关，一路只要求几何过关。文字这一路失败时
        # 仍要拿几何这一路的解去量「文字到底需要多大」，否则下限永远抬不上去
        # ——那就成了「因为字太大所以不量字」的死循环。
        clean, clean_s = _largest_feasible(attempt)
        geo, _geo_s = _largest_feasible(solve_only)
        if clean is not None:
            best, s = clean, clean_s
        ref = clean if clean is not None else geo
        if ref is None:
            break
        raised = required_row_floors(ref, template, font_scale, _floors)
        if raised == _floors:
            break
        _floors = raised
    if best is None:
        raise BoundaryError(
            (tw, th), ["任何缩放比例都装不下（元素太多或格子太小）"],
            None if probe else _min_size(solve_at, template, tw, th),
            template=template.name)

    # 先包框再体检：标题与说明在包框时被换成固定高度的 chrome，拿未包框的
    # 小盒子去量它们只会得到假警报。
    fitted = frame_mod.wrap(best, note_text=note_text,
                            subtitle_text=subtitle_text, canvas_in=(tw, th))
    problems = text_problems(fitted, font_scale)
    if problems:
        raise BoundaryError(
            (tw, th), problems,
            None if probe else _min_size(solve_at, template, tw, th),
            template=template.name)

    layout = dict(fitted.layout or {})
    meta = dict(layout.get("frame") or {})
    meta["fit"] = {"scale": round(s, 6), "target": [tw, th],
                   "font_scale": round(font_scale, 6)}
    layout["frame"] = meta
    return replace(fitted, layout=layout)


def _largest_feasible(attempt):
    """最大的可用 s（先粗扫、再向上细修）。

    可行区间不是单侧区间：s 太小标签装不下一行字，s 太大行列互相压。所以
    不能用二分找边界，只能扫——先按 ``COARSE_STEP`` 从 1.0 往下找第一个
    能用的，再在它上面一格范围内用 ``FINE_STEP`` 往上修。
    """
    steps = int(round((1.0 - S_FLOOR) / COARSE_STEP))
    for i in range(steps + 1):
        s = round(1.0 - i * COARSE_STEP, 6)
        if s < S_FLOOR:
            break
        spec = attempt(s)
        if spec is None:
            continue
        best, best_s = spec, s
        ceiling = min(1.0, round(s + COARSE_STEP, 6))
        t = round(s + FINE_STEP, 6)
        while t < ceiling - 1e-9:
            cand = attempt(t)
            if cand is not None:
                best, best_s = cand, t
            t = round(t + FINE_STEP, 6)
        return best, best_s
    return None, None


def minimum_target(solve_at, *, template, target_width_in, target_height_in,
                   natural: PageSpec | None = None,
                   note_text: str | None = None,
                   subtitle_text: str | None = None
                   ) -> tuple[float, float] | None:
    """最小可行尺寸的**每轴下限**：``(min_w, min_h) in``。

    两轴一起放大得到的「最小面积」会误导人（一个 2×2 的格子报出 6.7×6.7），
    所以分开量：求最小宽度时把高度放到 ``MAX_AXIS_IN``，反之亦然。两个数各自
    都是真实下限，合起来不保证同时可达，但足以回答「这类图最少要多宽/多高」。
    """
    big_w = max(float(target_width_in), 12.0)
    big_h = max(float(target_height_in), 8.0)

    def ok(w: float, h: float) -> bool:
        try:
            fit_to_target(solve_at, template=template, target_width_in=w,
                          target_height_in=h, natural=natural,
                          note_text=note_text, subtitle_text=subtitle_text,
                          probe=True)
            return True
        except BoundaryError:
            return False

    def axis(pred) -> float | None:
        import math
        lo, hi = 0.3, MAX_AXIS_IN
        if not pred(hi):
            return None
        if pred(lo):
            return lo
        for _ in range(11):
            mid = (lo + hi) / 2.0
            if pred(mid):
                hi = mid
            else:
                lo = mid
        return hi

    min_w = axis(lambda w: ok(w, big_h))
    min_h = axis(lambda h: ok(big_w, h))
    if min_w is None or min_h is None:
        return None
    return (round(min_w, 2), round(min_h, 2))


def _min_size(solve_at, template, tw, th):
    """BoundaryError 里那行「最小可行尺寸」——失败路径上的尽力而为。"""
    try:
        return minimum_target(solve_at, template=template,
                              target_width_in=tw, target_height_in=th)
    except Exception:                                    # pragma: no cover
        return None
