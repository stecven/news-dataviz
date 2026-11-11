"""D.2 step 3b（半圆图）/ E.3 #2、#3、#4 —— 半圆约束求解 + arc 扇区适配器。

本步验收：
  * 同一个 solve() 喂半圆模板，产出合法 PageSpec（C1 边界内）；
  * C2 两阶段 / C3 闭合 / C4 相邻 / C5 居中 / C7 半径随画布 / C8 扇角递推
    全部有手算字面量断言；
  * E.3 #2 半圆「换数据 → 180°/Σv 重算、Σθ=180° 闭合、无削顶」；
  * E.3 #3 半圆「同一 solve() 两份模板、复用 C1/C4/C5、同模板两份 spec
    constraints 相同 x_in 可不同」；
  * E.3 #4 中心数值 = v_center/Σv×100% 实时归一，禁止写死「80%」；
  * arc 扇区适配器产出 5 个原生 PIE 形状，角度写进 adjustments；
  * 失败路径：Σv=0 经 build_pagespec 抛 SolveError；n=20 经 C1 抛 SolveError。

所有期望值都是按 C 节约束式手算的字面量，不调用被测代码推导。
"""
import json
import os
import unittest

from tests.scratch import mkdtemp
from loop import build_loop as BL
from loop.data_source import DB_PATH, load_points
from loop.scaffold import build_pagespec
from loop.solve import SolveError, build_skeleton, solve
from loop.templates import get_template
from loop.verify import read_shapes

_, PTS = load_points(DB_PATH)
THERMO = get_template("thermometer")
SEMI = get_template("semicircle")


def _pts(values):
    return [{"seq": i + 1, "label": f"项{i + 1}", "value": float(v), "unit": "倍(超)"}
            for i, v in enumerate(values)]


def _by_id(spec, eid):
    return next(e for e in spec.elements if e.id == eid)


def _semi(values=None, W=10.0, H=6.0, param_overrides=None):
    pts = _pts(values) if values is not None else PTS
    return build_pagespec(pts, "半圆占比", template_name="semicircle",
                          width_in=W, height_in=H,
                          param_overrides=param_overrides)


