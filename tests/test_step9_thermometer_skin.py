"""D.2 step 9 —— 温度计「报纸原版皮肤」：柱体右侧刻度 / 管球交界 / 外圈轮廓。

用户 m02273 原话：「柱体右边加刻度，柱体与圆形交界面不够自然，以及外圈加一圈，
具体参考上面的图片」。

本步只做三件视觉事，**不改 loop/render.py**（m01073 硬约束）：
  1. 每根管多一条 `ticks` 图元：管身右侧的一串短横线（多轮廓 freeform 一个形状）；
  2. 每根管多一条 `outline` 图元：把「管身半圆顶 + 竖直管身 + 球泡外环」描成
     一条闭合轮廓（球与环之间的留白就是原版的「双重轮廓」）；
  3. 渲染走新增的 `loop/render_thermo.py` 适配器（与 render_arc.py 平级）。

所有期望值都是按参数手算的字面量（10×6 画布），不调用被测代码推导。
手算依据：track_1 = (0.5, 2.02, 0.28, 3.0)，0 点 = 5.02，bulb_d = 0.52，
outline_pad = 0.03，bulb_ring_pad = 0.045 → cx = 0.64, cy = 5.28,
R = 0.305, cap_r = 0.17。
"""
import unittest

from pptx.util import Inches

from tests.scratch import mkdtemp
from loop.data_source import DB_PATH, load_points
from loop.models import PageSpec
from loop.scaffold import build_pagespec
from loop.solve import SolveError, validate_spec
from loop.templates import get_template
from loop.thermo_shape import outline_polyline, tick_rects
from loop.verify import read_shapes

_, PTS = load_points(DB_PATH)
T = get_template("thermometer")


def _by_id(spec, eid):
    return next(e for e in spec.elements if e.id == eid)


def _pts(values):
    return [{"seq": i + 1, "label": f"项{i + 1}", "value": float(v), "unit": "倍(超)"}
            for i, v in enumerate(values)]


# ---------------------------------------------------------------------------
# 模板层：新参数与新图元必须是声明式的（@参数名 引用，无裸坐标）
# ---------------------------------------------------------------------------
class TestSkinDeclarations(unittest.TestCase):
    def test_new_params_exist_with_defaults(self):
        want = {
            "tick_count": 13, "tick_len": 0.10, "tick_thick": 0.012,
            "outline_pad": 0.03, "bulb_ring_pad": 0.045, "neck_h": 0.18,
        }
        for name, default in want.items():
            with self.subTest(name=name):
                self.assertIn(name, T.params)
                self.assertEqual(T.params[name]["default"], default)
        self.assertEqual(T.params["color_outline"]["default"], "C9C9C9")

    def test_ticks_and_outline_marks_are_declared(self):
        roles = {m["role"] for m in T.marks}
        self.assertIn("ticks", roles)
        self.assertIn("outline", roles)
        marks = {m["id"]: m for m in T.marks}
        self.assertEqual(marks["ticks"]["type"], "ticks")
        self.assertEqual(marks["outline"]["type"], "outline")
        # 与既有图元一样：几何字段全是 "@参数名"，fill 也是参数引用。
        for mid in ("ticks", "outline"):
            for f in ("x_in", "y_in", "w_in", "h_in", "fill"):
                self.assertTrue(str(marks[mid][f]).startswith("@"),
                                f"{mid}/{f} = {marks[mid][f]!r}")

    def test_c4_declaration_mentions_the_skin_relations(self):
        c4 = next(c for c in T.constraints if c["id"] == "C4")
        self.assertIn("bulb_ring_pad", c4["expr"])
        self.assertIn("neck_h", c4["expr"])


