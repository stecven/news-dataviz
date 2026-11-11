# -*- coding: utf-8 -*-
"""S4：给 11 个可检索图标批量打 ``asset_tags``。

**只写 ``asset_tags`` 与 ``assets.status``，不改表结构、不发明词表外的标签。**

打标对象（写死，不靠扫描推断——扫描会把 page_image / placeholder 混进来）：

===========  ====================  ================================
id           url                   为什么打这些
===========  ====================  ================================
16           local:leaf_soft       页脚季节装饰 → 枫叶 / 秋季 / 页脚装饰
17           local:radiator_soft   **比较大小（首选）**：暖气片是取暖本体
18           local:sock_soft       保暖用品主题
19           local:cup_soft        带热气的杯子 → 热水
20           local:thermometer_soft 比较大小（次选）+ 含负值；温度/测量
21           local:snowflake_soft  除湿机区块配图 → 雪花 / 寒冷 / 冬季
22           local:flame_soft      火焰 + 热量
25           local:droplet         湿度
26           local:people          **占比构成（首选）**：人群是构成分析主体
27           local:percent         **占比构成**
28           local:pin             地理位置 / 产地
===========  ====================  ================================

为什么 radiator 优先于 thermometer
----------------------------------
「比较大小」档两张图都能用，但原版信息图里温度计**本身就是区块③的图表**，
再拿温度计图标当配图会和图表撞车（读者分不清哪个是数据、哪个是插图）。
暖气片是取暖电器本体，做「大小比较」栏目的配图更中性。所以：

* ``radiator`` 的 ``比较大小`` 权重 1.0（首选）
* ``thermometer`` 的 ``比较大小`` 权重 0.6（次选，仍是可用素材）
* ``people`` / ``percent`` 的 ``占比构成`` 均为 1.0（两张各有所长，无优先级）

权重只在本轮内自洽：``v_asset_search`` 按 weight 排序，1.0 先出、0.6 后出。
权重**不参与**选型决策（选型看数据形态，不看素材）。

status 迁移
-----------
打标成功且该 icon 至少有一条 tag 的，``assets.status`` 由 ``待登记`` → ``已标注``。
这会让 ``tests/test_step15_register_icons.py`` 里「新行 status 必为待登记」那条
断言过期——S4 同步改为「status ∈ {待登记, 已标注}」，因为那条断言的本意是
「登记脚本不擅自改状态」，不是「状态永远是待登记」。

用法::

    python scripts/tag_assets.py            # 打标（幂等）
    python scripts/tag_assets.py --dry-run  # 只报告将要写什么
    python scripts/tag_assets.py --report   # 只打印当前打标结果
"""
import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "db", "assets.db")

#: ``asset_tags.source`` 有 CHECK 约束，只允许 'manual' / 'model' / 'crawl' ——
#: 不能写 'manual-s4' 之类带批次的字符串（S4 不改表结构，所以复用 'manual'）。
#: 批次的区分交给 ``created_at`` 与脚本文档，不塞进 source。
SOURCE = "manual"

#: ``asset_tags.created_at`` 是 NOT NULL 且没有默认值（DDL 如此，S4 不改表结构），
#: 所以每条插入都要显式给时间戳，格式与 ``scripts/make_placeholder.py`` 一致。
def _now():
    return datetime.now().isoformat(timespec="seconds")

