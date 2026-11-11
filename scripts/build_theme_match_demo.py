"""S6 桥接 0.1 演示（用户 m06731）：按**文本主题**配插图。

出两页，都在 ``out/demo/theme_match/``：

* ``theme/``：稿子里两段正文都写了「取暖电器」。第一段按主题抽到「取暖电器」→
  素材库 `assets/icons/radiator_soft.png`（暖气片）；第二段同样抽到「取暖电器」，
  但那张图已被这一页用过，于是**降级**到图表语义「占比构成」→ `people.png`
  —— 正是用户 m06739 裁定的那条路径。两张图 ``asset_id`` 不同。
* ``_no_theme/``：稿子只提图表语义、一个主题词都不含（讲的是「加热电器」，
  不是主题词表里的词）→ 每段 ``theme`` 都是 ``None``，插图回落到按
  ``chart_semantic`` 选。用来证明降级路径不是摆设。

对照物：素材库里的真实图标（不是画的），所以肉眼能看出暖气片与人形的区别。

产物：``preview.png`` / ``page.pptx`` / ``pagelayout.json`` / ``flow.json`` /
``summary.json``，外加 ``_sheet_all.png`` 与 ``_zoom_illustration.png``。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loop.compose import compose_page                       # noqa: E402
from loop.data_source import DB_PATH                        # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out", "demo", "theme_match")

#: 主稿：两段正文都提「取暖电器」，第二段还提了「年龄段」（=人群 的别名）。
#: 两段都抽到「取暖电器」是因为它更长（4 字 > 3 字），见 ``extract_theme``。
COPY = """取暖电器换季热销

随着气温下降，取暖电器进入销售旺季，线上渠道尤其明显。

分品类看，取暖电器各细分品类的成交额环比增速差异明显：欧式快热炉、踢脚线取暖器等品类领跑。

分年龄段看，各年龄段消费者对取暖电器的偏好不同，成交额占比也各不相同，中年群体是主力。
"""

#: 反例：只提图表语义，一个主题词都没有（「加热电器」不在主题词表里）。
NO_THEME = """加热电器品类增速一览

随着季节变化，加热电器市场出现波动，线上渠道尤其明显。

分品类看，加热电器各细分品类的成交额环比增速情况。
"""


def _page(copy: str, out_dir: str):
    return compose_page(copy, out_dir, width_in=10.0, height_in=15.0,
                        margin_in=0.4, gutter_in=0.3, column_count=2)


def _report(result) -> dict:
    """每段文字的主题与配图结果 —— 汇报里那张表的机器可读版本。"""
    images = [it for it in result.flow_summary() if it["kind"] == "image"]
    by_name = {it["name"]: it for it in images}
    rows = []
    for match in result.matches:
        picked = by_name.get(match.illustration)
        rows.append({"paragraph": match.paragraph,
                     "dataset": match.dataset_key,
                     "template": match.template,
                     "theme": match.theme,
                     "illustration": match.illustration,
                     "asset_id": picked["asset_id"] if picked else None,
                     "path": picked["path"] if picked else None,
                     "matched_by": picked["matched_by"] if picked else None})
    return {"canvas": [10.0, 15.0], "columns": 2,
            "themes": result.themes, "matches": rows,
            "image_count": len(images),
            "preview": result.outputs.get("preview")}


def _label(draw, xy, text):
    from PIL import ImageFont
    font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 26)
    draw.rectangle([xy[0] - 6, xy[1] - 4, xy[0] + 26 * len(text), xy[1] + 34],
                   fill=(255, 255, 255))
    draw.text(xy, text, fill=(40, 40, 40), font=font)


def _contact_sheet(a: str, b: str):
    """两页并排 + 两条插图放大带（暖气片 vs 人形，肉眼一看就知道换没换）。"""
    from PIL import Image, ImageDraw
    pages = [("theme/ 主题命中 + 降级", a), ("_no_theme/ 全部降级", b)]
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

    # 两条带：主题命中的暖气片（第一张）与降级后的人形（第二张），2 倍放大。
    page = json.load(open(os.path.join(OUT, "pagelayout.json"), encoding="utf-8"))
    bands = []
    for which, tag in ((0, "主题命中"), (1, "被占用后降级")):
        img = page["images"][which]
        dx, dy, dw, dh = img["rect"]
        box = (round((img["x_in"] + dx - 1.0) * 100),
               round((img["y_in"] + dy - 0.6) * 100),
               round((img["x_in"] + dx + dw + 1.0) * 100),
               round((img["y_in"] + dy + dh + 0.6) * 100))
        crop = Image.open(a).convert("RGB").crop(box)
        bands.append((f"{tag} · {img['name']} · {img['path']}",
                      crop.resize((crop.width * 2, crop.height * 2))))
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
    theme = _page(COPY, OUT)
    no_theme = _page(NO_THEME, os.path.join(OUT, "_no_theme"))
    summary = {"theme": _report(theme), "no_theme": _report(no_theme)}
    with open(os.path.join(OUT, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    sheet, zoom = _contact_sheet(summary["theme"]["preview"],
                                 summary["no_theme"]["preview"])

    for key, block in summary.items():
        print(f"[{key}] preview={block['preview']} 插图 {block['image_count']} 张")
        for row in block["matches"]:
            print(f"   theme={str(row['theme']):8s} basis={str(row['matched_by']):15s}"
                  f" asset={row['asset_id']} {row['path']}  <- {row['dataset']}")
    print("总览   ->", sheet)
    print("放大带 ->", zoom)


if __name__ == "__main__":
    main()
