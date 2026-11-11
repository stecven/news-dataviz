import unittest

from loop.data_source import DB_PATH, load_points
from loop.scaffold import (GOAL_STUB, TRACK_H_IN, compute_scale,
                           liquid_height_in, build_pagespec)


class TestScale(unittest.TestCase):
    def test_vmax_is_eleven_for_ten_times(self):
        self.assertEqual(compute_scale([10.0, 3.0, 3.0, 3.0, 3.0]).v_max, 11.0)

    def test_liquid_height_is_proportional_and_not_clipped(self):
        s = compute_scale([10.0, 3.0, 3.0, 3.0, 3.0])
        h10, h3 = liquid_height_in(10.0, s), liquid_height_in(3.0, s)
        self.assertAlmostEqual(h10, 3.0 * 10.0 / 11.0, places=9)
        self.assertAlmostEqual(h10 / h3, 10.0 / 3.0, places=9)
        self.assertLess(h10, TRACK_H_IN)                 # 旧逻辑 ratio>=10 会画满 3.0

    def test_all_zero_values_do_not_divide_by_zero(self):
        s = compute_scale([0.0, 0.0])
        self.assertEqual(s.v_max, 1.0)
        self.assertEqual(liquid_height_in(0.0, s), 0.0)

    def test_override_extends_scale_and_recomputes_all(self):
        _, pts = load_points(DB_PATH, overrides={1: 12.0})
        spec = build_pagespec(pts)
        self.assertEqual(spec.scale.v_max, 14.0)
        liqs = {e.id: e for e in spec.elements if e.role == "liquid"}
        for seq, v in [(1, 12.0), (2, 3.0), (3, 3.0), (4, 3.0), (5, 3.0)]:
            self.assertAlmostEqual(liqs[f"liquid_{seq}"].h_in, 3.0 * v / 14.0, places=9)

    # 用户 m00260 追加约束 #1：反削顶必须是测试断言，不靠人眼 / grep。
    # 会致其失败的「生产变更」：任何形如 `h = min(v, cap)`、`v >= 10 → 画满`、
    # 固定高度、或对某个值单独缩放的分支，都会破坏 h_i/v_i 恒定或 < 3.0 的断言。
    def test_no_clipping_is_asserted_linearly_across_all_37_elements(self):
        _, pts = load_points(DB_PATH)
        spec = build_pagespec(pts)
        self.assertEqual(len(spec.elements), 37)
        liqs = [e for e in spec.elements if e.role == "liquid"]
        self.assertEqual(len(liqs), 5)
        k = TRACK_H_IN / spec.scale.v_max                 # 手算常量 3.0/11.0
        for e in liqs:
            v = e.binding["value"]
            self.assertAlmostEqual(e.h_in / v, k, places=9,
                                   msg=f"{e.id}: 液柱高度与数值不成线性")
            self.assertAlmostEqual(e.h_in, liquid_height_in(v, spec.scale), places=9)
            self.assertLess(e.h_in, TRACK_H_IN,
                            msg=f"{e.id}: 出现画满/削顶（h_in == 管身高度）")
        heights = [e.h_in for e in liqs]
        self.assertAlmostEqual(max(heights), 3.0 * 10.0 / 11.0, places=9)  # 2.727 < 3.0
        # 只有「取值恰好等于量程上限」的柱子才满管；实际数据集中没有这样的值。
        self.assertAlmostEqual(liquid_height_in(spec.scale.v_max, spec.scale),
                               TRACK_H_IN, places=9)


class TestSpecGeometry(unittest.TestCase):
    def setUp(self):
        _, pts = load_points(DB_PATH)
        self.spec = build_pagespec(pts)

    def test_37_elements_with_unique_ids(self):
        ids = [e.id for e in self.spec.elements]
        self.assertEqual(len(ids), 37)
        self.assertEqual(len(set(ids)), 37)

    # 审查发现：track / scale_note 里字面写死 3.0，改 TRACK_H_IN 会失配。
    def test_track_h_constant_is_used_everywhere(self):
        tracks = [e for e in self.spec.elements if e.role == "track"]
        self.assertEqual(len(tracks), 5)
        for e in tracks:
            self.assertEqual(e.h_in, TRACK_H_IN)
        note = next(e.text for e in self.spec.elements if e.role == "scale_note")
        # 说明文案（用户 m04818）改讲读法，但几何量仍必须来自 TRACK_H_IN：
        # 满格数字取自 v_max，管线高度取自 track 的 h_in。
        self.assertIn("满格约", note)
        self.assertNotIn("V_max", note)

    def test_five_liquid_roles_and_bindings(self):
        liqs = [e for e in self.spec.elements if e.role == "liquid"]
        self.assertEqual(len(liqs), 5)
        self.assertEqual([e.binding["value"] for e in liqs], [10.0, 3.0, 3.0, 3.0, 3.0])
        self.assertEqual(liqs[0].binding["chart_key"], "heat_ratio_top5")

    def test_goal_stub_is_fixed_to_thermometer(self):
        self.assertEqual(GOAL_STUB["chart_type"], "thermometer")
        self.assertFalse(GOAL_STUB["fallback_used"])
        self.assertEqual(GOAL_STUB["semantic_tags"], [])
