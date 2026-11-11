"""Charticulator 借鉴 · D 节：约束求解器（预处理 + 线性求解 + 几何产出）。

设计文档 D.2 步骤 3 的落点。分两阶段，严格按 C.2 小结 / C7 硬规则：

  * 预处理 preprocess()：把 V_max、Σv、n、d、R、H_track、factor 全部算成
    **常量**（ceil / min / max / Σ 都在这一层算完），绝不把 Σv、min/max
    分支写进约束矩阵；
  * 线性求解 solve_linear()：只解 a·x = b（高斯消元 + 部分主元），
    奇异 / 非方阵抛 SolveError；
  * build_skeleton()：产出**不含绝对坐标**的规格骨架（x/y/w/h 全 0）；
  * solve()：用预处理常量 + 约束把每个 ElementSpec 的 x/y/w/h 回填。

所有 min/max/ceil 都在预处理算成常量，求解器不处理分支（C7 硬规则）。
"""
import copy
import math

from loop.models import Scale, ElementSpec, PageSpec
from loop.palette import PALETTE
from loop.templates import TemplateSpec, get_template


class SolveError(Exception):
    """约束矛盾 / 无解 / 输入非法。conflicts 列出 D.3 要求的冲突约束编号。"""

    def __init__(self, message: str, conflicts: list[str] | None = None):
        super().__init__(message)
        # 复审 I6：冲突 id 可能是 None / 非字符串（畸形约束行），__str__ 不能崩。
        self.conflicts = [c if isinstance(c, str) else repr(c)
                          for c in (conflicts or [])]

    def __str__(self) -> str:
        base = super().__str__()
        return f"{base} (conflicts: {', '.join(self.conflicts)})" if self.conflicts else base


def _defaults(t: TemplateSpec) -> dict:
    return {name: p["default"] for name, p in t.params.items()}


def preprocess(points: list[dict], template: TemplateSpec,
               width_in: float, height_in: float,
               param_overrides: dict | None = None) -> dict:
    """D.2 步骤 3 前半：数据聚合预处理，返回喂给约束矩阵的常量字典。

    所有 ceil / min / max / Σ 都在这里算完；求解器后续只看线性等式。
    任何不可行输入抛 SolveError（附冲突编号），不静默降级、不削顶。
    """
    if not points:
        raise SolveError("empty data set", ["C2"])

    p = _defaults(template)
    # 两类模板共用同一个 preprocess()（E.2「同一套求解逻辑供两类图形复用」）。
    # 温度计专有参数给中性默认，让半圆模板也能跑同一段预处理代码；
    # 半圆求解器不会用到 w_track / d / H_track 这些温度计常量。
    p.setdefault("w_track", 0.0)
    p.setdefault("liquid_w", 0.0)
    p.setdefault("gap_min", 0.0)
    p.setdefault("bulb_d", 0.0)
    p.setdefault("gap_label", 0.0)
    p.setdefault("h_label", 0.0)
    p.setdefault("gap_value", 0.0)
    p.setdefault("h_value", 0.0)
    p.setdefault("H_track", 0.0)
    p.setdefault("arc_total", 180.0)
    p.setdefault("tick_count", 0)
    p.setdefault("tick_len", 0.0)
    p.setdefault("tick_thick", 0.0)
    p.setdefault("outline_pad", 0.0)
    p.setdefault("bulb_ring_pad", 0.0)
    p.setdefault("neck_h", 0.0)
    if param_overrides:
        # 审查修复 3：top_reserve 是由竖直分量派生的量。单独覆盖它会与求解器的
        # y_track 错开（默认恰好相等才没暴露），造成伪 C1。要求改分量而不是
        # 静默忽略 / 制造无解。
        if "top_reserve" in param_overrides:
            raise SolveError(
                "top_reserve is derived from "
                "m+h_title+gap_title+h_note+gap_note; override a component instead",
                ["C4"])
        p.update(param_overrides)

    values = []
    for row in points:
        v = float(row["value"])
        if not math.isfinite(v):
            raise SolveError(f"non-finite value in data: {v!r}", ["C2"])
        values.append(v)

    n = len(values)
    W, H = float(width_in), float(height_in)
    m = float(p["margin"])
    w_track = float(p["w_track"])
    gap_min = float(p["gap_min"])
    arc_total = float(p["arc_total"])
    is_semicircle = template.name == "semicircle"

    # --- C2 / C3：V_max = ceil(max(v) × 1.1)，至少 1.0（预处理常量） ---
    top = max(values + [0.0])
    v_max = max(1.0, float(math.ceil(top * 11 / 10)))

    # --- C2 两阶段：Σv 在预处理算成常量，不进约束矩阵 ---
    sum_v = float(math.fsum(values))
    if is_semicircle and sum_v <= 0.0:
        raise SolveError(f"sum(v) = {sum_v:g} <= 0, cannot normalize angles", ["C2"])
    if is_semicircle and any(v < 0.0 for v in values):
        # 审查修复 4：单个负占比会产出负扇角（几何非法 PIE 楔形）。D.3 的
        # 物理下界 0 只适用于液体；占比图直接拒绝负分项，不静默截断。
        bad = [v for v in values if v < 0.0]
        raise SolveError(f"negative semicircle share(s): {bad}", ["C2"])
    # D.3「分项 > 5 → 按 B 节『不适用』在选型阶段显式换图并标 fallback_used」：
    # 选型逻辑不在本子集内，但模板元数据 max_slices 必须真实生效——否则 6 项
    # 会静默画出 6 个扇区，把「不适用」变成「悄悄降级」。这里硬拒绝。
    if is_semicircle:
        max_slices = int(p["max_slices"])
        if n > max_slices:
            raise SolveError(
                f"n={n} exceeds max_slices={max_slices}: 分项 > {max_slices} "
                f"属选型阶段 fallback（D.3），不静默画 {n} 个扇区",
                ["MAX_SLICES"])

    # --- C6：d = max(gap_min, (W − 2m − w_track)/(n−1))（预处理常量） ---
    # C6 是温度计 plot segment 的约束；半圆模板不声明 C6，跳过可行性检查。
    if n <= 1:
        d = 0.0
    else:
        d_free = (W - 2 * m - w_track) / (n - 1)
        d = max(gap_min, d_free)
    total_width = (n - 1) * d + w_track
    if not is_semicircle and total_width > W - 2 * m + 1e-9:
        raise SolveError(
            f"n={n} needs total width {total_width:.4f} in > W-2m={W - 2*m:.4f} in "
            f"(d={d:.4f}, gap_min={gap_min})",
            ["C1", "C6"],
        )

    # --- 竖直预留：top_reserve 由竖直分量派生（审查修复 3） ---
    # 必须先在算 R 之前求出来：半圆的扇区盒不能占用标题 / 量程说明的位置。
    top_reserve = (m + float(p["h_title"]) + float(p["gap_title"])
                   + float(p["h_note"]) + float(p["gap_note"]))
    p["top_reserve"] = top_reserve

    # --- C7：R = min((W−2m)/2, (H−top_reserve−bottom_margin)/2) ---
    # 审查修复：R 只按画布算会让扇区盒顶到 y=m，把已派生的标题/说明盖住。
    # 现在上下都扣除预留带，min 仍在预处理阶段算成常量（C7 硬规则）。
    bottom_margin = float(p["bottom_margin"])
    avail_h = H - top_reserve - bottom_margin
    if is_semicircle:
        # 宽画布上「半宽」会先于「半高」成为限制：半圆顶满宽度，图例列被挤没。
        # 先给图例留一列（宽 + 间隙），再取两轴的较小者。
        R_w = (W - 2 * m) / 2 - float(p["gap_legend"]) - float(p["w_legend"])
        R = min(R_w, avail_h / 2)
        if R <= 0.05:
            raise SolveError(
                f"W={W:g} leaves no room for the semicircle and its legend "
                f"column (R={R:.4f})", ["C1", "C7"])
    else:
        R = min((W - 2 * m) / 2, avail_h / 2)

    # --- H_track：随画布高度收缩；min 同样在预处理算成常量 ---
    # 温度计竖向堆叠（报纸原版外形，0 点 = 球的最上方顶点）：
    #   top_reserve → 标签行 → 管身(0..H_track) → 球泡 → 真值 → bottom_margin
    # 所以管子以下只剩 球泡 + 真值 两段；标签在管上方。
    if is_semicircle:
        below_stack = 0.0
    else:
        below_stack = (float(p["h_label"]) + float(p["gap_label"])
                       + float(p["bulb_d"]) + float(p["gap_value"])
                       + float(p["h_value"]) + bottom_margin)
    # round 掉浮点尾差：H=6.0 时精确得 3.0（保住旧闭环的 TRACK_H_IN 断言）。
    H_track = round(min(float(p["H_track"]), H - top_reserve - below_stack), 6)
    if not is_semicircle and H_track <= 0.0:
        raise SolveError(
            f"H_track={H_track:.4f} <= 0 on canvas H={H:g}", ["C1", "C4"])

    # --- factor：唯一的数值→尺寸线性比例尺（C2 / C3） ---
    if is_semicircle:
        factor = arc_total / sum_v
    else:
        factor = H_track / v_max

    return {
        "template": template.name,
        "W": W, "H": H, "m": m, "n": n,
        "v_max": v_max, "sum_v": sum_v, "d": d, "R": R,
        "H_track": H_track, "factor": factor,
        "arc_total": arc_total,
        "p": p,
        "top_reserve": top_reserve,
        "below_stack": below_stack,
    }


