# -*- coding: utf-8 -*-
"""S3：把 ``assets/icons/`` 下已存在但未登记的图标补登进 ``assets`` 表。

**只写 assets 表，不写 asset_tags**（批量打标是 S4）。

幂等策略（三层判断，缺一不可）：

1. ``url`` 已存在 → 整行跳过，**不覆盖**任何非空字段；
2. 行存在但某字段为空 → 只补该字段（``_fill_blanks``）；
3. 文件在磁盘上、库里没有 → 插入新行。

字段填法（与 S1/S2 的 schema、以及既有 7 个 icon 行的既有取值保持一致）：

* ``kind='icon'``
* ``status='待登记'`` —— 沿用既有 icon 行的取值。**注意**：这个词的本意是
  「素材已入表、语义标签还没打」，不是「还没进表」；S4 打标后应转为
  ``已标注``。这里不擅自改既有 7 行的状态，避免把「没打标」和「已打标」混为一谈。
* ``style_token='flat'``
* ``palette=NULL`` —— 现有 icon 全为 NULL，且没有色板词表；不自己发明取值
  （占位图的 ``neutral_grey`` 是 S5 为占位图单独定义的，不通用）。
* ``width`` / ``height`` / ``alpha`` 按文件实际值填（既有 icon 行这三列是 NULL，
  属于 S1/S2 只加列未回填；新行直接填对，不算破坏约定）。
* ``license=NULL`` —— 与既有 icon 行一致。
* 一律不打 ``asset_tags``。

用法::

    python scripts/register_icons.py            # 登记（幂等）
    python scripts/register_icons.py --dry-run  # 只报告
    python scripts/register_icons.py --list     # 只列清单，不写
"""
import argparse
import os
import sqlite3

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICONS = os.path.join(ROOT, "assets", "icons")
DB = os.path.join(ROOT, "db", "assets.db")

#: 本轮要登记的基名（S3 范围：磁盘上有文件、assets 表里没有的 4 个）
S3_BASES = ("droplet", "people", "percent", "pin")

#: 这些后缀的文件与基名是同一个素材的不同变体，登记时只登一次
VARIANT_SUFFIXES = ("_soft", "_flat")


def base_of(filename):
    """``percent.png`` / ``percent_soft.png`` → ``percent``。"""
    stem = filename[:-4] if filename.lower().endswith(".png") else filename
    for suf in VARIANT_SUFFIXES:
        if stem.endswith(suf):
            return stem[: -len(suf)]
    return stem


def scan(icons_dir=ICONS):
    """扫描目录，返回 ``[(基名, [文件名...])]``，按基名排序。"""
    found = {}
    if not os.path.isdir(icons_dir):
        return []
    for f in sorted(os.listdir(icons_dir)):
        if not f.lower().endswith(".png"):
            continue
        found.setdefault(base_of(f), []).append(f)
    return sorted(found.items())


def _registered_bases(con):
    rows = con.execute("SELECT url FROM assets WHERE kind='icon'").fetchall()
    return {base_of((u or "").split("local:")[-1]) for (u,) in rows}


def _image_facts(path):
    with Image.open(path) as im:
        w, h = im.size
        rgba = im.convert("RGBA")
        alphas = []
        for y in range(0, rgba.height, 2):
            for x in range(0, rgba.width, 2):
                a = rgba.getpixel((x, y))[3]
                if a > 0:
                    alphas.append(a)
    peak = max(alphas) if alphas else 0
    return {"width": w, "height": h, "alpha": round(peak / 255.0, 3)}


def _fill_blanks(con, asset_id, facts, dry_run):
    """只补空字段，非空不覆盖。返回补了哪些列。"""
    row = con.execute("SELECT width, height, alpha FROM assets WHERE id=?",
                      (asset_id,)).fetchone()
    filled = []
    for col, val in zip(("width", "height", "alpha"),
                        (facts["width"], facts["height"], facts["alpha"])):
        if row[("width", "height", "alpha").index(col)] is None:
            filled.append(col)
            if not dry_run:
                con.execute("UPDATE assets SET %s=? WHERE id=?" % col, (val, asset_id))
    return filled


