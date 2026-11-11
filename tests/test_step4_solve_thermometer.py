"""D.2 step 3b / E.3 #1 —— 线性求解器 + 温度计坐标求解 + build_pagespec 改造。

本步验收：
  * D.1 方案 ① 自写高斯消元求解 a·x = b（含奇异矩阵报错）；
  * D.2 步骤 3：solve() 用约束回填每个 ElementSpec 的 x/y/w/h；
  * D.2 步骤 2 改造：build_pagespec() 内部走「选模板 → 坐标无关骨架 → solve」，
    但对外仍返回 37 元素的合法 PageSpec（不破坏已交付闭环）；
  * C1/C2/C3/C4/C5/C6 全部有断言；
  * E.3 #1 换画布（10×6 → 10×4）与 n=20 反例。
  * E.3 #3 补遗「同一模板两份 spec constraints 相同、x_in 可以不同」的
    温度计半边（半圆那半边留到第 5 步）。

所有期望值都是按 C 节约束式手算的字面量，不调用被测代码推导。
"""
import os
import unittest

from pptx.util import Inches

from tests.scratch import mkdtemp
from loop.data_source import DB_PATH, load_points
from loop.models import PageSpec
from loop.render import render_pptx
from loop.scaffold import build_pagespec
from loop.solve import SolveError, solve_linear, build_skeleton, solve
from loop.templates import get_template
from loop.verify import read_shapes

_, PTS = load_points(DB_PATH)
T = get_template("thermometer")


def _pts(values):
    return [{"seq": i + 1, "label": f"项{i + 1}", "value": float(v), "unit": "倍(超)"}
            for i, v in enumerate(values)]


def _by_id(spec, eid):
    return next(e for e in spec.elements if e.id == eid)


# ---------------------------------------------------------------------------
# D.1 方案 ①：自写线性求解器（高斯消元 + 部分主元）
# ---------------------------------------------------------------------------
class TestGaussianSolver(unittest.TestCase):
    def test_solve_linear_2x2_hand_derived(self):
        # 2x + y = 5, x - y = 1  →  x=2, y=1（手算）。
        A = [[2.0, 1.0], [1.0, -1.0]]
        b = [5.0, 1.0]
        self.assertAlmostEqual(solve_linear(A, b)[0], 2.0, places=9)
        self.assertAlmostEqual(solve_linear(A, b)[1], 1.0, places=9)

    def test_solve_linear_3x3_needing_row_pivot(self):
        # 首个主元为 0，必须换主元：
        #   y + z = 3 ; x + y + z = 6 ; x + 2y = 5  → x=3, y=1, z=2（手算）。
        A = [[0.0, 1.0, 1.0], [1.0, 1.0, 1.0], [1.0, 2.0, 0.0]]
        b = [3.0, 6.0, 5.0]
        x = solve_linear(A, b)
        for got, want in zip(x, (3.0, 1.0, 2.0)):
            self.assertAlmostEqual(got, want, places=9)

    def test_solve_linear_singular_raises_solveerror(self):
        # 两行相同 → 奇异；不能静默返回垃圾解。
        with self.assertRaises(SolveError):
            solve_linear([[1.0, 1.0], [1.0, 1.0]], [2.0, 2.0])

    def test_solve_linear_rejects_rectangular_system(self):
        with self.assertRaises(SolveError):
            solve_linear([[1.0, 2.0, 3.0]], [1.0])


# ---------------------------------------------------------------------------
# D.2 步骤 2/3：坐标无关骨架 + solve() 回填
# ---------------------------------------------------------------------------
class TestSkeletonAndSolve(unittest.TestCase):
    def test_skeleton_has_no_absolute_coordinates(self):
        sk = build_skeleton(T, PTS, "heat_ratio_top5", "标题", 10.0, 6.0)
        self.assertTrue(sk.constraints)
        self.assertTrue(sk.layout)
        for e in sk.elements:
            self.assertEqual((e.x_in, e.y_in, e.w_in, e.h_in), (0.0, 0.0, 0.0, 0.0),
                             msg=f"{e.id}: 骨架里出现绝对坐标")
        liq = _by_id(sk, "liquid_1")
        self.assertIsNotNone(liq.geometry_expr)
        self.assertIsNotNone(liq.binding)

    def test_solve_skeleton_produces_37_elements_and_legal_geometry(self):
        sk = build_skeleton(T, PTS, "heat_ratio_top5", "标题", 10.0, 6.0)
        spec = solve(sk, PTS)
        self.assertEqual(len(spec.elements), 37)
        for e in spec.elements:
            self.assertGreaterEqual(e.x_in, 0.0)
            self.assertGreaterEqual(e.y_in, 0.0)

    def test_build_pagespec_records_constraints_layout_and_geometry_expr(self):
        spec = build_pagespec(PTS)
        # 审查修复：加结构字面量锚点，不只做「生产值比生产值」。
        self.assertEqual({c["id"] for c in spec.constraints},
                         {"C1", "DATA", "C3", "C4", "C5", "C6"})
        self.assertEqual(spec.constraints, T.constraints)
        self.assertIn("orient", spec.layout)
        self.assertIsNotNone(_by_id(spec, "liquid_1").geometry_expr)
        self.assertIsNotNone(spec.scale.factor)
        self.assertEqual(spec.scale.domain, [0.0, 11.0])


