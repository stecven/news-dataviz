"""Charticulator 借鉴 · B/E 节：可复用模板注册表（TemplateSpec）。

模板 = 参数 schema + 适用数据形态 + 确定性硬约束 + 输出规格片段(marks) +
渲染适配器标识（E.1 五件套）。**模板里没有任何绝对坐标**：marks 的
x/y/w/h 全是 "@参数名" 引用，数值只能出现在 params.default 与约束的线性
系数里。真正的坐标由 loop.solve.solve() 用约束求解产出。

只实现两种图形（用户硬要求 ①）：thermometer / semicircle。其余四类
（icon_progress / radial_nodes / point_map / dual_thermometer）按 C.2 小节
"注册表只登记温度计、半圆图两个模板，其余 4 类留条目、不实现" 留占位，
被选中时显式抛 NotImplementedError，绝不静默产出。
"""
from dataclasses import asdict, dataclass, field
import json

from loop.palette import PALETTE, FONT_SIZES


@dataclass
class TemplateSpec:
    name: str
    implemented: bool
    params: dict
    data_shape: str
    not_applicable_when: str
    constraints: list = field(default_factory=list)
    marks: list = field(default_factory=list)
    renderer: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "TemplateSpec":
        return cls(**d)


def _p(default, unit, desc=""):
    return {"default": default, "unit": unit, "desc": desc}


def _c(cid, kind, expr, reuse=False):
    return {"id": cid, "kind": kind, "linear": True,
            "expr": expr, "reuse_from_thermometer": reuse}


def _m(mid, mtype, role, x, y, w, h, fill=None, text=None,
       binding=None, geometry_expr=None):
    return {
        "id": mid, "type": mtype, "role": role,
        "x_in": x, "y_in": y, "w_in": w, "h_in": h,
        "fill": fill, "text": text, "binding": binding,
        "geometry_expr": geometry_expr,
    }


# ----------------------------------------------------------------------------
# 共享布局参数（E.1 ① 参数 schema）。数值都带名字 + 单位，不是绝对坐标。
# 刻意避开 E.3 #3 点名的旧硬编码字面量 0.8 / 1.30 / 4.30 / 5.05 / 5.40 / 1.8。
# ----------------------------------------------------------------------------
_SHARED_PARAMS = {
    "margin": _p(0.5, "in", "画布四周留白"),
    "top_reserve": _p(1.65, "in", "画布顶到图形区起点的高度（= 留白 + 标题 + 说明 + 间距）"),
    "h_title": _p(0.5, "in", "标题盒高"),
    "h_note": _p(0.3, "in", "量程说明盒高"),
    "gap_title": _p(0.15, "in", "标题与说明之间的间距"),
    "gap_note": _p(0.2, "in", "说明与图形区之间的间距"),
    "bottom_margin": _p(0.25, "in", "底部留白"),
    # 字号单一来源在 loop/palette.py（用户 m04549）。这里保留 text_size 是
    # 为了兼容既有 pagespec / param_override：它固定等于 label 档字号，
    # 真正的分层字号在渲染时按 ElementSpec.role 查 palette.font_size()。
    "text_size": _p(FONT_SIZES["label"], "pt", "文本字号（= 色板 label 档）"),
}

