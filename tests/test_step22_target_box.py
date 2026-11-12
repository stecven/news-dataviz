"""第 22 步：单卡片适配外部边界（用户 m05768）。

「内容决定画布」逆转为「外部给边界、内部自适应」：传 target_width_in /
target_height_in 时，卡片必须正好装进这个格子；不传时行为与之前逐位一致。
"""

import json
import os
import unittest

from loop import palette
from loop.data_source import DB_PATH, load_points
from loop.fit import BoundaryError, available_box, chrome_height_in
from loop.frame import CHROME_ROLES, validate_frame
from loop.pipeline import run_selected
from loop.scaffold import build_pagespec
from loop.selector import SEMANTIC_COMPARE, SEMANTIC_SHARE
from loop.solve import build_skeleton, solve, validate_spec
from loop.templates import get_template
from tests.scratch import mkdtemp

TOL = 0.01


def _rows(chart_key):
    _, points = load_points(DB_PATH, chart_key=chart_key)
    return points


def _inside(spec, w, h):
    out = []
    for e in spec.elements:
        if (e.x_in < -1e-6 or e.y_in < -1e-6
                or e.x_in + e.w_in > w + 1e-6 or e.y_in + e.h_in > h + 1e-6):
            out.append(e.id)
    return out


class TestTargetCanvas(unittest.TestCase):
    """闸口：传入 target 时产出画布严格等于给定值，且元素都在界内。"""

    def test_five_extreme_boxes_land_exactly_on_the_target(self):
        cases = [
            ("thermometer", "heat_ratio_top5", 5.0, 4.0),
            ("thermometer", "heat_ratio_top5", 7.0, 3.0),
            ("semicircle", "heat_age", 3.0, 3.0),
            ("semicircle", "heat_age", 5.0, 2.5),
            ("semicircle", "heat_age", 4.0, 4.0),
        ]
        for name, key, tw, th in cases:
            with self.subTest(template=name, target=(tw, th)):
                spec = build_pagespec(_rows(key), "标题", template_name=name,
                                      target_width_in=tw, target_height_in=th)
                self.assertAlmostEqual(spec.width_in, tw, delta=TOL)
                self.assertAlmostEqual(spec.height_in, th, delta=TOL)
                self.assertEqual(spec.frame_bbox, [0.0, 0.0, tw, th])
                self.assertEqual(_inside(spec, tw, th), [],
                                 "元素越出目标格子")
                validate_frame(spec)
                validate_spec(spec)

    def test_placeholder_card_centres_inside_the_target(self):
        r = run_selected(values=[10, 3, 2, 2, 2, 1], semantic=SEMANTIC_SHARE,
                         out_root=mkdtemp("t22-"),
                         target_width_in=4.0, target_height_in=4.0)
        self.assertEqual(r["status"], "no_applicable")
        with open(r["pagespec"], encoding="utf-8") as f:
            doc = json.load(f)
        self.assertAlmostEqual(doc["width_in"], 4.0, delta=TOL)
        self.assertAlmostEqual(doc["height_in"], 4.0, delta=TOL)
        img = [e for e in doc["elements"] if e["type"] == "image"]
        self.assertEqual(len(img), 1)
        e = img[0]
        self.assertAlmostEqual(e["x_in"] + e["w_in"] / 2, 2.0, delta=TOL)
        # 占位图在格子里居中，且不越出框
        self.assertAlmostEqual(e["x_in"] + e["w_in"] / 2, 2.0, delta=TOL)
        # 纵向落在「标题带以下、下内边距以上」的内容带里
        band_top = 2 * 0.3 + 0.5 + 0.15
        self.assertGreaterEqual(e["y_in"], band_top - 1e-9)
        self.assertLessEqual(e["y_in"] + e["h_in"], 4.0 - 0.3 + 1e-9)
        self.assertGreaterEqual(e["x_in"], 0.0 - 1e-9)
        self.assertLessEqual(e["x_in"] + e["w_in"], 4.0 + 1e-9)
        self.assertLessEqual(e["y_in"] + e["h_in"], 4.0 + 1e-9)
        self.assertEqual(doc["content_bbox"] is not None, True)
        self.assertEqual(_inside(PageSpecLike(doc), 4.0, 4.0), [])

    def test_fonts_stay_inside_the_clamp(self):
        spec = build_pagespec(_rows("heat_age"), "标题", template_name="semicircle",
                              target_width_in=3.0, target_height_in=3.0)
        for e in spec.elements:
            if e.type != "text":
                continue
            pt = palette.scaled_font_size(e.role, palette.spec_scale(spec))
            self.assertGreaterEqual(pt, palette.MIN_FONT_PT)
            self.assertLessEqual(pt, palette.MAX_FONT_PT)

    def test_too_small_a_box_raises_instead_of_bursting_out(self):
        from loop.solve import SolveError
        for name, key in (("thermometer", "heat_ratio_top5"),
                          ("semicircle", "heat_age")):
            with self.subTest(template=name):
                with self.assertRaises(BoundaryError) as cm:
                    build_pagespec(_rows(key), "标题", template_name=name,
                                   target_width_in=2.0, target_height_in=2.0)
                err = cm.exception
                self.assertEqual(err.target, (2.0, 2.0))
                self.assertTrue(err.problems)
                # 能报出「最小可行尺寸」就报，报不出来也必须说清为什么
                self.assertTrue(err.min_size is not None
                                or "压到最小" in str(err))