# ---------------------------------------------------------------------------
# D.1 方案 ①：自写线性求解器（高斯-约当消元 + 部分主元），零新依赖。
# ---------------------------------------------------------------------------
def solve_linear(A: list[list[float]], b: list[float]) -> list[float]:
    """解 n×n 线性系统 A·x = b；奇异 / 非方阵抛 SolveError。"""
    n = len(b)
    if len(A) != n or any(len(row) != n for row in A):
        raise SolveError(f"non-square linear system: {len(A)}x{len(A[0]) if A else 0} vs b[{n}]")
    M = [list(map(float, row)) + [float(b[i])] for i, row in enumerate(A)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[pivot][col]) < 1e-12:
            raise SolveError(f"singular linear system (pivot at col {col})", ["C6"])
        M[col], M[pivot] = M[pivot], M[col]
        pv = M[col][col]
        for j in range(col, n + 1):
            M[col][j] /= pv
        for r in range(n):
            if r == col:
                continue
            f = M[r][col]
            if f:
                for j in range(col, n + 1):
                    M[r][j] -= f * M[col][j]
    return [M[i][n] for i in range(n)]


# ---------------------------------------------------------------------------
# D.2 步骤 2：坐标无关骨架（TemplateSpec → 未求解的 PageSpec）
# ---------------------------------------------------------------------------
def _resolve(ref, ctx):
    """把 "@参数名" 引用解析成实际值；几何字段在骨架里一律留 0，不解析。"""
    if isinstance(ref, str) and ref.startswith("@"):
        val = ctx.get(ref[1:])
        return dict(val) if isinstance(val, dict) else val
    return ref


def _value_suffix(unit: str) -> str:
    """数据单位 → 真值后缀。`倍(超)` 显示「倍」，`%`/`％` 显示「%」，其余原样。

    原先写死「倍」，非倍数数据（报纸原版区块③就是 118%）会渲染成「118倍」。
    """
    u = (unit or "").strip()
    if u.startswith("倍"):
        return "倍"
    if u in ("%", "％"):
        return "%"
    return u


def _reader_unit(unit: str) -> str:
    """数据单位 → 读者看得懂的单位。`倍(超)` 这种内部标记只留「倍」。"""
    u = (unit or "").strip()
    if u.startswith("倍"):
        return "倍"
    return u


def _make_element(m: dict, ctx: dict, seq) -> ElementSpec:
    eid = m["id"] if seq is None else f"{m['id']}_{seq}"
    return ElementSpec(
        id=eid, type=m["type"], role=m["role"],
        x_in=0.0, y_in=0.0, w_in=0.0, h_in=0.0,   # 骨架：无绝对坐标
        fill=_resolve(m["fill"], ctx),
        text=_resolve(m["text"], ctx),
        binding=_resolve(m["binding"], ctx),
        geometry_expr=m["geometry_expr"],
    )


# 全局图元（每份模板只产出一份，不带 seq 后缀）。半圆的「中心数值」是
# 整图唯一一份，故与 title / scale_note 同属全局 mark；其余按数据点展开。
_GLOBAL_ROLES = {"title", "scale_note", "center"}


