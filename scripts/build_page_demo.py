"""自由布局 0.1 最小演示（用户 m05945）。

输出 ``out/demo/page/``：

* ``pagelayout.json`` —— 整版规格（每张卡片最终 x/y/w/h + 内部子 PageSpec）
* ``page.pptx`` / ``preview.png`` —— 一整页
* ``summary.json`` —— 三张卡片的实际坐标、行分配、gutter 复测
* ``_natural_overflow.txt`` —— 用「自然尺寸」排同一组卡片的报错（验收闸口的反例）

用法：``python -m scripts.build_page_demo``
"""
import json
import os
import sys

from loop.contract import dump_layout, write_layout_atomic
from loop.layout import (CardSpec, LayoutFitError, LayoutOverflowError,
                         LayoutSpec, flow_layout, page_spec_path)
from loop.render_page import render_layout

OUT = os.path.join("out", "demo", "page")


def _cards(preset: bool):
    if preset:
        # 第二行刻意给两个**不同高度**，演示 0.2 的同行等高拉伸：
        # semi 5.2 in 是行内最高，ph 3.6 in 被拉到 5.2 in。
        return [
            CardSpec("thermo", "thermometer", chart_key="heat_ratio_top5",
                     title="取暖电器成交额环比增速TOP5",
                     width_in=9.2, height_in=4.6),
            CardSpec("semi", "semicircle", chart_key="heat_age",
                     title="取暖电器各年龄段占比",
                     width_in=4.45, height_in=5.2),
            CardSpec("ph", "placeholder", title="无适用图形",
                     width_in=4.45, height_in=3.6),
        ]
    return [
        CardSpec("thermo", "thermometer", chart_key="heat_ratio_top5",
                 title="取暖电器成交额环比增速TOP5"),
        CardSpec("semi", "semicircle", chart_key="heat_age",
                 title="取暖电器各年龄段占比"),
        CardSpec("ph", "placeholder", title="无适用图形"),
    ]


def main() -> int:
    os.makedirs(OUT, exist_ok=True)

    # 反例：自然尺寸（温度计卡片 10.52 in 比 9.2 in 的可用宽度还宽）
    natural_report = []
    try:
        flow_layout(LayoutSpec(fit_oversized=False), _cards(preset=False))
        natural_report.append("natural: 未报错（意外）")
    except LayoutOverflowError as exc:
        natural_report.append(f"natural: LayoutOverflowError: {exc}")
        natural_report.append(f"  已排卡片 = {[c.name for c in exc.placed]}")
        natural_report.append(f"  排不下 = {[c.name for c in exc.remaining]}")
    with open(os.path.join(OUT, "_natural_overflow.txt"), "w",
              encoding="utf-8") as fh:
        fh.write("\n".join(natural_report) + "\n")

    # 保底防线：极窄整版 + 自然尺寸的温度计卡片 → LayoutFitError
    fit_report = []
    try:
        flow_layout(LayoutSpec(width_in=4.0, height_in=15.0),
                    [CardSpec("thermo", "thermometer",
                              chart_key="heat_ratio_top5", title="窄版温度计")])
        fit_report.append("narrow: 未报错（意外）")
    except LayoutFitError as exc:
        fit_report.append(f"narrow: LayoutFitError: {exc}")
    with open(os.path.join(OUT, "_fit_error.txt"), "w",
              encoding="utf-8") as fh:
        fh.write("\n".join(fit_report) + "\n")

    # 对照：关掉等高，同一组卡片会露出 0.1 的行内留白
    loose = flow_layout(LayoutSpec(width_in=10.0, height_in=15.0,
                                   margin_in=0.4, gutter_in=0.3,
                                   equal_height=False),
                        _cards(preset=True))
    loose_png = None
    res_loose = render_layout(loose, os.path.join(OUT, "_unequal"))

    # 正例：预设尺寸 + 等高拉伸（0.2）
    layout = LayoutSpec(width_in=10.0, height_in=15.0, margin_in=0.4,
                        gutter_in=0.3)
    page = flow_layout(layout, _cards(preset=True))

    write_layout_atomic(page_spec_path(OUT), dump_layout(page))

    res = render_layout(page, OUT)

    # gutter 复测：行内水平邻距、相邻行带垂直邻距
    h_gaps, v_gaps = [], []
    for r, row in enumerate(page.rows):
        names = row["cards"]
        members = [c for c in page.cards if c.name in names]
        members.sort(key=lambda c: c.x_in)
        for a, b in zip(members, members[1:]):
            h_gaps.append(round(b.x_in - (a.x_in + a.w_in), 6))
        if r:
            prev = page.rows[r - 1]
            v_gaps.append(round(row["y_in"] - (prev["y_in"] + prev["h_in"]), 6))

    summary = {
        "page": {"width_in": page.width_in, "height_in": page.height_in,
                 "margin_in": page.margin_in, "gutter_in": page.gutter_in},
        "rows": page.rows,
        "cards": [{"name": c.name, "kind": c.card.kind, "x_in": c.x_in,
                   "y_in": c.y_in, "w_in": c.w_in, "h_in": c.h_in,
                   "row": c.row, "elements": len(c.spec.elements)}
                  for c in page.cards],
        "gaps": {"horizontal": h_gaps, "vertical": v_gaps},
        "outputs": {"preview": res["preview"], "pptx": res["pptx"],
                    "pagelayout": page_spec_path(OUT)},
        "natural_overflow": natural_report,
        "fit_error": fit_report,
        "unequal_row_preview": res_loose["preview"],
    }
    with open(os.path.join(OUT, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