class TestBackwardCompatible(unittest.TestCase):
    """闸口：不传 target 时原有的「按内容长大」逐位不变。"""

    def test_natural_thermometer_is_untouched(self):
        spec = build_pagespec(_rows("heat_ratio_top5"), "标题", frame=True)
        self.assertEqual(len(spec.elements), 39)
        self.assertEqual(spec.width_in, 10.52)
        self.assertEqual(spec.height_in, 5.85)

    def test_natural_semicircle_radius_is_untouched(self):
        spec = build_pagespec(_rows("heat_age"), "标题",
                              template_name="semicircle", frame=True)
        self.assertEqual(len(spec.elements), 15)
        # w_legend 新增后 10×6 上仍是「高度限制」，半径必须还是 2.05
        sector = [e for e in spec.elements if e.type == "arc"][0]
        self.assertAlmostEqual(sector.geometry["R"], 2.05, places=6)

    def test_legacy_pagespec_still_reads_and_renders(self):
        from loop.build_loop import render_from_spec
        from loop.models import PageSpec
        from tests.scratch import mkdtemp
        path = os.path.join("out", "loop1", "pagespec.json")
        if not os.path.exists(path):
            self.skipTest("老产物不在仓库里")
        with open(path, encoding="utf-8") as f:
            spec = PageSpec.from_dict(json.load(f))
        self.assertEqual(len(spec.elements), 27)
        out = mkdtemp()
        render_from_spec(spec, out)
        for name in os.listdir(out):
            self.assertTrue(os.path.getsize(os.path.join(out, name)) > 1000,
                            name)


class TestWidthFloorForLegend(unittest.TestCase):
    """半圆图例列：宽画布上 R 不再吃满宽度，图例列有位置。"""

    def test_wide_canvas_keeps_a_legend_column(self):
        spec = build_pagespec(_rows("heat_age"), "标题", template_name="semicircle",
                              target_width_in=12.0, target_height_in=14.0)
        legends = [e for e in spec.elements if e.role == "legend"]
        self.assertEqual(len(legends), 5)
        for e in legends:
            self.assertGreaterEqual(e.w_in, 0.5 - 1e-9)

    def test_legend_text_fits_its_column(self):
        from loop.fit import text_problems
        spec = build_pagespec(_rows("heat_age"), "标题", template_name="semicircle",
                              target_width_in=12.0, target_height_in=14.0)
        self.assertEqual(text_problems(spec, palette.spec_scale(spec)), [])

    def test_narrow_tall_canvas_no_longer_leaves_zero_room(self):
        """12×14 曾经让 R 吃满宽度、图例只剩硬下限 0.5。"""
        tmpl = get_template("semicircle")
        _, points = load_points(DB_PATH, chart_key="heat_age")

        def solve_at(ov, w, h):
            sk = build_skeleton(tmpl, points, "heat_age", "标题", width_in=w,
                                height_in=h, param_overrides=ov, semantic_tags=[])
            return solve(sk, points)

        avail_w, _ = available_box(12.0, 14.0)
        spec = solve_at(None, avail_w, 14.0 - chrome_height_in())
        sector = [e for e in spec.elements if e.type == "arc"][0]
        self.assertLess(sector.geometry["R"] + 0.6, avail_w / 2,
                        "半径仍然吃满宽度，图例列会被挤没")


class PageSpecLike:
    """把 dict 版 pagespec 包成只有 elements/width_in 的最小白话对象。"""

    def __init__(self, doc):
        self.width_in = doc["width_in"]
        self.height_in = doc["height_in"]
        self.elements = [_El(e) for e in doc["elements"]]


class _El:
    def __init__(self, d):
        self.id = d["id"]
        self.x_in = d["x_in"]
        self.y_in = d["y_in"]
        self.w_in = d["w_in"]
        self.h_in = d["h_in"]


if __name__ == "__main__":
    unittest.main()