# ---------------------------------------------------------------------------
# C 节约束断言（全部手算字面量）
# ---------------------------------------------------------------------------
class TestThermometerConstraints(unittest.TestCase):
    def setUp(self):
        self.spec = build_pagespec(PTS, width_in=10.0, height_in=6.0)

    def test_C6_equal_spacing_d_is_2_18(self):
        # 手算 d_free = (10 − 2×0.5 − 0.28)/(5−1) = 8.72/4 = 2.18 > gap_min 0.5。
        xs = [_by_id(self.spec, f"track_{i}").x_in for i in range(1, 6)]
        for want, got in zip([0.5, 2.68, 4.86, 7.04, 9.22], xs):
            self.assertAlmostEqual(got, want, places=9)
        for a, b in zip(xs, xs[1:]):
            self.assertAlmostEqual(b - a, 2.18, places=9)

    def test_C1_all_elements_within_canvas(self):
        for e in self.spec.elements:
            self.assertGreaterEqual(e.x_in, 0.0, f"{e.id}: x < 0")
            self.assertGreaterEqual(e.y_in, 0.0, f"{e.id}: y < 0")
            self.assertLessEqual(e.x_in + e.w_in, 10.0, f"{e.id}: 右溢出")
            self.assertLessEqual(e.y_in + e.h_in, 6.0, f"{e.id}: 下溢出")

    def test_C4_vertical_stack_hand_derived(self):
        # 手算（报纸原版：类别名在管上方、0 点 = 球顶、真值在球下）：
        # y_title=0.5, y_note=0.5+0.5+0.15=1.15, y_label=1.15+0.3+0.2=1.65,
        # 0 点 y_bulb_top = 1.65+0.34+0.03+3.0 = 5.02,
        # y_track = 5.02−3.0 = 2.02, y_bulb = 5.02,
        # y_value = 5.02+0.52+0.03 = 5.57, 底部 5.57+0.18 = 5.75 ≤ 6.0。
        s = self.spec
        self.assertAlmostEqual(_by_id(s, "title").y_in, 0.5, places=9)
        self.assertAlmostEqual(_by_id(s, "scale_note").y_in, 1.15, places=9)
        for i in range(1, 6):
            self.assertAlmostEqual(_by_id(s, f"label_{i}").y_in, 1.65, places=9)
            self.assertAlmostEqual(_by_id(s, f"track_{i}").y_in, 2.02, places=9)
            self.assertAlmostEqual(_by_id(s, f"bulb_{i}").y_in, 5.02, places=9)
            self.assertAlmostEqual(_by_id(s, f"value_{i}").y_in, 5.57, places=9)

    def test_C4_liquid_sits_on_track_bottom(self):
        # C4 + 0 点：液柱底 = 球顶 = 管底 = 0 点 = 5.02。
        for i, v in zip(range(1, 6), [10.0, 3.0, 3.0, 3.0, 3.0]):
            liq = _by_id(self.spec, f"liquid_{i}")
            self.assertAlmostEqual(liq.y_in + liq.h_in, 5.02, places=9)
            self.assertAlmostEqual(liq.y_in + liq.h_in,
                                   _by_id(self.spec, f"bulb_{i}").y_in, places=9)
            self.assertAlmostEqual(liq.h_in, 3.0 * v / 11.0, places=9)

    def test_C5_centering_hand_derived(self):
        # 手算 x_bulb = x_track + (0.28−0.52)/2 = x_track−0.12；
        # x_label = x_track + (0.28−1.2)/2 = x_track−0.46。
        for i in range(1, 6):
            xt = _by_id(self.spec, f"track_{i}").x_in
            self.assertAlmostEqual(_by_id(self.spec, f"bulb_{i}").x_in,
                                   xt - 0.12, places=9)
            self.assertAlmostEqual(_by_id(self.spec, f"label_{i}").x_in,
                                   xt - 0.46, places=9)
            self.assertAlmostEqual(_by_id(self.spec, f"value_{i}").x_in,
                                   xt - 0.46, places=9)
            # C5 居中：x_label + w_label/2 == x_track + w_track/2
            self.assertAlmostEqual(
                _by_id(self.spec, f"label_{i}").x_in + 1.2 / 2,
                xt + 0.28 / 2, places=9)

    def test_C2_liquid_height_is_factor_times_binding_value(self):
        # 声明式表达式必须真的成立：h_in = scale.factor × binding.value。
        # 审查修复：加手算字面量锚点，避免「生产值比生产值」的 change-detector。
        self.assertAlmostEqual(self.spec.scale.factor, 3.0 / 11.0, places=9)
        for i, v in zip(range(1, 6), [10.0, 3.0, 3.0, 3.0, 3.0]):
            liq = _by_id(self.spec, f"liquid_{i}")
            self.assertEqual(liq.binding["value"], v)
            self.assertAlmostEqual(liq.h_in, 3.0 * v / 11.0, places=9)
            self.assertAlmostEqual(liq.h_in,
                                   self.spec.scale.factor * liq.binding["value"],
                                   places=9)

    def test_C3_no_clipping_linear_mapping(self):
        # 反削顶：h_i/v_i 恒定、全部 < H_track；v=V_max 才满管。
        liqs = [_by_id(self.spec, f"liquid_{i}") for i in range(1, 6)]
        k = 3.0 / 11.0
        for e in liqs:
            self.assertAlmostEqual(e.h_in / e.binding["value"], k, places=9)
            self.assertLess(e.h_in, 3.0)
        self.assertAlmostEqual(max(e.h_in for e in liqs), 30.0 / 11.0, places=9)

    def test_geometry_expr_is_a_declaration_not_a_baked_number(self):
        # E.1 ④：geometry_expr 存求解表达式，x/y/w/h 存求解结果。
        liq = _by_id(self.spec, "liquid_1")
        self.assertIn("scale.factor", liq.geometry_expr)
        self.assertIn("binding.value", liq.geometry_expr)

    def test_value_text_suffix_follows_the_data_unit(self):
        # 真值后缀必须来自数据单位：百分比数据不能渲染成「118倍」。
        pct = [{"seq": i + 1, "label": f"项{i + 1}", "value": float(v), "unit": "%"}
               for i, v in enumerate([118.0, 102.0, 84.0, 80.0, 65.0])]
        spec = build_pagespec(pct, chart_title="加热电器")
        self.assertEqual([_by_id(spec, f"value_{i}").text for i in range(1, 6)],
                         ["118%", "102%", "84%", "80%", "65%"])
        # 用户 m04818：说明文案面向读者，不再出现 V_max / 液柱高度 / 3.0 这类
        # 实现符号，改讲「怎么读这张图」。
        note = _by_id(spec, "scale_note").text
        self.assertIn("满格约 130%", note)
        self.assertIn("零点", note)
        self.assertNotIn("V_max", note)
        # 倍(超) 仍渲染成「倍」，保持已交付产物不变。
        self.assertEqual([_by_id(self.spec, f"value_{i}").text for i in range(1, 6)],
                         ["10倍", "3倍", "3倍", "3倍", "3倍"])