# ---------------------------------------------------------------------------
# 半圆几何：骨架 → solve() → 具体坐标 / 角度
# ---------------------------------------------------------------------------
class TestSemicircleGeometry(unittest.TestCase):
    def setUp(self):
        self.spec = _semi()

    def test_element_count_and_roles(self):
        # 2 全局文本 + 1 中心 + 5 扇区 + 5 图例 = 13。
        self.assertEqual(len(self.spec.elements), 13)
        self.assertEqual(len([e for e in self.spec.elements if e.role == "sector"]), 5)
        self.assertEqual(len([e for e in self.spec.elements if e.role == "legend"]), 5)
        self.assertEqual(len([e for e in self.spec.elements if e.role == "center"]), 1)
        for i in range(1, 6):
            self.assertEqual(_by_id(self.spec, f"sector_{i}").type, "arc")

    def test_C1_all_elements_within_canvas(self):
        # 手算扇区盒 (cx−R, m, 2R, 2R) = (2.5, 0.5, 5.0, 5.0)，
        # 右下角 (7.5, 5.5) ≤ (10, 6)；图例盒右下角 (9.5, 3.55) 也在界内。
        for e in self.spec.elements:
            self.assertGreaterEqual(e.x_in, 0.0, f"{e.id}: x < 0")
            self.assertGreaterEqual(e.y_in, 0.0, f"{e.id}: y < 0")
            self.assertLessEqual(e.x_in + e.w_in, 10.0, f"{e.id}: 右溢出")
            self.assertLessEqual(e.y_in + e.h_in, 6.0, f"{e.id}: 下溢出")

    def test_C7_radius_follows_canvas(self):
        # 手算 R = min((W−2m)/2, (H−top_reserve−bottom_margin)/2)：
        # 10×6 → min(4.5, (6−1.65−0.25)/2=2.05) = 2.05；
        # 10×4 → min(4.5, (4−1.9)/2=1.05) = 1.05。
        s1 = _by_id(self.spec, "sector_1")
        self.assertAlmostEqual(s1.geometry["R"], 2.05, places=9)
        self.assertAlmostEqual(s1.w_in, 4.1, places=9)     # 2R
        self.assertAlmostEqual(s1.h_in, 4.1, places=9)
        self.assertAlmostEqual(s1.x_in, 2.95, places=9)    # cx−R = 5−2.05
        self.assertAlmostEqual(s1.y_in, 1.65, places=9)    # top_reserve
        short = _semi(W=10.0, H=4.0)
        s2 = _by_id(short, "sector_1")
        self.assertAlmostEqual(s2.geometry["R"], 1.05, places=9)
        self.assertAlmostEqual(s2.w_in, 2.1, places=9)
        self.assertAlmostEqual(s2.y_in + s2.h_in, 3.75, places=9)  # ≤ 4.0

    def test_C8_arc_recurrence_hand_derived(self):
        # Σv=22, factor=180/22, α₀=180（设计文档 C8）；
        # θ=[81.81818,24.54545×4] → 边界 180/261.81818/286.36363/
        # 310.90909/335.45454/360（手算）。
        bounds = [180.0, 261.8181818181818, 286.3636363636364,
                  310.9090909090909, 335.4545454545455, 360.0]
        for i in range(1, 6):
            g = _by_id(self.spec, f"sector_{i}").geometry
            self.assertAlmostEqual(g["start_angle"], bounds[i - 1], places=6)
            self.assertAlmostEqual(g["end_angle"], bounds[i], places=6)
        # 递推闭合：上一扇区的 end == 下一扇区的 start。
        for i in range(1, 5):
            self.assertAlmostEqual(
                _by_id(self.spec, f"sector_{i}").geometry["end_angle"],
                _by_id(self.spec, f"sector_{i+1}").geometry["start_angle"], places=6)

    def test_C3_sum_theta_is_closed_at_180(self):
        # 手算 Σθ_i = 180°（C3 闭合），末扇区 end=360（α₀=180+180）。
        thetas = [_by_id(self.spec, f"sector_{i}").geometry["theta"] for i in range(1, 6)]
        self.assertAlmostEqual(sum(thetas), 180.0, places=6)
        self.assertAlmostEqual(_by_id(self.spec, "sector_5").geometry["end_angle"],
                               360.0, places=6)

    def test_C2_theta_per_value_is_constant(self):
        # θ_i/v_i 恒等于 180/22（线性、无削顶）。
        k = 180.0 / 22.0
        for i, v in zip(range(1, 6), [10.0, 3.0, 3.0, 3.0, 3.0]):
            e = _by_id(self.spec, f"sector_{i}")
            self.assertEqual(e.binding["value"], v)
            self.assertAlmostEqual(e.geometry["theta"] / v, k, places=9)
            self.assertGreater(e.geometry["theta"], 0.0)
            self.assertLess(e.geometry["theta"], 180.0)

    def test_C5_center_box_centered_on_pie(self):
        # 中心盒 (cx−R, cy−h_center, 2R, h_center)；居中即 x+w/2 == cx。
        # 审查修复：R 让出 top_reserve 后 R=2.05，cx=5.0，x=2.95，w=4.1；
        # cy = top_reserve + R = 1.65 + 2.05 = 3.7 → y = 3.7 − 0.4 = 3.3。
        c = _by_id(self.spec, "center")
        cx = _by_id(self.spec, "sector_1").geometry["cx"]
        self.assertAlmostEqual(c.x_in + c.w_in / 2, cx, places=9)
        self.assertAlmostEqual(c.x_in, 2.95, places=9)
        self.assertAlmostEqual(c.w_in, 4.1, places=9)
        self.assertAlmostEqual(c.y_in, 3.3, places=9)

    def test_C4_legend_rows_stacked_with_fixed_gap(self):
        # 图例行 y_i = top_reserve + i×(h_legend+gap_legend) = 1.65 + 0.4i。
        ys = [_by_id(self.spec, f"legend_{i}").y_in for i in range(1, 6)]
        for want, got in zip([1.65, 2.05, 2.45, 2.85, 3.25], ys):
            self.assertAlmostEqual(got, want, places=9)
        for a, b in zip(ys, ys[1:]):
            self.assertAlmostEqual(b - a, 0.4, places=9)
        self.assertAlmostEqual(_by_id(self.spec, "legend_5").y_in + 0.3, 3.55, places=9)

    def test_scale_note_reports_arc_total_not_liquid_height(self):
        # 半圆量程说明应讲扇角总和，不能出现温度计的「液柱高度 0.0」。
        note = _by_id(self.spec, "scale_note").text
        # 用户 m04818：讲「扇面越大占比越高」，不出现 Σθ / arc_total 这类符号。
        self.assertIn("扇面越大", note)
        self.assertIn("圆心", note)
        self.assertNotIn("Σθ", note)
        self.assertNotIn("液柱高度", note)

    def test_pagespec_roundtrip_preserves_arc_geometry(self):
        d = self.spec.to_dict()
        self.assertEqual(_by_id(type(self.spec).from_dict(d), "sector_1").geometry,
                         _by_id(self.spec, "sector_1").geometry)


