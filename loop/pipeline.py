"""流水线薄封装：选型器 → build_pagespec → 渲染（用户 m03536）。

本轮只做「接得上」这件事，不做新规则、不做素材库、不做整版排版：

    points ──features_from_points──► features
           ──selector.select──────► {selected_template, rationale, rejected}
           ──build_pagespec───────► PageSpec ──► pagespec.json + preview.png

设计约束（与 selector.py / solve.py / render.py 的边界）：
* **不复制选型规则**：本模块不读模板元数据、不判全相等/负值/零值/容量，
  一切判断都问 ``selector.select()``；想改规则只能改 selector.py。
* **不直接调求解器**：只经 ``build_pagespec()`` 出规格，不碰 build_skeleton。
* **不自己渲染**：复用 ``build_loop.render_from_spec()`` 的分发（温度计走
  render_thermo、半圆走 render_arc），本模块不认识任何图形类型。
* **不静默兜底**：``selected_template is None`` 时走 no_applicable 分支——不再
  「什么都不画」，而是查 ``v_fallback_assets`` 拿一张占位图、拼进 PageSpec 再渲染。
  这是显式的「无适用图形」产物，不是伪装成成功画了一张真图（用户 m04220）。
"""
from __future__ import annotations

import json
import os

from loop.asset_lookup import find_fallback_assets
from loop.build_loop import render_from_spec, write_pagespec_atomic
from loop.frame import wrap as wrap_frame
from loop.data_source import DB_PATH, load_points
from loop.models import ElementSpec, PageSpec, Scale
from loop.scaffold import build_pagespec
from loop.selector import (
    SEMANTIC_COMPARE,
    SEMANTIC_OTHER,
    SEMANTIC_SHARE,
    features_from_points,
    select,
)

# 校验器与求解器同在 loop.solve，但本模块只用它的「读回校验」这一个纯函数，
# 不调用 solve()（那一步在 build_pagespec 内部完成）。因此按模块导入而非
# 按函数导入，避免误以为流水线自己在求解。
import loop.solve as _solve_module

_SEMANTIC_SLUG = {
    SEMANTIC_SHARE: "share",
    SEMANTIC_COMPARE: "compare",
    SEMANTIC_OTHER: "other",
}

# ---------------------------------------------------------------------------
# 接口对照表（用户 m03536 第 3 件事）
#
# selector 输出三个字段，build_pagespec 的签名是：
#   build_pagespec(points, chart_title=..., goal=None, semantic_tags=None,
#                  width_in=..., height_in=..., template_name=None,
#                  param_overrides=None)
# 逐项对照结果如下。表就是代码，不要在两处各写一份。
# ---------------------------------------------------------------------------
STATUS_DIRECT = "直接可用"
STATUS_CONVERT = "需转换"
STATUS_MISSING = "缺失"

INTERFACE_MAP: list[dict] = [
    {
        "selector_field": "selected_template",
        "status": STATUS_DIRECT,
        "destination": "template_name",
        "note": ("非 None 时原样传给 build_pagespec(template_name=...)：字符串就是"
                 " get_template() 的注册表键（thermometer / semicircle），"
                 "中间不需要任何映射表或别名。"),
    },
    {
        "selector_field": "selected_template",
        "status": STATUS_CONVERT,
        "destination": "流水线内 None 守卫（不进入 build_pagespec）",
        "note": ("selector 用 None 表示「无适用图形」，但 build_pagespec 的 "
                 "template_name 只认字符串——传 None 会回落到 GOAL_STUB 的 "
                 "chart_type（thermometer），等于静默选了默认图形。因此必须在"
                 "流水线里先判 None 并短路，这个转换不能省。"),
    },
    {
        "selector_field": "rationale",
        "status": STATUS_MISSING,
        "destination": "selection.json（产物目录内旁挂文件）",
        "note": ("build_pagespec 没有 rationale 入参（GOAL_STUB 里虽有 rationale "
                 "字段，但不在函数签名上、也不会写进 PageSpec）。为免理由丢失，"
                 "流水线把它落到 selection.json，与 pagespec.json 并排存放。"),
    },
    {
        "selector_field": "rejected",
        "status": STATUS_MISSING,
        "destination": "selection.json（产物目录内旁挂文件）",
        "note": ("PageSpec 没有承载「被拒模板 + 拒因」的字段，rejected 同样只能"
                 "旁挂到 selection.json；未来若要进 PageSpec，需先扩 schema。"),
    },
]


def _points_from_values(values, unit="占比") -> list[dict]:
    return [{"seq": i + 1, "label": f"项{i + 1}", "value": float(v), "unit": unit}
            for i, v in enumerate(values)]


