"""用户 m05104：温度计的管身 / 液柱 / 球泡 / 外圈必须共用同一条竖直中心线。

背景：包框（用户 m04818）只平移了元素的 x_in / y_in，没有平移
``ElementSpec.geometry`` 里的绝对坐标（``cx`` / ``cy`` / ``cap_top`` /
``tube_bottom``）。外圈轮廓按 geometry.cx 画，于是整圈比管身左偏
一个平移量——肉眼看到的「液柱贴着管身左侧」其实是外圈错位。

这批用例同时守住两件事：
1. 形状函数从**外接盒**推导位置，geometry 只提供相对尺寸；
2. ``wrap`` / ``unwrap`` 把 geometry 里的绝对坐标一起平移。
"""
import math
import unittest

from pptx.enum.shapes import MSO_SHAPE_TYPE

from loop.data_source import DB_PATH, load_points
from loop.models import ElementSpec
from loop.scaffold import build_pagespec
from loop.thermo_shape import outline_polyline, tick_rects

TOL = 0.001          # 用户要求的误差上限（英寸）


def _by_id(spec, eid):
    return next(e for e in spec.elements if e.id == eid)


def _center_x(el):
    return el.x_in + el.w_in / 2


def _points(rows):
    return [{"seq": i + 1, "label": f"p{i + 1}", "value": float(v), "unit": "倍(超)"}
            for i, v in enumerate(rows)]


class TestThermometerCentrelines(unittest.TestCase):
    """未包框规格：液柱 / 球泡 / 外圈与管身共中轴。"""

    @classmethod
    def setUpClass(cls):
        title, rows = load_points(DB_PATH, chart_key="heat_ratio_top5")
        cls.spec = build_pagespec(rows, title, template_name="thermometer")

    def test_liquid_bulb_and_track_share_one_centre_line(self):
        for seq in range(1, 6):
            track = _by_id(self.spec, f"track_{seq}")
            for role in ("liquid", "bulb"):
                el = _by_id(self.spec, f"{role}_{seq}")
                self.assertAlmostEqual(
                    _center_x(el), _center_x(track), delta=TOL,
                    msg=f"{role}_{seq} 中心 {_center_x(el):.4f} != "
                        f"track_{seq} 中心 {_center_x(track):.4f}")

    def test_outline_polyline_is_symmetric_about_the_track_centre(self):
        for seq in range(1, 6):
            track = _by_id(self.spec, f"track_{seq}")
            outline = _by_id(self.spec, f"outline_{seq}")
            xs = [p[0] for p in outline_polyline(outline)]
            self.assertAlmostEqual(
                (min(xs) + max(xs)) / 2, _center_x(track), delta=TOL,
                msg=f"outline_{seq} 折线中心 {(min(xs)+max(xs))/2:.4f} != "
                    f"track_{seq} 中心 {_center_x(track):.4f}")

    def test_outline_polyline_sits_inside_the_recorded_bbox(self):
        # 折线不能跑出自己声明的外接盒——这是包框平移时最容易漏掉的一致性。
        for seq in range(1, 6):
            o = _by_id(self.spec, f"outline_{seq}")
            xs = [p[0] for p in outline_polyline(o)]
            ys = [p[1] for p in outline_polyline(o)]
            self.assertAlmostEqual(min(xs), o.x_in, delta=TOL)
            self.assertAlmostEqual(max(xs), o.x_in + o.w_in, delta=TOL)
            self.assertAlmostEqual(min(ys), o.y_in, delta=TOL)
            self.assertAlmostEqual(max(ys), o.y_in + o.h_in, delta=TOL)


class TestAlignmentSurvivesFraming(unittest.TestCase):
    """包框 / 拆框之后中轴仍重合（这就是本轮 bug 的现场）。"""

    @classmethod
    def setUpClass(cls):
        title, rows = load_points(DB_PATH, chart_key="heat_ratio_top5")
        cls.framed = build_pagespec(rows, title, template_name="thermometer",
                                    frame=True)
        cls.raw = build_pagespec(rows, title, template_name="thermometer")

    def test_centres_still_match_after_wrap(self):
        for seq in range(1, 6):
            track = _by_id(self.framed, f"track_{seq}")
            for role in ("liquid", "bulb"):
                el = _by_id(self.framed, f"{role}_{seq}")
                self.assertAlmostEqual(_center_x(el), _center_x(track), delta=TOL)

    def test_wrap_shifts_absolute_geometry_by_the_origin(self):
        dx, dy = self.framed.layout["frame"]["origin"]
        for seq in range(1, 6):
            before = _by_id(self.raw, f"outline_{seq}").geometry
            after = _by_id(self.framed, f"outline_{seq}").geometry
            for key in ("cx",):
                self.assertAlmostEqual(after[key] - before[key], dx, delta=1e-6,
                                       msg=f"outline_{seq}.{key} 没跟着平移")
            for key in ("cy", "cap_top", "tube_bottom"):
                self.assertAlmostEqual(after[key] - before[key], dy, delta=1e-6,
                                       msg=f"outline_{seq}.{key} 没跟着平移")

    def test_outline_polyline_matches_the_tube_after_wrap(self):
        dx, _ = self.framed.layout["frame"]["origin"]
        for seq in range(1, 6):
            track = _by_id(self.framed, f"track_{seq}")
            outline = _by_id(self.framed, f"outline_{seq}")
            xs = [p[0] for p in outline_polyline(outline)]
            self.assertAlmostEqual((min(xs) + max(xs)) / 2, _center_x(track),
                                   delta=TOL)
            # 相邻两根管的中心距不受包框影响
            if seq > 1:
                prev = _by_id(self.framed, f"track_{seq-1}")
                self.assertAlmostEqual(_center_x(track) - _center_x(prev),
                                       _center_x(_by_id(self.raw, f"track_{seq}"))
                                       - _center_x(_by_id(self.raw, f"track_{seq-1}")),
                                       delta=1e-6)

    def test_unwrap_restores_the_original_geometry(self):
        from loop.frame import unwrap
        back = unwrap(self.framed)
        for seq in range(1, 6):
            a = _by_id(back, f"outline_{seq}")
            b = _by_id(self.raw, f"outline_{seq}")
            for key in ("cx", "cy", "cap_top", "tube_bottom"):
                self.assertAlmostEqual(a.geometry[key], b.geometry[key],
                                       delta=1e-6,
                                       msg=f"unwrap 后 {key} 没还原")
            self.assertAlmostEqual(a.x_in, b.x_in, delta=1e-6)


class TestSkinStaysAligned(unittest.TestCase):
    """刻度仍贴管身右缘、球泡环仍以管身中轴为心。"""

    def test_ticks_end_on_the_tube_right_edge_after_wrap(self):
        spec = build_pagespec(_points([10, 8, 4, 2, 1]), "t",
                              template_name="thermometer", frame=True)
        for seq in range(1, 6):
            track = _by_id(spec, f"track_{seq}")
            ticks = _by_id(spec, f"ticks_{seq}")
            for x, _y, _w, _h in tick_rects(ticks):
                self.assertAlmostEqual(x + _w, track.x_in + track.w_in, delta=TOL)


if __name__ == "__main__":
    unittest.main()