# ---------------------------------------------------------------------------
# E.3 #2（半圆半边）：换数据 → 180°/Σv 重算、Σθ 闭合、无削顶
# ---------------------------------------------------------------------------
class TestE3Assertion2Semicircle(unittest.TestCase):
    def test_override_1_12_recomputes_factor_and_all_angles(self):
        base = _semi()
        self.assertAlmostEqual(base.scale.factor, 180.0 / 22.0, places=9)
        # override 1=12.0 → Σv=24，factor 180/24=7.5；θ_1=90，θ_2..5=22.5。
        over = _semi([12.0, 3.0, 3.0, 3.0, 3.0])
        self.assertAlmostEqual(over.scale.factor, 180.0 / 24.0, places=9)
        self.assertAlmostEqual(_by_id(over, "sector_1").geometry["theta"], 90.0, places=6)
        for i in range(2, 6):
            self.assertAlmostEqual(_by_id(over, f"sector_{i}").geometry["theta"],
                                   22.5, places=6)
        thetas = [_by_id(over, f"sector_{i}").geometry["theta"] for i in range(1, 6)]
        self.assertAlmostEqual(sum(thetas), 180.0, places=6)
        for i, v in zip(range(1, 6), [12.0, 3.0, 3.0, 3.0, 3.0]):
            self.assertAlmostEqual(
                _by_id(over, f"sector_{i}").geometry["theta"] / v, 7.5, places=9)

    def test_no_clipping_with_a_value_far_above_ten(self):
        # 反削顶：v=100 时 Σv=112，θ_1=100×180/112≈160.71 < 180，
        # 仍线性、不出现「超 10 倍画满」。
        spec = _semi([100.0, 3.0, 3.0, 3.0, 3.0])
        g = _by_id(spec, "sector_1").geometry
        self.assertAlmostEqual(g["theta"], 100.0 * 180.0 / 112.0, places=6)
        self.assertLess(g["theta"], 180.0)
        thetas = [_by_id(spec, f"sector_{i}").geometry["theta"] for i in range(1, 6)]
        self.assertAlmostEqual(sum(thetas), 180.0, places=6)
        for i, v in zip(range(1, 6), [100.0, 3.0, 3.0, 3.0, 3.0]):
            self.assertAlmostEqual(thetas[i - 1] / v, 180.0 / 112.0, places=9)

    def test_legend_text_and_binding_track_data(self):
        over = _semi([12.0, 3.0, 3.0, 3.0, 3.0])
        self.assertIn("12", _by_id(over, "legend_1").text)
        self.assertEqual(_by_id(over, "sector_1").binding["value"], 12.0)


# ---------------------------------------------------------------------------
# E.3 #3：同一个 solve() 两份模板、复用 C1/C4/C5、同模板两份 spec
# ---------------------------------------------------------------------------
class TestE3Assertion3Semicircle(unittest.TestCase):
    def test_same_solve_feeds_both_templates_producing_legal_specs(self):
        for t in (THERMO, SEMI):
            with self.subTest(template=t.name):
                sk = build_skeleton(t, PTS, "heat_ratio_top5", "标题", 10.0, 6.0)
                self.assertFalse(any((e.x_in, e.y_in, e.w_in, e.h_in) != (0, 0, 0, 0)
                                     for e in sk.elements))
                spec = solve(sk, PTS)
                for e in spec.elements:
                    self.assertGreaterEqual(e.x_in, 0.0)
                    self.assertGreaterEqual(e.y_in, 0.0)
                    self.assertLessEqual(e.x_in + e.w_in, 10.0)
                    self.assertLessEqual(e.y_in + e.h_in, 6.0)

    def test_semicircle_reuses_c1_c4_c5_primitives(self):
        ids = {c["id"] for c in _semi().constraints}
        self.assertTrue({"C1", "C4", "C5"}.issubset(ids))
        self.assertNotIn("C9", ids)

    def test_same_template_two_specs_same_constraints_different_x(self):
        a = _semi(W=10.0)
        b = _semi(W=12.0)
        self.assertEqual(a.constraints, b.constraints)
        # W=12 → R=min(5.5,2.05)=2.05，cx=6，x=3.95；W=10 → x=2.95。
        self.assertAlmostEqual(_by_id(a, "sector_1").x_in, 2.95, places=9)
        self.assertAlmostEqual(_by_id(b, "sector_1").x_in, 3.95, places=9)
        self.assertNotEqual(_by_id(a, "sector_1").x_in,
                            _by_id(b, "sector_1").x_in)


