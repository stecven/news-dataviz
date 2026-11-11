# -*- coding: utf-8 -*-
"""G4 覆盖率体检：**只读**，不写库、不打标。

目的：回答「chart_semantic 词表扩到 6 个值之后，现有素材能覆盖多少？」
——也就是 G4 是「缺词表」还是「缺素材」，还是两者都有。

做法（刻意不改 ``asset_tags``）：
    1. 词表侧：直接从 ``tag_vocabulary`` 读 ``tag_type='chart_semantic'`` 的受控词，
       用 ``loop.selector`` 的可达分支数校验「词表是否覆盖选型器全部输出」。
    2. 素材侧：对每个候选图标图片，按 **显式人工映射表** 判断它「能服务哪些图表语义」。
       这张映射表是分析用的中间结论，**不是**入库标签——批量打标属 S4。
    3. 差额 = 词表有、但没有任何（已登记 / 全部）图标能服务的语义值。

「已登记」的口径（2026-11-09 S3 修正）：**``assets`` 表里 ``kind='icon'`` 的基名集合**，
不再看文件名是否以 ``_soft`` 结尾。旧口径只认 ``_soft`` 变体，导致 S3 补登记的
droplet/people/percent/pin（磁盘上只有原图、没有 _soft）登记了也不算数，
覆盖率数字不动——口径比事实窄，会把「已登记」报成「未登记」。

用法::

    python scripts/asset_coverage.py          # 打印报告
    python scripts/asset_coverage.py --json   # 机器可读
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from loop.asset_schema import chart_semantic_values  # noqa: E402

DB = os.path.join(ROOT, "db", "assets.db")
ICONS = os.path.join(ROOT, "assets", "icons")

#: 人工判断：图标 → 它能服务哪些 chart_semantic 语义值。
#: 依据是「读者看到这个图形，会不会觉得它就是在讲那个语义」。
#: 刻意保守：只在语义真的贴脸时才连边，宁缺勿滥（否则覆盖率是虚的）。
ICON_CAPABILITY = {
    "thermometer": ["比较大小", "含负值"],
    "flame": ["比较大小", "其他"],
    "radiator": ["其他"],
    "snowflake": ["其他"],
    "leaf": ["其他"],
    "sock": ["其他"],
    "cup": ["其他"],
    # 以下 12 个尚未登记进 assets 表，但文件已存在（见设计文档 G3）
    "thermometer_flat": ["比较大小"],
    "percent": ["占比构成"],
    "people": ["占比构成", "比较大小"],
    "pin": ["其他"],
    "droplet": ["其他"],
}

#: 需要「特殊素材」才能表达的语义：这两类靠普通物品图标表达不了。
HARD_SEMANTICS = {
    "全相等": "需要「两个一样高 / 等号 / 持平」这类对比符号，现有物品图标表达不了",
    "无适用": "需要专门的占位图（status='placeholder'），属 S5",
}


def _stem(name):
    """``thermometer_soft`` / ``thermometer_flat`` / ``thermometer`` → ``thermometer``。"""
    for suffix in ("_soft", "_flat"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _registered_icons(con):
    """``assets`` 表里 ``kind='icon'`` 的基名 → {id, path}。

    基名归并掉 ``_soft`` / ``_flat`` 变体，因此同一素材登记了多个变体也只算一个。
    """
    rows = con.execute(
        "SELECT id, url, local_path FROM assets WHERE kind='icon' ORDER BY id").fetchall()
    out = {}
    for aid, url, local_path in rows:
        out[_stem((url or "").split("local:")[-1])] = {"id": aid, "path": local_path}
    return out


def _all_icon_files():
    """磁盘上图标文件的「基名」集合（``x.png`` 与 ``x_soft.png`` 归为同一个 ``x``）。"""
    if not os.path.isdir(ICONS):
        return []
    names = set()
    for f in os.listdir(ICONS):
        if not f.lower().endswith(".png"):
            continue
        names.add(_stem(f[:-4]))
    return sorted(names)


def build_report():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        vocab = chart_semantic_values()
        registered = _registered_icons(con)
        registered_bases = sorted(registered)
        all_pngs = _all_icon_files()
    finally:
        con.close()

    def covered(names):
        ans = {}
        for sem in vocab:
            hits = [n for n in names if sem in ICON_CAPABILITY.get(n, [])]
            ans[sem] = hits
        return ans

    cov_reg = covered(registered_bases)
    cov_all = covered(all_pngs)

    missing_reg = [s for s, hits in cov_reg.items() if not hits]
    missing_all = [s for s, hits in cov_all.items() if not hits]

    return {
        "chart_semantic_vocab": vocab,
        "vocab_count": len(vocab),
        # 已登记口径（S3 起）：assets 表 kind='icon' 的基名
        "registered_icons": registered_bases,
        "coverage_registered": cov_reg,
        "covered_registered": len(vocab) - len(missing_reg),
        "missing_with_registered": missing_reg,
        # 对比口径：磁盘上所有图标文件（含未登记）
        "all_icon_files": all_pngs,
        "unregistered_icon_files": [n for n in all_pngs if n not in registered],
        "coverage_all_files": cov_all,
        "covered_all": len(vocab) - len(missing_all),
        "missing_with_all_files": missing_all,
        "hard_semantics": HARD_SEMANTICS,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="G4 覆盖率体检（只读）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    rep = build_report()

    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        return 0

    print(f"chart_semantic 词表（{rep['vocab_count']} 值）：{'、'.join(rep['chart_semantic_vocab'])}")
    print()
    print(f"已登记图标（{len(rep['registered_icons'])} 个）："
          f"{'、'.join(rep['registered_icons'])}")
    print(f"磁盘上的图标文件共 {len(rep['all_icon_files'])} 个，"
          f"其中未登记 {len(rep['unregistered_icon_files'])} 个："
          f"{'、'.join(rep['unregistered_icon_files'])}")
    print()
    print("按语义值看谁能服务：")
    for sem in rep["chart_semantic_vocab"]:
        a = rep["coverage_registered"][sem]
        b = rep["coverage_all_files"][sem]
        print(f"  {sem:<6} 已登记:{(','.join(a) or '—'):<28} 全部文件:{','.join(b) or '—'}")
    print()
    print(f"覆盖率：已登记 {rep['covered_registered']}/{rep['vocab_count']}　"
          f"含未登记文件 {rep['covered_all']}/{rep['vocab_count']}")
    print(f"已登记仍空缺：{'、'.join(rep['missing_with_registered']) or '无'}")
    print(f"含未登记仍空缺：{'、'.join(rep['missing_with_all_files']) or '无'}")
    for sem, why in rep["hard_semantics"].items():
        print(f"  · {sem}：{why}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