# ---------------------------------------------------------------------------
# 求解层：皮肤图元的位置由参数与既有几何确定（手算字面量）
# ---------------------------------------------------------------------------
class TestSkinGeometry(unittest.TestCase):
    def setUp(self):
        self.spec = build_pagespec(PTS, width_in=10.0, height_in=6.0)

    def test_element_count_grows_by_ten(self):
        # 原 27（2 全局 + 5 管 × 5）→ 每管多 ticks/outline 两条 = 27 + 10 = 37。
        self.assertEqual(len(self.spec.elements), 37)
        self.assertEqual(len({e.id for e in self.spec.elements}), 37)

    def test_ticks_cover_exactly_the_track_box(self):
        for seq in range(1, 6):
            t = _by_id(self.spec, f"track_{seq}")
            k = _by_id(self.spec, f"ticks_{seq}")
            with self.subTest(seq=seq):
                self.assertEqual((k.x_in, k.y_in, k.w_in, k.h_in),
                                 (t.x_in, t.y_in, t.w_in, t.h_in))

    def test_ticks_geometry_records_count_and_length(self):
        k = _by_id(self.spec, "ticks_1")
        self.assertEqual(k.geometry["count"], 13)
        self.assertAlmostEqual(k.geometry["len"], 0.10, places=9)
        self.assertAlmostEqual(k.geometry["thick"], 0.012, places=9)
        # 刻度不是数据驱动的，绝不能带 binding（否则会被当成数值图元）。
        self.assertIsNone(k.binding)

    def test_outline_box_covers_the_whole_silhouette(self):
        # 手算：x = cx − R = 0.64 − 0.305 = 0.335；w = 2R = 0.61
        #       y = 管口 2.02（半圆顶的 apex）；h = 球环底 5.585 − 2.02 = 3.565
        o = _by_id(self.spec, "outline_1")
        self.assertAlmostEqual(o.x_in, 0.335, places=9)
        self.assertAlmostEqual(o.y_in, 2.02, places=9)
        self.assertAlmostEqual(o.w_in, 0.61, places=9)
        self.assertAlmostEqual(o.h_in, 3.565, places=9)

    def test_outline_geometry_records_the_silhouette_constants(self):
        # 渲染器只读 geometry，不反推参数（两个后端共用同一份事实）。
        g = _by_id(self.spec, "outline_1").geometry
        self.assertAlmostEqual(g["cx"], 0.64, places=9)     # 0.5 + 0.28/2
        self.assertAlmostEqual(g["cy"], 5.28, places=9)     # 5.02 + 0.52/2
        self.assertAlmostEqual(g["R"], 0.305, places=9)     # 0.26 + 0.045
        self.assertAlmostEqual(g["cap_r"], 0.17, places=9)  # 0.14 + 0.03
        self.assertAlmostEqual(g["neck_h"], 0.18, places=9)
        self.assertAlmostEqual(g["tube_bottom"], 5.02, places=9)

    def test_outline_never_covers_the_label_row(self):
        # 0 点在球顶、标签在管口上方（底边 1.99）；外圈顶边 = 管口半圆顶点 2.02，
        # 只差 gap_label 0.03，不许再往上鼓出压住类别名。
        la = _by_id(self.spec, "label_1")
        o = _by_id(self.spec, "outline_1")
        self.assertGreaterEqual(o.y_in, la.y_in + la.h_in - 1e-9)

    def test_validate_spec_accepts_the_fresh_spec(self):
        self.assertIs(validate_spec(self.spec), self.spec)