# ---------------------------------------------------------------------------
# E.3 #4：中心数值 = v_center/Σv×100% 实时归一，禁止写死「80%」
# ---------------------------------------------------------------------------
class TestE3Assertion4Center(unittest.TestCase):
    def test_center_text_equals_live_normalized_percentage(self):
        # 手算：base Σv=22、v_center(seq1)=10 → 45.5%；
        # override seq2 3→12 使 Σv=31 → 32.3%；[5,5,5,5,5] Σv=25 → 20.0%。
        self.assertEqual(_by_id(_semi(), "center").text, "45.5%")
        self.assertEqual(_by_id(_semi([10.0, 12.0, 3.0, 3.0, 3.0]), "center").text,
                         "32.3%")
        self.assertEqual(_by_id(_semi([5.0, 5.0, 5.0, 5.0, 5.0]), "center").text,
                         "20.0%")

    def test_center_value_changes_when_a_non_center_sector_changes(self):
        a = _by_id(_semi(), "center")
        b = _by_id(_semi([10.0, 12.0, 3.0, 3.0, 3.0]), "center")
        self.assertNotEqual(a.text, b.text)
        # 中心扇区自身值未变（仍是 seq1=10），变的是 Σv。
        self.assertEqual(a.binding["value"], 10.0)
        self.assertEqual(b.binding["value"], 10.0)
        self.assertAlmostEqual(a.geometry["percent"], 100.0 * 10.0 / 22.0, places=6)
        self.assertAlmostEqual(b.geometry["percent"], 100.0 * 10.0 / 31.0, places=6)

    def test_center_slice_id_selects_which_value_is_normalized(self):
        # center_slice_id=2 → v_center=3、Σv=22 → 13.6%（不是写死的 80）。
        c = _by_id(_semi(param_overrides={"center_slice_id": 2}), "center")
        self.assertEqual(c.text, "13.6%")
        self.assertEqual(c.binding["seq"], 2)
        self.assertEqual(c.binding["center_slice_id"], 2)

    def test_no_dataset_yields_a_hardcoded_80_percent(self):
        # 三份 Σv 各不相同的中心数值互不相同，且都不等于固定「80.0%」，
        # 证明是 v_center/Σv 实时归一而非写死。
        texts = {
            _by_id(_semi(v), "center").text
            for v in ([10, 3, 3, 3, 3], [10, 12, 3, 3, 3], [5, 5, 5, 5, 5])
        }
        self.assertEqual(len(texts), 3)
        self.assertNotIn("80.0%", texts)


# ---------------------------------------------------------------------------
# arc 扇区适配器：5 个原生 PIE 形状，角度写进 adjustments（不改 render.py）
# ---------------------------------------------------------------------------
class TestArcAdapter(unittest.TestCase):
    def test_render_pptx_arc_produces_five_pie_shapes_with_angles(self):
        from loop.render_arc import render_pptx_arc
        spec = _semi()
        d = mkdtemp(prefix="arc-")
        p = os.path.join(d, "semi.pptx")
        render_pptx_arc(spec, p)
        shapes = read_shapes(p)
        self.assertEqual(len(shapes), 13)
        bounds = [180.0, 261.8181818181818, 286.3636363636364,
                  310.9090909090909, 335.4545454545455, 360.0]
        for i in range(1, 6):
            s = shapes[f"sector_{i}"]
            self.assertIn("PIE", (s["auto_shape_type"] or ""))
            self.assertEqual(len(s["adjustments"]), 2)
            # python-pptx 把 adjustments 存成 5 位小数；允许 1e-3 误差。
            self.assertAlmostEqual(s["adjustments"][0], bounds[i - 1], delta=1e-3)
            self.assertAlmostEqual(s["adjustments"][1], bounds[i], delta=1e-3)

    def test_build_loop_semicircle_pipeline_writes_arc_spec_and_pie_pptx(self):
        d = mkdtemp(prefix="arc-pipe-")
        r = BL.build_loop(d, template_name="semicircle")
        with open(r["pagespec"], encoding="utf-8") as f:
            doc = json.load(f)
        self.assertTrue(any(e["type"] == "arc" for e in doc["elements"]))
        self.assertEqual(doc["layout"]["template"], "semicircle")
        shapes = read_shapes(r["pptx"])
        self.assertIn("PIE", (shapes["sector_1"]["auto_shape_type"] or ""))
        self.assertTrue(os.path.exists(r["png"]))


