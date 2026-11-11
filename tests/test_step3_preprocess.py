"""D.2 step 3a — solve() 的数据聚合预处理（把聚合结果当常量喂约束矩阵）。

设计文档 D.2 步骤 3 / C.2 小结 / C7 硬规则：V_max、Σv、n、d、R 全部在
**预处理阶段算成常量**，求解器只解线性等式 / 不等式，不处理 min/max/ceil
分支。本步同时覆盖用户点名的两条失败路径：n=20 → SolveError(C1+C6)、
Σv=0 → 抛错。所有期望值都是手算字面量，不调用被测代码推导。
"""


def _pts(values):
    return [{"seq": i + 1, "label": f"项{i + 1}", "value": float(v), "unit": "倍(超)"}
            for i, v in enumerate(values)]


import unittest

from loop.data_source import DB_PATH, load_points
from loop.solve import SolveError, preprocess
from loop.templates import get_template

THERMO = get_template("thermometer")
SEMI = get_template("semicircle")


class TestPreprocessConstants(unittest.TestCase):
    def setUp(self):
        _, pts = load_points(DB_PATH)
        self.pts = pts
        self.p = preprocess(pts, THERMO, 10.0, 6.0)

    def test_n_is_the_row_count(self):
        self.assertEqual(self.p["n"], 5)

    def test_vmax_is_ceiled_eleven_for_ten_times(self):
        # 手算 ceil(10.0 × 1.1) = 11.0（用 top*11/10 避开浮点陷阱）。
        self.assertEqual(self.p["v_max"], 11.0)

    def test_vmax_recomputes_when_override_raises_max_to_twelve(self):
        # 手算 ceil(12.0 × 1.1) = ceil(13.2) = 14.0（E.3 #2）。
        _, pts = load_points(DB_PATH, overrides={1: 12.0})
        self.assertEqual(preprocess(pts, THERMO, 10.0, 6.0)["v_max"], 14.0)

    def test_thermometer_factor_is_htrack_over_vmax(self):
        # 手算 3.0 / 11.0。
        self.assertAlmostEqual(self.p["factor"], 3.0 / 11.0, places=9)

    def test_thermometer_factor_recomputes_with_vmax(self):
        # 手算 3.0 / 14.0（E.3 #2：scale.factor 自动由 3/11 变 3/14）。
        _, pts = load_points(DB_PATH, overrides={1: 12.0})
        self.assertAlmostEqual(preprocess(pts, THERMO, 10.0, 6.0)["factor"],
                               3.0 / 14.0, places=9)

    def test_sum_v_is_the_data_sum(self):
        # 手算 10 + 3 + 3 + 3 + 3 = 22.0。
        self.assertEqual(self.p["sum_v"], 22.0)

    def test_semicircle_factor_is_180_over_sum_v(self):
        # C2 两阶段：S = Σv 预处理成常量，θ_i = (180/S)·v_i，Σv 不进矩阵。
        self.assertAlmostEqual(preprocess(self.pts, SEMI, 10.0, 6.0)["factor"],
                               180.0 / 22.0, places=9)

    def test_d_at_n5_is_hand_derived_2_125(self):
        # C6 手算 d_free = (10 − 2×0.5 − 0.28)/(5−1) = 8.72/4 = 2.18 > gap_min 0.5。
        # （0.28 为报纸原版细管宽；0 点在球顶的竖向模型不改变水平 pitch。）
        self.assertAlmostEqual(self.p["d"], 2.18, places=9)

    def test_d_shrinks_when_row_count_grows(self):
        # E.2「换数据自动重排」：6 行手算 d_free = 8.72/5 = 1.744。
        self.assertAlmostEqual(preprocess(_pts([10, 3, 3, 3, 3, 3]),
                                          THERMO, 10.0, 6.0)["d"], 1.744, places=9)

    def test_R_is_min_of_half_width_and_available_height(self):
        # C7 审查修复：R 为标题/说明预留 top_reserve(1.65) 与 bottom_margin(0.25)，
        # 手算 min((10−1)/2=4.5, (6−1.65−0.25)/2=2.05) = 2.05。
        self.assertAlmostEqual(self.p["R"], 2.05, places=9)

    def test_R_recomputes_when_canvas_shrinks(self):
        # 换画布 10×6 → 10×4：min(4.5, (4−1.9)/2=1.05) = 1.05。
        self.assertAlmostEqual(preprocess(self.pts, SEMI, 10.0, 4.0)["R"], 1.05,
                               places=9)

    def test_H_track_is_three_at_height_six(self):
        # 手算 TOP_RESERVE = m+h_title+g_title+h_note+g_note = 1.65，
        # BELOW_STACK = bulb_d/2+g_label+h_label+g_value+h_value+bottom_margin = 1.35，
        # min(3.0, 6 − 1.65 − 1.35) = min(3.0, 3.0) = 3.0（保住旧闭环）。
        self.assertAlmostEqual(self.p["H_track"], 3.0, places=9)

    def test_H_track_fits_a_four_inch_canvas(self):
        # E.3 #1：手算 min(3.0, 4 − 1.65 − 1.35) = 1.0。
        self.assertEqual(preprocess(self.pts, THERMO, 10.0, 4.0)["H_track"], 1.0)

    def test_factor_follows_H_track_on_short_canvas(self):
        # 手算 1.0 / 11.0：换画布后比例尺跟着重算，不是烘焙的 3/11。
        self.assertAlmostEqual(preprocess(self.pts, THERMO, 10.0, 4.0)["factor"],
                               1.0 / 11.0, places=9)

    def test_n1_does_not_divide_by_zero(self):
        # n=1 时 (n−1)=0，d 必须定义为 0 而不是崩在除法上。
        self.assertEqual(preprocess(_pts([10.0]), THERMO, 10.0, 6.0)["d"], 0.0)