# ---------------------------------------------------------------------------
# 几何助手：刻度与轮廓的形状必须能直接交给两个渲染后端
# ---------------------------------------------------------------------------
class TestSkinHelpers(unittest.TestCase):
    def setUp(self):
        self.spec = build_pagespec(PTS, width_in=10.0, height_in=6.0)

    def test_tick_rects_are_thirteen_separated_short_bars(self):
        rs = tick_rects(_by_id(self.spec, "ticks_1"))
        self.assertEqual(len(rs), 13)
        _x0, _y0, w, h = rs[0]
        self.assertAlmostEqual(w, 0.10, places=9)
        self.assertAlmostEqual(h, 0.012, places=9)
        # 全部贴管身右缘内侧：右端 == 管右缘 0.78。
        for x, _y, rw, _h in rs:
            self.assertAlmostEqual(x + rw, 0.78, places=9)
        # 自下（0 点附近）向上等距；刻度带上下各让一段：
        # 上让半圆管顶 cap_r = 0.28/2 + 0.03 = 0.17，下让锥形收口 neck_h = 0.18。
        # 步长 = (3.0 − 0.17 − 0.18) / 13 = 2.65 / 13。
        ys = [r[1] for r in rs]
        step = (3.0 - 0.17 - 0.18) / 13
        for a, b in zip(ys, ys[1:]):
            self.assertAlmostEqual(a - b, step, places=9)
        # 不越出管身：全部刻度落在 [管口 2.02, 0 点 5.02] 内，
        # 且最上一条让开半圆顶（>= 2.02 + 0.17）、最下一条让开收口（<= 5.02 - 0.18）。
        for _x, y, _w, hh in rs:
            self.assertGreaterEqual(y, 2.02 + 0.17 - 1e-9)
            self.assertLessEqual(y + hh, 5.02 - 0.18 + 1e-9)

    def test_outline_polyline_is_one_closed_contour_around_tube_and_bulb(self):
        pts = outline_polyline(_by_id(self.spec, "outline_1"))
        self.assertGreater(len(pts), 20)
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        # 最左 = 球环左极点 0.335，最右 = 球环右极点 0.945：
        # 球环比管身(0.28)宽，故轮廓最宽处是球环而不是管身。
        self.assertAlmostEqual(min(xs), 0.335, places=9)
        self.assertAlmostEqual(max(xs), 0.945, places=9)
        self.assertAlmostEqual(min(ys), 2.02, places=9)   # 半圆顶点
        self.assertAlmostEqual(max(ys), 5.585, places=9)  # 球环底
        # 闭合：首尾点重合（freeform 用 close=True 收口，点列本身也要可闭合）。
        self.assertAlmostEqual(pts[0][0], pts[-1][0], places=9)
        self.assertAlmostEqual(pts[0][1], pts[-1][1], places=9)


# ---------------------------------------------------------------------------
# 液柱细杆：原版的液柱是约管宽 1/3 的细杆，不是塞满管身的矩形
# ---------------------------------------------------------------------------
class TestLiquidRod(unittest.TestCase):
    def setUp(self):
        self.spec = build_pagespec(PTS, width_in=10.0, height_in=6.0)

    def test_liquid_w_param_exists(self):
        self.assertIn("liquid_w", T.params)
        self.assertAlmostEqual(T.params["liquid_w"]["default"], 0.10, places=9)

    def test_liquid_mark_uses_its_own_width_param(self):
        marks = {m["id"]: m for m in T.marks}
        self.assertEqual(marks["liquid"]["w_in"], "@liquid_w")
        self.assertEqual(marks["liquid"]["x_in"], "@x_liquid")
        self.assertTrue(marks["liquid"]["geometry_expr"].strip())

    def test_liquid_is_a_thin_rod_centered_in_the_tube(self):
        # 手算：w_track 0.28，liquid_w 0.10 → x = x_track + (0.28−0.10)/2 = x_track + 0.09
        for seq in range(1, 6):
            t = _by_id(self.spec, f"track_{seq}")
            l = _by_id(self.spec, f"liquid_{seq}")
            with self.subTest(seq=seq):
                self.assertAlmostEqual(l.w_in, 0.10, places=9)
                self.assertAlmostEqual(l.x_in, t.x_in + 0.09, places=9)
                self.assertAlmostEqual(l.x_in + l.w_in / 2,
                                       t.x_in + t.w_in / 2, places=9)

    def test_liquid_rod_stays_inside_the_tube_and_keeps_its_height(self):
        for i, v in zip(range(1, 6), [10.0, 3.0, 3.0, 3.0, 3.0]):
            t = _by_id(self.spec, f"track_{i}")
            l = _by_id(self.spec, f"liquid_{i}")
            with self.subTest(seq=i):
                self.assertGreaterEqual(l.x_in, t.x_in - 1e-9)
                self.assertLessEqual(l.x_in + l.w_in, t.x_in + t.w_in + 1e-9)
                # 变细只改宽度：高度仍是 factor×v，底仍压在 0 点。
                self.assertAlmostEqual(l.h_in, 3.0 * v / 11.0, places=9)
                self.assertAlmostEqual(l.y_in + l.h_in, t.y_in + t.h_in, places=9)

    def test_off_center_liquid_rod_is_rejected(self):
        d = self.spec.to_dict()
        for e in d["elements"]:
            if e["id"] == "liquid_1":
                e["x_in"] += 0.02          # 仍在管内，只是不居中了
        with self.assertRaises(SolveError) as ctx:
            validate_spec(PageSpec.from_dict(d))
        self.assertIn("C5", ctx.exception.conflicts)