def _resolve_inputs(chart_key, values, chart_title):
    """取 (title, points)。两条数据来源互斥，都不改入参。"""
    if chart_key and values is not None:
        raise ValueError("pass either chart_key or values, not both")
    if chart_key:
        title, points = load_points(DB_PATH, chart_key=chart_key)
        return (chart_title or title), points
    if values is None:
        raise ValueError("one of chart_key / values is required")
    return (chart_title or "临时构造数据"), _points_from_values(values)


def _default_group_name(chart_key, semantic, n) -> str:
    if chart_key:
        return chart_key
    return f"{_SEMANTIC_SLUG.get(semantic, 'other')}_{n}_items"


# ---------------------------------------------------------------------------
# no_applicable 分支的占位图规格（用户 m04220）
#
# 本轮**不做排版决策**：位置写死一个合理值（版面中部偏下），只为验证
# 「占位图能被承载、能画出来」。等版面引擎做出来之后，这个常量会被
# layout_slot 的布局结果替换掉。
# ---------------------------------------------------------------------------
PLACEHOLDER_W_IN = 2.2
PLACEHOLDER_H_IN = 2.2
PLACEHOLDER_TOP_IN = 3.0          # 6 in 画布的中部偏下
#: 占位图的读者说明（用户 m04818）：占位图没有比例尺，讲清它是什么就够。
PLACEHOLDER_NOTE = "示意图：这里暂时缺一张图，数据补齐后会替换成对应图表。"


def _placeholder_element(asset, width_in: float,
                         box: tuple | None = None) -> ElementSpec:
    """把一条 ``v_fallback_assets`` 记录转成 image 图元。

    默认在 ``width_in`` 宽的画布里水平居中、纵向压 ``PLACEHOLDER_TOP_IN``
    （为了 H=6 的既有产物逐像素不变）。``box`` 给定时按 ``(x, y, side)``
    直接摆放——卡片模式下位置由可用内容盒算出来，不该再叠一份常量。
    """
    if box is not None:
        x_in, y_in, side = box
        return ElementSpec(
            id="placeholder_1",
            type="image",
            role="placeholder",
            x_in=round(x_in, 6),
            y_in=round(y_in, 6),
            w_in=round(side, 6),
            h_in=round(side, 6),
            image_path=asset["local_path"].replace("\\", "/"),
        )
    return ElementSpec(
        id="placeholder_1",
        type="image",
        role="placeholder",
        x_in=round((width_in - PLACEHOLDER_W_IN) / 2, 6),
        y_in=PLACEHOLDER_TOP_IN,
        w_in=PLACEHOLDER_W_IN,
        h_in=PLACEHOLDER_H_IN,
        # 相对项目根存，换机器可读；render.resolve_image_path 负责拼接。
        image_path=asset["local_path"].replace("\\", "/"),
    )


# ---------------------------------------------------------------------------
# 占位图边界兜底（用户 m04449）
#
# 背景：占位图分支是全流水线唯一一条既不走约束求解、也不走 `validate_spec`
# 的路径。`PLACEHOLDER_TOP_IN = 3.0` 是绝对常量，画布从 6 in 变 4 in 时
# 底部 5.20 就溢出 1.20 in，而 `status` 仍是 no_applicable、不报错——属于
# 「静默产出错误画面」。这里补一道与 C1 等价的边界校验。
#
# 选择「自适应」而不是「直接报错」的理由：
#   1. 这条分支存在的意义就是「无适用图形时也要有可见产物」。报错会让
#      no_applicable 退化成空手交出，等于撤销 m04220 的目的。
#   2. 占位图没有数据绑定、没有约束，缩放它不会造成「数值失真」——
#      而同一条原则（不可静默失真）在温度计/半圆上恰恰禁止缩放。
#   3. 调整不是静默的：结果里带 `placeholder_fit`（原始盒 / 最终盒 /
#      adjusted 标记），message 也会写明被调整过，调用方与人都能看到。
# 自适应只兜「位置/尺寸不匹配」；若画布小到连 2×margin 都放不下（缩放系数
# 归零），仍然显式报错——那属于调用方给了不可用的画布，不该由这里假装成功。
# ---------------------------------------------------------------------------
FIT_MARGIN_IN = 0.5
_EPS = 1e-9


def _is_inside(el, width_in: float, height_in: float) -> bool:
    """元素矩形是否完整落在 [0,W]×[0,H] 内（与 C1 同口径）。"""
    return (el.x_in >= -_EPS and el.y_in >= -_EPS
            and el.x_in + el.w_in <= width_in + _EPS
            and el.y_in + el.h_in <= height_in + _EPS)


