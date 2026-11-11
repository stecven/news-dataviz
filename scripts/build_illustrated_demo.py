"""图文并茂 1.0 演示（用户 m06471）：把素材库接进自动编排。

出三页，都在 ``out/demo/illustrated/``：

* ``auto/``：**全自动** —— 只给一段稿子和数据库。2 栏排版，编排器自己决定
  哪段配哪组数据、配什么图、装饰插图从素材库的哪个语义档里挑。
* ``_spread/``：**手工**一股流，严格照用户描述的结构摆一遍 ——
  标题（跨 2 栏）→ 导语 → 温度计卡片（2 栏）→ 正文 → 半圆图卡片（1 栏）
  + 插图（1 栏）。
* ``_no_asset/``：**查不到素材**的反例 —— 把素材检索打桩成空结果，整页照样
  排得出来，只是没有插图。用来证明「少一张插图是遗憾，排不出整版是事故」。

产物：``preview.png`` / ``page.pptx`` / ``pagelayout.json`` / ``flow.json``。
"""
import json
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loop.asset_lookup import find_assets_by_semantic   # noqa: E402
from loop.compose import compose_page                    # noqa: E402
from loop.data_source import DB_PATH                     # noqa: E402
from loop.layout import (CardSpec, ImageBlock, LayoutSpec,  # noqa: E402
                         TextBlock, flow_layout, page_spec_path)
from loop.render_page import render_layout                # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out", "demo", "illustrated")

COPY = """取暖电器换季热销：五类小家电增速领跑
入冬以来取暖电器进入销售旺季，平台成交额环比走高，多个细分品类出现两位数增长。
从细分品类看，取暖电器的成交额环比增速居前，欧式快热炉、踢脚线取暖器等品类领跑。
分年龄看，各年龄段消费者的取暖电器成交额占比不同，中年群体是主力，年轻群体增速更快。"""

LEAD = ("入冬以来取暖电器进入销售旺季，平台成交额环比走高，多个细分品类出现两位数增长，"
        "线上渠道尤其明显。")
BODY = ("分年龄看，各年龄段消费者的取暖电器成交额占比不同：中年群体贡献了最大的份额，"
        "年轻群体的增速更快，但基数还小。把两件事分开看更清楚 —— 谁的盘子大是占比问题，"
        "谁长得快是增速问题，新闻里常把两者混着说。")

#: 手工页用哪张插图：直接问素材库要「占比构成」档的第一名（S4 按 weight 排好序）。
PEOPLE = find_assets_by_semantic("占比构成", DB_PATH)[0]
RADIATOR = find_assets_by_semantic("比较大小", DB_PATH)[0]


def _pick(semantic: str) -> dict:
    rows = find_assets_by_semantic(semantic, DB_PATH)
    if not rows:
        raise LookupError(f"素材库里没有 {semantic} 档的插图")
    return rows[0]


def _write_flow(out_dir: str, flow: list) -> None:
    with open(os.path.join(out_dir, "flow.json"), "w", encoding="utf-8") as fh:
        json.dump([{"kind": type(x).__name__, "name": x.name,
                    "template": getattr(x, "kind", None),
                    "path": getattr(x, "path", None),
                    "span": getattr(x, "column_span", 1),
                    "columns": getattr(x, "columns", 1)} for x in flow],
                  fh, ensure_ascii=False, indent=2)


def _auto_page():
    """全自动：只给 text + db，2 栏。"""
    result = compose_page(COPY, OUT, width_in=10.0, height_in=15.0,
                          margin_in=0.4, gutter_in=0.3, column_count=2)
    _write_flow(OUT, result.flow)
    return result


def _no_asset_page():
    """素材检索返回空 —— 整页照排，只是没有插图。"""
    out_dir = os.path.join(OUT, "_no_asset")
    with mock.patch("loop.compose.find_assets_by_semantic", return_value=[]):
        result = compose_page(COPY, out_dir, width_in=10.0, height_in=15.0,
                              margin_in=0.4, gutter_in=0.3, column_count=2)
    _write_flow(out_dir, result.flow)
    return result


def _spread_page():
    """手工流：标题跨栏 → 导语 → 温度计卡(2栏) → 正文 → 半圆卡(1栏)+插图(1栏)。"""
    out_dir = os.path.join(OUT, "_spread")
    layout = LayoutSpec(width_in=10.0, height_in=15.0, margin_in=0.4,
                        gutter_in=0.3, column_count=2, column_gutter_in=0.2)
    flow = [
        TextBlock("取暖电器换季热销：五类小家电增速领跑", "title", "center",
                  column_span=2),
        TextBlock(LEAD, "body", column_span=1),
        CardSpec("heat_ratio_top5", "thermometer", chart_key="heat_ratio_top5",
                 title="取暖电器细分品类成交额环比增速TOP5", column_span=2),
        TextBlock(BODY, "body", column_span=2, columns=2),
        CardSpec("heat_age", "semicircle", chart_key="heat_age",
                 title="取暖电器成交额年龄占比", column_span=1),
        ImageBlock(_pick("占比构成")["local_path"], style="icon",
                   column_span=1, asset_id=PEOPLE["asset_id"],
                   tag=PEOPLE["tag"], semantic="占比构成",
                   name=f"illustration_{PEOPLE['asset_id']}"),
    ]
    os.makedirs(out_dir, exist_ok=True)
    page = flow_layout(layout, flow)
    with open(page_spec_path(out_dir), "w", encoding="utf-8") as fh:
        json.dump(page.to_dict(), fh, ensure_ascii=False, indent=2)
    _write_flow(out_dir, flow)
    rendered = render_layout(page, out_dir)
    return page, rendered