#: id → [(tag, tag_type, weight), ...]
#:
#: 每条 tag 必须先在 ``tag_vocabulary`` 里存在，否则会被 ``insert_tag`` 里的
#: 预检查直接拒掉（不依赖 FK —— ``PRAGMA foreign_keys`` 默认是关的，
#: 靠 FK 兜底等于没兜底）。
TAG_PLAN = {
    16: [  # leaf_soft：页脚那片枫叶
        ("枫叶", "semantic", 1.0),
        ("图标", "appearance", 1.0),
        ("淡化", "appearance", 1.0),
        ("平涂", "appearance", 1.0),
        ("秋季", "season", 1.0),
        ("页脚装饰", "usage", 1.0),
    ],
    17: [  # radiator_soft：「比较大小」首选
        ("暖气片", "semantic", 1.0),
        ("取暖电器", "semantic", 1.0),
        ("比较大小", "chart_semantic", 1.0),
        ("图标", "appearance", 1.0),
        ("淡化", "appearance", 1.0),
        ("平涂", "appearance", 1.0),
        ("soft", "style", 1.0),
        ("冬季", "season", 1.0),
        ("图表插图", "usage", 1.0),
    ],
    18: [  # sock_soft
        ("袜子", "semantic", 1.0),
        ("暖脚套", "semantic", 1.0),
        ("保暖用品", "semantic", 1.0),
        ("图标", "appearance", 1.0),
        ("淡化", "appearance", 1.0),
        ("平涂", "appearance", 1.0),
        ("soft", "style", 1.0),
        ("冬季", "season", 1.0),
        ("图表插图", "usage", 1.0),
    ],
    19: [  # cup_soft：冒热气的杯子 → 热水（用户裁定，不是「饮水」）
        ("热水", "semantic", 1.0),
        ("图标", "appearance", 1.0),
        ("淡化", "appearance", 1.0),
        ("平涂", "appearance", 1.0),
        ("soft", "style", 1.0),
        ("图表插图", "usage", 1.0),
    ],
    20: [  # thermometer_soft：「比较大小」次选 + 含负值
        ("温度计图标", "semantic", 1.0),
        ("温度", "semantic", 1.0),
        ("测量", "semantic", 1.0),
        ("比较大小", "chart_semantic", 0.6),  # 次选，见模块 docstring
        ("含负值", "chart_semantic", 1.0),
        ("图标", "appearance", 1.0),
        ("淡化", "appearance", 1.0),
        ("平涂", "appearance", 1.0),
        ("带刻度", "appearance", 1.0),
        ("soft", "style", 1.0),
        ("图表插图", "usage", 1.0),
    ],
    21: [  # snowflake_soft：除湿机区块的现成配图
        ("雪花", "semantic", 1.0),
        ("寒冷", "semantic", 1.0),
        ("其他", "chart_semantic", 1.0),
        ("图标", "appearance", 1.0),
        ("淡化", "appearance", 1.0),
        ("平涂", "appearance", 1.0),
        ("soft", "style", 1.0),
        ("冬季", "season", 1.0),
        ("图表插图", "usage", 1.0),
    ],
    22: [  # flame_soft：火焰 + 热量（用户裁定，不打「加热」）
        ("火焰", "semantic", 1.0),
        ("热量", "semantic", 1.0),
        ("比较大小", "chart_semantic", 1.0),
        ("其他", "chart_semantic", 1.0),
        ("图标", "appearance", 1.0),
        ("淡化", "appearance", 1.0),
        ("平涂", "appearance", 1.0),
        ("soft", "style", 1.0),
        ("图表插图", "usage", 1.0),
    ],
    25: [  # droplet
        ("湿度", "semantic", 1.0),
        ("其他", "chart_semantic", 1.0),
        ("图标", "appearance", 1.0),
        ("平涂", "appearance", 1.0),
        ("flat", "style", 1.0),
        ("图表插图", "usage", 1.0),
    ],
    26: [  # people：「占比构成」并列首选
        ("人群", "semantic", 1.0),
        ("占比构成", "chart_semantic", 1.0),
        ("比较大小", "chart_semantic", 1.0),
        ("图标", "appearance", 1.0),
        ("平涂", "appearance", 1.0),
        ("flat", "style", 1.0),
        ("图表插图", "usage", 1.0),
    ],
    27: [  # percent
        ("百分比", "semantic", 1.0),
        ("占比构成", "chart_semantic", 1.0),
        ("图标", "appearance", 1.0),
        ("平涂", "appearance", 1.0),
        ("flat", "style", 1.0),
        ("图表插图", "usage", 1.0),
    ],
    28: [  # pin
        ("地理位置", "semantic", 1.0),
        ("产地", "semantic", 1.0),
        ("其他", "chart_semantic", 1.0),
        ("图标", "appearance", 1.0),
        ("平涂", "appearance", 1.0),
        ("flat", "style", 1.0),
        ("图表插图", "usage", 1.0),
    ],
}