def register(db_path=DB, icons_dir=ICONS, bases=S3_BASES, dry_run=False):
    """登记指定基名。返回 ``{inserted, skipped, filled}`` 三个明细列表。"""
    inserted, skipped, filled = [], [], []
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")
    try:
        page_id = con.execute(
            "SELECT id FROM pages ORDER BY id DESC LIMIT 1").fetchone()
        page_id = page_id[0] if page_id else None
        already = _registered_bases(con)
        for base in bases:
            variants = [v for b, vs in scan(icons_dir) if b == base for v in vs]
            if not variants:
                skipped.append((base, "磁盘上没有文件"))
                continue
            # 优先登记原图（无后缀的那个），没有才退回第一个变体
            primary = base + ".png" if (base + ".png") in variants else variants[0]
            # url 约定与既有 7 行一致：去掉 .png 的完整文件名（含 _soft/_flat 后缀）
            url = "local:" + primary[:-4]
            if base in already:
                row = con.execute("SELECT id FROM assets WHERE url=?",
                                  (url,)).fetchone()
                if row is not None:
                    f = _fill_blanks(con, row[0],
                                     _image_facts(os.path.join(icons_dir, primary)),
                                     dry_run)
                    skipped.append((base, "已登记（id=%d）%s" % (
                        row[0], "，补空列 " + "/".join(f) if f else "")))
                    if f:
                        filled.append((base, f))
                else:
                    skipped.append((base, "已登记但 url 不匹配"))
                continue
            facts = _image_facts(os.path.join(icons_dir, primary))
            rel = os.path.relpath(os.path.join(icons_dir, primary),
                                  ROOT).replace(os.sep, "/")
            note = "S3 补登记：%s（%d×%d）" % (primary, facts["width"], facts["height"])
            if not dry_run:
                con.execute(
                    "INSERT INTO assets(page_id, kind, url, local_path, sha256,"
                    " bytes, note, style_token, palette, alpha, width, height,"
                    " license, status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (page_id, "icon", url, rel, "",
                     os.path.getsize(os.path.join(icons_dir, primary)),
                     note, "flat", None, facts["alpha"], facts["width"],
                     facts["height"], None, "待登记"))
            inserted.append((base, primary, facts))
        if not dry_run:
            con.commit()
    finally:
        con.close()
    return {"inserted": inserted, "skipped": skipped, "filled": filled}


def _print_scan(icons_dir=ICONS):
    print("文件扫描（assets/icons/）：")
    for base, files in scan(icons_dir):
        for f in files:
            with Image.open(os.path.join(icons_dir, f)) as im:
                print("  %-24s %s %-4s %6d B" % (
                    f, "%dx%d" % im.size, im.mode,
                    os.path.getsize(os.path.join(icons_dir, f))))


def main(argv=None):
    ap = argparse.ArgumentParser(description="S3 图标补登记（只写 assets 表）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--list", action="store_true", help="只列清单不写库")
    ap.add_argument("--db", default=DB)
    args = ap.parse_args(argv)

    _print_scan()
    if args.list:
        con = sqlite3.connect("file:%s?mode=ro" % args.db.replace("\\", "/"),
                              uri=True)
        try:
            reg = _registered_bases(con)
        finally:
            con.close()
        print("\n登记状态：")
        for base, _files in scan():
            print("  %-16s %s" % (base, "已登记" if base in reg else "未登记"))
        return 0

    res = register(db_path=args.db, dry_run=args.dry_run)
    pre = "[dry] " if args.dry_run else ""
    for base, primary, facts in res["inserted"]:
        print("%s新增 %-10s → %s (%dx%d, alpha=%s)" % (
            pre, base, primary, facts["width"], facts["height"], facts["alpha"]))
    for base, why in res["skipped"]:
        print("%s跳过 %-10s %s" % (pre, base, why))
    print("%s合计：新增 %d / 跳过 %d" % (pre, len(res["inserted"]),
                                        len(res["skipped"])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