def _label(draw, xy, text):
    from PIL import ImageFont
    font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 26)
    draw.rectangle([xy[0] - 6, xy[1] - 4, xy[0] + 26 * len(text), xy[1] + 34],
                   fill=(255, 255, 255))
    draw.text(xy, text, fill=(40, 40, 40), font=font)


def _contact_sheet() -> str:
    """三页并排总览 + 两条插图放大带（给人肉眼验收用）。"""
    from PIL import Image, ImageDraw
    pages = [("手工页 _spread（图文咬合）", os.path.join(OUT, "_spread", "preview.png")),
             ("全自动 auto（2 栏）", os.path.join(OUT, "preview.png")),
             ("查不到素材 _no_asset", os.path.join(OUT, "_no_asset", "preview.png"))]
    ims = [(t, Image.open(p).convert("RGB")) for t, p in pages]
    h = max(im.height for _, im in ims)
    gap = 24
    width = sum(int(im.width * h / im.height) for _, im in ims) + gap * (len(ims) + 1)
    sheet = Image.new("RGB", (width, h + 56), (238, 238, 238))
    draw = ImageDraw.Draw(sheet)
    x = gap
    for title, im in ims:
        scaled = im.resize((int(im.width * h / im.height), h))
        sheet.paste(scaled, (x, 48))
        _label(draw, (x + 8, 8), title)
        x += scaled.width + gap
    sheet_path = os.path.join(OUT, "_sheet_all.png")
    sheet.save(sheet_path)

    # 两条放大带：手工页与自动页里各挑一处插图，2 倍放大。
    spread = json.load(open(os.path.join(OUT, "_spread", "pagelayout.json"),
                            encoding="utf-8"))
    auto = json.load(open(os.path.join(OUT, "pagelayout.json"), encoding="utf-8"))
    bands = []
    for tag, page, path, which in (
            ("手工页", spread, os.path.join(OUT, "_spread", "preview.png"), -1),
            ("自动页", auto, os.path.join(OUT, "preview.png"), 0)):
        img = json.loads(json.dumps(page["images"][which]))
        dx, dy, dw, dh = img["rect"]
        box = (round((img["x_in"] + dx - 1.0) * 100),
               round((img["y_in"] + dy - 0.6) * 100),
               round((img["x_in"] + dx + dw + 1.0) * 100),
               round((img["y_in"] + dy + dh + 0.6) * 100))
        crop = Image.open(path).convert("RGB").crop(box)
        big = crop.resize((crop.width * 2, crop.height * 2))
        bands.append((f"{tag} {img['name']} · {img['path']}", big))
    zoom_h = max(b.height for _, b in bands)
    zoom = Image.new("RGB", (max(b.width for _, b in bands), zoom_h * 2 + 96),
                     (238, 238, 238))
    zd = ImageDraw.Draw(zoom)
    y = 0
    for title, band in bands:
        zoom.paste(band, (0, y + 48))
        _label(zd, (8, y + 8), title)
        y += zoom_h + 48
    zoom_path = os.path.join(OUT, "_zoom_illustration.png")
    zoom.save(zoom_path)
    return sheet_path, zoom_path


def main():
    os.makedirs(OUT, exist_ok=True)
    auto = _auto_page()
    no_asset = _no_asset_page()
    page, _ = _spread_page()
    sheet, zoom = _contact_sheet()

    def _has_image(result):
        return any(type(x).__name__ == "ImageBlock" for x in result.flow)

    summary = {
        "auto": {
            "columns": 2,
            "preview": auto.outputs.get("preview"),
            "has_illustration": _has_image(auto),
            "matches": [{"dataset": m.dataset_key, "template": m.template,
                         "illustration": m.illustration}
                        for m in auto.matches],
        },
        "no_asset": {
            "preview": no_asset.outputs.get("preview"),
            "has_illustration": _has_image(no_asset),
            "note": "素材检索返回空 → 照排图表，不阻塞",
        },
        "spread": {
            "canvas": [page.width_in, page.height_in],
            "columns": page.column_count,
            "items": [dict(kind=k, name=o.name, x_in=o.x_in, y_in=o.y_in,
                           w_in=o.w_in, h_in=o.h_in,
                           rect=list(o.rect) if k == "image" else None)
                      for k, o in page.items()],
        },
    }
    with open(os.path.join(OUT, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)

    print("auto     ->", auto.outputs.get("preview"),
          "插图", _has_image(auto))
    print("no_asset ->", no_asset.outputs.get("preview"),
          "插图", _has_image(no_asset))
    print("spread   ->", os.path.join(OUT, "_spread", "preview.png"))
    print("总览      ->", sheet)
    print("放大带    ->", zoom)
    for k, o in page.items():
        extra = f" rect={tuple(round(v, 4) for v in o.rect)}" if k == "image" else ""
        print(f"  {k:5s} {o.name[:14]:16s} x={o.x_in:7.4f} y={o.y_in:7.4f} "
              f"w={o.w_in:7.4f} h={o.h_in:6.4f}{extra}")


if __name__ == "__main__":
    main()