def build_skeleton(template: TemplateSpec, points: list[dict],
                   chart_key: str, chart_title: str,
                   width_in: float = 10.0, height_in: float = 6.0,
                   param_overrides: dict | None = None,
                   semantic_tags: list | None = None) -> PageSpec:
    """产出带 constraints/layout/geometry_expr、但 x/y/w/h 全为 0 的骨架。"""
    pre = preprocess(points, template, width_in, height_in, param_overrides)
    p = pre["p"]
    unit = points[0]["unit"] if points else ""
    v_max, H_track = pre["v_max"], pre["H_track"]
    is_semi = template.name == "semicircle"
    # 面向读者的说明文案（用户 m04818）：原来这两句是写给实现者看的
    # （「量程上限 V_max=11倍｜液柱高度 = 3.0 × 数值 / V_max」），读者看不懂
    # 「V_max」「3.0 × 数值 / V_max」。现在改成讲「长度代表什么」的人话，
    # 具体比例尺仍然如实换算出来（每格 ≈ v_max / tick_count），不写死。
    if is_semi:
        scale_note = ("扇面越大，占比越高；圆心那个百分比，"
                      "就是它所在扇区自己的占比。")
    else:
        scale_note = (f"液柱越长，涨幅越高；满格约 {v_max:g}{_reader_unit(unit)}，"
                      "球泡处为零点。")
    # 审查修复（Minor）：半圆图复用了共享 Scale，但语义不同——
    #   thermometer: factor 单位 in/value，h_in = 管身英寸长，domain = [0, V_max]；
    #   semicircle : factor 单位 deg/value，h_in = 扇角总和(度)，domain = [0, Σθ]。
    # h_in 不再为 0.0；v_max 仅为 schema 兼容保留（半圆不消费，见 C3 半圆分支）。
    if is_semi:
        scale = Scale(v_max=v_max, h_in=pre["arc_total"], unit="deg",
                      factor=pre["factor"], domain=[0.0, pre["arc_total"]])
    else:
        scale = Scale(v_max=v_max, h_in=H_track, unit=unit,
                      factor=pre["factor"], domain=[0.0, v_max])

    base = {name: spec["default"] for name, spec in template.params.items()}
    base["chart_title"] = chart_title
    base["scale_note"] = scale_note
    # 兜底色：仅在模板参数被删时才会用到。色板是单一来源（loop/palette.py），
    # 这里取 PALETTE 而不是写字面量，避免换色后兜底色悄悄不同步。
    palette = [p.get(f"color_sector_{i}", PALETTE["primary"]) for i in range(1, 6)]

    # E.3 #4：中心数值按 center_slice_id 取对应分项，实时归一（不写死 80%）。
    if is_semi:
        cid = int(p["center_slice_id"])
        cpt = next((pt for pt in points if pt["seq"] == cid), points[0])
        pct = 100.0 * cpt["value"] / pre["sum_v"]
        base["center_text"] = f"{pct:.1f}%"
        base["center_point"] = {
            "chart_key": chart_key, "seq": cpt["seq"],
            "value": cpt["value"], "unit": cpt["unit"],
            "center_slice_id": cid,
        }

    elements: list[ElementSpec] = []
    # 全局图元：标题、量程说明、（半圆）中心数值。
    for m in template.marks:
        if m["role"] in _GLOBAL_ROLES:
            elements.append(_make_element(m, base, None))
    # 逐数据点图元：x/y/w/h 留空，由 solve() 回填。
    for point in points:
        seq = point["seq"]
        ctx = dict(base)
        ctx["label"] = point["label"]
        # 真值后缀取自数据单位：`倍(超)` → 「10倍」，`%` → 「118%」。
        # 原实现写死「倍」，非倍数数据（如百分比）会渲染成「118倍」。
        ctx["value_text"] = f"{point['value']:g}{_value_suffix(point['unit'])}"
        ctx["point"] = {"chart_key": chart_key, "seq": seq,
                        "value": point["value"], "unit": point["unit"]}
        ctx["sector_color"] = palette[(seq - 1) % len(palette)]
        ctx["legend_text"] = f"{point['label']} {point['value']:g}"
        for m in template.marks:
            if m["role"] in _GLOBAL_ROLES:
                continue
            elements.append(_make_element(m, ctx, seq))

    layout = {
        "template": template.name,
        "orient": "horizontal" if template.name == "thermometer" else "radial",
        "margin": float(p["margin"]),
        "gap_min": float(p["gap_min"]),
        # 审查修复：R 的推导依赖这两个派生量；写进 layout 让读回校验能
        # 独立复算 R（而不是拿 geometry 里的 R 自证）。
        "top_reserve": pre["top_reserve"],
        "bottom_margin": float(p["bottom_margin"]),
        "param_overrides": dict(param_overrides or {}),
    }
    return PageSpec(
        width_in=width_in, height_in=height_in,
        chart_key=chart_key, chart_title=chart_title,
        scale=scale, elements=elements,
        semantic_tags=list(semantic_tags or []),
        constraints=copy.deepcopy(template.constraints),
        layout=layout,
    )


# ---------------------------------------------------------------------------
# D.2 步骤 3 后半：solve() —— 用预处理常量把骨架解成具体坐标
# ---------------------------------------------------------------------------
def _place_header(sk: PageSpec, pre: dict) -> tuple[float, float]:
    """把整图唯一的「标题 / 量程说明」两条全局 mark 摆到页眉带。

    两类模板共用这一份（重构前温度计与半圆各自抄了一遍同样的 8 行回填，
    属复制粘贴）。返回 (y_title, y_note) 供调用方继续往下堆叠。
    """
    p = pre["p"]
    W, m = pre["W"], pre["m"]
    h_title, h_note = float(p["h_title"]), float(p["h_note"])
    gap_title = float(p["gap_title"])
    y_title = m
    y_note = y_title + h_title + gap_title
    by = {e.id: e for e in sk.elements}
    by["title"].x_in = m
    by["title"].y_in = y_title
    by["title"].w_in = W - 2 * m
    by["title"].h_in = h_title
    by["scale_note"].x_in = m
    by["scale_note"].y_in = y_note
    by["scale_note"].w_in = W - 2 * m
    by["scale_note"].h_in = h_note
    return y_title, y_note


def _check_canvas_bounds(sk: PageSpec, W: float, H: float) -> None:
    """C1 可行性检查（不等式）：任一元素越界即无解，不静默压缩。

    求解器末尾统一调用这一份（重构前两个求解器各有一份逐字相同的循环）。
    """
    for e in sk.elements:
        if (e.x_in < -1e-9 or e.y_in < -1e-9
                or e.x_in + e.w_in > W + 1e-9
                or e.y_in + e.h_in > H + 1e-9):
            raise SolveError(f"{e.id} out of canvas {W:g}×{H:g}", ["C1"])


