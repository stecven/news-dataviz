"""自动化编排端到端演示（用户 m06157）。

只喂一段新闻稿 + 数据库：拆段、认标题、配数据、组流、排版、出图。
产物在 ``out/demo/auto_layout/``。
"""
import json
import os
import sys

from loop.compose import compose_page, load_catalog, split_paragraphs

OUT = os.path.join("out", "demo", "auto_layout")

COPY = """取暖电器换季热销：五类小家电增速领跑

入冬以来取暖电器进入销售旺季。平台数据显示，成交额环比明显走高，多款单品的增速超过一倍。

从细分品类看，取暖电器的成交额环比增速以欧式快热炉、电油汀等品类居前，取暖画与电热地垫也进入前五。

分年龄看，各年龄段消费者的取暖电器成交额占比差异并不悬殊，26岁至35岁人群贡献最多。"""

#: 反例：通篇不提任何数据组 → 应退化为纯文本页，不崩。
PLAIN = """换季消费观察

这是一篇没有任何数据引用的短评，只谈季节变化与生活习惯。
降温来得比往年早，人们提前添置了过冬用品。"""


def main() -> int:
    os.makedirs(OUT, exist_ok=True)

    result = compose_page(COPY, OUT, width_in=10.0, height_in=15.0)
    page = result.page

    # 退化演示：没有任何数据组被提到 → 纯文本页
    plain_out = os.path.join(OUT, "_plain")
    plain = compose_page(PLAIN, plain_out, width_in=10.0, height_in=15.0)

    summary = {
        "catalog": [d.key for d in load_catalog()],
        "paragraphs": split_paragraphs(COPY),
        "flow": result.flow_summary(),
        "matches": [m.to_dict() for m in result.matches],
        "notes": result.notes,
        "items": [{"kind": k, "name": v.name,
                   "x_in": round(v.x_in, 4), "y_in": round(v.y_in, 4),
                   "w_in": round(v.w_in, 4), "h_in": round(v.h_in, 4)}
                  for k, v in page.items()],
        "outputs": result.outputs,
        "plain_page": {
            "notes": plain.notes,
            "flow": plain.flow_summary(),
            "outputs": plain.outputs,
        },
    }
    with open(os.path.join(OUT, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
