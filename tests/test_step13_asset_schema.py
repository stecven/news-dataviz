# -*- coding: utf-8 -*-
"""第五层 S1/S2 验收：素材库语义层建表 + 词表 + P1 硬规则 + 缓存一致性。

两组测试：
* ``TestMigrationOnScratchDb`` —— 在**库的临时副本**上跑迁移，验证结构、幂等、
  P1 硬规则、约束与体检。不污染真库。
* ``TestRealDbAfterMigration`` —— 对真库 ``db/assets.db`` 断言「已迁移 + 旧数据完好 +
  体检 0 行」。这类断言要求真库已执行过 ``scripts/migrate_db.py``。
"""
import hashlib
import json
import os
import shutil
import sqlite3
import unittest

from loop import asset_schema as A
from loop.data_source import DB_PATH
from tests.scratch import mkdtemp

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIGRATE = os.path.join(ROOT, "scripts", "migrate_db.py")
TS = "2026-11-09T10:30:00+08:00"


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest().upper()


_MOD = None


def _mod():
    """加载迁移脚本模块（它是 script 不是 package，只能按路径加载）。"""
    global _MOD
    if _MOD is None:
        import importlib.util

        spec = importlib.util.spec_from_file_location("_migrate_db_mod", MIGRATE)
        _MOD = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_MOD)
    return _MOD


def _legacy_db():
    """造一个 S1 之前的库（工作区内临时目录，沙箱不允许写系统 temp），
    数据从真库按旧四表复制过来。这样每个用例都在真正「未迁移」的库上跑迁移。"""
    d = mkdtemp()
    dst = os.path.join(d, "assets.db")
    _mod().create_legacy_db(dst, seed_from=DB_PATH)
    return d, dst


def _migrate(db_path, dry_run=False):
    return _mod().migrate(db_path, dry_run=dry_run, verbose=False)


