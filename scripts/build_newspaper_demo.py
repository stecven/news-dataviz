"""微型报纸演示：图文混排 0.1（用户 m06055）。

流：大标题 → 导语正文 → 温度计卡片 → 一段正文 → 半圆图与占位图并排。
整版 10 × 15 in，输出 ``out/demo/paper/``。
"""
import json
import os
import sys

from loop.contract import dump_layout, write_layout_atomic
from loop.layout import (CardSpec, LayoutOverflowError, LayoutSpec, TextBlock,
                         flow_layout, page_spec_path)
from loop.render_page import render_layout

OUT = os.path.join("out", "demo", "paper")

TITLE = "取暖电器换季热销：五类小家电成交额环比增速榜"
LEAD = ("入冬以来取暖电器进入销售旺季。平台数据显示，电暖器、暖风机等品类的成交额"
        "环比增速明显高于其他小家电，其中高端取暖器的增速接近翻倍。")
BODY_1 = ("从品类结构看，暖风机与电热毯的占比继续提升，传统油汀的增速则趋于平缓；"
          "各年龄段的消费偏好差异也在拉大。")
BODY_2 = ("分年龄看，26—35 岁人群贡献了近三分之一的取暖电器成交额，"
          "而 36—45 岁人群更偏好大功率机型。")


def _items():
    return [
        TextBlock(TITLE, "title", "center"),
        TextBlock(LEAD, "body"),
        CardSpec("thermo", "thermometer", chart_key="heat_ratio_top5",
                 title="取暖电器成交额环比增速TOP5",
                 width_in=9.2, height_in=4.2),
        TextBlock(BODY_1, "body"),
        CardSpec("semi", "semicircle", chart_key="heat_age",
                 title="取暖电器各年龄段占比",
                 width_in=4.45, height_in=4.6),
        CardSpec("ph", "placeholder", title="无适用图形",
                 width_in=4.45, height_in=3.4),
        TextBlock(BODY_2, "body"),
    ]


def main() -> int:
    os.makedirs(OUT, exist_ok=True)

    page = flow_layout(LayoutSpec(width_in=10.0, height_in=15.0,
                                  margin_in=0.4, gutter_in=0.3), _items())
    write_layout_atomic(page_spec_path(OUT), dump_layout(page))
    res = render_layout(page, OUT)

    # 溢出验证：同样的流塞进 10×6 的版面
    overflow = []
    try:
        flow_layout(LayoutSpec(width_in=10.0, height_in=6.0), _items())
        overflow.append("short page: 未报错（意外）")
    except LayoutOverflowError as exc:
        overflow.append(f"short page: LayoutOverflowError: {exc}")
    with open(os.path.join(OUT, "_overflow.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(overflow) + "\n")

    # 间距复测：按 y 排序，相邻项之间要么同行的水平 gutter、要么垂直 gutter
    ordered = page.items()
    summary = {
        "page": {"width_in": page.width_in, "height_in": page.height_in,
                 "margin_in": page.margin_in, "gutter_in": page.gutter_in},
        "rows": page.rows,
        "items": [{"kind": k, "name": v.name,
                   "x_in": round(v.x_in, 4), "y_in": round(v.y_in, 4),
                   "w_in": round(v.w_in, 4), "h_in": round(v.h_in, 4),
                   "row": v.row,
                   **({"lines": len(v.lines)} if k == "text" else {})}
                  for k, v in ordered],
        "outputs": {"preview": res["preview"], "pptx": res["pptx"],
                    "pagelayout": page_spec_path(OUT)},
        "overflow": overflow,
    }
    with open(os.path.join(OUT, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
