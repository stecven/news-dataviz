# -*- coding: utf-8 -*-
"""第五层 S5 验收：fallback 占位图能生成、能登记、能被「无适用」这条链路查到。

分三组：

* ``TestPlaceholderFiles`` —— 图片真的画出来了、能读、尺寸/模式对。
* ``TestFallbackView`` —— ``v_fallback_assets`` 这个视图的定义与语义：
  只收 ``status='placeholder'`` 且打了 ``fallback_placeholder`` 的素材；
  正常检索（``v_asset_search``）**照旧查不到**占位图（P1 对 placeholder 也生效）。
* ``TestEndToEndNoApplicable`` —— 6 项占比 → 选型器返回 None → 流水线
  no_applicable → 有占位图可查。不崩溃、不返回空。

前置：真库要已跑过 ``scripts/migrate_db.py`` 与 ``scripts/make_placeholder.py``。
"""
import os
import sqlite3
import unittest

from PIL import Image

from loop import asset_schema as A
from loop.data_source import DB_PATH

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLACEHOLDER_DIR = os.path.join(ROOT, "assets", "placeholders")
ICONS = os.path.join(ROOT, "assets", "icons")  # 真图标目录，占位图刻意不混在里面

#: 本轮登记的两张占位图，基名固定（顺序稳定，便于逐条断言）
PLACEHOLDER_BASES = ("placeholder_todo", "placeholder_chart")


def _con(db=DB_PATH):
    con = sqlite3.connect("file:%s?mode=ro" % db.replace("\\", "/"), uri=True)
    con.row_factory = sqlite3.Row
    return con


class TestPlaceholderFiles(unittest.TestCase):
    def test_both_png_files_exist(self):
        for base in PLACEHOLDER_BASES:
            path = os.path.join(PLACEHOLDER_DIR, base + ".png")
            self.assertTrue(os.path.exists(path), "%s 没生成" % path)

    def test_files_are_readable_rgba_400px(self):
        for base in PLACEHOLDER_BASES:
            path = os.path.join(PLACEHOLDER_DIR, base + ".png")
            with Image.open(path) as im:
                im.load()
                self.assertEqual(im.size, (400, 400), base)
                self.assertEqual(im.mode, "RGBA", base)
                self.assertGreater(os.path.getsize(path), 500, base)

    def test_placeholders_are_neutral_grey_not_coloured(self):
        """中性灰：任一像素的 R/G/B 三通道差不超过 40，避免抢真素材的视觉。"""
        for base in PLACEHOLDER_BASES:
            path = os.path.join(PLACEHOLDER_DIR, base + ".png")
            with Image.open(path).convert("RGBA") as im:
                worst = 0
                for y in range(0, im.height, 4):
                    for x in range(0, im.width, 4):
                        r, g, b, a = im.getpixel((x, y))
                        if a > 128:
                            worst = max(worst, max(r, g, b) - min(r, g, b))
                self.assertLessEqual(worst, 40, "%s 不是中性灰" % base)


class TestFallbackView(unittest.TestCase):
    def test_view_ddl_is_declared_in_schema(self):
        self.assertTrue(hasattr(A, "DDL_VIEW_FALLBACK"),
                        "asset_schema 没声明 v_fallback_assets")
        self.assertIn("v_fallback_assets", A.DDL_VIEW_FALLBACK)

    def test_view_exists_in_real_db(self):
        con = _con()
        try:
            row = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='view'"
                " AND name='v_fallback_assets'").fetchone()
            self.assertIsNotNone(row, "真库没有 v_fallback_assets，迁移没生效")
        finally:
            con.close()

    def test_fallback_view_hits_the_placeholders(self):
        con = _con()
        try:
            rows = con.execute(
                "SELECT asset_id, kind, status, tag, tag_type"
                " FROM v_fallback_assets ORDER BY asset_id").fetchall()
        finally:
            con.close()
        self.assertGreaterEqual(len(rows), 2, "一张占位图都没查到")
        for r in rows:
            self.assertEqual(r["kind"], "placeholder")
            self.assertNotEqual(r["kind"], "page_image")
            self.assertEqual(r["status"], "placeholder")
            self.assertEqual(r["tag"], "fallback_placeholder")
            self.assertEqual(r["tag_type"], "usage")
        urls = set()
        con = _con()
        try:
            for r in con.execute(
                    "SELECT url FROM v_fallback_assets").fetchall():
                urls.add(r["url"])
        finally:
            con.close()
        for base in PLACEHOLDER_BASES:
            self.assertIn("local:" + base, urls)

    def test_normal_search_never_returns_placeholders(self):
        """P1 对 placeholder 也生效：正常检索视图查不到占位图。"""
        con = _con()
        try:
            n = con.execute(
                "SELECT COUNT(*) FROM v_asset_search"
                " WHERE kind = 'placeholder'").fetchone()[0]
            self.assertEqual(n, 0)
            n = con.execute(
                "SELECT COUNT(*) FROM v_asset_search"
                " WHERE tag = 'fallback_placeholder'").fetchone()[0]
            self.assertEqual(n, 0)
            # 反向确认：正常检索的候选池本身没被查空（7 个真图标在池里）。
            # 这里查 v_searchable_assets 而不是 v_asset_search——后者要 JOIN
            # asset_tags，而本轮不打标，真素材还没有 tag，JOIN 后本来就是 0 行。
            self.assertGreater(
                con.execute("SELECT COUNT(*) FROM v_searchable_assets").fetchone()[0], 0)
        finally:
            con.close()

    def test_comparison_semantic_does_not_hit_placeholder(self):
        """「比较大小」是温度计的场景，不该返回占位图。

        注意：本轮 S5 明确不批量打标，真素材（7 个 icon）还没有任何 tag，
        所以这里不能断言「一定有真素材命中」——只断言「结果里没有占位图」。
        等 S4 打标落地后，这条断言可加强为 ``assertTrue(rows)``。
        """
        con = _con()
        try:
            rows = con.execute(
                "SELECT asset_id, kind FROM v_asset_search"
                " WHERE tag = '比较大小'").fetchall()
        finally:
            con.close()
        for r in rows:
            self.assertNotEqual(r["kind"], "placeholder",
                                "占位图污染了「比较大小」检索")

    def test_placeholder_carries_no_chart_semantic_tag(self):
        """用户裁定：占位图只打 usage=fallback_placeholder，不挂 chart_semantic。"""
        con = _con()
        try:
            ids = [r[0] for r in con.execute(
                "SELECT id FROM assets WHERE kind='placeholder'").fetchall()]
            for aid in ids:
                n = con.execute(
                    "SELECT COUNT(*) FROM asset_tags WHERE asset_id=?"
                    " AND tag_type='chart_semantic'", (aid,)).fetchone()[0]
                self.assertEqual(n, 0, "asset %d 不该有 chart_semantic 标签" % aid)
        finally:
            con.close()