class TestPreprocessFailures(unittest.TestCase):
    # 用户点名失败路径 1：n=20 抛 SolveError（冲突编号 C1+C6）。
    def test_n20_raises_solveerror_with_conflicts_c1_and_c6(self):
        # 手算 d_free = 8.5/19 ≈ 0.447 < gap_min=0.5 → d=0.5，
        # 总宽 (20−1)×0.5 + 0.5 = 10.0 > W−2m = 9.0 → 无解。
        with self.assertRaises(SolveError) as ctx:
            preprocess(_pts([1.0] * 20), THERMO, 10.0, 6.0)
        self.assertIn("C1", ctx.exception.conflicts)
        self.assertIn("C6", ctx.exception.conflicts)

    def test_n19_also_overruns_and_reports_c1_c6(self):
        # 手算 18×0.5 + 0.5 = 9.5 > 9.0。
        with self.assertRaises(SolveError) as ctx:
            preprocess(_pts([1.0] * 19), THERMO, 10.0, 6.0)
        self.assertIn("C6", ctx.exception.conflicts)

    # 用户点名失败路径 2：Σv = 0 抛错。
    def test_sum_v_zero_on_semicircle_raises_solveerror(self):
        # Σv 是半圆角度的除数；为 0 时不能静默产出（D.3）。
        with self.assertRaises(SolveError) as ctx:
            preprocess(_pts([0.0, 0.0, 0.0]), SEMI, 10.0, 6.0)
        self.assertIn("C2", ctx.exception.conflicts)

    def test_negative_sum_v_on_semicircle_raises_solveerror(self):
        with self.assertRaises(SolveError):
            preprocess(_pts([2.0, -5.0]), SEMI, 10.0, 6.0)

    def test_thermometer_all_zero_values_are_still_allowed(self):
        # D.3「非正值 v ≤ 0 沿用物理下界守 0，不删数据点」：温度计允许。
        p = preprocess(_pts([0.0, 0.0]), THERMO, 10.0, 6.0)
        self.assertEqual(p["v_max"], 1.0)
        self.assertEqual(p["sum_v"], 0.0)

    def test_non_finite_value_raises_solveerror(self):
        with self.assertRaises(SolveError):
            preprocess(_pts([float("nan")]), THERMO, 10.0, 6.0)

    def test_empty_points_raises_solveerror(self):
        with self.assertRaises(SolveError):
            preprocess([], THERMO, 10.0, 6.0)