_THERMO_PARAMS = {
    **_SHARED_PARAMS,
    # 报纸原版外形：细管 + 底部圆球 + 管上方两行类别名 + 球下方真值。
    # 竖向模型见 C4：0 点 = 圆球最上方顶点，液柱从 0 点向上长。
    # 这组默认值让 H_track 恰好仍为 3.0（k=3/11 不变，只改竖向布局）。
    "w_track": _p(0.28, "in", "管身宽（原版为细管）"),
    # 报纸原版的液柱是**细杆**（实测约管宽 36%），居中悬在管身里、不塞满管身。
    "liquid_w": _p(0.10, "in", "液柱细杆宽（C5：居中于管身）"),
    "H_track": _p(3.0, "in", "管身长（0 点在球顶，向上量的可用长度）"),
    "gap_min": _p(0.5, "in", "C6 最小间距；取到它仍超界即无解"),
    "bulb_d": _p(0.52, "in", "球泡直径（0 点在其最上方顶点）"),
    "h_label": _p(0.34, "in", "标签盒高（原版为两行类别名，在管上方）"),
    "h_value": _p(0.18, "in", "真值盒高（在球下方）"),
    "gap_label": _p(0.03, "in", "标签与管口的间距"),
    "gap_value": _p(0.03, "in", "球底与真值的间距"),
    "w_label": _p(1.2, "in", "标签 / 真值盒宽（C5 居中用）"),
    "color_track": _p(PALETTE["surface"], "hex", "管身填色（白底 + 刻度线）"),
    "color_liquid": _p(PALETTE["primary"], "hex", "液柱 / 球泡填色（色板 primary）"),
    "color_tick": _p(PALETTE["neutral_hairline"], "hex", "管内刻度线颜色（色板中性发丝线）"),
    # 报纸原版皮肤（用户 m02273）：右侧短刻度 + 管球锥形收口 + 外圈轮廓。
    # 三者都由纯形状画出，不是位图；数值只在此处出现，marks 里只引用参数名。
    "tick_count": _p(13, "count", "每根管右侧的短刻度条数"),
    "tick_len": _p(0.10, "in", "刻度线长度（贴管身右缘内侧）"),
    "tick_thick": _p(0.012, "in", "刻度线粗细"),
    "outline_pad": _p(0.03, "in", "管口半圆顶相对管身的半径外扩量"),
    "bulb_ring_pad": _p(0.045, "in", "球泡外环相对球半径的外扩量（双重轮廓的留白）"),
    "neck_h": _p(0.18, "in", "管身与球泡之间锥形收口的高度"),
    "color_outline": _p(PALETTE["neutral_hairline"], "hex", "外圈轮廓 / 刻度线描边色"),
}

_SEMI_PARAMS = {
    **_SHARED_PARAMS,
    "arc_total": _p(180.0, "deg", "半圆扇角总和 Σθ"),
    "max_slices": _p(5, "count", "容量上限：分项 > 5 按 B 节「不适用」在选型阶段 fallback（D.3）"),
    "center_slice_id": _p(1, "seq", "中心数值所对应的扇区（E.3 #4，不写死数值）"),
    "h_legend": _p(0.3, "in", "图例盒高"),
    # 图例列宽下限（用户 m05768）：R 原来是 min(半宽, 可用半高)，宽画布上「半宽」
    # 先成为限制，半圆顶满宽度、图例列被挤成 0.5 in。给图例留一列后，只有在
    # 宽高比偏「高」的格子上才起作用——10×6 仍是高度限制，半径与几何逐位不变。
    "w_legend": _p(0.5, "in", "图例列宽下限（C7 为它留位）"),
    "h_center": _p(0.4, "in", "中心数值盒高"),
    "gap_center": _p(0.1, "in", "平直直径与中心数值盒的间距"),
    "gap_legend": _p(0.1, "in", "中心数值盒与图例行间距"),
    "color_sector_1": _p(PALETTE["primary"], "hex", "扇区 1 填色（色板 primary）"),
    "color_sector_2": _p(PALETTE["secondary"], "hex", "扇区 2 填色（色板 secondary）"),
    "color_sector_3": _p(PALETTE["accent_1"], "hex", "扇区 3 填色（色板 accent_1）"),
    "color_sector_4": _p(PALETTE["accent_2"], "hex", "扇区 4 填色（色板 accent_2）"),
    "color_sector_5": _p(PALETTE["accent_3"], "hex", "扇区 5 填色（色板 accent_3）"),
}