def _fit_placeholder(el, width_in: float, height_in: float,
                     margin_in: float = FIT_MARGIN_IN) -> dict:
    """把越界的占位图等比缩进画布并居中；就地修改 el，返回调整记录。

    画布够大时**原样不动**（保证 H=6 的既有产物逐像素不变）。
    """
    before = [el.x_in, el.y_in, el.w_in, el.h_in]
    if _is_inside(el, width_in, height_in):
        return {"adjusted": False, "before": before, "after": before}

    avail_w = width_in - 2 * margin_in
    avail_h = height_in - 2 * margin_in
    if avail_w <= _EPS or avail_h <= _EPS:
        raise ValueError(
            f"canvas {width_in:g}×{height_in:g} in cannot hold a placeholder "
            f"with margin={margin_in:g} in (available "
            f"{avail_w:g}×{avail_h:g} in)")

    scale = min(1.0, avail_w / el.w_in, avail_h / el.h_in)
    el.w_in = round(el.w_in * scale, 6)
    el.h_in = round(el.h_in * scale, 6)
    el.x_in = round((width_in - el.w_in) / 2, 6)
    el.y_in = round((height_in - el.h_in) / 2, 6)
    if not _is_inside(el, width_in, height_in):
        # 理论上到不了这里（缩放后必然 <= avail），但一旦到就是真 bug，
        # 宁可炸也不要把越界的盒子交给渲染器。
        raise ValueError(
            f"placeholder still out of canvas after fit: "
            f"{[el.x_in, el.y_in, el.w_in, el.h_in]} vs "
            f"{width_in:g}×{height_in:g}")
    return {"adjusted": True, "before": before,
            "after": [el.x_in, el.y_in, el.w_in, el.h_in]}


def _build_fallback_spec(asset, title: str, width_in=10.0, height_in=6.0,
                         target_width_in=None,
                         target_height_in=None,
                         note: str | None = None) -> PageSpec:
    """构造只含一个 image 图元的 PageSpec。

    刻意**不写 constraints**：这是占位图，没有数据驱动几何、没有可重新推导的
    约束。``validate_spec`` 基于模板（template）跑，而占位图没有模板，所以
    该分支不走 validate_spec —— 若要强行走，就得给 solve.py 加模板豁免分支，
    那属于改动求解逻辑，超出本轮范围。

    正因为绕过了 validate_spec（连同 C1 越界检查一起绕过），这里**必须**
    自己补一道边界校验（用户 m04449）：越界就自适应缩进画布并居中，
    调整记录写进 ``layout["placeholder_fit"]``，供调用方判断是否被改过。
    """
    card = target_width_in is not None and target_height_in is not None
    if card:
        # 卡片模式（用户 m05768）：先算可用内容盒，占位图等比缩进去居中，
        # 再由 wrap(canvas_in=...) 把框钉死在目标尺寸上。
        from loop.fit import available_box
        avail_w, avail_h = available_box(target_width_in, target_height_in)
        side = min(PLACEHOLDER_W_IN, avail_w * 0.9, avail_h * 0.9)
        el = _placeholder_element(
            asset, avail_w,
            box=((avail_w - side) / 2, (avail_h - side) / 2, side))
        fit = {"adjusted": True, "before": [el.x_in, el.y_in, el.w_in, el.h_in],
               "after": [el.x_in, el.y_in, el.w_in, el.h_in],
               "reason": "card mode: scaled into the target box"}
        base_w, base_h = avail_w, avail_h
    else:
        el = _placeholder_element(asset, width_in)
        fit = _fit_placeholder(el, width_in, height_in)
        base_w, base_h = width_in, height_in
    spec = PageSpec(
        width_in=base_w,
        height_in=base_h,
        chart_key="placeholder",
        chart_title=title,
        scale=Scale(v_max=1.0, h_in=0.0, unit="n/a"),
        elements=[el],
        semantic_tags=[],
        constraints=[],
        layout={"template": None, "kind": "fallback_placeholder",
                "placeholder_fit": fit},
    )
    # 图框（用户 m04818）：占位图也是一张「单张图表」，同样要有框、标题带和
    # 一句面向读者的说明。默认那句是通用话术；编排层知道「为什么没配图」时
    # 传 ``note`` 覆盖它（用户 m06230：把原因写进 note，例如「分项过多，建议看表格」）。
    framed = wrap_frame(
        spec, note_text=note or PLACEHOLDER_NOTE,
        canvas_in=(target_width_in, target_height_in) if card else None)
    framed.layout["kind"] = "fallback_placeholder"
    return framed