# ---------------------------------------------------------------------------
# E.3 #1：换画布 10×6 → 10×4
# ---------------------------------------------------------------------------
class TestE3Assertion1(unittest.TestCase):
    def test_height_4_all_elements_within_canvas(self):
        spec = build_pagespec(PTS, width_in=10.0, height_in=4.0)
        self.assertEqual(spec.height_in, 4.0)
        self.assertEqual(len(spec.elements), 37)
        for e in spec.elements:
            self.assertGreaterEqual(e.y_in, 0.0, f"{e.id}: y < 0")
            self.assertLessEqual(e.y_in + e.h_in, 4.0, f"{e.id}: 掉出画布")
            self.assertGreaterEqual(e.x_in, 0.0, f"{e.id}: x < 0")
            self.assertLessEqual(e.x_in + e.w_in, 10.0, f"{e.id}: 右溢出")

    def test_height_4_H_track_is_one_and_factor_follows(self):
        # 手算 min(3.0, 4 − 1.65 − 1.35) = 1.0 → factor 1.0/11.0。
        spec = build_pagespec(PTS, width_in=10.0, height_in=4.0)
        self.assertAlmostEqual(spec.scale.h_in, 1.0, places=9)
        self.assertAlmostEqual(spec.scale.factor, 1.0 / 11.0, places=9)
        for i, v in zip(range(1, 6), [10.0, 3.0, 3.0, 3.0, 3.0]):
            self.assertAlmostEqual(_by_id(spec, f"liquid_{i}").h_in,
                                   1.0 * v / 11.0, places=9)

    def test_height_4_spacing_and_labels_do_not_overlap(self):
        spec = build_pagespec(PTS, width_in=10.0, height_in=4.0)
        xs = [_by_id(spec, f"track_{i}").x_in for i in range(1, 6)]
        for a, b in zip(xs, xs[1:]):
            self.assertAlmostEqual(b - a, 2.18, places=9)
        labels = [_by_id(spec, f"label_{i}") for i in range(1, 6)]
        for a, b in zip(labels, labels[1:]):
            self.assertLessEqual(a.x_in + a.w_in, b.x_in,
                                 "相邻标签盒重叠")
        values = [_by_id(spec, f"value_{i}") for i in range(1, 6)]
        for lab, val in zip(labels, values):
            self.assertLessEqual(lab.y_in + lab.h_in, val.y_in,
                                 "标签与真值盒重叠")

    def test_height_4_pptx_shapes_all_within_canvas(self):
        spec = build_pagespec(PTS, width_in=10.0, height_in=4.0)
        d = mkdtemp(prefix="e3a1-")
        p = os.path.join(d, "loop1.pptx")
        render_pptx(spec, p)
        shapes = read_shapes(p)
        self.assertEqual(len(shapes), 37)
        for name, s in shapes.items():
            self.assertGreaterEqual(s["left"], 0, f"{name}: left < 0")
            self.assertGreaterEqual(s["top"], 0, f"{name}: top < 0")
            self.assertLessEqual(s["left"] + s["width"], Inches(10.0),
                                 f"{name}: 右溢出")
            self.assertLessEqual(s["top"] + s["height"], Inches(4.0),
                                 f"{name}: 掉出画布")

    def test_n20_raises_solveerror_on_build_pagespec(self):
        # 失败路径 1（E.3 #1 反例）：d_free≈0.447 < gap_min=0.5 → C1+C6。
        with self.assertRaises(SolveError) as ctx:
            build_pagespec(_pts([1.0] * 20))
        self.assertIn("C1", ctx.exception.conflicts)
        self.assertIn("C6", ctx.exception.conflicts)

    def test_n5_d_is_2_18_with_gap_min_0_5(self):
        # 拍板确认：gap_min 改 0.5 不影响已交付的 heat_ratio_top5 产物。
        spec = build_pagespec(PTS)
        xs = [_by_id(spec, f"track_{i}").x_in for i in range(1, 6)]
        self.assertAlmostEqual(xs[1] - xs[0], 2.18, places=9)