# ---------------------------------------------------------------------------
# 失败路径（用户点名）
# ---------------------------------------------------------------------------
class TestSemicircleFailures(unittest.TestCase):
    def test_sum_v_zero_raises_solveerror_via_build_pagespec(self):
        with self.assertRaises(SolveError) as ctx:
            build_pagespec(_pts([0.0, 0.0, 0.0]), "半圆占比",
                           template_name="semicircle")
        self.assertIn("C2", ctx.exception.conflicts)

    def test_n20_legend_overflow_raises_solveerror_not_clipped(self):
        # 20 行图例按固定间距堆叠会顶出画布 → C1 无解；不静默压缩。
        # 半圆模板默认 max_slices=5（D.3），故这里把上限放宽到 20，
        # 让 20 项通过容量守卫、专门测「图例堆叠溢出」这条路径。
        with self.assertRaises(SolveError) as ctx:
            _semi([1.0] * 20, param_overrides={"max_slices": 20})
        self.assertIn("C1", ctx.exception.conflicts)


# ---------------------------------------------------------------------------
# 目视复核发现的缺陷：扇区是整圆 PIE 的 180° 楔形，覆盖 (250..750, 50..350)
# 的整块 bbox；按规格顺序先画文字再画扇区会把中心百分比 / 量程说明盖掉。
# 修复 = 渲染层把文字留到最后画（z-order），规格与求解器不动。
# ---------------------------------------------------------------------------
class TestSemicircleTextOnTop(unittest.TestCase):
    def test_text_marks_are_last_in_render_order(self):
        # 规格里最后一个 arc 之后的每个 text 都必须在所有扇区之上。
        spec = _semi()
        last_arc = max(i for i, e in enumerate(spec.elements) if e.type == "arc")
        # 求解器不改规格顺序，故用渲染器的排序结果断言（预览 + PPTX 同口径）。
        from loop.preview import _render_order
        ordered = _render_order(spec)
        last_shape = max(i for i, e in enumerate(ordered)
                         if e.type in ("arc", "rect", "ellipse"))
        self.assertLess(last_shape, len(ordered) - 1)
        self.assertTrue(all(e.type == "text" for e in ordered[last_shape + 1:]),
                        "文字必须排在最后，否则被扇区盖住")
        self.assertEqual(len(ordered), len(spec.elements))

    def test_center_percentage_is_visible_in_preview(self):
        # 审查修复后中心数值盒 (295..705, 330..370) 内必须有深色像素。
        from PIL import Image
        from loop.preview import render_preview
        d = mkdtemp(prefix="semi-visible-")
        p = os.path.join(d, "preview.png")
        render_preview(_semi(), p)
        im = Image.open(p).convert("RGB")
        dark = sum(1 for y in range(330, 370) for x in range(295, 705)
                   if sum(im.getpixel((x, y))) < 150)
        self.assertGreater(dark, 50, "中心 45.5% 被扇区盖住了")

    def test_scale_note_is_visible_in_preview(self):
        # 量程说明盒 (350..650, 115..145) 内必须有深色像素。
        from PIL import Image
        from loop.preview import render_preview
        d = mkdtemp(prefix="semi-note-")
        p = os.path.join(d, "preview.png")
        render_preview(_semi(), p)
        im = Image.open(p).convert("RGB")
        dark = sum(1 for y in range(115, 145) for x in range(350, 650)
                   if sum(im.getpixel((x, y))) < 150)
        self.assertGreater(dark, 50, "量程说明被扇区盖住了")

    def test_pptx_text_shapes_are_last_in_shape_tree(self):
        # PPTX 的 z-order 由 slide.shapes 插入顺序决定，文字必须在扇区之后。
        from loop.render_arc import render_pptx_arc
        d = mkdtemp(prefix="semi-pptx-")
        p = os.path.join(d, "loop1.pptx")
        render_pptx_arc(_semi(), p)
        shapes = read_shapes(p)
        # read_shapes 是 dict（按名字），改用有序计数：直接看 XML 顺序。
        from pptx import Presentation
        tree = list(Presentation(p).slides[0].shapes)
        types = [("arc" if "sector_" in s.name else "text")
                 for s in tree]
        last_arc = max(i for i, t in enumerate(types) if t == "arc")
        self.assertTrue(all(t == "text" for t in types[last_arc + 1:]),
                        "PPTX 文字形状必须排在扇区之后")
        self.assertEqual(len(shapes), 13)


if __name__ == "__main__":
    unittest.main()