def run_selected(chart_key: str | None = None, values=None, *,
                 semantic: str = SEMANTIC_OTHER,
                 chart_title: str | None = None,
                 out_root: str = os.path.join("out", "demo", "pipeline"),
                 target_width_in: float | None = None,
                 target_height_in: float | None = None,
                 group_name: str | None = None,
                 width_in: float = 10.0,
                 height_in: float = 6.0) -> dict:
    """选型 → 建模 → 渲染，一条龙。返回结构化结果（含失败分支）。

    返回字段：
        status            "rendered" | "no_applicable"
        selected_template 模板名或 None
        rationale         选型理由（原样，不改写）
        rejected          [{template, reason}]（原样）
        message           面向人的一句话结论（no_applicable 时的可读提示）
        out_dir / pagespec / preview / pptx / selection 产物路径（未出图为 None）
        placeholder_fit   仅 no_applicable 分支：占位图边界自适应记录
                          {"adjusted", "before", "after"}（用户 m04449）
    """
    title, points = _resolve_inputs(chart_key, values, chart_title)
    features = features_from_points(points, semantic)
    picked = select(features)

    out_dir = os.path.join(out_root,
                           group_name or _default_group_name(
                               chart_key, semantic, features["n"]))
    os.makedirs(out_dir, exist_ok=True)

    selection_path = os.path.join(out_dir, "selection.json")
    with open(selection_path, "w", encoding="utf-8") as f:
        json.dump({"semantic": semantic, "chart_title": title,
                   "features": features, **picked},
                  f, ensure_ascii=False, indent=2)

    template_name = picked["selected_template"]
    base = {
        "status": None,
        "selected_template": template_name,
        "rationale": picked["rationale"],
        "rejected": picked["rejected"],
        "semantic": semantic,
        "out_dir": out_dir,
        "selection": selection_path,
        "pagespec": None,
        "preview": None,
        "pptx": None,
        "message": "",
    }

    # --- 无适用图形：画占位图（用户 m04220）-----------------------------
    # 旧行为是只写 selection.json 然后返回；现在查 v_fallback_assets 拿一张占位图
    # 拼进 PageSpec，正常落盘 + 渲染，让「无适用」有可见产物而不是空手交出。
    # 选型结论（status=no_applicable、selected_template=None）保持不变——画占位图
    # 不等于选了个图形，状态必须如实反映「没有适用的图形模板」。
    if template_name is None:
        base["status"] = "no_applicable"
        assets = find_fallback_assets()
        if not assets:
            base["message"] = (
                f"未渲染任何图形：{picked['rationale']}"
                "（数据库里也没有占位图，无法给兜底产物。）")
            return base

        spec = _build_fallback_spec(assets[0], title, width_in, height_in,
                                    target_width_in=target_width_in,
                                    target_height_in=target_height_in)
        pagespec_path = os.path.join(out_dir, "pagespec.json")
        write_pagespec_atomic(pagespec_path, spec.to_dict())
        with open(pagespec_path, encoding="utf-8") as f:
            disk_spec = PageSpec.from_dict(json.load(f))
        # 不走 validate_spec：占位图规格没有模板、没有约束（见 _build_fallback_spec）。
        # 边界校验已在 _build_fallback_spec 里自己做掉（用户 m04449）。
        fit = disk_spec.layout.get("placeholder_fit") or {}
        adjusted_note = ""
        if fit.get("adjusted"):
            adjusted_note = (
                f"（占位图原盒 {fit['before']} 在 {width_in:g}×{height_in:g} in "
                f"画布上越界，已等比缩进并居中为 {fit['after']}。）")
        artifacts = render_from_spec(disk_spec, out_dir)

        base.update({
            "pagespec": pagespec_path,
            "preview": artifacts["png"],
            "pptx": artifacts["pptx"],
            "placeholder": next((e.image_path for e in disk_spec.elements
                                 if e.type == "image"), None),
            "placeholder_fit": fit,
            "message": (
                f"{picked['rationale']}"
                f"（已画出占位图 "
                f"{next((e.image_path for e in disk_spec.elements if e.type == 'image'), '')}"
                " 作为兜底产物，"
                "表示此处缺一个图形，不是选型成功。）" + adjusted_note),
        })
        return base

    # --- 有适用图形：build_pagespec → 原子写 → 读回校验 → 渲染 ---------
    spec = build_pagespec(points, title, template_name=template_name,
                          width_in=width_in, height_in=height_in, frame=True,
                          target_width_in=target_width_in,
                          target_height_in=target_height_in)

    pagespec_path = os.path.join(out_dir, "pagespec.json")
    write_pagespec_atomic(pagespec_path, spec.to_dict())
    with open(pagespec_path, encoding="utf-8") as f:
        disk_spec = PageSpec.from_dict(json.load(f))
    _solve_module.validate_spec(disk_spec)
    artifacts = render_from_spec(disk_spec, out_dir)

    base.update({
        "status": "rendered",
        "pagespec": pagespec_path,
        "preview": artifacts["png"],
        "pptx": artifacts["pptx"],
        "message": f"已渲染 {template_name}：{picked['rationale']}",
    })
    return base
