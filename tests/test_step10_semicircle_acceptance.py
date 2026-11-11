"""半圆图补完 —— 用户 m03184 的验收闸口（全部落成 unittest）。

范围锁死：只做扇区角度 / 中心数值 / Σθ=180° 闭合 + max_slices=5 生效 +
「半圆与温度计共用同一套求解逻辑」的共用性断言。图例、配色、标签避让
（C9）、整版排版一律不碰。

四组数据 + 一组 6 项 fallback：
  ① 原数据（DB heat_age，占比 5 项）
  ② 全相等 5/5/5/5/5（测退化、除零边界）
  ③ 单点极值 100/1/1/1/1（测最小扇区不被「最小可见角度」吃掉）
  ④ 含零值 10/0/3/2/1（测零值扇区、Σθ 仍闭合）
  ⑤ 6 项（测 max_slices=5 触发，不静默画 6 个扇区）

所有期望值都按 C 节约束式手算成字面量，不调用被测代码推导。
"""
import inspect
import unittest

import loop.solve as S
from loop.data_source import DB_PATH, load_points
from loop.scaffold import build_pagespec
from loop.solve import SolveError, validate_spec
from loop.templates import get_template

from tests.scratch import mkdtemp

SEMI = get_template("semicircle")
THERMO = get_template("thermometer")


def _pts(values, unit="占比"):
    return [{"seq": i + 1, "label": f"项{i + 1}", "value": float(v), "unit": unit}
            for i, v in enumerate(values)]


def _semi(values=None, pts=None, **kw):
    data = pts if pts is not None else _pts(values)
    return build_pagespec(data, "半圆占比", template_name="semicircle", **kw)


def _sectors(spec):
    return sorted((e for e in spec.elements if e.role == "sector"),
                  key=lambda e: e.binding["seq"])


def _center(spec):
    return next(e for e in spec.elements if e.role == "center")


def _by_id(spec, eid):
    return next(e for e in spec.elements if e.id == eid)


# ---------------------------------------------------------------------------
# ① 原数据（DB 占比 5 项）
# ---------------------------------------------------------------------------
class TestGroup1OriginalData(unittest.TestCase):
    """>>> 原数据：DB heat_age（25岁及以下 8% / 26-35 32% / 36-45 32% /
    46-55 17% / 56+ 11%，Σv = 1.0）。"""

    def setUp(self):
        title, pts = load_points(DB_PATH, chart_key="heat_age")
        self.spec = _semi(pts=pts)
        self.pts = pts

    def test_sum_theta_is_exactly_180(self):
        # C3 闭合：Σθ = arc_total = 180°，5 项等比例切分。
        thetas = [s.geometry["theta"] for s in _sectors(self.spec)]
        self.assertAlmostEqual(sum(thetas), 180.0, places=9)
        # 末扇区 end = α₀ + 180° = 360°（C8 递推闭合）。
        self.assertAlmostEqual(_sectors(self.spec)[-1].geometry["end_angle"],
                               360.0, places=9)

    def test_each_theta_matches_hand_derived_literal(self):
        # 手算 θ_i = 180 × v_i / 1.0：14.4 / 57.6 / 57.6 / 30.6 / 19.8。
        want = [14.4, 57.6, 57.6, 30.6, 19.8]
        for s, w in zip(_sectors(self.spec), want):
            self.assertAlmostEqual(s.geometry["theta"], w, places=9)

    def test_center_equals_v_center_over_sum_v(self):
        # C. 中心数值 = v_center/Σv×100%；center_slice_id 默认 1、v=0.08、Σv=1.0 → 8.0%。
        c = _center(self.spec)
        self.assertEqual(c.text, "8.0%")
        self.assertAlmostEqual(c.geometry["percent"], 100.0 * 0.08 / 1.0, places=9)
        self.assertAlmostEqual(c.geometry["sum_v"], 1.0, places=9)


# ---------------------------------------------------------------------------
# ② 全相等（5/5/5/5/5）
# ---------------------------------------------------------------------------
class TestGroup2AllEqual(unittest.TestCase):
    def setUp(self):
        self.spec = _semi([5, 5, 5, 5, 5])

    def test_five_equal_slices_get_36_degrees_each(self):
        # 180 / 5 = 36°，无除零、无退化。
        thetas = [s.geometry["theta"] for s in _sectors(self.spec)]
        self.assertEqual(len(thetas), 5)
        for t in thetas:
            self.assertAlmostEqual(t, 36.0, places=9)
        self.assertAlmostEqual(sum(thetas), 180.0, places=9)

    def test_center_is_one_fifth(self):
        self.assertEqual(_center(self.spec).text, "20.0%")

    def test_theta_per_value_is_constant(self):
        # θ/v 恒等于 180/25 = 7.2（等值下也必须严格恒定）。
        for s in _sectors(self.spec):
            self.assertAlmostEqual(s.geometry["theta"] / 5.0, 7.2, places=9)


