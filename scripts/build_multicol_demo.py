"""多栏图文混排 0.1 演示（用户 m06230）。

出两页，都在 ``out/demo/multicol/``：

* ``multicol/``：**全自动**的一页 —— 只给一段稿子和数据库，2 栏排版。标题跨栏、
  正文落单栏、卡片占满整行，是编排器自己决定的。
* ``multicol/_spread/``：**手工**一股流，专门演示两件事 —— 跨栏标题、块内均分
  两栏的正文（同一段话折成左右两栏）、以及两张单栏卡片并排。

产物：``preview.png`` / ``page.pptx`` / ``pagelayout.json`` / ``flow.json``。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loop.compose import compose_page                     # noqa: E402
from loop.layout import (CardSpec, LayoutSpec, TextBlock,  # noqa: E402
                         flow_layout, page_spec_path)
from loop.render_page import render_layout                 # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out", "demo", "multicol")

COPY = """取暖电器换季热销：五类小家电增速领跑
入冬以来取暖电器进入销售旺季，平台成交额环比走高，多个细分品类出现两位数增长。
从细分品类看，取暖电器的成交额环比增速居前，欧式快热炉、踢脚线取暖器等品类领跑。
分年龄看，各年龄段消费者的取暖电器成交额占比不同，中年群体是主力，年轻群体增速更快。"""

LEAD = ("入冬以来取暖电器进入销售旺季，平台成交额环比走高，多个细分品类出现两位数增长，"
        "线上渠道尤其明显。")
BODY = ("分年龄看，各年龄段消费者的取暖电器成交额占比不同：中年群体贡献了最大的份额，"
        "年轻群体的增速更快，但基数还小。把两件事分开看更清楚 —— 谁的盘子大是占比问题，"
        "谁长得快是增速问题，新闻里常把两者混着说。")
TAIL = ("综合来看，取暖电器这一轮增长由品类结构和人群结构共同推动。")


def _auto_page():
    """全自动：只给 text + db。"""
    result = compose_page(COPY, OUT, width_in=10.0, height_in=15.0,
                          margin_in=0.4, gutter_in=0.3, column_count=2)
    with open(os.path.join(OUT, "flow.json"), "w", encoding="utf-8") as fh:
        json.dump([{"kind": type(x).__name__,
                    "name": x.name,
                    "template": getattr(x, "kind", None),
                    "span": getattr(x, "column_span", 1)}
                   for x in result.flow], fh, ensure_ascii=False, indent=2)
    return result


def _spread_page():
    """手工流：跨栏标题 + 块内两栏正文 + 两张单栏卡片并排。"""
    out_dir = os.path.join(OUT, "_spread")
    layout = LayoutSpec(width_in=10.0, height_in=15.0, margin_in=0.4,
                        gutter_in=0.3, column_count=2, column_gutter_in=0.2)
    flow = [
        TextBlock("取暖电器换季热销：五类小家电增速领跑", "title", "center",
                  column_span=2),
        TextBlock(LEAD, "body", column_span=1),
        TextBlock(TAIL, "body", column_span=1),
        CardSpec("heat_ratio_top5", "thermometer", chart_key="heat_ratio_top5",
                 title="取暖电器细分品类成交额环比增速TOP5", column_span=2),
        TextBlock(BODY, "body", column_span=2, columns=2),
        CardSpec("heat_age", "semicircle", chart_key="heat_age",
                 title="取暖电器成交额年龄占比", column_span=1),
        CardSpec("placeholder", "placeholder", title="无适用图形",
                 note="示意图：分项过多，建议看表格。", column_span=1),
    ]
    os.makedirs(out_dir, exist_ok=True)
    page = flow_layout(layout, flow)
    with open(page_spec_path(out_dir), "w", encoding="utf-8") as fh:
        json.dump(page.to_dict(), fh, ensure_ascii=False, indent=2)
    with open(os.path.join(out_dir, "flow.json"), "w", encoding="utf-8") as fh:
        json.dump([{"kind": type(x).__name__, "name": x.name,
                    "template": getattr(x, "kind", None),
                    "span": getattr(x, "column_span", 1),
                    "columns": getattr(x, "columns", 1)} for x in flow],
                  fh, ensure_ascii=False, indent=2)
    rendered = render_layout(page, out_dir)
    return page, rendered


def main():
    os.makedirs(OUT, exist_ok=True)
    auto = _auto_page()
    page, _ = _spread_page()

    summary = {
        "auto": {
            "product": {"pagespec": page_spec_path(OUT),
                        "preview": auto.outputs.get("preview"),
                        "pptx": auto.outputs.get("pptx")},
            "selected": [{"dataset": m.dataset_key, "template": m.template}
                         for m in auto.matches],
        },
        "spread": {"canvas": [page.width_in, page.height_in],
                   "columns": page.column_count,
                   "column_gutter_in": page.column_gutter_in,
                   "items": [dict(kind=k, name=o.name, x_in=o.x_in, y_in=o.y_in,
                                  w_in=o.w_in, h_in=o.h_in,
                                  span=getattr(o.card if k == "card" else o.block,
                                               "column_span", 1))
                             for k, o in page.items()]},
    }
    with open(os.path.join(OUT, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)

    print("auto   ->", auto.outputs.get("preview"))
    print("spread ->", os.path.join(OUT, "_spread", "preview.png"))
    for k, o in page.items():
        span = getattr(o.card if k == "card" else o.block, "column_span", 1)
        print(f"  {k:4s} {o.name[:12]:14s} x={o.x_in:7.4f} y={o.y_in:7.4f} "
              f"w={o.w_in:7.4f} h={o.h_in:6.4f} span={span}")


if __name__ == "__main__":
    main()