# ----------------------------------------------------------------------------
# 约束声明（C 节原语）。求解器按 kind 分派 handler；expr 只是审计用字符串，
# 不含裸数字坐标。C9（标签避让，非线性 / 非凸）明确排除，不登记。
# ----------------------------------------------------------------------------
_BOUND = _c("C1", "bound", "0 <= x, x + w <= W, 0 <= y, y + h <= H")
_LINK = _c("DATA", "data_link", "h_liquid = scale.factor * binding.value; theta = arc_total * v / sum(v)")
_SHARED_SCALE = _c("C3", "shared_scale", "V_max = ceil(max(v) * 1.1) (preprocessed); sum(theta) = arc_total")
_CENTER = _c("C5", "center", "x_child + w_child / 2 = x_parent + w_parent / 2")

_THERMO_CONSTRAINTS = [
    _BOUND,
    _LINK,
    _SHARED_SCALE,
    _c("C4", "vertical_adjacent",
       "y_liquid + h_liquid = y_track + H_track (0 point); "
       "y_bulb = y_track + H_track (球顶 = 0 点), bulb_d 向下; "
       "y_value = y_bulb + bulb_d + gap_value; "
       "outline: cap_top = y_track, tube_bottom = y_track + H_track, "
       "R = bulb_d / 2 + bulb_ring_pad, cap_r = w_track / 2 + outline_pad, "
       "CX = x_track + w_track / 2, neck_h = 锥形收口高度; "
       "ticks: box = track box, count = tick_count, len = tick_len"),
    _CENTER,
    _c("C6", "equal_spacing", "x_{i+1} - x_i = d = max(gap_min, (W - 2*m - w_track)/(n-1))"),
]

_SEMI_CONSTRAINTS = [
    _BOUND,                       # C1 复用
    _LINK,
    _SHARED_SCALE,
    _c("C4", "vertical_adjacent", "center/legend 堆叠：y_next = y_prev + h_prev + gap", reuse=True),
    dict(_CENTER, reuse_from_thermometer=True),   # C5 复用
    _c("C7", "radius_from_canvas", "R = min((W - 2*m)/2 - gap_legend - w_legend, (H - top_reserve - bottom_margin)/2) (preprocessed constant); legend column keeps w_legend"),
    _c("C8", "arc_recurrence", "alpha_0 = 180 (半圆定义); alpha_i = alpha_{i-1} + theta_i; theta_i = arc_total * v_i / sum(v); sum(theta) = arc_total"),
]

# ----------------------------------------------------------------------------
# 输出规格片段（E.1 ④）。每个 mark 的 x/y/w/h 都是 "@参数名" 引用。
# geometry_expr 是 E.1 ④ / B 节要求的「声明式求解表达式」审计留痕。
# ----------------------------------------------------------------------------
_THERMO_MARKS = [
    _m("title", "text", "title", "@margin", "@y_title", "@w_canvas", "@h_title",
       text="@chart_title"),
    _m("scale_note", "text", "scale_note", "@margin", "@y_note", "@w_canvas", "@h_note",
       text="@scale_note"),
    _m("track", "rect", "track", "@x_track", "@y_track", "@w_track", "@H_track",
       fill="@color_track"),
    _m("outline", "outline", "outline", "@x_outline", "@y_outline",
       "@w_outline", "@h_outline", fill="@color_outline",
       geometry_expr="cx = x_track + w_track / 2; cy = bulb_y + bulb_d / 2; "
                     "R = bulb_d / 2 + bulb_ring_pad; cap_r = w_track / 2 + outline_pad; "
                     "cap_top = y_track; tube_bottom = y_track + H_track; "
                     "flare end = tube_bottom - neck_h"),
    _m("liquid", "rect", "liquid", "@x_liquid", "@y_liquid", "@liquid_w", "@h_liquid",
       fill="@color_liquid", binding="@point",
       geometry_expr="h_in = scale.factor * binding.value; "
                     "w_in = liquid_w; x_in = x_track + (w_track - liquid_w) / 2"),
    _m("bulb", "ellipse", "bulb", "@x_bulb", "@y_bulb", "@bulb_d", "@bulb_d",
       fill="@color_liquid"),
    # 刻度排在液柱/球泡之后：原版的刻度是压在液面上也能看见的浅色短线，
    # 若排在前面会被液柱整片盖住（只剩液面以上那几格可见）。
    _m("ticks", "ticks", "ticks", "@x_track", "@y_track", "@w_track", "@H_track",
       fill="@color_outline",
       geometry_expr="count = tick_count; len = tick_len; thick = tick_thick; "
                     "pad_top = cap_r = w_track / 2 + outline_pad; pad_bottom = neck_h; "
                     "step = (H_track - pad_top - pad_bottom) / count; "
                     "y_i = y_track + pad_top + (count - 1 - i) * step; "
                     "x_right = x_track + w_track"),
    _m("label", "text", "label", "@x_label", "@y_label", "@w_label", "@h_label",
       text="@label"),
    _m("value", "text", "value", "@x_value", "@y_value", "@w_label", "@h_value",
       text="@value_text", binding="@point"),
]

