# -*- coding: utf-8 -*-
"""素材库语义层迁移（第五层 S1/S2）。**幂等**：重复执行不改变数据库字节。

用法::

    python scripts/migrate_db.py --db db/assets.db          # 执行迁移
    python scripts/migrate_db.py --db db/assets.db --dry-run # 只报告将要做什么
    python scripts/migrate_db.py --audit                     # 只跑体检（不改库）

做什么（全部来自 ``loop/asset_schema.py`` 的常量）：

1. 建 ``tag_vocabulary`` / ``asset_tags`` / ``asset_usage`` 三张表 + 索引；
2. 给 ``assets`` 逐列 ADD COLUMN（靠 ``PRAGMA table_info`` 判重，已有列跳过）；
3. 灌 52 条词表种子（``INSERT ... ON CONFLICT(tag) DO UPDATE``）；
4. 建 P1 硬规则的视图 ``v_searchable_assets`` / ``v_asset_search``
   与触发器 ``trg_page_image_no_chart_semantic``；
5. 写 ``schema_migrations`` 版本标记。

**不写任何 ``asset_tags`` 数据**（批量打标不在本轮范围），所以 ``assets``
新增的两列缓存仍是 NULL，与真源（空集）一致，体检返回 0 行。

为什么要用脚本而不是手改 db 文件：可复现、可 review、可回滚（先 ``cp`` 备份）、
幂等（可在 CI 与每台机器上重复跑）。
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from loop.asset_schema import (  # noqa: E402
    ASSETS_NEW_COLUMNS,
    DDL_ASSET_TAGS,
    DDL_ASSET_USAGE,
    DDL_INDEXES,
    DDL_TAG_VOCABULARY,
    DDL_TRIGGER_PAGE_IMAGE_NO_CHART_SEMANTIC,
    DDL_VIEW_FALLBACK,
    DDL_VIEW_SEARCHABLE,
    DDL_VIEW_SEARCH,
    audit,
    vocabulary_rows,
)

DEFAULT_DB = os.path.join(ROOT, "db", "assets.db")

MIGRATION_ID = "2026-11-09-asset-semantic-schema/S1S2"

#: S1 之前的库结构快照（与 scripts/fetch_assets.py::init 一致）。
#: 仅用于测试构造「未迁移」的库，生产路径不调用。
LEGACY_SCHEMA = """
CREATE TABLE pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    layout_url TEXT UNIQUE, date TEXT, page TEXT, title TEXT, author TEXT,
    fetched_at TEXT
);
CREATE TABLE assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    page_id INTEGER, kind TEXT, url TEXT UNIQUE, local_path TEXT,
    sha256 TEXT, bytes INTEGER, note TEXT
);
CREATE TABLE paragraphs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    page_id INTEGER, seq INTEGER, text TEXT
);
CREATE TABLE chart_points (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    page_id INTEGER, chart_key TEXT, chart_title TEXT,
    seq INTEGER, label TEXT, value REAL, unit TEXT
);
"""

LEGACY_TABLES = ("pages", "assets", "paragraphs", "chart_points")

#: 旧四表的列（迁移后 assets 会多出 9 列，所以这里必须显式列名而不是 SELECT *）。
LEGACY_COLUMNS = {
    "pages": ("id", "layout_url", "date", "page", "title", "author", "fetched_at"),
    "assets": ("id", "page_id", "kind", "url", "local_path", "sha256", "bytes", "note"),
    "paragraphs": ("id", "page_id", "seq", "text"),
    "chart_points": ("id", "page_id", "chart_key", "chart_title",
                     "seq", "label", "value", "unit"),
}


def create_legacy_db(path, seed_from=None):
    """造一个 S1 之前的库；``seed_from`` 指向一个已迁移库时按旧四表复制数据。"""
    import sqlite3 as _sq

    con = _sq.connect(path)
    try:
        con.executescript(LEGACY_SCHEMA)
        if seed_from:
            src = _sq.connect(f"file:{seed_from}?mode=ro", uri=True)
            try:
                for t, cols in LEGACY_COLUMNS.items():
                    collist = ", ".join(cols)
                    rows = src.execute(f"SELECT {collist} FROM {t}").fetchall()
                    if not rows:
                        continue
                    con.executemany(
                        f"INSERT INTO {t}({collist}) "
                        f"VALUES({','.join('?' * len(cols))})", rows)
            finally:
                src.close()
        con.commit()
    finally:
        con.close()


def _columns(con, table):
    try:
        return [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
    except sqlite3.DatabaseError:
        return []


def _object_exists(con, kind, name):
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type=? AND name=?", (kind, name)).fetchone()
    return row is not None


def _migrations_table(con):
    con.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id         TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )""")


def _seed_vocabulary(con):
    sql = ("INSERT INTO tag_vocabulary(tag, tag_type, label_zh, aliases, parent_tag, "
           "deprecated, note) VALUES(?,?,?,?,?,0,?) "
           "ON CONFLICT(tag) DO UPDATE SET "
           "tag_type=excluded.tag_type, label_zh=excluded.label_zh, "
           "aliases=excluded.aliases, parent_tag=excluded.parent_tag, "
           "note=excluded.note "
           "WHERE tag_vocabulary.tag_type<>excluded.tag_type "
           "   OR tag_vocabulary.label_zh<>excluded.label_zh "
           "   OR IFNULL(tag_vocabulary.aliases,'')<>IFNULL(excluded.aliases,'') "
           "   OR IFNULL(tag_vocabulary.parent_tag,'')<>IFNULL(excluded.parent_tag,'') "
           "   OR IFNULL(tag_vocabulary.note,'')<>IFNULL(excluded.note,'')")
    added = 0
    for tag, tag_type, label_zh, aliases, parent_tag, note in vocabulary_rows():
        cur = con.execute(sql, (tag, tag_type, label_zh, aliases, parent_tag, note))
        added += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
    return added


