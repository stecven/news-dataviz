"""确定性脚手架：把「数值 → 液柱高度」写成纯函数硬约束。

对应 LIDA VISGENERATOR 的「脚手架 + 填充中间」：
- 脚手架（本文件）钉死几何与比例尺，不接受 LLM / 人工填坐标；
- 填充中间（GOAL_STUB + chart_points 数值）只提供数据与受控 stub。

数值忠实度为最高约束：V_max = ceil(max(v) × 1.1)，h_i = 3.0 × v_i / V_max。
禁止按上限夹取数值、禁止「超阈值画满」、禁止固定尺寸、禁止用文字补真值。
"""
import math

from loop.models import Scale, ElementSpec, PageSpec

# 固定目标 stub（Spec C/E 字段名）；本轮不含 LLM，可整体替换而不动脚手架。
GOAL_STUB: dict = {
    "id": "g1",
    "question": "哪些取暖电器品类成交额环比增速最高？",
    "chart_key": "heat_ratio_top5",
    "chart_type": "thermometer",
    "data_shape": "比较",
    "rationale": "5 个品类为倍数比较(10.0/3.0/3.0/3.0/3.0)，温度计以液柱高度直接编码倍数且共用同一量程",
    "required_fields": [
        {"name": "value", "source": "chart_points", "unit": "倍(超)", "aggregation": "none"}
    ],
    "semantic_tags": [],
    "fallback_used": False,
    "fallback_reason": None,
    "inner_h_in": 3.0,
}

TRACK_H_IN: float = 3.0


def compute_scale(values: list[float]) -> Scale:
    """V_max = ceil(max(v) × 1.1)，至少 1.0。

    用 top * 11 / 10 而不是 top * 1.1：后者在 10.0 上得
    11.000000000000002，会被 ceil 成 12，属于浮点陷阱。
    """
    top = max(values + [0.0])          # 空组 / 全负组也不会抛、不会得负 V_max
    v_max = max(1.0, float(math.ceil(top * 11 / 10)))
    return Scale(v_max=v_max, h_in=TRACK_H_IN, unit="")


def liquid_height_in(v: float, scale: Scale) -> float:
    """液柱高度是数值的线性映射，无任何削顶分支。

    非正值下限守 0（避免负 EMU / 非法形状）；这是物理下界，不是被禁的
    天花板夹取截断。
    """
    if v <= 0.0:
        return 0.0
    return scale.h_in * v / scale.v_max


def build_pagespec(points: list[dict],
                   chart_title: str = "取暖电器细分品类成交额环比增速TOP5",
                   goal: dict | None = None,
                   semantic_tags: list | None = None,
                   width_in: float = 10.0, height_in: float = 6.0,
                   template_name: str | None = None,
                   param_overrides: dict | None = None,
                   frame: bool = False,
                   subtitle_text: str | None = None,
                   target_width_in: float | None = None,
                   target_height_in: float | None = None) -> PageSpec:
    """生成 PageSpec：选模板 → 坐标无关骨架 → 约束求解回填几何。

    D.2 步骤 2/3 改造后的版本。「脚手架 + 填充中间」仍然成立，但硬约束
    不再是一张写死坐标表，而是 TemplateSpec 里的 C1–C8 约束声明 + 求解器。
    对外契约不变：默认仍是 27 元素、10×6 画布、温度计、同一份 DB 数据。
    compute_scale()/liquid_height_in() 保留作为「数值→尺寸」硬约束的纯函数
    参考实现（简洁、可单独断言），求解器使用同口径的 scale.factor。

    ``frame``（用户 m04818）：默认 False，返回纯求解坐标（逐约束单测关心的
    就是这套数）；交付路径（``build_loop`` / ``pipeline``）显式传 True，
    把结果包成「图框 + 标题带 + 标题 + 说明」的一张卡片。包框不改任何图形
    几何，只整体平移，所以「求解」与「chrome」两层可以各自断言。
    """
    if goal is None:
        goal = GOAL_STUB
    if semantic_tags is None:
        semantic_tags = goal["semantic_tags"]

    from loop.solve import build_skeleton, solve
    from loop.templates import get_template

    name = template_name or goal.get("chart_type", "thermometer")
    template = get_template(name)

    if (target_width_in is None) != (target_height_in is None):
        raise ValueError(
            "target_width_in and target_height_in must be given together: "
            "a card is fitted into a box, not into a strip")

    def solve_at(overrides, w, h):
        sk = build_skeleton(template, points, goal["chart_key"], chart_title,
                            width_in=w, height_in=h,
                            param_overrides=overrides,
                            semantic_tags=semantic_tags)
        return solve(sk, points)

    if target_width_in is not None:
        # 外部给定边界（用户 m05768）：卡片必须装进这个格子。
        from loop.fit import available_box, fit_to_target
        from loop.solve import SolveError
        try:
            natural = solve_at(param_overrides, width_in, height_in)
        except SolveError:
            natural = None            # 量不到文字就退化成纯几何下限
        return fit_to_target(
            solve_at,
            template=template,
            target_width_in=target_width_in,
            target_height_in=target_height_in,
            natural=natural,
            subtitle_text=subtitle_text)

    solved = solve_at(param_overrides, width_in, height_in)
    if not frame:
        return solved
    from loop.frame import wrap
    return wrap(solved, subtitle_text=subtitle_text)
