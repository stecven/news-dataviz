# -*- coding: utf-8 -*-
"""S4 验收：11 个 icon 批量打 asset_tags。

分四组：

* ``TestTargets``     —— 打标对象与预期一一对应，没误伤 page_image / placeholder
* ``TestVocabulary``  —— 所有 tag 都在词表里、tag_type 对齐词表（不依赖 FK 兜底）
* ``TestTagPlanShape``—— 每个 icon 都有标签、chart_semantic 覆盖两个主档
* ``TestSearchHits``  —— 走 v_asset_search 能真的命中，且不误命中
* ``TestStatusFlip``  —— 打标后 status 从「待登记」翻成「已标注」
"""
import os
import sqlite3
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scripts import tag_assets as S  # noqa: E402

DB = os.path.join(ROOT, "db", "assets.db")


def _con():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only = ON")
    return con


class TestTargets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = _con()

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def test_exactly_eleven_icons_are_targeted(self):
        rows = self.con.execute(
            "SELECT id FROM assets WHERE kind='icon' ORDER BY id").fetchall()
        self.assertEqual([r["id"] for r in rows], list(S.EXPECTED_IDS))
        self.assertEqual(len(S.EXPECTED_IDS), 11)

    def test_urls_match_expectation(self):
        for aid in S.EXPECTED_IDS:
            url = self.con.execute(
                "SELECT url FROM assets WHERE id=?", (aid,)).fetchone()["url"]
            self.assertEqual(url, S.EXPECTED_URLS[aid], aid)

    def test_page_image_and_placeholders_are_not_in_the_plan(self):
        """P1：整版图不参与检索；占位图已有自己的标签，不该进 S4 计划。"""
        for forbidden in (15, 23, 24):
            self.assertNotIn(forbidden, S.TAG_PLAN)

    def test_page_image_has_no_tags_at_all(self):
        n = self.con.execute(
            "SELECT COUNT(*) FROM asset_tags WHERE asset_id=15").fetchone()[0]
        self.assertEqual(n, 0, "P1：整版图不该有任何标签")

    def test_placeholder_tags_untouched(self):
        for aid in (23, 24):
            rows = self.con.execute(
                "SELECT tag FROM asset_tags WHERE asset_id=?", (aid,)).fetchall()
            self.assertEqual([r["tag"] for r in rows], ["fallback_placeholder"])


class TestVocabulary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = _con()

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def test_every_planned_tag_exists_in_vocabulary(self):
        self.assertEqual(S.missing_vocabulary(self.con), [])

    def test_every_planned_tag_type_matches_vocabulary(self):
        self.assertEqual(S.tag_type_drift(self.con), [])

    def test_no_tag_outside_vocabulary_was_written(self):
        """反向检查：库里已写的 tag 全部能在词表找到（没有裸写）。"""
        orphans = self.con.execute(
            "SELECT DISTINCT tag FROM asset_tags"
            " WHERE tag NOT IN (SELECT tag FROM tag_vocabulary)").fetchall()
        self.assertEqual([r["tag"] for r in orphans], [])

    def test_no_new_tag_type_invented(self):
        types = {r[0] for r in self.con.execute(
            "SELECT DISTINCT tag_type FROM asset_tags")}
        vocab_types = {r[0] for r in self.con.execute(
            "SELECT DISTINCT tag_type FROM tag_vocabulary")}
        self.assertTrue(types.issubset(vocab_types),
                        "出现了词表没有的 tag_type：%s" % (types - vocab_types))