class TestLookupFunction(unittest.TestCase):
    """可复用查询函数（loop/asset_lookup.py），让「能查到」不只存在于 SQL 里。"""

    def test_find_fallback_assets_returns_both_placeholders(self):
        from loop import asset_lookup as L
        rows = L.find_fallback_assets()
        self.assertGreaterEqual(len(rows), 2)
        urls = {r["url"] for r in rows}
        for base in PLACEHOLDER_BASES:
            self.assertIn("local:" + base, urls)
        for r in rows:
            self.assertEqual(r["status"], "placeholder")
            self.assertNotEqual(r["kind"], "page_image")
            self.assertEqual(r["tag"], "fallback_placeholder")

    def test_every_fallback_row_points_at_a_real_file(self):
        from loop import asset_lookup as L
        for r in L.find_fallback_assets():
            self.assertIsNotNone(L.resolve_local_path(r),
                                 "%s 的 local_path 指不到文件" % r["url"])

    def test_semantic_lookup_never_returns_placeholders(self):
        from loop import asset_lookup as L
        for sem in ("比较大小", "占比构成", "含负值", "其他", "全相等", "无适用"):
            for r in L.find_assets_by_semantic(sem):
                self.assertNotEqual(r["kind"], "placeholder",
                                    "%s 检索到了占位图" % sem)


class TestEndToEndNoApplicable(unittest.TestCase):
    def test_no_applicable_branch_has_a_placeholder_to_fall_back_to(self):
        """6 项占比 → 选型器 None → 流水线 no_applicable → 兜底图存在。"""
        from loop import pipeline
        from loop.selector import SEMANTIC_SHARE

        values = [10, 3, 2, 2, 2, 1]
        con = sqlite3.connect("file:%s?mode=ro" % DB_PATH.replace("\\", "/"),
                               uri=True)
        con.row_factory = sqlite3.Row
        try:
            before = con.execute(
                "SELECT COUNT(*) FROM v_fallback_assets").fetchone()[0]
        finally:
            con.close()
        from tests.scratch import mkdtemp
        out_dir = mkdtemp("s5_fallback_")
        res = pipeline.run_selected(values=values, semantic=SEMANTIC_SHARE,
                                    out_root=out_dir, group_name="six_share")
        self.assertEqual(res["status"], "no_applicable")
        self.assertIsNone(res["selected_template"])
        # m04220 起：no_applicable 不再空手交出，而是画出占位图兜底。
        # 状态口径没变（仍是「无适用图形」），变的是有了可见产物。
        self.assertIsNotNone(res["preview"])
        self.assertTrue(res["placeholder"].endswith(".png"))
        # 兜底：这条链路虽不出图，但必须有占位素材可查
        con = sqlite3.connect("file:%s?mode=ro" % DB_PATH.replace("\\", "/"),
                               uri=True)
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute(
                "SELECT asset_id, url, kind, status FROM v_fallback_assets"
                " WHERE tag = 'fallback_placeholder'").fetchall()
        finally:
            con.close()
        self.assertGreaterEqual(len(rows), 1, "no_applicable 时查不到占位图")

        # 走公开查询函数再确认一次（不只是内联 SQL 能查）
        from loop import asset_lookup as L
        via_func = L.find_fallback_assets()
        self.assertGreaterEqual(len(via_func), 1, "查询函数查不到占位图")
        for r in via_func:
            self.assertIsNotNone(L.resolve_local_path(r))
        self.assertEqual(before, len(rows))
        for r in rows:
            self.assertEqual(r["status"], "placeholder")
            self.assertNotEqual(r["kind"], "page_image")
            self.assertTrue(os.path.exists(
                os.path.join(PLACEHOLDER_DIR,
                             r["url"].split("local:", 1)[1] + ".png")))

    def test_placeholders_do_not_pollute_the_icon_directory(self):
        """占位图不进 assets/icons/：asset_coverage.py 按该目录统计图标覆盖率。"""
        for base in PLACEHOLDER_BASES:
            self.assertFalse(os.path.exists(os.path.join(ICONS, base + ".png")),
                             "%s 不该放在 assets/icons/ 里" % base)

    def test_layout_slot_is_a_declared_value(self):
        self.assertIn("fallback_placeholder", A.LAYOUT_SLOTS)


if __name__ == "__main__":
    unittest.main()