def _solve_thermometer(sk: PageSpec, points: list[dict], pre: dict,
                       template: TemplateSpec) -> PageSpec:
    p = pre["p"]
    W, H, m, n, d = pre["W"], pre["H"], pre["m"], pre["n"], pre["d"]
    H_track, factor = pre["H_track"], pre["factor"]
    w_track = float(p["w_track"])
    liquid_w = float(p["liquid_w"])   # 液柱是细杆（原版约管宽 36%），C5 居中
    bulb_d = float(p["bulb_d"])
    h_title, h_note = float(p["h_title"]), float(p["h_note"])
    gap_title, gap_note = float(p["gap_title"]), float(p["gap_note"])
    h_label, h_value = float(p["h_label"]), float(p["h_value"])
    gap_label, gap_value = float(p["gap_label"]), float(p["gap_value"])
    w_label = float(p["w_label"])
    outline_pad = float(p["outline_pad"])
    bulb_ring_pad = float(p["bulb_ring_pad"])

    # C6：水平等距排布写成 n 元线性系统，交给高斯消元求解。
    #   x_0 = m ; x_i − x_{i−1} = d  (i = 1..n−1)
    A = [[0.0] * n for _ in range(n)]
    b = [0.0] * n
    A[0][0] = 1.0
    b[0] = m
    for i in range(1, n):
        A[i][i] = 1.0
        A[i][i - 1] = -1.0
        b[i] = d
    xs = solve_linear(A, b)
    by = {e.id: e for e in sk.elements}

    # C4：报纸原版竖向堆叠（0 点 = 圆球最上方顶点）：
    #   标题 → 量程说明 → 标签(类别名) → 管身(H_track) → 球泡 → 真值 → 底留白
    # y_bulb_top 就是 0 点：液柱底与它重合，液柱高度 = factor·v（从 0 点向上）。
    y_title, y_note = _place_header(sk, pre)
    y_label = y_note + h_note + gap_note
    y_bulb_top = y_label + h_label + gap_label + H_track   # = 0 点
    y_track = y_bulb_top - H_track                          # 管口（0 点上方 H_track）
    y_bulb = y_bulb_top
    y_value = y_bulb_top + bulb_d + gap_value

    for idx, point in enumerate(points):
        seq = point["seq"]
        x = xs[idx]
        v = point["value"]
        h = factor * v if v > 0 else 0.0       # C2：h = scale.factor × binding.value

        t = by[f"track_{seq}"]
        t.x_in, t.y_in, t.w_in, t.h_in = x, y_track, w_track, H_track
        # C2 + 0 点：液柱从 0 点（=球顶）向上长 h，故液柱底恒等于 y_bulb_top。
        # 原版液柱是细杆：宽度取 liquid_w，水平居中对齐管身（C5）。
        l = by[f"liquid_{seq}"]
        l.x_in = x + (w_track - liquid_w) / 2
        l.y_in, l.w_in, l.h_in = y_bulb_top - h, liquid_w, h
        bu = by[f"bulb_{seq}"]
        bu.x_in = x + (w_track - bulb_d) / 2   # C5 居中
        bu.y_in, bu.w_in, bu.h_in = y_bulb, bulb_d, bulb_d
        la = by[f"label_{seq}"]
        la.x_in = x + (w_track - w_label) / 2  # C5 居中
        la.y_in, la.w_in, la.h_in = y_label, w_label, h_label
        va = by[f"value_{seq}"]
        va.x_in = x + (w_track - w_label) / 2
        va.y_in, va.w_in, va.h_in = y_value, w_label, h_value

        # --- 皮肤（用户 m02273）：右侧刻度 + 外圈轮廓，全由几何常量确定 ---
        cap_r = w_track / 2 + outline_pad      # 半圆管顶半径（刻度的上让位量）
        R_ring = bulb_d / 2 + bulb_ring_pad    # 球泡外环半径
        cx = x + w_track / 2
        cy = y_bulb + bulb_d / 2

        # 刻度盒 = 管身盒（渲染端按 geometry 里的 count/len/thick 展开成小矩形）。
        k = by[f"ticks_{seq}"]
        k.x_in, k.y_in, k.w_in, k.h_in = x, y_track, w_track, H_track
        k.geometry = {
            "count": int(float(p["tick_count"])),
            "len": float(p["tick_len"]),
            "thick": float(p["tick_thick"]),
            # 刻度带上下各让一段：上让半圆管口圆顶、下让锥形收口。
            "pad_top": cap_r,
            "pad_bottom": float(p["neck_h"]),
        }
        # 轮廓：半圆顶 apex 恰在管口 y_track，球环底 = 球心 + R。
        o = by[f"outline_{seq}"]
        o.x_in = cx - R_ring
        o.y_in = y_track
        o.w_in = 2 * R_ring
        o.h_in = (cy + R_ring) - y_track
        o.geometry = {
            "cx": cx, "cy": cy, "R": R_ring, "cap_r": cap_r,
            "cap_top": y_track, "tube_bottom": y_bulb_top,
            "neck_h": float(p["neck_h"]),
        }

    # C1：可行性检查（不等式），越界即无解，不静默压缩。
    _check_canvas_bounds(sk, W, H)
    return sk


def _solve_semicircle(sk: PageSpec, points: list[dict], pre: dict,
                      template: TemplateSpec) -> PageSpec:
    """半圆图：C1/C2(两阶段)/C3/C4/C5/C7/C8 全部用预处理常量线性回填。

    α₀ = 180°（C8），θ_i = scale.factor × v_i（Σv 已在预处理算成常量）。
    求解器只做加法递推与线性等式，不含 min/max/Σ 分支（C7 硬规则）。
    """
    p = pre["p"]
    W, H, m, n, R = pre["W"], pre["H"], pre["m"], pre["n"], pre["R"]
    factor, sum_v, arc_total = pre["factor"], pre["sum_v"], pre["arc_total"]
    h_title, h_note = float(p["h_title"]), float(p["h_note"])
    gap_title, gap_note = float(p["gap_title"]), float(p["gap_note"])
    h_legend, h_center = float(p["h_legend"]), float(p["h_center"])
    gap_legend = float(p["gap_legend"])
    top_reserve = pre["top_reserve"]   # 由竖直分量派生，与 H_track 同源

    # C7：R 已在预处理由 min 算成常量；cx / cy / 直径均为线性派生。
    cx = m + (W - 2 * m) / 2
    cy = top_reserve + R
    diameter = 2 * R
    x_pie = cx - R
    # 审查修复：扇区盒从 top_reserve 起，不再顶到 m 压住标题 / 量程说明。
    y_pie = top_reserve

    # C4 垂直相邻：标题 / 说明与温度计同口径（共用 _place_header）。
    y_title, y_note = _place_header(sk, pre)
    # 图例行：y_i = top_reserve + (i−1)·(h_legend + gap_legend)。
    y_legend_0 = top_reserve
    pitch = h_legend + gap_legend
    legend_bottom = y_legend_0 + (n - 1) * pitch + h_legend
    # 图例在扇区左侧（不同 x），其下界用声明的 bottom_margin 而非 m：
    # C7 的 R=(H−2m)/2 让扇区盒底恰为 H−m，图例不需要退让到那条线。
    avail_bottom = H - float(p["bottom_margin"])
    if legend_bottom > avail_bottom + 1e-9:
        # C9 明确不实现；图例堆叠越过画布即无解，不静默压缩间距（D.3）。
        raise SolveError(
            f"n={n} legend stack bottom {legend_bottom:.4f} > H-bottom_margin={avail_bottom:.4f}",
            ["C1"])

    # C8 扇角递推：α₀ = 180°，θ_i = factor·v_i，α_i = α_{i−1} + θ_i。
    alpha = 180.0
    angles: dict[int, dict] = {}
    for idx, point in enumerate(points):
        seq = point["seq"]
        theta = factor * point["value"]
        angles[seq] = {"start_angle": alpha, "end_angle": alpha + theta,
                       "theta": theta, "R": R, "cx": cx, "cy": cy}
        alpha += theta
    # C3 闭合：末扇区 end == α₀ + Σθ = 180 + 180 = 360。
    if abs(alpha - (180.0 + arc_total)) > 1e-6:
        raise SolveError(f"arc sum {alpha:g} != {180.0 + arc_total:g}", ["C3"])

    by = {e.id: e for e in sk.elements}

    # C5 居中：中心数值盒 (cx−R, cy−h_center, 2R, h_center)。
    by["center"].x_in = x_pie
    by["center"].y_in = cy - h_center
    by["center"].w_in = diameter
    by["center"].h_in = h_center
    # E.3 #4：中心数值 = v_center/Σv×100% 实时归一（不写死 80%）。
    cid = int(p["center_slice_id"])
    cpt = next((pt for pt in points if pt["seq"] == cid), points[0])
    pct = 100.0 * cpt["value"] / sum_v
    by["center"].geometry = {"percent": pct, "v_center": cpt["value"],
                             "sum_v": sum_v, "center_slice_id": cid}
    by["center"].text = f"{pct:.1f}%"

    # 图例放在扇区盒左侧留白带，x_legend = m、w_legend = x_pie − m（不重叠）。
    w_legend = max(float(p["w_legend"]), x_pie - m)
    for idx, point in enumerate(points):
        seq = point["seq"]
        s = by[f"sector_{seq}"]
        s.x_in, s.y_in, s.w_in, s.h_in = x_pie, y_pie, diameter, diameter
        s.geometry = angles[seq]
        lg = by[f"legend_{seq}"]
        lg.x_in = m
        lg.y_in = y_legend_0 + idx * pitch
        lg.w_in = w_legend
        lg.h_in = h_legend

    # C1 可行性检查（不等式），越界即无解。
    _check_canvas_bounds(sk, W, H)
    return sk