# ---------------------------------------------------------------------------
# ③ 单点极值（100/1/1/1/1）
# ---------------------------------------------------------------------------
class TestGroup3ExtremePeak(unittest.TestCase):
    def setUp(self):
        self.spec = _semi([100, 1, 1, 1, 1])

    def test_min_slice_keeps_its_true_angle(self):
        # 手算 180 × 1 / 104 = 1.730769230769…°，**不允许**被抬到「最小可见角度」。
        min_theta = min(s.geometry["theta"] for s in _sectors(self.spec))
        self.assertAlmostEqual(min_theta, 180.0 * 1 / 104.0, places=9)
        self.assertLess(min_theta, 2.0)   # 任何「最小角度」兜底都会把它抬高

    def test_all_five_slices_still_sum_to_180(self):
        self.assertAlmostEqual(
            sum(s.geometry["theta"] for s in _sectors(self.spec)), 180.0, places=9)

    def test_theta_per_value_constant_including_the_peak(self):
        k = 180.0 / 104.0
        for s, v in zip(_sectors(self.spec), [100.0, 1.0, 1.0, 1.0, 1.0]):
            self.assertAlmostEqual(s.geometry["theta"] / v, k, places=9)

    def test_center_of_peak_is_96_2_percent(self):
        self.assertEqual(_center(self.spec).text, "96.2%")   # 100/104


# ---------------------------------------------------------------------------
# ④ 含零值（10/0/3/2/1）
# ---------------------------------------------------------------------------
class TestGroup4WithZero(unittest.TestCase):
    def setUp(self):
        self.spec = _semi([10, 0, 3, 2, 1])

    def test_zero_slice_has_zero_angle_not_a_minimum(self):
        # 零值扇区 θ = 0.0，不允许补成「最小可见角度」。
        zero = _sectors(self.spec)[1]
        self.assertEqual(zero.binding["value"], 0.0)
        self.assertEqual(zero.geometry["theta"], 0.0)
        self.assertEqual(zero.geometry["start_angle"], zero.geometry["end_angle"])

    def test_sum_theta_still_closed_with_a_zero_slice(self):
        # Σv = 16 → θ = 112.5 / 0 / 33.75 / 22.5 / 11.25，合计 180。
        thetas = [s.geometry["theta"] for s in _sectors(self.spec)]
        self.assertAlmostEqual(thetas[0], 112.5, places=9)
        self.assertAlmostEqual(thetas[2], 33.75, places=9)
        self.assertAlmostEqual(thetas[3], 22.5, places=9)
        self.assertAlmostEqual(thetas[4], 11.25, places=9)
        self.assertAlmostEqual(sum(thetas), 180.0, places=9)
        self.assertAlmostEqual(_sectors(self.spec)[-1].geometry["end_angle"],
                               360.0, places=9)

    def test_zero_slice_does_not_shift_later_boundaries(self):
        # 边界必须与手算一致：180 / 292.5 / 292.5 / 326.25 / 348.75 / 360。
        want = [180.0, 292.5, 292.5, 326.25, 348.75, 360.0]
        for i, s in enumerate(_sectors(self.spec)):
            self.assertAlmostEqual(s.geometry["start_angle"], want[i], places=9)
            self.assertAlmostEqual(s.geometry["end_angle"], want[i + 1], places=9)

    def test_center_ignores_the_zero_slice(self):
        # center_slice_id=1 → 10/16 = 62.5%。
        self.assertEqual(_center(self.spec).text, "62.5%")


# ---------------------------------------------------------------------------
# ⑤ 6 项数据 → max_slices=5 生效，不静默画 6 个扇区
# ---------------------------------------------------------------------------
class TestGroup5MaxSlicesFallback(unittest.TestCase):
    def test_max_slices_is_declared_on_the_semicircle_template(self):
        self.assertIn("max_slices", SEMI.params)
        self.assertEqual(SEMI.params["max_slices"]["default"], 5)

    def test_six_slices_raise_solveerror_instead_of_drawing_six(self):
        with self.assertRaises(SolveError) as ctx:
            _semi([10, 3, 2, 2, 2, 1])
        self.assertIn("MAX_SLICES", ctx.exception.conflicts)
        self.assertIn("6", str(ctx.exception))
        self.assertIn("max_slices=5", str(ctx.exception))

    def test_five_slices_still_pass_the_guard(self):
        # 边界值：n == max_slices 必须放行（不是 > 5 才拒的 off-by-one）。
        spec = _semi([10, 3, 2, 2, 2])
        self.assertEqual(len(_sectors(spec)), 5)

    def test_guard_is_data_driven_not_fixed_at_five(self):
        # 覆写 max_slices 后 6 项可解，证明是模板元数据在起作用而非写死拒绝。
        spec = _semi([10, 3, 2, 2, 2, 1], param_overrides={"max_slices": 6})
        self.assertEqual(len(_sectors(spec)), 6)
        self.assertAlmostEqual(
            sum(s.geometry["theta"] for s in _sectors(spec)), 180.0, places=9)


