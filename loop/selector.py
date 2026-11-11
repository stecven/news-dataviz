"""图形选型器（第一版，规则写死）。

定位：D 层「目标与选型」的最小落点。输入数据特征，输出
``{selected_template, rationale, rejected}``；**不渲染、不求解、不写盘**，
真正出图仍走既有脚手架（本模块不 import 任何渲染/求解模块）。

与 solve.py 的关系：选型是**更早**的判定。半圆 ``max_slices`` 在
``solve.preprocess()`` 里仍会硬拒绝（最后一道防线，本轮不改）；本模块只是
把同样的边界提前到选型阶段说清楚，两者不冲突。

规则优先级（用户 m03467 原文 + 两处冲突裁定）：
  5a  全相等 → 一律优先温度计，**不论语义**（比「占比」更高的否决条件）。
  4   含负值 → 温度计（非正值守 0）；半圆不适用（占比不能为负）。
  1   n > max_slices → 半圆不适用；语义「比较」则温度计，否则无适用图形。
  2   语义「占比」且 n ≤ max_slices 且无负值、非全相等 → 半圆。
  3   语义「比较」→ 温度计。
  5b  含零值 → 不改变上面的选型结果，但 rationale 必须点名零值退化扇区。
  6   其余 → 返回无适用图形 + 原因，不静默选默认。
"""
from __future__ import annotations

SEMANTIC_SHARE = "占比构成"
SEMANTIC_COMPARE = "比较大小"
SEMANTIC_OTHER = "其他"

_TEMPLATE_THERMOMETER = "thermometer"
_TEMPLATE_SEMICIRCLE = "semicircle"


class SelectorError(Exception):
    """选型器无法作出判断（例如模板元数据缺失）。不要静默兜底。"""


def _semicircle_max_slices() -> int:
    """从半圆模板元数据读容量上限；缺失就报错，绝不默认 5。"""
    from loop.templates import get_template

    params = get_template(_TEMPLATE_SEMICIRCLE).params
    if "max_slices" not in params:
        raise SelectorError(
            "semicircle template is missing max_slices metadata; "
            "refuse to default it to 5")
    return int(params["max_slices"]["default"])


def features_from_points(points: list[dict], semantic: str) -> dict:
    """从数据点推出选型需要的特征（不修改入参）。"""
    values = [float(p["value"]) for p in points]
    n = len(values)
    all_equal = n > 0 and len(set(values)) == 1
    return {
        "n": n,
        "all_equal": all_equal,
        "has_zero": any(v == 0.0 for v in values),
        "has_negative": any(v < 0.0 for v in values),
        "semantic": semantic,
    }


def _result(selected, rationale, rejected):
    return {"selected_template": selected,
            "rationale": rationale,
            "rejected": rejected}


def _rej(template, reason):
    return {"template": template, "reason": reason}


def _semi_not_applicable(reason: str):
    return _rej(_TEMPLATE_SEMICIRCLE, reason)


