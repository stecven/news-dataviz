# -*- coding: utf-8 -*-
"""第五层 S3 验收：``assets/icons/`` 下 4 个未登记基名补登进 ``assets`` 表。

分四组：

* ``TestScan`` —— 扫描逻辑（基名归并、变体后缀）。
* ``TestRegistration`` —— 真库上 4 个基名已登记，字段填法符合 schema。
* ``TestIdempotency`` —— 在库副本上重复跑：不新增行、不覆盖非空字段、只补空列。
* ``TestNoBulkTagging`` —— 没打任何 asset_tags（除 S5 占位图那 2 条）。

前置：真库已执行 ``scripts/register_icons.py``。
"""
import os
import shutil
import sqlite3
import unittest

from loop.data_source import DB_PATH
from tests.scratch import mkdtemp

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICONS = os.path.join(ROOT, "assets", "icons")
REGISTER = os.path.join(ROOT, "scripts", "register_icons.py")

S3_BASES = ("droplet", "people", "percent", "pin")

_MOD = None


def _mod():
    global _MOD
    if _MOD is None:
        import importlib.util

        spec = importlib.util.spec_from_file_location("_register_icons_mod", REGISTER)
        _MOD = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_MOD)
    return _MOD


def _con(db=DB_PATH):
    con = sqlite3.connect("file:%s?mode=ro" % str(db).replace("\\", "/"), uri=True)
    con.row_factory = sqlite3.Row
    return con


def _copy_db():
    d = mkdtemp("s3_copy_")
    dst = os.path.join(d, "assets.db")
    shutil.copyfile(DB_PATH, dst)
    return dst


class TestScan(unittest.TestCase):
    def test_base_name_strips_variant_suffixes(self):
        m = _mod()
        self.assertEqual(m.base_of("percent.png"), "percent")
        self.assertEqual(m.base_of("percent_soft.png"), "percent")
        self.assertEqual(m.base_of("thermometer_flat.png"), "thermometer")

    def test_scan_finds_all_four_s3_bases(self):
        found = dict(_mod().scan())
        for base in S3_BASES:
            self.assertIn(base, found, "%s 没扫描到" % base)
            self.assertEqual(found[base], [base + ".png"],
                             "%s 应只有原图一个文件" % base)

    def test_scan_merges_variants_of_registered_icons(self):
        found = dict(_mod().scan())
        self.assertEqual(sorted(found["thermometer"]),
                         ["thermometer.png", "thermometer_flat.png",
                          "thermometer_soft.png"])


class TestRegistration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = _con()

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def test_each_base_is_registered_exactly_once(self):
        for base in S3_BASES:
            rows = self.con.execute(
                "SELECT id FROM assets WHERE url=?", ("local:" + base,)).fetchall()
            self.assertEqual(len(rows), 1, "%s 登记了 %d 行" % (base, len(rows)))

    def test_new_rows_use_the_same_conventions_as_existing_icons(self):
        for base in S3_BASES:
            r = self.con.execute(
                "SELECT * FROM assets WHERE url=?", ("local:" + base,)).fetchone()
            self.assertEqual(r["kind"], "icon", base)
            # S4 打标后 status 会从「待登记」翻成「已标注」；这条断言的本意是
            # 「登记脚本不擅自改状态」，不是「状态永远是待登记」，故放宽为二选一。
            self.assertIn(r["status"], ("待登记", "已标注"), base)
            self.assertEqual(r["style_token"], "flat", base)
            self.assertIsNone(r["palette"], "%s 的 palette 应为 NULL" % base)
            self.assertEqual(r["width"], 400, base)
            self.assertEqual(r["height"], 400, base)
            self.assertGreater(r["alpha"], 0.9, "%s 是原图，alpha 应接近 1" % base)
            self.assertTrue(r["local_path"].endswith(base + ".png"), base)
            self.assertTrue(os.path.exists(
                os.path.join(ROOT, r["local_path"].replace("\\", os.sep))), base)

    def test_no_duplicate_urls_in_assets(self):
        dup = self.con.execute(
            "SELECT url, COUNT(*) c FROM assets GROUP BY url HAVING c > 1").fetchall()
        self.assertEqual([dict(r) for r in dup], [])

    def test_registration_added_exactly_four_rows(self):
        """S1/S2 的 8 行 + S5 的 2 张占位图 + S3 的 4 个图标 = 14 行。"""
        self.assertEqual(
            self.con.execute("SELECT COUNT(*) FROM assets").fetchone()[0], 14)

    def test_original_eight_untouched(self):
        self.assertEqual(self.con.execute(
            "SELECT COUNT(*) FROM assets WHERE kind <> 'placeholder'"
            " AND url LIKE 'local:%_soft'").fetchone()[0], 7)