# ---------------------------------------------------------------------------
# 读回层：C4 必须把皮肤关系一起重推，不许「谁都没说」就放过
# ---------------------------------------------------------------------------
class TestSkinReadback(unittest.TestCase):
    def setUp(self):
        self.spec = build_pagespec(PTS, width_in=10.0, height_in=6.0)

    def _tampered(self, eid, **changes):
        d = self.spec.to_dict()
        for e in d["elements"]:
            if e["id"] == eid:
                e.update(changes)
        return PageSpec.from_dict(d)

    def test_outline_shifted_off_the_track_is_rejected(self):
        s = self._tampered("outline_1", x_in=0.60)
        with self.assertRaises(SolveError) as ctx:
            validate_spec(s)
        self.assertIn("C4", ctx.exception.conflicts)

    def test_outline_shrunk_ring_is_rejected(self):
        s = self._tampered("outline_1", h_in=3.2)
        with self.assertRaises(SolveError):
            validate_spec(s)

    def test_ticks_box_must_match_the_track(self):
        s = self._tampered("ticks_1", h_in=2.5)
        with self.assertRaises(SolveError) as ctx:
            validate_spec(s)
        self.assertIn("C4", ctx.exception.conflicts)

    def test_tick_count_tampering_is_rejected(self):
        d = self.spec.to_dict()
        for e in d["elements"]:
            if e["id"] == "ticks_1":
                e["geometry"]["count"] = 7
        with self.assertRaises(SolveError):
            validate_spec(PageSpec.from_dict(d))

    def test_deleting_one_skin_element_is_rejected(self):
        d = self.spec.to_dict()
        d["elements"] = [e for e in d["elements"] if e["id"] != "outline_3"]
        with self.assertRaises(SolveError):
            validate_spec(PageSpec.from_dict(d))


# ---------------------------------------------------------------------------
# 渲染层：新适配器产出原生（可编辑）形状，预览图同步出现刻度和轮廓
# ---------------------------------------------------------------------------
class TestSkinRendering(unittest.TestCase):
    def setUp(self):
        self.d = mkdtemp(prefix="skin-")
        self.spec = build_pagespec(PTS, width_in=10.0, height_in=6.0)

    def test_render_thermo_makes_native_freeform_skin_shapes(self):
        from pptx.enum.shapes import MSO_SHAPE_TYPE
        from loop.render_thermo import render_pptx_thermo
        out = f"{self.d}/loop1.pptx"
        render_pptx_thermo(self.spec, out)
        shapes = read_shapes(out)
        self.assertEqual(len(shapes), 37)   # 未包框的纯内容规格
        for eid in ("ticks_1", "outline_1", "ticks_5", "outline_5"):
            self.assertIn(eid, shapes)
            self.assertEqual(shapes[eid]["shape_type"], MSO_SHAPE_TYPE.FREEFORM)
        # 既有图元的渲染口径不变：液柱仍是原生 AUTO_SHAPE。
        self.assertEqual(shapes["liquid_1"]["shape_type"], MSO_SHAPE_TYPE.AUTO_SHAPE)
        self.assertAlmostEqual(shapes["liquid_1"]["height"],
                               Inches(3.0 * 10.0 / 11.0), delta=1)

    def test_build_loop_dispatches_thermometer_to_the_skin_adapter(self):
        from loop.build_loop import build_loop
        r = build_loop(mkdtemp(prefix="skin-e2e-"))
        names = read_shapes(r["pptx"])
        self.assertIn("outline_1", names)
        self.assertEqual(len(names), 39)   # 37 内容 + frame + title_band

    def test_preview_paints_outline_and_ticks(self):
        from PIL import Image
        from loop.preview import render_preview
        png = f"{self.d}/preview.png"
        render_preview(self.spec, png)
        img = Image.open(png).convert("RGB")
        px = list(img.getdata())
        grey = sum(1 for r, g, b in px
                   if abs(r - 0xC9) <= 14 and abs(g - 0xC9) <= 14
                   and abs(b - 0xC9) <= 14)
        # 13 刻度 × 5 管 + 5 圈轮廓，像素数远大于零；纯白图不会满足。
        self.assertGreater(grey, 800, "预览里没有刻度线 / 外圈轮廓")


if __name__ == "__main__":
    unittest.main()