_SEMI_MARKS = [
    _m("title", "text", "title", "@margin", "@y_title", "@w_canvas", "@h_title",
       text="@chart_title"),
    _m("scale_note", "text", "scale_note", "@margin", "@y_note", "@w_canvas", "@h_note",
       text="@scale_note"),
    _m("sector", "arc", "sector", "@cx", "@cy", "@diameter", "@diameter",
       fill="@sector_color", binding="@point",
       geometry_expr="start_angle = alpha_{i-1}; end_angle = alpha_{i-1} + theta_i; theta_i = arc_total * binding.value / sum(v)"),
    _m("center", "text", "center", "@cx", "@cy", "@diameter", "@h_center",
       text="@center_text", binding="@center_point",
       geometry_expr="text = v_center / sum(v) * 100% (实时归一，禁止写死 80%)"),
    _m("legend", "text", "legend", "@x_legend", "@y_legend", "@w_legend", "@h_legend",
       text="@legend_text", binding="@point"),
]

_THERMOMETER = TemplateSpec(
    name="thermometer", implemented=True,
    params=_THERMO_PARAMS, data_shape="比较",
    not_applicable_when="数值含负值且需对比时（本轮数据全正）；分项 > 5 时排版不适用",
    constraints=_THERMO_CONSTRAINTS, marks=_THERMO_MARKS, renderer="pptx_basic",
)

_SEMICIRCLE = TemplateSpec(
    name="semicircle", implemented=True,
    params=_SEMI_PARAMS, data_shape="占比 / 构成",
    not_applicable_when="分项 > 5 不适用（设计文档 B 节）；选型阶段换图并标 fallback_used 属 GoalExplorer 职责，本最小子集未实现，故此处仅声明、不强制（审查修复：避免误导）",
    constraints=_SEMI_CONSTRAINTS, marks=_SEMI_MARKS, renderer="pptx_arc",
)


def _placeholder(name: str, label: str) -> TemplateSpec:
    return TemplateSpec(
        name=name, implemented=False,
        params={}, data_shape="", not_applicable_when="",
        constraints=[], marks=[], renderer="",
    )


# 注册表：2 个已实现 + 4 个占位（C.2 末行）。
TEMPLATES: dict[str, TemplateSpec] = {
    "thermometer": _THERMOMETER,
    "semicircle": _SEMICIRCLE,
    "icon_progress": _placeholder("icon_progress", "带图标进度条"),
    "radial_nodes": _placeholder("radial_nodes", "辐射节点图"),
    "point_map": _placeholder("point_map", "点位连线地图"),
    "dual_thermometer": _placeholder("dual_thermometer", "双色温度计"),
}


def list_templates() -> list[str]:
    return list(TEMPLATES)


def get_template(name: str) -> TemplateSpec:
    if name not in TEMPLATES:
        raise ValueError(f"unknown template: {name}")
    t = TEMPLATES[name]
    if not t.implemented:
        raise NotImplementedError(f"template not implemented in this subset: {name}")
    return t


def export_template(name: str) -> dict:
    """导出模板 JSON（只含参数名与约束标识符，绝不含绝对坐标）。"""
    return get_template(name).to_dict()


def export_template_file(name: str, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(export_template(name), f, ensure_ascii=False, indent=2)