_SOLVERS = {"thermometer": _solve_thermometer,
            "semicircle": _solve_semicircle}


def solve(sk: PageSpec, points: list[dict]) -> PageSpec:
    """把坐标无关的骨架解成具体 PageSpec（原地回填并返回同一对象）。

    审查修复 1：先校验骨架的**声明集**完整且每行都在约束注册表内。删掉一行
    声明会真实改变 solve() 的行为（拒绝），而不是被硬编码 handler 静默忽略。
    """
    name = sk.layout.get("template")
    template = get_template(name)
    _check_constraint_declarations(sk, template)
    overrides = sk.layout.get("param_overrides") or None
    pre = preprocess(points, template, sk.width_in, sk.height_in, overrides)
    handler = _SOLVERS.get(template.name)
    if handler is None:
        raise SolveError(f"no solver registered for template {template.name}", ["C2"])
    return handler(sk, points, pre, template)


# ---------------------------------------------------------------------------
# D.2 步骤 5：读回约束校验（从磁盘 pagespec.json 还原后再跑一次）
# ---------------------------------------------------------------------------
# 审查修复 1/2：声明行不再是惰性元数据。
#   * solve() 与 validate_spec() 都先校验声明集完整（删一行就拒绝）；
#   * validate_spec() 按 spec.constraints **每一行**分派校验器，从已求解的
#     几何重新推导该约束（C3 闭合 / C4 竖直相邻 / C5 居中 / C6 等距 / C7
#     半径 / C8 扇角递推 / DATA 数值→尺寸链接），而不是只查一条子串。
# ---------------------------------------------------------------------------
def _check_constraint_declarations(spec: PageSpec,
                                   template: TemplateSpec) -> None:
    """声明集必须完整、无未知行、无重复行；畸形行抛 SolveError 而非 AttributeError。"""
    required = [c["id"] for c in template.constraints]
    # 复审 I5：约束行必须是带 "id" 的 dict，否则 row.get 会漏出 AttributeError。
    for i, row in enumerate(spec.constraints):
        if not isinstance(row, dict) or "id" not in row:
            raise SolveError(
                f"malformed constraint row #{i}: {row!r} (expected dict with 'id')",
                ["C1"] if not isinstance(row, dict) else [row.get("id") or "C1"])
    declared = [row["id"] for row in spec.constraints]
    unknown = [cid for cid in declared if cid not in required]
    if unknown:
        raise SolveError(f"unknown declared constraint id(s): {unknown}", unknown)
    # 复审 M6：重复声明会让同一约束被「验两遍」，掩盖缺失的其他行。
    dupes = sorted({cid for cid in declared if declared.count(cid) > 1})
    if dupes:
        raise SolveError(f"duplicate declared constraint id(s): {dupes}", dupes)
    missing = [cid for cid in required if cid not in set(declared)]
    if missing:
        raise SolveError(f"missing required constraint row(s): {missing}", missing)


def _sorted_by_seq(spec: PageSpec, role: str) -> list[ElementSpec]:
    els = [e for e in spec.elements if e.role == role]
    return sorted(els, key=lambda e: int(e.id.rsplit("_", 1)[-1]))


def _by_id(spec: PageSpec, eid: str) -> ElementSpec:
    for e in spec.elements:
        if e.id == eid:
            return e
    raise SolveError(f"missing element: {eid}", ["C1"])


def _chk_C1(spec: PageSpec, ctx: dict) -> None:
    W, H = ctx["W"], ctx["H"]
    for e in spec.elements:
        if (e.x_in < -1e-9 or e.y_in < -1e-9
                or e.x_in + e.w_in > W + 1e-9
                or e.y_in + e.h_in > H + 1e-9):
            raise SolveError(f"{e.id} out of canvas {W:g}×{H:g}", ["C1"])


def _chk_DATA(spec: PageSpec, ctx: dict) -> None:
    """数值→尺寸 / 数值→扇角 的数据链接；半圆中心数值实时归一（E.3 #4）。"""
    factor = spec.scale.factor
    if factor is None:
        raise SolveError("scale.factor is missing", ["DATA", "C2"])
    if ctx["is_semi"]:
        sectors = _sorted_by_seq(spec, "sector")
        sum_v = float(math.fsum(float(s.binding["value"]) for s in sectors))
        if sum_v <= 0.0:
            raise SolveError("sum(v) <= 0 on readback", ["DATA", "C2"])
        for s in sectors:
            g = s.geometry or {}
            v = float(s.binding["value"])
            # geometry_expr 同样是承重的：扇区必须声明 θ_i 的求解表达式。
            if not s.geometry_expr or "theta_i" not in s.geometry_expr:
                raise SolveError(f"{s.id} missing theta_i geometry_expr", ["DATA", "C2"])
            if not math.isclose(float(g.get("theta", float("nan"))), factor * v,
                                rel_tol=1e-6, abs_tol=1e-6):
                raise SolveError(
                    f"{s.id} theta={g.get('theta')} != scale.factor*value={factor*v}",
                    ["DATA", "C2"])
        c = _by_id(spec, "center")
        cg = c.geometry or {}
        if not c.geometry_expr or "sum(v)" not in c.geometry_expr:
            raise SolveError("center missing live-normalization geometry_expr",
                             ["DATA", "C2"])
        v_center = float(c.binding["value"])
        pct = 100.0 * v_center / sum_v
        if (not math.isclose(float(cg.get("percent", float("nan"))), pct,
                             rel_tol=1e-6, abs_tol=1e-6)
                or not math.isclose(float(cg.get("sum_v", float("nan"))), sum_v,
                                    rel_tol=1e-6, abs_tol=1e-6)
                or not math.isclose(float(cg.get("v_center", float("nan"))), v_center,
                                    rel_tol=1e-6, abs_tol=1e-6)
                or c.text != f"{pct:.1f}%"):
            raise SolveError(
                f"center is not live-normalized (expected {pct:.1f}%)",
                ["DATA", "C2"])
    else:
        for l in _sorted_by_seq(spec, "liquid"):
            v = float(l.binding["value"])
            if not l.geometry_expr or "scale.factor" not in l.geometry_expr:
                raise SolveError(f"{l.id} missing scale.factor geometry_expr",
                                 ["DATA", "C2"])
            # 复审 M1：温度计的 v≤0 按 D.3「物理下界守 0、不删数据点」钳到 0，
            # 这是**有意**的非对称——液柱长度 0 在几何上合法；而半圆的负占比会
            # 产生负扇角（非法 PIE 楔形），故半圆在 preprocess 直接拒绝（C2）。
            expected = factor * v if v > 0 else 0.0
            if not math.isclose(l.h_in, expected, rel_tol=1e-6, abs_tol=1e-6):
                raise SolveError(
                    f"{l.id} h_in={l.h_in:.6f} != scale.factor*binding.value="
                    f"{expected:.6f}",
                    ["DATA", "C2"])