# ---------------------------------------------------------------------------
# E.3 #3 补遗（温度计半边）：同模板两份 spec constraints 相同、x_in 可不同
# ---------------------------------------------------------------------------
class TestE3Assertion3ThermometerHalf(unittest.TestCase):
    def test_same_template_same_constraints_different_x_for_different_canvas(self):
        a = build_pagespec(PTS, width_in=10.0, height_in=6.0)
        b = build_pagespec(PTS, width_in=12.0, height_in=6.0)
        self.assertEqual(a.constraints, b.constraints)
        self.assertNotEqual(_by_id(a, "track_2").x_in,
                            _by_id(b, "track_2").x_in)
        # W=12 手算 d = (12 − 1 − 0.28)/4 = 2.68 → x_track_2 = 0.5 + 2.68 = 3.18。
        self.assertAlmostEqual(_by_id(b, "track_2").x_in, 3.18, places=9)
        # 两份 spec 都合法。
        for e in b.elements:
            self.assertLessEqual(e.x_in + e.w_in, 12.0)

    def test_pagespec_roundtrip_preserves_new_fields(self):
        spec = build_pagespec(PTS)
        self.assertEqual(PageSpec.from_dict(spec.to_dict()).to_dict(), spec.to_dict())


if __name__ == "__main__":
    unittest.main()
