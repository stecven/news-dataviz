"""三组回归出图（m04549 统一色板 + 字号表的验收用）。

跑 thermometer / semicircle / fallback 三条链路，各出一份
pagespec.json + preview.png + loop1.pptx 到 ``out/demo/palette/<组名>/``，
并拼一张总览 ``_sheet_all.png`` 供目视对比配色与字号层级。

只读数据、只写 out/ 下产物；不碰 db、不改任何 loop/ 模块的行为。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image

from loop.data_source import load_points
from loop.build_loop import DB_PATH
from loop.preview import render_preview
from loop.selector import SEMANTIC_COMPARE, SEMANTIC_SHARE
from loop.pipeline import run_selected

OUT_ROOT = os.path.join("out", "demo", "palette")


def _sheet(rows, out_path):
    tiles = []
    for name, path in rows:
        if os.path.exists(path):
            tiles.append((name, Image.open(path).convert("RGB")))
    if not tiles:
        return None
    w, h = tiles[0][1].size
    canvas = Image.new("RGB", (w, h * len(tiles) + 8 * (len(tiles) - 1)), "white")
    for i, (_name, im) in enumerate(tiles):
        canvas.paste(im.resize((w, h)), (0, i * (h + 8)))
    canvas.save(out_path, "PNG")
    return out_path


def main():
    summary = []

    # ① 温度计：环比增速比较（37 元素）
    title, rows = load_points(DB_PATH, chart_key="heat_ratio_top5")
    res = run_selected(chart_key="heat_ratio_top5", semantic=SEMANTIC_COMPARE,
                       chart_title=title, out_root=OUT_ROOT,
                       group_name="thermometer")
    summary.append({"group": "thermometer", "status": res["status"],
                    "template": res["selected_template"],
                    "preview": res["preview"], "pptx": res["pptx"]})

    # ② 半圆图：年龄构成占比（13 元素）
    title2, _rows2 = load_points(DB_PATH, chart_key="heat_age")
    res2 = run_selected(chart_key="heat_age", semantic=SEMANTIC_SHARE,
                        chart_title=title2, out_root=OUT_ROOT,
                        group_name="semicircle")
    summary.append({"group": "semicircle", "status": res2["status"],
                    "template": res2["selected_template"],
                    "preview": res2["preview"], "pptx": res2["pptx"]})

    # ③ 兜底：6 项占比 → 无适用图形 → 占位图
    # values 只接受「纯数值列表」，pipeline 内部自己补 seq/label/unit。
    res3 = run_selected(values=[10, 3, 2, 2, 2, 1], semantic=SEMANTIC_SHARE,
                        chart_title="六项占比（无适用图形）",
                        out_root=OUT_ROOT, group_name="fallback")
    summary.append({"group": "fallback", "status": res3["status"],
                    "template": res3["selected_template"],
                    "preview": res3["preview"], "pptx": res3["pptx"]})

    sheet = os.path.join(OUT_ROOT, "_sheet_all.png")
    _sheet([(s["group"], s["preview"]) for s in summary], sheet)

    with open(os.path.join(OUT_ROOT, "summary.json"), "w",
              encoding="utf-8", newline="\n") as fh:
        json.dump({"groups": summary, "sheet": sheet}, fh,
                  ensure_ascii=False, indent=2)

    for s in summary:
        print(f'{s["group"]:12s} status={s["status"]:14s} '
              f'template={str(s["template"]):12s} preview={s["preview"]}')
    print("sheet:", sheet)


if __name__ == "__main__":
    main()