class TestTagPlanShape(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = _con()

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def test_no_icon_is_left_without_tags(self):
        rows = self.con.execute(
            "SELECT a.id, COUNT(t.tag) c FROM assets a"
            " LEFT JOIN asset_tags t ON t.asset_id=a.id"
            " WHERE a.kind='icon' GROUP BY a.id").fetchall()
        self.assertEqual(len(rows), 11)
        for r in rows:
            self.assertGreater(r["c"], 0, "id %d 没有标签" % r["id"])

    def test_total_tag_count_matches_plan(self):
        """按 asset_id 圈定范围，不按 source —— source 只能是 'manual'
        （CHECK 约束），占位图的两条标签也是 manual，按 source 统计会多算 2 条。"""
        marks = ",".join("?" * len(S.EXPECTED_IDS))
        total = self.con.execute(
            "SELECT COUNT(*) FROM asset_tags WHERE asset_id IN (%s)" % marks,
            S.EXPECTED_IDS).fetchone()[0]
        self.assertEqual(total, S.planned_count())

    def test_compare_hits_radiator_first_then_thermometer(self):
        rows = self.con.execute(
            "SELECT asset_id, weight FROM asset_tags"
            " WHERE tag='比较大小' ORDER BY weight DESC, asset_id").fetchall()
        ids = [r["asset_id"] for r in rows]
        self.assertIn(17, ids, "radiator 必须打『比较大小』")
        self.assertIn(20, ids, "thermometer 必须打『比较大小』")
        # radiator 是首选（权重 1.0），thermometer 是次选（0.6），避免与图内温度计撞车
        w = {r["asset_id"]: r["weight"] for r in rows}
        self.assertGreater(w[17], w[20])
        self.assertEqual(ids[0], 17)

    def test_share_hits_people_and_percent(self):
        rows = self.con.execute(
            "SELECT DISTINCT asset_id FROM asset_tags"
            " WHERE tag='占比构成' ORDER BY asset_id").fetchall()
        ids = {r["asset_id"] for r in rows}
        self.assertTrue({26, 27}.issubset(ids), "'占比构成' 需 people + percent，得到 %s" % ids)

    def test_negative_chart_semantic_only_on_thermometer(self):
        rows = self.con.execute(
            "SELECT DISTINCT asset_id FROM asset_tags"
            " WHERE tag='含负值'").fetchall()
        self.assertEqual({r["asset_id"] for r in rows}, {20},
                         "含负值档只有温度计能表达")

    def test_equal_and_no_applicable_are_not_faked(self):
        """两档缺素材就如实缺着，不拿别的图标凑。"""
        for tag in ("全相等", "无适用"):
            rows = self.con.execute(
                "SELECT COUNT(*) FROM asset_tags WHERE tag=?", (tag,)).fetchone()[0]
            self.assertEqual(rows, 0,
                             "%s 档没有合适素材，不该硬凑标签" % tag)


class TestSearchHits(unittest.TestCase):
    def test_compare_semantic_hits_radiator_and_thermometer(self):
        from loop.asset_lookup import find_assets_by_semantic
        rows = find_assets_by_semantic("比较大小")
        ids = [r["asset_id"] for r in rows]
        self.assertIn(17, ids)
        self.assertIn(20, ids)
        # radiator 必须排第一（首选），thermometer 权重低往后排
        self.assertEqual(ids[0], 17)
        self.assertLess(ids.index(17), ids.index(20))

    def test_share_semantic_hits_people_and_percent(self):
        from loop.asset_lookup import find_assets_by_semantic
        rows = find_assets_by_semantic("占比构成")
        ids = [r["asset_id"] for r in rows]
        self.assertIn(26, ids)
        self.assertIn(27, ids)

    def test_search_never_returns_page_image(self):
        from loop.asset_lookup import find_assets_by_semantic
        for semantic in ("比较大小", "占比构成", "含负值", "其他"):
            for r in find_assets_by_semantic(semantic):
                self.assertNotEqual(r["asset_id"], 15)

    def test_search_never_returns_placeholder(self):
        from loop.asset_lookup import find_assets_by_semantic
        for semantic in ("比较大小", "占比构成", "含负值", "其他"):
            for r in find_assets_by_semantic(semantic):
                self.assertNotIn(r["asset_id"], (23, 24))

    def test_fallback_path_still_works_independently(self):
        """S4 打标不能把 S5 的兜底路径弄坏。"""
        from loop.asset_lookup import find_fallback_assets
        self.assertEqual(len(find_fallback_assets()), 2)


class TestStatusFlip(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = _con()

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def test_tagged_icons_are_marked_as_tagged(self):
        for aid in S.EXPECTED_IDS:
            status = self.con.execute(
                "SELECT status FROM assets WHERE id=?", (aid,)).fetchone()["status"]
            self.assertEqual(status, S.STATUS_TAGGED, "id %d 打标后应为已标注" % aid)

    def test_placeholders_keep_their_own_status(self):
        for aid in (23, 24):
            status = self.con.execute(
                "SELECT status FROM assets WHERE id=?", (aid,)).fetchone()["status"]
            self.assertEqual(status, "placeholder")

    def test_page_image_status_untouched(self):
        status = self.con.execute(
            "SELECT status FROM assets WHERE id=15").fetchone()["status"]
        self.assertEqual(status, "待登记")


class TestIdempotency(unittest.TestCase):
    def test_second_run_inserts_nothing(self):
        import shutil
        import tests.scratch as scratch
        tmp = scratch.mkdtemp()
        copy = os.path.join(tmp, "assets_copy.db")
        shutil.copyfile(DB, copy)
        first = S.tag_assets(copy)
        second = S.tag_assets(copy)
        self.assertEqual(first["inserted"], 0, "库里已有全部标签，不该再插")
        self.assertEqual(second["inserted"], 0)
        self.assertEqual(second["retyped"], 0)
        self.assertEqual(second["skipped"], S.planned_count())


if __name__ == "__main__":
    unittest.main()
