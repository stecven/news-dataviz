# -*- coding: utf-8 -*-
"""S5：生成通用占位图并登记进素材库。

用途单一——选型器返回 ``no_applicable`` 时，版面上要有一张「这里本该有图但没有」
的中性图，而不是留白或崩溃。

两张图，都刻意做成中性灰、无品牌色，避免和真素材抢视觉：

* ``placeholder_todo``  —— 虚线方框 + 三个点，表示「待补充」
* ``placeholder_chart`` —— 通用图表符号（坐标轴 + 三根柱），表示「此处缺一张图」

登记规则（与 S1/S2 的 schema 对齐，不改 schema）：

* ``kind = 'placeholder'``（不是 ``page_image``，也不是 ``icon``——不想让它
  出现在图标覆盖率统计里）
* ``status = 'placeholder'``，这是 P1 的第二道闸：``v_searchable_assets`` 会把
  ``status='placeholder'`` 排除掉，所以占位图**不会**污染「比较大小」这类正常检索
* 只打一个标签 ``fallback_placeholder``（``tag_type='usage'``）。
  **不打 chart_semantic**——占位图不是「适合配某类图」，它本身是「没有图」的标记；
  chart_semantic 那一侧留给真素材（用户 2026-11-09 裁定）。
* 两个缓存列 ``semantic_tags`` / ``asset_tags`` 保持 NULL：不打 semantic /
  appearance 标签时，真源里对应集合为空，NULL 与之一致，audit 不报错。

用法::

占位图刻意放在 ``assets/placeholders/`` 而不是 ``assets/icons/``——
``scripts/asset_coverage.py`` 会扫 ``assets/icons/`` 统计图标覆盖率，把占位图混进
去会污染「未登记图标」的口径。

用法::

    python scripts/make_placeholder.py            # 生成图片 + 登记（幂等）
    python scripts/make_placeholder.py --dry-run  # 只看会做什么
"""
import os
import sqlite3
import sys
from datetime import datetime, timezone

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLACEHOLDER_DIR = os.path.join(ROOT, "assets", "placeholders")
DB = os.path.join(ROOT, "db", "assets.db")

S = 4    # 超采样倍数，与 make_icons.py 一致，边缘不毛
W = 400  # 输出逻辑尺寸

# 占位图的三档中性灰取自色板（m04549：颜色单一来源）。这三个值原本就是
# 手写死在这里的，与色板的 neutral_strong / neutral_mid / neutral_light 逐位
# 相同——所以改成派生之后图片字节完全不变（见台账的 sha 复核）。
from loop.palette import color as _palette_color


def _rgb(role):
    h = _palette_color(role)
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)


GREY_DARK = _rgb("placeholder_stroke")
GREY_MID = _rgb("placeholder_mid")
GREY_LIGHT = _rgb("placeholder_light")

#: (文件名基名, 绘制函数名, 说明) —— 顺序稳定，便于测试断言
PLACEHOLDERS = (
    ("placeholder_todo", "todo", "尚未支持该图表语义时的占位（通用「待补充」）"),
    ("placeholder_chart", "chart", "通用图表符号占位（此处缺一张图）"),
)


def _canvas():
    return Image.new("RGBA", (W * S, W * S), (0, 0, 0, 0))