class TestMigrationStructure(unittest.TestCase):
    """迁移后的结构：三张新表 + assets 扩列 + 视图 + 触发器 + 索引。"""

    @classmethod
    def setUpClass(cls):
        cls.dir, cls.db = _legacy_db()
        _migrate(cls.db)
        cls.con = sqlite3.connect(cls.db)
        cls.con.execute("PRAGMA foreign_keys = ON")

    @classmethod
    def tearDownClass(cls):
        cls.con.close()
        shutil.rmtree(cls.dir, ignore_errors=True)

    def _cols(self, table):
        return [r[1] for r in self.con.execute(f"PRAGMA table_info({table})")]

    def test_three_new_tables_exist(self):
        names = {r[0] for r in self.con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertLessEqual({"tag_vocabulary", "asset_tags", "asset_usage"}, names)

    def test_asset_tags_columns_and_pk(self):
        self.assertEqual(
            self._cols("asset_tags"),
            ["asset_id", "tag", "tag_type", "weight", "source", "created_at"])
        pk = [r[1] for r in self.con.execute("PRAGMA table_info(asset_tags)") if r[5]]
        self.assertEqual(pk, ["asset_id", "tag"])

    def test_tag_vocabulary_columns(self):
        self.assertEqual(
            self._cols("tag_vocabulary"),
            ["tag", "tag_type", "label_zh", "aliases", "parent_tag", "deprecated", "note"])

    def test_asset_usage_columns(self):
        self.assertEqual(
            self._cols("asset_usage"),
            ["id", "asset_id", "goal_key", "layout_slot", "score", "chosen",
             "miss_reason", "note", "created_at"])

    def test_assets_gained_all_nine_columns(self):
        cols = set(self._cols("assets"))
        for name, _ in A.ASSETS_NEW_COLUMNS:
            self.assertIn(name, cols)
        # 旧列一个都不能少
        self.assertLessEqual(
            {"id", "page_id", "kind", "url", "local_path", "sha256", "bytes", "note"}, cols)

    def test_status_defaults_to_pending_registration(self):
        row = self.con.execute("SELECT status FROM assets WHERE id=15").fetchone()
        self.assertEqual(row[0], "待登记")

    def test_style_token_defaults_to_flat(self):
        row = self.con.execute("SELECT style_token FROM assets WHERE id=15").fetchone()
        self.assertEqual(row[0], "flat")

    def test_views_and_trigger_exist(self):
        kinds = {}
        for name, typ in self.con.execute(
                "SELECT name, type FROM sqlite_master WHERE type IN ('view','trigger')"):
            kinds[name] = typ
        self.assertEqual(kinds.get("v_searchable_assets"), "view")
        self.assertEqual(kinds.get("v_asset_search"), "view")
        self.assertEqual(kinds.get("trg_page_image_no_chart_semantic"), "trigger")

    def test_migration_version_recorded(self):
        rows = self.con.execute("SELECT id FROM schema_migrations").fetchall()
        self.assertIn(("2026-11-09-asset-semantic-schema/S1S2",), rows)


class TestVocabularySeed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir, cls.db = _legacy_db()
        _migrate(cls.db)
        cls.con = sqlite3.connect(cls.db)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_seed_is_deduped_and_matches_module(self):
        self.assertEqual(len(A.vocabulary_rows()), len(A.VOCABULARY_SEED))
        n = self.con.execute("SELECT COUNT(*) FROM tag_vocabulary").fetchone()[0]
        self.assertEqual(n, len(A.vocabulary_rows()))

    def test_all_six_tag_types_present(self):
        got = {r[0] for r in self.con.execute(
            "SELECT DISTINCT tag_type FROM tag_vocabulary")}
        self.assertEqual(got, set(A.TAG_TYPES))

    def test_chart_semantic_covers_all_selector_outputs(self):
        """选型器可能说出的每一档语义，词表里都要有对应词。"""
        from loop import selector

        values = set(A.chart_semantic_values())
        # 选型器的三个常量
        self.assertIn(selector.SEMANTIC_SHARE, values)
        self.assertIn(selector.SEMANTIC_COMPARE, values)
        self.assertIn(selector.SEMANTIC_OTHER, values)
        # 两条特殊分支（规则 5a 全相等 / 规则 4 含负值）
        self.assertIn("全相等", values)
        self.assertIn("含负值", values)
        # no_applicable（规则 1 非比较、规则 6）
        self.assertIn("无适用", values)

    def test_chart_semantic_rows_all_typed_correctly(self):
        rows = self.con.execute(
            "SELECT tag, tag_type FROM tag_vocabulary WHERE tag_type='chart_semantic'")
        self.assertGreaterEqual(len(rows.fetchall()), 6)

    def test_no_duplicate_tags(self):
        total = self.con.execute("SELECT COUNT(*) FROM tag_vocabulary").fetchone()[0]
        distinct = self.con.execute(
            "SELECT COUNT(DISTINCT tag) FROM tag_vocabulary").fetchone()[0]
        self.assertEqual(total, distinct)

    def test_alias_does_not_shadow_another_tag(self):
        rows = self.con.execute(A.SQL_ALIAS_CONFLICT).fetchall()
        self.assertEqual(rows, [])

    def test_no_parent_cycle(self):
        rows = self.con.execute(A.SQL_PARENT_CYCLE).fetchall()
        self.assertEqual(rows, [])

    def test_every_parent_exists(self):
        rows = self.con.execute("""
            SELECT v.tag, v.parent_tag FROM tag_vocabulary v
            LEFT JOIN tag_vocabulary p ON p.tag = v.parent_tag
            WHERE v.parent_tag IS NOT NULL AND p.tag IS NULL""").fetchall()
        self.assertEqual(rows, [])

    def test_usage_placeholder_vocab_entry_exists(self):
        self.assertIn("fallback_placeholder", A.chart_semantic_values() + [
            r[0] for r in self.con.execute(
                "SELECT tag FROM tag_vocabulary WHERE tag_type='usage'")])


class TestP1HardRule(unittest.TestCase):
    """P1：kind='page_image' 的素材不参与检索。"""

    @classmethod
    def setUpClass(cls):
        cls.dir, cls.db = _legacy_db()
        _migrate(cls.db)
        cls.con = sqlite3.connect(cls.db)
        cls.con.execute("PRAGMA foreign_keys = ON")

    @classmethod
    def tearDownClass(cls):
        cls.con.close()
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_page_image_is_not_in_searchable_view(self):
        ids = [r[0] for r in self.con.execute(
            "SELECT id FROM v_searchable_assets")]
        self.assertNotIn(15, ids)
        self.assertIn(16, ids)  # 普通图标仍可检索

    def test_page_image_tags_never_surface_in_search_view_even_if_tagged(self):
        """给整版图打满主题标签，v_asset_search 也查不出它 —— 这是 P1 的核心断言。"""
        self.con.execute(
            "INSERT OR REPLACE INTO asset_tags(asset_id, tag, tag_type, weight, source, "
            "created_at) VALUES(15, '取暖电器', 'semantic', 1.0, 'manual', ?)", (TS,))
        self.con.execute(
            "INSERT OR REPLACE INTO asset_tags(asset_id, tag, tag_type, weight, source, "
            "created_at) VALUES(15, '小家电', 'semantic', 1.0, 'manual', ?)", (TS,))
        hits = self.con.execute(
            "SELECT * FROM v_asset_search WHERE tag IN ('取暖电器','小家电')").fetchall()
        self.assertEqual(hits, [])

        # 但标签本身是存在的（不静默丢弃数据），只是不进检索结果
        stored = self.con.execute(
            "SELECT COUNT(*) FROM asset_tags WHERE asset_id=15").fetchone()[0]
        self.assertEqual(stored, 2)

    def test_page_image_cannot_carry_chart_semantic(self):
        with self.assertRaises(sqlite3.IntegrityError) as cm:
            self.con.execute(
                "INSERT INTO asset_tags(asset_id, tag, tag_type, weight, source, created_at) "
                "VALUES(15, '比较大小', 'chart_semantic', 1.0, 'manual', ?)", (TS,))
        self.assertIn("page_image", str(cm.exception))

    def test_placeholder_assets_are_excluded_from_search(self):
        self.con.execute("UPDATE assets SET status='placeholder' WHERE id=16")
        ids = [r[0] for r in self.con.execute("SELECT id FROM v_searchable_assets")]
        self.assertNotIn(16, ids)
        self.con.execute("UPDATE assets SET status='已标注' WHERE id=16")

    def test_search_view_only_joins_live_vocabulary(self):
        self.con.execute(
            "INSERT OR REPLACE INTO asset_tags(asset_id, tag, tag_type, weight, source, "
            "created_at) VALUES(16, '枫叶', 'semantic', 1.0, 'manual', ?)", (TS,))
        self.assertEqual(
            len(self.con.execute(
                "SELECT 1 FROM v_asset_search WHERE asset_id=16 AND tag='枫叶'").fetchall()), 1)
        self.con.execute("UPDATE tag_vocabulary SET deprecated=1 WHERE tag='枫叶'")
        self.assertEqual(
            self.con.execute(
                "SELECT 1 FROM v_asset_search WHERE asset_id=16 AND tag='枫叶'").fetchall(), [])
        self.con.execute("UPDATE tag_vocabulary SET deprecated=0 WHERE tag='枫叶'")


class TestConstraints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir, cls.db = _legacy_db()
        _migrate(cls.db)
        cls.con = sqlite3.connect(cls.db)
        cls.con.execute("PRAGMA foreign_keys = ON")

    @classmethod
    def tearDownClass(cls):
        cls.con.close()
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_unknown_tag_is_rejected_by_foreign_key(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.con.execute(
                "INSERT INTO asset_tags(asset_id, tag, tag_type, weight, source, created_at) "
                "VALUES(16, '不存在的词', 'semantic', 1.0, 'manual', ?)", (TS,))

    def test_weight_out_of_range_is_rejected(self):
        for bad in (-0.1, 1.5):
            with self.subTest(bad=bad):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.con.execute(
                        "INSERT INTO asset_tags(asset_id, tag, tag_type, weight, source, "
                        "created_at) VALUES(16, '枫叶', 'semantic', ?, 'manual', ?)",
                        (bad, TS))

    def test_bad_miss_reason_is_rejected(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.con.execute(
                "INSERT INTO asset_usage(asset_id, goal_key, layout_slot, chosen, "
                "miss_reason, created_at) VALUES(NULL, 'k', 'body', 0, '??', ?)", (TS,))

    def test_bad_layout_slot_is_rejected(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.con.execute(
                "INSERT INTO asset_usage(asset_id, goal_key, layout_slot, chosen, "
                "miss_reason, created_at) VALUES(NULL, 'k', 'nowhere', 0, 'no_asset', ?)",
                (TS,))

    def test_miss_row_with_null_asset_is_allowed(self):
        """未命中也要能留记录（no_asset），所以 asset_id 必须可空。"""
        self.con.execute(
            "INSERT INTO asset_usage(asset_id, goal_key, layout_slot, chosen, "
            "miss_reason, created_at) VALUES(NULL, 'six_share', 'fallback_placeholder', "
            "0, 'no_asset', ?)", (TS,))
        n = self.con.execute(
            "SELECT COUNT(*) FROM asset_usage WHERE asset_id IS NULL").fetchone()[0]
        self.assertEqual(n, 1)

    def test_bad_status_value_is_rejected(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.con.execute("UPDATE assets SET status='乱写' WHERE id=16")

    def test_tag_type_drift_is_caught_by_audit(self):
        """同一个词被当成别的维度用 —— 外键拦不住，靠体检抓。"""
        self.con.execute(
            "INSERT INTO asset_tags(asset_id, tag, tag_type, weight, source, created_at) "
            "VALUES(17, '取暖电器', 'style', 1.0, 'manual', ?)", (TS,))
        problems = A.audit(self.con)
        self.assertIn("tag_type_drift", problems)
        self.con.execute("DELETE FROM asset_tags WHERE asset_id=17 AND tag='取暖电器'")


class TestCacheConsistency(unittest.TestCase):
    def setUp(self):
        self.dir, self.db = _legacy_db()
        _migrate(self.db)
        self.con = sqlite3.connect(self.db)

    def tearDown(self):
        self.con.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_fresh_migration_has_zero_cache_mismatch(self):
        self.assertEqual(self.con.execute(A.SQL_CACHE_SEMANTIC_MISMATCH).fetchall(), [])
        self.assertEqual(self.con.execute(A.SQL_CACHE_APPEARANCE_MISMATCH).fetchall(), [])

    def test_audit_passes_on_fresh_migration(self):
        self.assertEqual(A.audit(self.con), {})

    def test_cache_drift_is_detected(self):
        # 只写真源、不更新缓存 → 体检必须报出来
        self.con.execute(
            "INSERT INTO asset_tags(asset_id, tag, tag_type, weight, source, created_at) "
            "VALUES(16, '枫叶', 'semantic', 1.0, 'manual', ?)", (TS,))
        problems = A.audit(self.con)
        self.assertIn("cache_semantic_mismatch", problems)

    def test_cache_matching_truth_passes(self):
        self.con.execute(
            "INSERT INTO asset_tags(asset_id, tag, tag_type, weight, source, created_at) "
            "VALUES(16, '枫叶', 'semantic', 1.0, 'manual', ?)", (TS,))
        truth = [r[0] for r in self.con.execute(
            "SELECT tag FROM asset_tags WHERE asset_id=16 AND tag_type='semantic' "
            "ORDER BY tag")]
        self.con.execute("UPDATE assets SET semantic_tags=? WHERE id=16",
                         (json.dumps(truth, ensure_ascii=False),))
        self.assertNotIn("cache_semantic_mismatch", A.audit(self.con))

    def test_orphan_tag_check_catches_missing_vocab(self):
        self.con.execute("PRAGMA foreign_keys = OFF")
        self.con.execute(
            "INSERT INTO asset_tags(asset_id, tag, tag_type, weight, source, created_at) "
            "VALUES(16, '词表外', 'semantic', 1.0, 'manual', ?)", (TS,))
        problems = A.audit(self.con)
        self.assertIn("orphan_tags", problems)


class TestIdempotency(unittest.TestCase):
    def setUp(self):
        self.dir, self.db = _legacy_db()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_second_run_reports_no_change_and_leaves_bytes_identical(self):
        changed1, _ = _migrate(self.db)
        self.assertTrue(changed1)
        sha1 = _sha(self.db)

        changed2, _ = _migrate(self.db)
        self.assertFalse(changed2)
        self.assertEqual(_sha(self.db), sha1)

        changed3, _ = _migrate(self.db)
        self.assertFalse(changed3)
        self.assertEqual(_sha(self.db), sha1)

    def test_dry_run_does_not_touch_the_file(self):
        before = _sha(self.db)
        changed, log = _migrate(self.db, dry_run=True)
        self.assertTrue(changed)
        self.assertTrue(log)
        self.assertEqual(_sha(self.db), before)

    def test_legacy_rows_survive_migration(self):
        con = sqlite3.connect(self.db)
        before = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in ("pages", "assets", "paragraphs", "chart_points")}
        assets_before = con.execute(
            "SELECT id, kind, url, bytes FROM assets ORDER BY id").fetchall()
        con.close()

        _migrate(self.db)

        con = sqlite3.connect(self.db)
        after = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                 for t in ("pages", "assets", "paragraphs", "chart_points")}
        assets_after = con.execute(
            "SELECT id, kind, url, bytes FROM assets ORDER BY id").fetchall()
        con.close()
        self.assertEqual(before, after)
        self.assertEqual(assets_before, assets_after)

    def test_vocabulary_reseed_after_manual_edit_is_corrected(self):
        _migrate(self.db)
        con = sqlite3.connect(self.db)
        con.execute("UPDATE tag_vocabulary SET label_zh='乱改' WHERE tag='枫叶'")
        con.commit()
        con.close()
        changed, _ = _migrate(self.db)
        self.assertTrue(changed)
        con = sqlite3.connect(self.db)
        val = con.execute(
            "SELECT label_zh FROM tag_vocabulary WHERE tag='枫叶'").fetchone()[0]
        con.close()
        self.assertEqual(val, "枫叶")


class TestChartSemanticCoverage(unittest.TestCase):
    """G4 结论的可复现形式：覆盖率脚本能跑，且结论与人工映射一致。"""

    @classmethod
    def setUpClass(cls):
        import importlib.util

        path = os.path.join(ROOT, "scripts", "asset_coverage.py")
        spec = importlib.util.spec_from_file_location("_asset_coverage_mod", path)
        cls.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)
        cls.rep = cls.mod.build_report()

    def test_vocab_has_six_values(self):
        self.assertEqual(self.rep["vocab_count"], 6)
        self.assertEqual(len(self.rep["chart_semantic_vocab"]), 6)

    def test_registered_icons_count_matches_assets_table(self):
        """S3 起「已登记」口径 = assets 表里 kind='icon' 的基名（不再只看 _soft）。

        S1/S2 时这里是 7（只有 _soft 变体登记过）；S3 补登记 droplet/people/
        percent/pin 后为 11。
        """
        self.assertEqual(len(self.rep["registered_icons"]), 11)

    def test_registered_cover_four_of_six(self):
        """S3 之后「占比构成」有了 people/percent，覆盖率 3 → 4。"""
        self.assertEqual(self.rep["covered_registered"], 4)
        self.assertEqual(self.rep["missing_with_registered"], ["全相等", "无适用"])

    def test_all_files_coverage_equals_registered_now(self):
        """S3 把磁盘上 11 个基名全登记了 → 两个口径应当一致。"""
        self.assertEqual(self.rep["covered_all"], 4)
        self.assertEqual(self.rep["missing_with_all_files"], ["全相等", "无适用"])
        self.assertEqual(self.rep["registered_icons"], self.rep["all_icon_files"])
        self.assertEqual(self.rep["unregistered_icon_files"], [])
        self.assertIn("percent", self.rep["coverage_all_files"]["占比构成"])

    def test_hard_semantics_are_declared_with_reasons(self):
        self.assertLessEqual({"全相等", "无适用"}, set(self.rep["hard_semantics"]))
        for why in self.rep["hard_semantics"].values():
            self.assertTrue(why)

    def test_map_only_uses_vocabulary_semantics(self):
        vocab = set(self.rep["chart_semantic_vocab"])
        for name, sems in self.mod.ICON_CAPABILITY.items():
            for sem in sems:
                self.assertIn(sem, vocab, f"{name} 映射到了词表外的语义 {sem}")


class TestRealDbAfterMigration(unittest.TestCase):
    """真库已迁移后的断言（要求先跑过 scripts/migrate_db.py）。"""

    def setUp(self):
        self.con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)

    def tearDown(self):
        self.con.close()

    def test_real_db_has_all_tables(self):
        names = {r[0] for r in self.con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertLessEqual(
            {"tag_vocabulary", "asset_tags", "asset_usage", "schema_migrations"}, names)

    def test_real_db_audit_is_clean(self):
        self.assertEqual(A.audit(self.con), {})

    def test_real_db_still_has_the_original_eight_assets(self):
        """S1/S2 时的 8 行原始素材（id 15–22）必须一行不少。

        不再按「总行数」或「kind<>'placeholder' 的行数」断言——S3 补登记了 4 个
        图标、S5 加了 2 张占位图，任何写死计数的写法都会随素材增减失效。
        这里直接钉住那 8 个 id：素材增加不影响、素材被删才会红。
        """
        ids = {r[0] for r in self.con.execute(
            "SELECT id FROM assets WHERE id BETWEEN 15 AND 22").fetchall()}
        self.assertEqual(ids, set(range(15, 23)))
        self.assertEqual(
            self.con.execute(
                "SELECT kind FROM assets WHERE id=15").fetchone()[0], "page_image")

    def test_real_db_keeps_the_page_image(self):
        row = self.con.execute(
            "SELECT kind, bytes FROM assets WHERE id=15").fetchone()
        self.assertEqual(row, ("page_image", 510350))

    def test_real_db_page_image_not_searchable(self):
        ids = [r[0] for r in self.con.execute("SELECT id FROM v_searchable_assets")]
        self.assertNotIn(15, ids)

    def test_real_db_chart_points_untouched(self):
        n = self.con.execute("SELECT COUNT(*) FROM chart_points").fetchone()[0]
        self.assertEqual(n, 60)

    def test_real_db_bulk_tagging_only_touches_retrievable_icons(self):
        """S4 之后有批量打标了，但范围被锁死：打标的 asset 只能是 kind='icon'。

        S1/S2 时这条断言写的是「除占位图外 asset_tags 为空」，S4 打标后必然过期。
        断言的本意是「打标不会误伤不可检索的素材」，所以按 kind 判定，不按条数。
        """
        rows = self.con.execute(
            "SELECT DISTINCT a.id, a.kind FROM asset_tags t"
            " JOIN assets a ON a.id = t.asset_id"
            " WHERE t.tag <> 'fallback_placeholder'").fetchall()
        kinds = {r[1] for r in rows}
        self.assertEqual(kinds, {"icon"}, "只允许给 icon 打语义标签")
        self.assertNotIn(15, {r[0] for r in rows}, "P1：整版图不打标")


if __name__ == "__main__":
    unittest.main()