#: 只核这 11 个；出现别的 id 就报错，避免误伤 page_image / placeholder。
EXPECTED_IDS = tuple(sorted(TAG_PLAN))
EXPECTED_URLS = {
    16: "local:leaf_soft",
    17: "local:radiator_soft",
    18: "local:sock_soft",
    19: "local:cup_soft",
    20: "local:thermometer_soft",
    21: "local:snowflake_soft",
    22: "local:flame_soft",
    25: "local:droplet",
    26: "local:people",
    27: "local:percent",
    28: "local:pin",
}

STATUS_PENDING = "待登记"
STATUS_TAGGED = "已标注"

#: ``assets`` 的两个缓存列，必须与真源 ``asset_tags`` 保持一致。
#:
#: S1/S2 的设计是「asset_tags 是唯一真源，assets.semantic_tags / assets.asset_tags
#: 只是可空冗余缓存」，并且 ``loop/asset_schema.py::audit`` 有一条
#: ``cache_semantic_mismatch`` 专门抓「只写真源、不更缓存」。所以打标脚本
#: **必须同步回填缓存**，否则 migrate_db.py --audit 会立刻报脏。
#:
#: 回填口径与 ``_CACHE_TRUTH_SEMANTIC`` / ``_CACHE_TRUTH_APPEARANCE`` 完全一致：
#: 按 tag 排序的 JSON 数组，无标签时写 '[]'。
_CACHE_COLUMNS = (
    ("semantic_tags", "semantic"),
    ("asset_tags", "appearance"),
)


def _refresh_cache(con, asset_ids):
    """按真源重算缓存列。返回被改动的 id 列表。"""
    changed = []
    for aid in asset_ids:
        row = con.execute(
            "SELECT semantic_tags, asset_tags FROM assets WHERE id=?",
            (aid,)).fetchone()
        if row is None:
            continue
        new = {}
        for column, tag_type in _CACHE_COLUMNS:
            tags = [r[0] for r in con.execute(
                "SELECT tag FROM asset_tags WHERE asset_id=? AND tag_type=?"
                " ORDER BY tag", (aid, tag_type))]
            # separators 必须写死：sqlite 的 json_group_array 输出无空格
            # （'["a","b"]'），而 json.dumps 默认会写成 '["a", "b"]'，
            # 两者字面不同，缓存校验会因此永远判不一致。
            new[column] = json.dumps(tags, ensure_ascii=False,
                                     separators=(",", ":"))
        if (row["semantic_tags"], row["asset_tags"]) != (
                new["semantic_tags"], new["asset_tags"]):
            con.execute(
                "UPDATE assets SET semantic_tags=?, asset_tags=? WHERE id=?",
                (new["semantic_tags"], new["asset_tags"], aid))
            changed.append(aid)
    return changed


def planned_count():
    """预计标签条数。"""
    return sum(len(v) for v in TAG_PLAN.values())


def _connect(db_path=DB):
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")  # 默认是关的，这里显式打开
    return con


def verify_targets(con):
    """核对 11 个打标对象存在且 url 与预期一致，返回 [(id, url)]。"""
    rows = con.execute(
        "SELECT id, url FROM assets WHERE kind='icon' ORDER BY id").fetchall()
    got = [(r["id"], r["url"]) for r in rows]
    if [i for i, _ in got] != list(EXPECTED_IDS):
        raise SystemExit(
            "打标对象与预期不符：期望 id %s，实际 %s；先列清单再动"
            % (list(EXPECTED_IDS), [i for i, _ in got]))
    for aid, url in got:
        if url != EXPECTED_URLS[aid]:
            raise SystemExit("id %d 的 url 是 %s，期望 %s" % (aid, url, EXPECTED_URLS[aid]))
    return got


def missing_vocabulary(con):
    """返回 TAG_PLAN 里所有不在 tag_vocabulary 的 tag（应为空）。"""
    used = sorted({t for tags in TAG_PLAN.values() for t, _, _ in tags})
    have = {r[0] for r in con.execute("SELECT tag FROM tag_vocabulary")}
    return [t for t in used if t not in have]


def tag_type_drift(con):
    """返回 TAG_PLAN 里 tag_type 与词表不一致的 (tag, plan_type, vocab_type)。"""
    vocab = {r["tag"]: r["tag_type"]
             for r in con.execute("SELECT tag, tag_type FROM tag_vocabulary")}
    drift = []
    for tags in TAG_PLAN.values():
        for tag, ttype, _w in tags:
            if tag in vocab and vocab[tag] != ttype:
                drift.append((tag, ttype, vocab[tag]))
    return sorted(set(drift))