def _draw_todo():
    """虚线方框 + 三个点：一眼看出「这里待补充」。"""
    im = _canvas()
    d = ImageDraw.Draw(im)
    x0, y0, x1, y1 = 60, 60, W - 60, W - 60
    dash, gap = 26, 18
    # 四条虚线边（不追求圆角，方框更中性）
    for x in range(x0, x1, dash + gap):
        d.line([x * S, y0 * S, min(x + dash, x1) * S, y0 * S], fill=GREY_MID, width=8 * S)
        d.line([x * S, y1 * S, min(x + dash, x1) * S, y1 * S], fill=GREY_MID, width=8 * S)
    for y in range(y0, y1, dash + gap):
        d.line([x0 * S, y * S, x0 * S, min(y + dash, y1) * S], fill=GREY_MID, width=8 * S)
        d.line([x1 * S, y * S, x1 * S, min(y + dash, y1) * S], fill=GREY_MID, width=8 * S)
    # 三个点：中间大、两侧小，读作「…」
    cy = W // 2
    for cx, r, col in ((W // 2 - 70, 14, GREY_LIGHT), (W // 2, 22, GREY_DARK),
                       (W // 2 + 70, 14, GREY_LIGHT)):
        d.ellipse([(cx - r) * S, (cy - r) * S, (cx + r) * S, (cy + r) * S], fill=col)
    return im.resize((W, W), Image.LANCZOS), None


def _draw_chart():
    """通用图表符号：坐标轴 + 三根高低不同的柱。"""
    im = _canvas()
    d = ImageDraw.Draw(im)
    left, bottom, right, top = 72, W - 78, W - 72, 74
    d.line([left * S, top * S, left * S, bottom * S], fill=GREY_DARK, width=8 * S)
    d.line([left * S, bottom * S, right * S, bottom * S], fill=GREY_DARK, width=8 * S)
    bars = ((96, 120, GREY_MID), (176, 190, GREY_DARK), (256, 148, GREY_LIGHT))
    for bx, h, col in bars:
        d.rectangle([bx * S, (bottom - h) * S, (bx + 46) * S, bottom * S], fill=col)
    return im.resize((W, W), Image.LANCZOS), None


_DRAWERS = {"todo": _draw_todo, "chart": _draw_chart}


def image_paths(icons_dir=PLACEHOLDER_DIR):
    """返回 ``[(基名, 绝对路径, 说明)]``，不落盘。"""
    return [(base, os.path.join(icons_dir, base + ".png"), note)
            for base, _fn, note in PLACEHOLDERS]


def build_images(icons_dir=PLACEHOLDER_DIR, dry_run=False):
    """生成两张占位图，返回写出的路径列表。"""
    if not dry_run:
        os.makedirs(icons_dir, exist_ok=True)
    out = []
    for base, fn_name, _note in PLACEHOLDERS:
        path = os.path.join(icons_dir, base + ".png")
        if not dry_run:
            im, _ = _DRAWERS[fn_name]()
            im.save(path)
        out.append(path)
    return out


def seed(db_path=DB, icons_dir=PLACEHOLDER_DIR, dry_run=False):
    """登记占位图（assets 行 + asset_tags 标签）。幂等：重复跑不改行数。"""
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")
    con.row_factory = sqlite3.Row
    added_assets, added_tags = 0, 0
    try:
        page_id = con.execute(
            "SELECT id FROM pages ORDER BY id DESC LIMIT 1").fetchone()
        page_id = page_id[0] if page_id else None
        for base, path, note in image_paths(icons_dir):
            url = "local:" + base
            rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
            row = con.execute("SELECT id FROM assets WHERE url = ?", (url,)).fetchone()
            size = os.path.getsize(path) if os.path.exists(path) else None
            if row is None:
                if not dry_run:
                    con.execute(
                        "INSERT INTO assets(page_id, kind, url, local_path, sha256,"
                        " bytes, note, style_token, palette, alpha, width, height,"
                        " license, status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (page_id, "placeholder", url, rel, "", size,
                         "S5 占位图：" + note, "flat", "neutral_grey", 1.0,
                         W, W, "self-drawn (PIL)", "placeholder"))
                added_assets += 1
            asset_id = (row["id"] if row is not None else
                        con.execute("SELECT id FROM assets WHERE url = ?",
                                    (url,)).fetchone())
            asset_id = asset_id[0] if isinstance(asset_id, sqlite3.Row) else asset_id
            if asset_id is None:      # dry_run 且未插入
                continue
            if row is not None:
                # 自愈：图片挪过目录、或库里路径与磁盘不一致时纠正（幂等）
                old = con.execute("SELECT local_path FROM assets WHERE id = ?",
                                  (asset_id,)).fetchone()[0]
                if old != rel and not dry_run:
                    con.execute("UPDATE assets SET local_path = ? WHERE id = ?",
                                (rel, asset_id))
            has = con.execute(
                "SELECT 1 FROM asset_tags WHERE asset_id = ? AND tag = ?",
                (asset_id, "fallback_placeholder")).fetchone()
            if has is None:
                if not dry_run:
                    con.execute(
                        "INSERT INTO asset_tags(asset_id, tag, tag_type, weight,"
                        " source, created_at) VALUES(?,?,?,?,?,?)",
                        (asset_id, "fallback_placeholder", "usage", 1.0,
                         "manual", now))
                added_tags += 1
        if not dry_run:
            con.commit()
    finally:
        con.close()
    return {"added_assets": added_assets, "added_tags": added_tags}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    dry = "--dry-run" in argv
    paths = build_images(dry_run=dry)
    for p in paths:
        print(("[dry] " if dry else "") + "占位图 " + os.path.relpath(p, ROOT))
    stats = seed(dry_run=dry)
    print((" [dry]" if dry else "") + f" 新增 assets {stats['added_assets']} 行 / "
          f"asset_tags {stats['added_tags']} 行")
    if dry:
        print("（dry-run：未写入任何文件与数据库）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