class TestIdempotency(unittest.TestCase):
    def test_second_run_inserts_nothing(self):
        db = _copy_db()
        m = _mod()
        first = m.register(db_path=db)
        second = m.register(db_path=db)
        self.assertEqual(len(first["inserted"]), 0, "副本里已登记过，不该再插")
        self.assertEqual(len(second["inserted"]), 0)
        self.assertEqual(len(second["skipped"]), 4)

    def test_registering_into_a_fresh_copy_inserts_four(self):
        """把 4 行删掉再登记，应恰好补回 4 行（验证插入路径本身）。"""
        db = _copy_db()
        con = sqlite3.connect(db)
        for base in S3_BASES:
            con.execute("DELETE FROM assets WHERE url=?", ("local:" + base,))
        con.commit()
        con.close()
        res = _mod().register(db_path=db)
        self.assertEqual(len(res["inserted"]), 4, res)
        con = sqlite3.connect(db)
        try:
            n = con.execute(
                "SELECT COUNT(*) FROM assets WHERE kind='icon'").fetchone()[0]
        finally:
            con.close()
        self.assertEqual(n, 11)   # 7 个原 _soft + 4 个新登记的

    def test_non_empty_fields_are_never_overwritten(self):
        db = _copy_db()
        con = sqlite3.connect(db)
        con.execute("UPDATE assets SET palette='keep_me', alpha=0.5"
                    " WHERE url='local:droplet'")
        con.commit()
        con.close()
        _mod().register(db_path=db)
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        try:
            r = con.execute("SELECT palette, alpha FROM assets"
                            " WHERE url='local:droplet'").fetchone()
        finally:
            con.close()
        self.assertEqual(r["palette"], "keep_me", "非空字段被覆盖了")
        self.assertAlmostEqual(r["alpha"], 0.5, msg="非空 alpha 被覆盖了")

    def test_blank_fields_get_backfilled(self):
        db = _copy_db()
        con = sqlite3.connect(db)
        con.execute("UPDATE assets SET width=NULL, height=NULL, alpha=NULL"
                    " WHERE url='local:pin'")
        con.commit()
        con.close()
        res = _mod().register(db_path=db)
        self.assertTrue(any(b == "pin" for b, _ in res["filled"]))
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        try:
            r = con.execute("SELECT width, height FROM assets"
                            " WHERE url='local:pin'").fetchone()
        finally:
            con.close()
        self.assertEqual((r["width"], r["height"]), (400, 400))


class TestNoBulkTagging(unittest.TestCase):
    def test_asset_tags_still_only_has_the_two_placeholders(self):
        con = _con()
        try:
            rows = con.execute(
                "SELECT asset_id, tag FROM asset_tags ORDER BY asset_id").fetchall()
        finally:
            con.close()
        # S4 给 11 个 icon 打了标，占位图那 2 条仍在且只属于占位图。
        ph = [r for r in rows if r["asset_id"] in (23, 24)]
        self.assertEqual(len(ph), 2, [dict(r) for r in rows])
        for r in ph:
            self.assertEqual(r["tag"], "fallback_placeholder")

    def test_new_icons_got_tagged_by_s4(self):
        """S3 只登记不打标；S4 之后这 4 个基名应当都有标签了。"""
        con = _con()
        try:
            for base in S3_BASES:
                n = con.execute(
                    "SELECT COUNT(*) FROM asset_tags t JOIN assets a"
                    " ON a.id = t.asset_id WHERE a.url=?",
                    ("local:" + base,)).fetchone()[0]
                self.assertGreater(n, 0, "%s 在 S4 之后应当有标签" % base)
        finally:
            con.close()


class TestSearchVisibility(unittest.TestCase):
    def test_new_icons_are_in_the_searchable_pool(self):
        con = _con()
        try:
            ids = {r[0] for r in con.execute(
                "SELECT id FROM v_searchable_assets").fetchall()}
            for base in S3_BASES:
                aid = con.execute("SELECT id FROM assets WHERE url=?",
                                  ("local:" + base,)).fetchone()[0]
                self.assertIn(aid, ids, "%s 不在可检索池里" % base)
        finally:
            con.close()

    def test_placeholder_and_page_image_stay_out(self):
        con = _con()
        try:
            kinds = {r[0] for r in con.execute(
                "SELECT DISTINCT kind FROM v_searchable_assets").fetchall()}
        finally:
            con.close()
        self.assertNotIn("placeholder", kinds)
        self.assertNotIn("page_image", kinds)

    def test_kind_query_finds_the_new_icons(self):
        con = _con()
        try:
            rows = con.execute(
                "SELECT a.url FROM assets a JOIN v_searchable_assets v"
                " ON v.id = a.id WHERE a.kind='icon' AND a.url IN"
                " ('local:droplet','local:people','local:percent','local:pin')"
            ).fetchall()
        finally:
            con.close()
        self.assertEqual(len(rows), 4, [dict(r) for r in rows])


class TestCoverageScopeChange(unittest.TestCase):
    """覆盖率口径改为「assets 表里已登记的基名」，不再只看文件名带 _soft 的。"""

    @classmethod
    def setUpClass(cls):
        import importlib.util

        path = os.path.join(ROOT, "scripts", "asset_coverage.py")
        spec = importlib.util.spec_from_file_location("_asset_coverage_s3", path)
        cls.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)
        cls.rep = cls.mod.build_report()

    def test_registered_bases_are_eleven(self):
        self.assertEqual(len(self.rep["registered_icons"]), 11)

    def test_newly_registered_bases_are_counted(self):
        for base in S3_BASES:
            self.assertIn(base, self.rep["registered_icons"])

    def test_coverage_rises_to_four(self):
        self.assertEqual(self.rep["covered_registered"], 4)
        self.assertEqual(self.rep["missing_with_registered"], ["全相等", "无适用"])

    def test_share_semantic_now_has_percent_and_people(self):
        hits = self.rep["coverage_registered"]["占比构成"]
        self.assertIn("percent", hits)
        self.assertIn("people", hits)

    def test_no_unregistered_files_left(self):
        self.assertEqual(self.rep["unregistered_icon_files"], [])


if __name__ == "__main__":
    unittest.main()