def _chk_C3(spec: PageSpec, ctx: dict) -> None:
    """共享比例尺：V_max=ceil(max(v)×1.1) / Σθ=scale.factor×Σv 闭合。"""
    if ctx["is_semi"]:
        sectors = _sorted_by_seq(spec, "sector")
        sum_v = float(math.fsum(float(s.binding["value"]) for s in sectors))
        theta_sum = float(math.fsum(float((s.geometry or {}).get("theta", float("nan")))
                                    for s in sectors))
        if (sum_v <= 0.0 or theta_sum <= 0.0
                or not math.isfinite(theta_sum)):
            raise SolveError("arc sum/v non-positive", ["C3"])
        if not math.isclose(spec.scale.factor, theta_sum / sum_v,
                            rel_tol=1e-6, abs_tol=1e-6):
            raise SolveError(
                f"scale.factor={spec.scale.factor} != sum(theta)/sum(v)="
                f"{theta_sum / sum_v}", ["C3"])
        # 复审 I2：Σθ 必须等于 arc_total（factor 减半后 Σθ=90 必须被拒）。
        arc_total = float(spec.layout.get("arc_total", spec.scale.h_in))
        if not math.isclose(theta_sum, arc_total, rel_tol=1e-6, abs_tol=1e-6):
            raise SolveError(
                f"sum(theta)={theta_sum:.6f} != arc_total={arc_total:.6f}", ["C3"])
        # 复审 I2：Scale 的声明的量程长度必须与 arc_total 一致。
        if not math.isclose(spec.scale.h_in, arc_total,
                            rel_tol=1e-6, abs_tol=1e-6):
            raise SolveError(
                f"scale.h_in={spec.scale.h_in} != arc_total={arc_total}", ["C3"])
    else:
        liquids = _sorted_by_seq(spec, "liquid")
        vs = [float(l.binding["value"]) for l in liquids]
        v_max = max(1.0, float(math.ceil(max(vs + [0.0]) * 11 / 10)))
        if not math.isclose(spec.scale.v_max, v_max, rel_tol=1e-9, abs_tol=1e-9):
            raise SolveError(
                f"scale.v_max={spec.scale.v_max} != ceil(max(v)*1.1)={v_max}", ["C3"])
        if not math.isclose(spec.scale.factor, spec.scale.h_in / spec.scale.v_max,
                            rel_tol=1e-6, abs_tol=1e-6):
            raise SolveError("scale.factor != scale.h_in / scale.v_max", ["C3"])
        if not math.isclose(spec.scale.h_in, _by_id(spec, "track_1").h_in,
                            rel_tol=1e-6, abs_tol=1e-6):
            raise SolveError("scale.h_in != track height", ["C3"])


def _chk_C5(spec: PageSpec, ctx: dict) -> None:
    """居中：子元素中心 == 父元素中心。"""
    if ctx["is_semi"]:
        c = _by_id(spec, "center")
        for s in _sorted_by_seq(spec, "sector"):
            if not math.isclose(c.x_in + c.w_in / 2, s.x_in + s.w_in / 2,
                                rel_tol=1e-6, abs_tol=1e-6):
                raise SolveError("center box not centered on pie", ["C5"])
    else:
        tracks = _sorted_by_seq(spec, "track")
        for role in ("liquid", "bulb", "label", "value"):
            for t, k in zip(tracks, _sorted_by_seq(spec, role)):
                if not math.isclose(k.x_in + k.w_in / 2, t.x_in + t.w_in / 2,
                                    rel_tol=1e-6, abs_tol=1e-6):
                    raise SolveError(f"{k.id} not centered on {t.id}", ["C5"])


def _chk_C6(spec: PageSpec, ctx: dict) -> None:
    """温度计水平等距：x_i 必须由公式 d 重新推导出来。

    复审 I1：只查「等距 + 首柱在 margin」会让「把所有管挤到 pitch=0.01」通过。
    这里按 C6 声明重新算 d = max(gap_min, (W−2m−w_track)/(n−1))，再逐根比对
    x_i == m + i·d；首柱锚定 layout.margin（不是 title.x_in，那是自指）。
    """
    p = ctx["params"]
    m = ctx["m"]
    n_tracks = len(_sorted_by_seq(spec, "track"))
    w_track = float(p["w_track"])
    gap_min = ctx["layout"].get("gap_min", 0.5)
    if n_tracks <= 1:
        d = 0.0
    else:
        d = max(float(gap_min), (ctx["W"] - 2 * m - w_track) / (n_tracks - 1))
    for i, t in enumerate(_sorted_by_seq(spec, "track")):
        want = m + i * d
        if not math.isclose(t.x_in, want, rel_tol=1e-6, abs_tol=1e-6):
            raise SolveError(
                f"{t.id} x={t.x_in:.6f} != m+i*d={want:.6f} "
                f"(d=max(gap_min,(W-2m-w_track)/(n-1))={d:.6f})", ["C6"])