def select(features: dict) -> dict:
    """按写死的规则二选一。返回结构永远带 rationale 与 rejected。

    不修改 ``features``、不调用 ``solve()``、不写盘。
    """
    n = int(features["n"])
    all_equal = bool(features["all_equal"])
    has_zero = bool(features["has_zero"])
    has_negative = bool(features["has_negative"])
    semantic = features.get("semantic", SEMANTIC_OTHER)
    max_slices = _semicircle_max_slices()

    # 零值只是「画得出但有一条退化扇区」，不改变选型结论（规则 5b），
    # 但 rationale 必须说清楚，否则读者会以为图上少画了一块。
    # 注意：各条 rationale 都以句号结尾，下面直接拼接，避免出现「。；」。
    zero_note = ("注意数据含 0 值，半圆图会出现 start==end 的零值退化扇区"
                 "（0° 楔形，正常但不显示面积）。" if has_zero else "")

    # --- 5a：全相等一律温度计（高于「占比」的否决条件） ---
    if all_equal:
        return _result(
            _TEMPLATE_THERMOMETER,
            f"数据全相等（{n} 项数值完全相同）：半圆图各扇区都是等角 {180.0 / max(n, 1):.1f}°，"
            f"看不出差异，且任意一个扇区都不比别的大，占比图的比较语义失效；"
            f"温度计等高的液柱能直观看清「一样高」，故不论语义都优先温度计。"
            f"{zero_note}",
            [_semi_not_applicable(
                "全相等：各扇区等角，占比图失去比较意义，且最小可见角度无法区分"
                if not has_zero else
                "全相等：各扇区等角，占比图失去比较意义")])

    # --- 4：含负值 → 温度计可处理，半圆不行 ---
    if has_negative:
        return _result(
            _TEMPLATE_THERMOMETER,
            f"数据含负值：半圆图的扇角是占比，占比不能为负，负数会产出负角度的非法楔形，"
            f"故半圆图不适用；温度计可以画，非正值的液柱高度按物理定义守 0（不是削顶截断），"
            f"负值照样保留在数据与标签里。{zero_note}",
            [_semi_not_applicable("含负值：占比不能为负，负扇角是非法几何")])

    # --- 1：超出半圆容量 ---
    if n > max_slices:
        semi_reason = (f"MAX_SLICES：分项数 n={n} 超过半圆图上限 max_slices={max_slices}，"
                       f"扇区过多不可读")
        if semantic == SEMANTIC_COMPARE:
            return _result(
                _TEMPLATE_THERMOMETER,
                f"数据是「比较大小」语义，选温度计：n={n} 恰好超过半圆图上限 "
                f"max_slices={max_slices}（{semi_reason}），而温度计按水平等距排布，"
                f"任意分项数都能放下。{zero_note}",
                [_semi_not_applicable(semi_reason)])
        return _result(
            None,
            f"无适用图形：数据是「{semantic}」语义，本应走半圆图，但 {semi_reason}；"
            f"温度计只编码「大小比较」，不适合表达构成占比，故不替代。"
            f"按设计文档 D.3 需在选型阶段换图并标 fallback_used（本子集未实现换图）。",
            [_semi_not_applicable(semi_reason),
             _rej(_TEMPLATE_THERMOMETER,
                  "语义是构成占比，温度计按高度编码绝对值，无法表达部分与整体的关系")])

    # --- 2：占比构成 → 半圆 ---
    if semantic == SEMANTIC_SHARE:
        return _result(
            _TEMPLATE_SEMICIRCLE,
            f"数据是「占比构成」语义、n={n} 满足 n≤5（max_slices={max_slices}）、"
            f"且无负值：半圆图用扇角编码部分与整体的关系，Σθ 恒等于 180° 闭合，"
            f"中心数值实时按 v_center/Σv 归一，最贴合「构成」表达。{zero_note}",
            [_rej(_TEMPLATE_THERMOMETER,
                  "语义是构成占比，温度计编码的是各自绝对高度，不体现「占整体的多少」")])

    # --- 3：比较大小 → 温度计 ---
    if semantic == SEMANTIC_COMPARE:
        return _result(
            _TEMPLATE_THERMOMETER,
            f"数据是「比较大小」语义：温度计以液柱高度直接编码数值、全组共用同一量程 "
            f"V_max，比较一目了然；n={n} 不受半圆图 max_slices={max_slices} 约束。"
            f"{zero_note}",
            [_semi_not_applicable(
                "语义是比较大小：扇角表达的是占比，读者会误以为在讲「占到多少」")])

    # --- 6：其余 → 无适用图形 ---
    return _result(
        None,
        f"无适用图形：数据语义「{semantic}」不在本版支持的两类里（半圆图只做占比构成、"
        f"温度计只做大小比较），不静默选默认图形。需扩展选型规则或换用其他图形。",
        [_semi_not_applicable("语义不支持：半圆图只用于占比构成"),
         _rej(_TEMPLATE_THERMOMETER, "语义不支持：温度计只用于大小比较")])