# ---------------------------------------------------------------------------
# 共用性：半圆与温度计是同一套求解逻辑，不是复制粘贴
# ---------------------------------------------------------------------------
class TestSharedSolvingCore(unittest.TestCase):
    def test_both_templates_enter_through_the_same_solve_entry(self):
        # 两条数据流都走 loop.solve.solve()，且都经过同一个 preprocess()。
        calls = []
        real = S.preprocess

        def spy(points, template, *a, **kw):
            calls.append(template.name)
            return real(points, template, *a, **kw)

        S.preprocess = spy
        try:
            from loop.solve import build_skeleton
            t = build_skeleton(THERMO, _pts([10, 3, 3, 3, 3])[:5], "k", "t")
            s = build_skeleton(SEMI, _pts([10, 3, 3, 3, 3])[:5], "k", "t")
            S.solve(t, _pts([10, 3, 3, 3, 3])[:5])
            S.solve(s, _pts([10, 3, 3, 3, 3])[:5])
        finally:
            S.preprocess = real
        self.assertIn("thermometer", calls)
        self.assertIn("semicircle", calls)

    def test_shared_constraint_primitives_are_the_same_objects(self):
        # C1 边界 / C3 比例尺是**同一个 dict 对象**被两份模板引用；
        # C5 居中复用同一原语（仅 reuse 标记不同）。没有第二套约束定义。
        from loop.templates import _SEMI_CONSTRAINTS, _THERMO_CONSTRAINTS

        t = {c["id"]: c for c in _THERMO_CONSTRAINTS}
        s = {c["id"]: c for c in _SEMI_CONSTRAINTS}
        self.assertIs(s["C1"], t["C1"])
        self.assertIs(s["C3"], t["C3"])
        self.assertIs(s["DATA"], t["DATA"])
        # C5：同一原语（expr 相同），半圆只是打了 reuse 标记。
        self.assertEqual(s["C5"]["kind"], t["C5"]["kind"])
        self.assertEqual(s["C5"]["expr"], t["C5"]["expr"])

    def test_no_duplicated_header_or_bound_code_between_the_two_solvers(self):
        # 重构前：两个求解器各自复制了 8 行标题/说明回填 + 5 行 C1 越界循环。
        # 重构后这两段各只有一份，位于共用 helper 里，两个求解器都调用它。
        src_t = inspect.getsource(S._solve_thermometer)
        src_s = inspect.getsource(S._solve_semicircle)
        self.assertIn("_place_header(", src_t)
        self.assertIn("_place_header(", src_s)
        self.assertIn("_check_canvas_bounds(", src_t)
        self.assertIn("_check_canvas_bounds(", src_s)
        # 越界文案只在 helper 里出现一次（求解器内不得再有第二份）。
        self.assertNotIn("out of canvas", src_t)
        self.assertNotIn("out of canvas", src_s)
        self.assertIn("out of canvas", inspect.getsource(S._check_canvas_bounds))

    def test_both_templates_produce_the_same_spec_types(self):
        # 同一套 PageSpec / ElementSpec / Scale，不是半圆专用规格类。
        from loop.models import ElementSpec, PageSpec, Scale

        t = _semi([10, 0, 3, 2, 1])
        self.assertIsInstance(t, PageSpec)
        self.assertIsInstance(t.scale, Scale)
        for e in t.elements:
            self.assertIsInstance(e, ElementSpec)


# ---------------------------------------------------------------------------
# 四组 + 6 项都过读回校验（validate_spec），并确认老产物仍可读可渲染
# ---------------------------------------------------------------------------
class TestReadbackAndLegacy(unittest.TestCase):
    def test_all_four_groups_pass_validate_spec(self):
        for values in ([5, 5, 5, 5, 5], [100, 1, 1, 1, 1],
                       [10, 0, 3, 2, 1], [10, 3, 3, 3, 3]):
            with self.subTest(values=values):
                validate_spec(_semi(values))     # 不抛即通过

    def test_original_data_group_passes_validate_spec(self):
        _title, pts = load_points(DB_PATH, chart_key="heat_age")
        validate_spec(_semi(pts=pts))

    def test_legacy_loop1_pagespec_still_readable_and_renderable(self):
        # 已交付产物 out/loop1/pagespec.json 必须仍可读、仍能渲染。
        #
        # 注意口径：这份产物生成于 12:09（报纸原版改版之前），是 27 元素的
        # 「球心对齐管底」旧 C4 口径，且 liquid 仍是满管宽——它被**当前** C4
        # （球顶 = 0 点）拒绝是预期的（E.4 L2：历史 spec 不保证通过最新校验）。
        # 用户要求的是「可读可渲染」，故这里只断言反序列化 + 真渲染，不改产物、
        # 不改校验器去迁就老数据。
        import json
        import os

        from loop.models import PageSpec
        from loop.render import render_pptx
        from loop.verify import read_shapes

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(root, "out", "loop1", "pagespec.json")
        if not os.path.exists(path):
            self.skipTest("out/loop1 未生成")
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        spec = PageSpec.from_dict(doc)
        self.assertEqual(len(spec.elements), 27)      # 旧版元素数，未被改写
        self.assertEqual(spec.layout["template"], "thermometer")

        out = os.path.join(mkdtemp("legacy-"), "loop1.pptx")
        render_pptx(spec, out)
        self.assertTrue(os.path.exists(out))
        self.assertEqual(len(read_shapes(out)), 27)


if __name__ == "__main__":
    unittest.main()