def _chk_C4(spec: PageSpec, ctx: dict) -> None:
    """竖直相邻：温度计液柱底=管底 / 半圆图例按 h_legend+gap_legend 等距堆叠。"""
    p = ctx["params"]
    if ctx["is_semi"]:
        legends = _sorted_by_seq(spec, "legend")
        if not legends:
            raise SolveError("semicircle has no legend rows", ["C4"])
        h_legend = float(p["h_legend"])
        gap_legend = float(p["gap_legend"])
        pitch = h_legend + gap_legend
        # 复审 I4：top_reserve 必须由竖直分量重新推导，不能自报。
        top0 = (ctx["m"] + float(p["h_title"]) + float(p["gap_title"])
                + float(p["h_note"]) + float(p["gap_note"]))
        # 复审 I3：间距必须等于 h_legend+gap_legend（否则框会重叠/漂浮）。
        for i, e in enumerate(legends):
            want = top0 + i * pitch
            if not math.isclose(e.y_in, want, rel_tol=1e-6, abs_tol=1e-6):
                raise SolveError(
                    f"{e.id} y={e.y_in:.6f} != top_reserve+i*(h_legend+gap_legend)"
                    f"={want:.6f}", ["C4"])
            if not math.isclose(e.h_in, h_legend, rel_tol=1e-6, abs_tol=1e-6):
                raise SolveError(f"{e.id} h={e.h_in:.6f} != h_legend={h_legend}",
                                 ["C4"])
        # 复审 I4：扇区盒顶不得压住标题 / 量程说明带。
        for s in _sorted_by_seq(spec, "sector"):
            if s.y_in < top0 - 1e-9:
                raise SolveError(
                    f"{s.id} y={s.y_in:.6f} overlaps title band "
                    f"(top_reserve={top0:.6f})", ["C4"])
    else:
        pairs = list(zip(_sorted_by_seq(spec, "track"), _sorted_by_seq(spec, "liquid"),
                         _sorted_by_seq(spec, "bulb"), _sorted_by_seq(spec, "label"),
                         _sorted_by_seq(spec, "value")))
        if len(pairs) != len(_sorted_by_seq(spec, "track")):
            raise SolveError("thermometer element groups have unequal length", ["C4"])
        for t, l, b, la, va in pairs:
            bottom = t.y_in + t.h_in          # 管底 = 0 点（球的最上方顶点）
            if not math.isclose(l.y_in + l.h_in, bottom, rel_tol=1e-6, abs_tol=1e-6):
                raise SolveError(f"{l.id} bottom != {t.id} bottom (0 point)", ["C4"])
            # 报纸原版：球泡顶点即 0 点，液柱从这里向上长。
            if not math.isclose(b.y_in, bottom, rel_tol=1e-6, abs_tol=1e-6):
                raise SolveError(f"{b.id} top != {t.id} bottom (0 point)", ["C4"])
            # 类别名在管口上方，真值在球底下方。
            if la.y_in + la.h_in > t.y_in + 1e-9:
                raise SolveError(f"{la.id} overlaps {t.id} top", ["C4"])
            if va.y_in < b.y_in + b.h_in - 1e-9:
                raise SolveError(f"{va.id} overlaps {b.id} bottom", ["C4"])
        _chk_skin(spec, ctx)


def _chk_skin(spec: PageSpec, ctx: dict) -> None:
    """用户 m02273 的皮肤图元：刻度盒与外圈轮廓必须由 track/bulb 重新推导。

    复审教训（C6 自指）：不能只比「自己跟自己对得上」，要从 track/bulb 的
    现有几何 + 参数重算，位移 / 缩放 / 删条都能被抓到。
    """
    p = ctx["params"]
    w_track = float(p["w_track"])
    bulb_d = float(p["bulb_d"])
    outline_pad = float(p["outline_pad"])
    bulb_ring_pad = float(p["bulb_ring_pad"])
    neck_h = float(p["neck_h"])
    count_want = int(float(p["tick_count"]))
    len_want = float(p["tick_len"])
    thick_want = float(p["tick_thick"])

    def _close(a, b):
        return math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-6)

    tracks = _sorted_by_seq(spec, "track")
    for t, k, o, bu in zip(tracks, _sorted_by_seq(spec, "ticks"),
                           _sorted_by_seq(spec, "outline"),
                           _sorted_by_seq(spec, "bulb")):
        # 刻度：盒 = 管身盒；geometry 的三项必须等于参数（改条数也算篡改）。
        if not (_close(k.x_in, t.x_in) and _close(k.y_in, t.y_in)
                and _close(k.w_in, t.w_in) and _close(k.h_in, t.h_in)):
            raise SolveError(f"{k.id} box != {t.id} box", ["C4"])
        kg = k.geometry or {}
        if (int(kg.get("count", -1)) != count_want
                or not _close(float(kg.get("len", float("nan"))), len_want)
                or not _close(float(kg.get("thick", float("nan"))), thick_want)):
            raise SolveError(
                f"{k.id} tick geometry != (tick_count={count_want}, "
                f"tick_len={len_want}, tick_thick={thick_want})", ["C4"])
        # 刻度带的上下让位量也必须可复算（上让半圆顶、下让锥形收口）。
        pad_top_want = w_track / 2 + outline_pad
        if not _close(float(kg.get("pad_top", float("nan"))), pad_top_want):
            raise SolveError(
                f"{k.id} pad_top={kg.get('pad_top')} != derived {pad_top_want:.6f}",
                ["C4"])
        if not _close(float(kg.get("pad_bottom", float("nan"))), neck_h):
            raise SolveError(
                f"{k.id} pad_bottom={kg.get('pad_bottom')} != neck_h={neck_h:.6f}",
                ["C4"])
        # 外圈：中心/半径/半圆顶/管底全部由 track + bulb 重新推导。
        cap_r = w_track / 2 + outline_pad
        R_ring = bulb_d / 2 + bulb_ring_pad
        cx = t.x_in + w_track / 2
        cy = bu.y_in + bulb_d / 2
        want = {
            "cx": cx, "cy": cy, "R": R_ring, "cap_r": cap_r,
            "cap_top": t.y_in, "tube_bottom": t.y_in + t.h_in, "neck_h": neck_h,
        }
        og = o.geometry or {}
        for key, v in want.items():
            if not _close(float(og.get(key, float("nan"))), v):
                raise SolveError(
                    f"{o.id} {key}={og.get(key)} != derived {v:.6f}", ["C4"])
        if not (_close(o.x_in, cx - R_ring) and _close(o.y_in, t.y_in)
                and _close(o.w_in, 2 * R_ring)
                and _close(o.h_in, (cy + R_ring) - t.y_in)):
            raise SolveError(f"{o.id} bbox != derived silhouette box", ["C4"])
        # 半圆顶不能鼓到标签行上面去（原版这里只留 gap_label 一点空隙）。
        la = _sorted_by_seq(spec, "label")[tracks.index(t)]
        if o.y_in < la.y_in + la.h_in - 1e-9:
            raise SolveError(f"{o.id} overlaps {la.id} (label row)", ["C4"])