def tag_assets(db_path=DB, dry_run=False):
    """打标。返回统计 dict。"""
    con = _connect(db_path)
    try:
        verify_targets(con)
        bad = missing_vocabulary(con)
        if bad:
            raise SystemExit(
                "以下标签不在 tag_vocabulary 里，先加词条再加标签：%s" % bad)
        drift = tag_type_drift(con)
        if drift:
            raise SystemExit("tag_type 与词表不一致：%s" % drift)

        inserted = 0
        skipped = 0
        retyped = 0
        for aid, tags in TAG_PLAN.items():
            for tag, ttype, weight in tags:
                cur = con.execute(
                    "SELECT tag_type, weight FROM asset_tags WHERE asset_id=?"
                    " AND tag=?", (aid, tag)).fetchone()
                if cur is None:
                    if not dry_run:
                        con.execute(
                            "INSERT INTO asset_tags"
                            " (asset_id, tag, tag_type, weight, source, created_at)"
                            " VALUES (?,?,?,?,?,?)",
                            (aid, tag, ttype, weight, SOURCE, _now()))
                    inserted += 1
                elif cur["tag_type"] != ttype or abs(cur["weight"] - weight) > 1e-9:
                    if not dry_run:
                        con.execute(
                            "UPDATE asset_tags SET tag_type=?, weight=?, source=?"
                            " WHERE asset_id=? AND tag=?",
                            (ttype, weight, SOURCE, aid, tag))
                    retyped += 1
                else:
                    skipped += 1

            # 该 icon 至少有一条 tag 才翻 status
            if not dry_run:
                con.execute(
                    "UPDATE assets SET status=? WHERE id=?"
                    " AND EXISTS (SELECT 1 FROM asset_tags WHERE asset_id=?)",
                    (STATUS_TAGGED, aid, aid))
        cache_changed = [] if dry_run else _refresh_cache(con, EXPECTED_IDS)
        if dry_run:
            con.rollback()
        else:
            con.commit()
        return {"inserted": inserted, "skipped": skipped,
                "retyped": retyped, "planned": planned_count(),
                "cache_changed": cache_changed, "dry_run": dry_run}
    finally:
        con.close()


def report(db_path=DB):
    """打印当前 11 个 icon 的打标结果（只读）。"""
    con = _connect(db_path)
    con.execute("PRAGMA query_only = ON")
    try:
        rows = con.execute(
            "SELECT a.id, a.url, a.status, t.tag, t.tag_type, t.weight"
            " FROM assets a JOIN asset_tags t ON t.asset_id = a.id"
            " WHERE a.kind='icon' ORDER BY a.id, t.tag_type, t.tag").fetchall()
        out = {}
        for r in rows:
            out.setdefault((r["id"], r["url"], r["status"]), []).append(
                (r["tag"], r["tag_type"], r["weight"]))
        for (aid, url, status), tags in sorted(out.items()):
            print("id=%-3s %-22s status=%-5s %2d 条" % (aid, url, status, len(tags)))
            for tag, ttype, weight in tags:
                print("        %-8s %-14s w=%.2f" % (tag, ttype, weight))
        print("\n合计 %d 条 / %d 个 icon" % (sum(len(v) for v in out.values()), len(out)))
        return out
    finally:
        con.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description="S4：给 11 个 icon 批量打 asset_tags")
    ap.add_argument("--dry-run", action="store_true", help="只报告将要写什么")
    ap.add_argument("--report", action="store_true", help="只打印当前打标结果")
    args = ap.parse_args(argv)
    if args.report:
        report()
        return 0
    stats = tag_assets(dry_run=args.dry_run)
    print("计划 %(planned)d 条；新增 %(inserted)d / 已存在 %(skipped)d"
          " / 权重或类型更正 %(retyped)d" % stats)
    if stats["cache_changed"]:
        print("同步缓存列的 asset id：%s" % stats["cache_changed"])
    if args.dry_run:
        print("（dry-run：未写入）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
