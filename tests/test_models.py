import hashlib
import unittest

from loop.models import Scale, ElementSpec, PageSpec
from loop.data_source import DB_PATH, load_points


def _sha(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


class TestPageSpecRoundtrip(unittest.TestCase):
    def test_roundtrip_preserves_all_fields(self):
        spec = PageSpec(
            10.0, 6.0, "heat_ratio_top5", "标题",
            Scale(11.0, 3.0, "倍(超)"),
            [ElementSpec("liquid_1", "rect", "liquid", 0.8, 1.57, 0.5, 2.727,
                         "C01F2A", None,
                         {"chart_key": "heat_ratio_top5", "seq": 1, "value": 10.0})],
            [],
        )
        self.assertEqual(PageSpec.from_dict(spec.to_dict()).to_dict(), spec.to_dict())


class TestLoadPoints(unittest.TestCase):
    def test_loads_five_rows_sorted_by_seq(self):
        title, rows = load_points(DB_PATH)
        self.assertEqual(title, "取暖电器细分品类成交额环比增速TOP5")
        self.assertEqual([r["seq"] for r in rows], [1, 2, 3, 4, 5])
        self.assertEqual([r["value"] for r in rows], [10.0, 3.0, 3.0, 3.0, 3.0])
        self.assertEqual(rows[0]["label"], "欧式快热炉")
        self.assertEqual(rows[0]["unit"], "倍(超)")

    def test_db_file_unchanged(self):
        before = _sha(DB_PATH)
        load_points(DB_PATH)
        self.assertEqual(_sha(DB_PATH), before)

    def test_override_changes_only_named_seq(self):
        _, rows = load_points(DB_PATH, overrides={1: 12.0})
        self.assertEqual([r["value"] for r in rows], [12.0, 3.0, 3.0, 3.0, 3.0])

    def test_unknown_seq_raises_valueerror(self):
        with self.assertRaisesRegex(ValueError, "99"):
            load_points(DB_PATH, overrides={99: 12.0})

    def test_non_numeric_override_raises_valueerror(self):
        with self.assertRaises(ValueError):
            load_points(DB_PATH, overrides={1: "abc"})

    # 审查发现：nan/inf 是合法 float，旧校验会放过，进而污染几何或崩在 ceil()。
    def test_nan_inf_overrides_are_rejected(self):
        for bad in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(ValueError, "non-finite"):
                    load_points(DB_PATH, overrides={1: bad})

    def test_bool_override_rejected(self):
        with self.assertRaises(ValueError):
            load_points(DB_PATH, overrides={1: True})

    def test_db_sha256_matches_known_constant(self):
        # 只比对「前后不变」抓不到「库本来就被改过」，钉死验收常量。
        # 2026-11-09：S1/S2 迁移（建三张语义表 + assets 扩 9 列 + 词表）后换新常量；
        # 同日 S5 又写入了 2 张 fallback 占位图（assets 2 行 + asset_tags 2 行 +
        # v_fallback_assets 视图 + local_path 指向 assets/placeholders/），故再换一次。
        # 同日 S3 又把 assets/icons/ 下 4 个未登记基名（droplet/people/percent/pin）
        # 补登进 assets（id 25–28），故再换一次。
        # S4 给 11 个 icon 打了 85 条 asset_tags 并回填两个缓存列，故再换一次。
        # 迁移、占位图、登记、打标脚本都幂等，重跑不会改变这个值。
        self.assertEqual(
            _sha(DB_PATH).upper(),
            "45E875A2AFF56ADF6BEFCA1BD97C6B2E30D3DF793F8D5397B612C90B8ABE3195",
        )