def _check_element_integrity(spec: PageSpec, template: TemplateSpec) -> None:
    """复审 I7：每组图元的数量必须与其他组一致。

    删掉 bulb_5 时 zip() 会静默截断，让 C4/C5 只校验前 4 组 → 检查被关闭。
    这里先按 role 分组、要求每组的 id 后缀集合完全相同。
    """
    groups: dict[str, set] = {}
    for e in spec.elements:
        if e.role in ("title", "scale_note", "center"):
            continue
        suffix = e.id.rsplit("_", 1)[-1]
        groups.setdefault(e.role, set()).add(suffix)
    if not groups:
        return
    all_suffixes = set().union(*groups.values())
    for role, got in groups.items():
        if got != all_suffixes:
            missing = sorted(all_suffixes - got)
            raise SolveError(
                f"role '{role}' is missing element(s) {missing} "
                f"(groups must have identical seq sets)", ["C1"])
    # 每个数据点都应有绑定（半圆图例/温度计标签等）；缺绑定说明规格被截断。
    for e in spec.elements:
        if e.role in ("sector", "liquid", "center", "legend", "value"):
            if e.binding is None:
                raise SolveError(f"{e.id} has no binding", ["DATA", "C2"])


def _chk_C7(spec: PageSpec, ctx: dict) -> None:
    """半圆半径 R = min((W−2m)/2 − gap_legend − w_legend,
    (H−top_reserve−bottom_margin)/2)：图例列要占一列宽度。

    审查修复：R 必须为标题 / 量程说明预留 top_reserve，否则扇区会盖住文字。
    top_reserve / bottom_margin 取自 layout（求解时写入），可独立复算。
    复审 I4：top_reserve 必须由竖直分量重新推导（不信 layout 里的自报值），
    否则「top_reserve=0.6 + 相称的 R/cx/cy」这种自洽篡改会让扇区压住标题。
    """
    p = ctx["params"]
    m = ctx["m"]
    top_reserve = (m + float(p["h_title"]) + float(p["gap_title"])
                   + float(p["h_note"]) + float(p["gap_note"]))
    reported = ctx["layout"].get("top_reserve")
    if reported is not None and not math.isclose(float(reported), top_reserve,
                                                 rel_tol=1e-6, abs_tol=1e-6):
        raise SolveError(
            f"layout.top_reserve={reported} != m+h_title+gap_title+h_note+gap_note"
            f"={top_reserve:.6f}", ["C7"])
    bottom_margin = float(ctx["layout"].get("bottom_margin", p["bottom_margin"]))
    R = min((ctx["W"] - 2 * m) / 2 - float(p["gap_legend"])
            - float(p["w_legend"]),
            (ctx["H"] - top_reserve - bottom_margin) / 2)
    for s in _sorted_by_seq(spec, "sector"):
        g = s.geometry or {}
        r = float(g.get("R", float("nan")))
        if (not math.isclose(s.w_in, 2 * R, rel_tol=1e-6, abs_tol=1e-6)
                or not math.isclose(s.h_in, 2 * R, rel_tol=1e-6, abs_tol=1e-6)
                or not math.isclose(r, R, rel_tol=1e-6, abs_tol=1e-6)):
            raise SolveError(
                f"{s.id} radius != min((W-2m)/2-gap_legend-w_legend,"
                f"(H-2m)/2)={R}", ["C7"])


def _chk_C8(spec: PageSpec, ctx: dict) -> None:
    """扇角递推：α₀=180°, end=start+θ, start_i=end_{i−1}, Σθ 闭合。"""
    sectors = _sorted_by_seq(spec, "sector")
    nan = float("nan")
    def _g(s, key):
        return float((s.geometry or {}).get(key, nan))
    if not math.isclose(_g(sectors[0], "start_angle"), 180.0,
                        rel_tol=1e-6, abs_tol=1e-6):
        raise SolveError("alpha_0 != 180° (半圆定义)", ["C8"])
    prev_end = None
    for s in sectors:
        st, en, th = _g(s, "start_angle"), _g(s, "end_angle"), _g(s, "theta")
        if not math.isclose(en, st + th, rel_tol=1e-6, abs_tol=1e-6):
            raise SolveError(f"{s.id} end != start + theta", ["C8"])
        if prev_end is not None and not math.isclose(st, prev_end,
                                                     rel_tol=1e-6, abs_tol=1e-6):
            raise SolveError(f"{s.id} start != previous end", ["C8"])
        prev_end = en
    theta_sum = float(math.fsum(_g(s, "theta") for s in sectors))
    if not math.isclose(prev_end, 180.0 + theta_sum,
                        rel_tol=1e-6, abs_tol=1e-6):
        raise SolveError("arc recurrence does not close", ["C8"])


_CONSTRAINT_CHECKERS = {
    "C1": _chk_C1, "DATA": _chk_DATA, "C3": _chk_C3, "C4": _chk_C4,
    "C5": _chk_C5, "C6": _chk_C6, "C7": _chk_C7, "C8": _chk_C8,
}


def validate_spec(spec: PageSpec) -> PageSpec:
    """按 spec.constraints 每行重新推导约束；幂等、不改坐标，违反即抛 SolveError。

    审查修复 1/2：不再是「只查 scale.factor 子串」的半途校验。声明集完整性 +
    逐行分派校验器，半圆扇角 / Σθ 闭合 / 中心数值 / 图例堆叠 / 半径 / 等距 /
    竖直相邻全部重新推导。老格式（无 constraints）退回只验 C1，保持可读。
    """
    # 包框的规格（用户 m04818）：width/height 指的是**框**，而 C1/C6/C7 这些
    # 约束依赖的是求解时的内容画布。这里先校 chrome（框/带/标题），再把内容
    # 还原成求解坐标继续往下校验——一个入口，调用方不用记得拆框。
    if (spec.layout or {}).get("frame"):
        from loop.frame import unwrap, validate_frame
        validate_frame(spec)
        spec = unwrap(spec)
    W, H = float(spec.width_in), float(spec.height_in)
    layout = spec.layout or {}
    if spec.scale is None:
        raise SolveError("scale is missing (None) in spec", ["C3"])
    name = layout.get("template")
    try:
        template = get_template(name)
    except (ValueError, NotImplementedError):
        raise SolveError(f"unknown layout template: {name!r}", ["C2"])
    # 复审：params 必须是「默认值 + 该规格实际使用的 override」，不是参数 schema。
    params = _defaults(template)
    params.update(layout.get("param_overrides") or {})
    ctx = {"W": W, "H": H, "layout": layout, "params": params,
           "m": float(layout.get("margin", params["margin"])),
           "is_semi": name == "semicircle"}
    if not spec.constraints:
        _chk_C1(spec, ctx)          # B 节之前的老 pagespec.json
        return spec
    _check_constraint_declarations(spec, template)
    _check_element_integrity(spec, template)
    for row in spec.constraints:
        checker = _CONSTRAINT_CHECKERS.get(row["id"])
        if checker is None:
            raise SolveError(f"no checker for declared constraint {row['id']}",
                             [row["id"]])
        try:
            checker(spec, ctx)
        except (KeyError, TypeError, ValueError) as ex:
            # 磁盘规格被改缺字段时给结构化错误，不漏出原始 KeyError / TypeError。
            raise SolveError(
                f"constraint {row['id']} could not be re-derived: {ex}",
                [row["id"]]) from ex
    return spec