def _normalise_sql(sql):
    """把 DDL 压成可比较的形式（去空白差异、去 CREATE 前缀大小写差异）。"""
    return " ".join((sql or "").split()).lower()


def _view_matches(con, name, ddl):
    """视图已存在且定义与期望一致时返回 True（视图定义改了就重建）。"""
    row = con.execute(
        "SELECT sql FROM sqlite_master WHERE type='view' AND name=?", (name,)).fetchone()
    if row is None:
        return False
    want = _normalise_sql(ddl).replace("create view if not exists", "create view", 1)
    return _normalise_sql(row[0]) == want


def migrate(db_path=DEFAULT_DB, dry_run=False, verbose=True):
    """执行迁移。返回 (changed, log)。

    ``changed`` 为 False 表示「本来就已经是最新状态」，此时没有写入任何数据，
    数据库文件字节不会变化（幂等性的可验证形式）。
    """
    log = []
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")
    try:
        if _object_exists(con, "table", "schema_migrations"):
            row = con.execute("SELECT 1 FROM schema_migrations WHERE id=?",
                              (MIGRATION_ID,)).fetchone()
            already_marked = row is not None
        else:
            already_marked = False

        todo = []

        # 1. 三张新表
        for ddl, name in ((DDL_TAG_VOCABULARY, "tag_vocabulary"),
                          (DDL_ASSET_TAGS, "asset_tags"),
                          (DDL_ASSET_USAGE, "asset_usage")):
            if not _object_exists(con, "table", name):
                todo.append(("create_table", name, ddl))

        # 2. assets 扩列
        have = set(_columns(con, "assets"))
        for col, decl in ASSETS_NEW_COLUMNS:
            if col not in have:
                todo.append(("add_column", col, f"ALTER TABLE assets ADD COLUMN {col} {decl}"))

        # 3. 词表种子（内容不一致也算 todo）
        seed = vocabulary_rows()
        existing = {}
        if _object_exists(con, "table", "tag_vocabulary"):
            existing = {r[0]: tuple(r[1:]) for r in con.execute(
                "SELECT tag, tag_type, label_zh, IFNULL(aliases,''), "
                "IFNULL(parent_tag,''), IFNULL(note,'') FROM tag_vocabulary")}
        seed_delta = [
            (t, tt, lz, al or "", pt or "", nt or "")
            for (t, tt, lz, al, pt, nt) in seed
            if existing.get(t) != (tt, lz, al or "", pt or "", nt or "")
        ]
        if seed_delta:
            todo.append(("seed_vocabulary", f"{len(seed_delta)} rows", ""))

        # 4. 视图与触发器
        for kind, name, ddl in (
                ("view", "v_searchable_assets", DDL_VIEW_SEARCHABLE),
                ("view", "v_asset_search", DDL_VIEW_SEARCH),
                ("view", "v_fallback_assets", DDL_VIEW_FALLBACK),
                ("trigger", "trg_page_image_no_chart_semantic",
                 DDL_TRIGGER_PAGE_IMAGE_NO_CHART_SEMANTIC)):
            if kind == "view":
                if _view_matches(con, name, ddl):
                    continue
                if _object_exists(con, kind, name):
                    # 视图定义变了就重建：CREATE VIEW IF NOT EXISTS 不会更新定义
                    todo.append(("recreate_view", name, "DROP VIEW IF EXISTS %s" % name))
                todo.append((f"create_{kind}", name, ddl))
            elif not _object_exists(con, kind, name):
                todo.append((f"create_{kind}", name, ddl))

        # 5. 索引
        for ddl in DDL_INDEXES:
            name = ddl.split("IF NOT EXISTS", 1)[1].split("ON", 1)[0].strip()
            if not _object_exists(con, "index", name):
                todo.append(("create_index", name, ddl))

        # 6. 版本标记
        if not already_marked:
            todo.append(("mark_version", MIGRATION_ID, ""))

        for kind, name, _ in todo:
            log.append(f"  · {kind:<15} {name}")
        if not todo:
            log.append("  · (无变更，库已是最新状态)")

        if dry_run or not todo:
            return (False if not todo else True), log

        con.execute("BEGIN")
        _migrations_table(con)
        for kind, name, ddl in todo:
            if kind == "recreate_view":
                con.execute(ddl)
            elif kind == "create_table" or kind.startswith("create_"):
                con.execute(ddl)
            elif kind == "add_column":
                con.execute(ddl)
            elif kind == "create_index":
                con.execute(ddl)
            elif kind == "mark_version":
                con.execute("INSERT OR REPLACE INTO schema_migrations(id, applied_at) "
                            "VALUES(?, datetime('now'))", (name,))
        if seed_delta:
            _seed_vocabulary(con)

        problems = audit(con)
        if problems:
            con.rollback()
            raise SystemExit(f"迁移后体检未通过，已回滚：{problems}")
        con.commit()
        return True, log
    finally:
        con.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description="素材库语义层迁移（幂等）")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--dry-run", action="store_true", help="只列出将要执行的变更")
    ap.add_argument("--audit", action="store_true", help="只跑体检，不改库")
    args = ap.parse_args(argv)

    if args.audit:
        con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
        try:
            problems = audit(con)
        finally:
            con.close()
        if problems:
            for name, rows in problems.items():
                print(f"[FAIL] {name}: {rows[:5]}")
            return 1
        print("[OK] 9 项体检全部返回 0 行")
        return 0

    changed, log = migrate(args.db, dry_run=args.dry_run)
    print("\n".join(log))
    print(f"{'将执行' if args.dry_run else '已执行' if changed else '无变更'}: {args.db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
