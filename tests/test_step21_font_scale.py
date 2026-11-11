"""用户 m05688：半圆扇区描边 + 字号随画布缩放。

两件事：
1. 半圆扇区加 0.5 pt 的 neutral_mid 描边——14.4° 这类窄扇区靠颜色分不开，
   必须有边界；
2. 字号随画布缩放：``font_scale = min(frame_w/10, frame_h/6)``，缩放后截断到
   6–24 pt。图框让画布变大之后，固定 pt 会让字显得小（反之则溢出）。

边界：只改渲染层。形状数不变（描边是属性不是新元素），求解 / 选型 / 模型 /
数据库一律不动。
"""
import json
import os
import unittest
from dataclasses import replace

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Pt

from loop import palette as P
from loop.data_source import DB_PATH, load_points
from loop.pipeline import run_selected
from loop.render_arc import render_pptx_arc
from loop.render_thermo import render_pptx_thermo
from loop.scaffold import build_pagespec
from tests.scratch import mkdtemp


def _points(values, unit="%"):
    return [{"seq": i + 1, "label": f"p{i+1}", "value": float(v), "unit": unit}
            for i, v in enumerate(values)]


def _title_size(pptx_path, name="title"):
    prs = Presentation(pptx_path)
    for shp in prs.slides[0].shapes:
        if shp.name == name:
            return shp.text_frame.paragraphs[0].runs[0].font.size.pt
    raise AssertionError(f"shape {name!r} not found in {pptx_path}")


def _shape_names(pptx_path):
    prs = Presentation(pptx_path)
    return [s.name for s in prs.slides[0].shapes]


class TestSectorStroke(unittest.TestCase):
    """闸口：14.4° 窄扇区有清晰边界。"""

    @classmethod
    def setUpClass(cls):
        cls.dir = mkdtemp()
        cls.spec = build_pagespec(_points([10, 3, 3, 3, 3]), "占比构成",
                                  template_name="semicircle", frame=True)
        cls.pptx = os.path.join(cls.dir, "semi.pptx")
        cls.png = os.path.join(cls.dir, "semi.png")
        render_pptx_arc(cls.spec, cls.pptx)
        from loop.preview import render_preview
        render_preview(cls.spec, cls.png)

    def test_every_sector_has_the_palette_stroke(self):
        prs = Presentation(self.pptx)
        want = RGBColor.from_string(P.PALETTE[P.SECTOR_STROKE_ROLE])
        seen = 0
        for shp in prs.slides[0].shapes:
            if not shp.name.startswith("sector_"):
                continue
            seen += 1
            self.assertEqual(shp.line.width, Pt(P.SECTOR_STROKE_PT),
                             f"{shp.name} 线宽不是 {P.SECTOR_STROKE_PT} pt")
            self.assertEqual(str(shp.line.color.rgb), str(want),
                             f"{shp.name} 描边色不是 {P.SECTOR_STROKE_ROLE}")
        self.assertEqual(seen, 5)

    def test_stroke_is_an_attribute_so_shape_count_is_unchanged(self):
        names = _shape_names(self.pptx)
        self.assertEqual(len(names), 15)          # 5 扇区 + 中心 + 5 图例 + 框 + 带 + 标题 + 说明
        self.assertEqual(len(names), len(self.spec.elements))

    def test_preview_draws_the_sector_boundary(self):
        from PIL import Image
        im = Image.open(self.png).convert("RGB")
        want = tuple(int(P.PALETTE[P.SECTOR_STROKE_ROLE][i:i+2], 16)
                     for i in (0, 2, 4))
        hits = 0
        for y in range(0, im.height, 1):
            for x in range(0, im.width, 1):
                if im.getpixel((x, y)) == want:
                    hits += 1
        self.assertGreater(hits, 500, "预览里看不到扇区描边")


class TestCanvasScaleFormula(unittest.TestCase):
    """闸口：font_scale 公式与极值。"""

    def test_base_canvas_is_one(self):
        self.assertAlmostEqual(P.canvas_scale(10.0, 6.0), 1.0)

    def test_takes_the_smaller_of_the_two_ratios(self):
        self.assertAlmostEqual(P.canvas_scale(20.0, 6.0), 1.0)   # 只变宽
        self.assertAlmostEqual(P.canvas_scale(20.0, 12.0), 2.0)
        self.assertAlmostEqual(P.canvas_scale(5.0, 3.0), 0.5)

    def test_degenerate_canvas_falls_back_to_one(self):
        self.assertAlmostEqual(P.canvas_scale(0.0, 6.0), 1.0)
        self.assertAlmostEqual(P.canvas_scale(10.0, 0.0), 1.0)

    def test_spec_scale_prefers_the_frame_box(self):
        spec = build_pagespec(_points([1, 2, 3]), "t",
                             template_name="semicircle", frame=True)
        w, h = spec.frame_bbox[2], spec.frame_bbox[3]
        self.assertAlmostEqual(P.spec_scale(spec), P.canvas_scale(w, h))
        plain = replace(spec, frame_bbox=None)          # 无框时退回画布尺寸
        self.assertAlmostEqual(P.spec_scale(plain),
                               P.canvas_scale(plain.width_in, plain.height_in))

    def test_font_is_clamped_to_six_and_twenty_four(self):
        self.assertEqual(P.scaled_font_size("title", 10.0), P.MAX_FONT_PT)
        self.assertEqual(P.scaled_font_size("note", 0.1), P.MIN_FONT_PT)
        self.assertEqual(P.scaled_font_size("title", 1.0), 20.0)
        self.assertEqual(P.scaled_font_size("note", 1.0), 8.0)


class TestRenderersApplyTheScale(unittest.TestCase):
    """闸口：画布变大时字放大、变小时字缩小，且真的落到渲染产物里。"""

    @classmethod
    def setUpClass(cls):
        cls.dir = mkdtemp()
        title, rows = load_points(DB_PATH, chart_key="heat_ratio_top5")
        cls.plain = build_pagespec(rows, title, template_name="thermometer")
        cls.base = build_pagespec(rows, title, template_name="thermometer",
                                  frame=True)

    def _render_title(self, spec, renderer=render_pptx_thermo, name="title"):
        path = os.path.join(self.dir, f"{name}-{id(spec)}.pptx")
        renderer(spec, path)
        return _title_size(path, name)

    def test_unframed_spec_keeps_the_table_size(self):
        # 未包框时画布就是基准 10×6，字不加不减。
        self.assertAlmostEqual(self._render_title(self.plain), 20.0, places=2)

    def test_bigger_canvas_grows_the_font(self):
        bigger = replace(self.base, frame_bbox=[0.0, 0.0, 12.0, 7.2])
        self.assertAlmostEqual(self._render_title(self.base), 19.5, places=2)
        self.assertGreater(self._render_title(bigger),
                           self._render_title(self.base))

    def test_smaller_canvas_shrinks_the_font(self):
        smaller = replace(self.base, frame_bbox=[0.0, 0.0, 8.0, 4.8])
        # python-pptx 把字号存成「百分之一磅」，回读会有 1e-2 级浮点尾差。
        self.assertAlmostEqual(self._render_title(smaller), 16.0, places=2)

    def test_preview_font_follows_the_scale_too(self):
        from loop.preview import render_preview
        from PIL import Image
        small = os.path.join(self.dir, "pv-small.png")
        big = os.path.join(self.dir, "pv-big.png")
        render_preview(replace(self.base, frame_bbox=[0.0, 0.0, 8.0, 4.8]), small)
        render_preview(replace(self.base, frame_bbox=[0.0, 0.0, 12.0, 7.2]), big)
        def dark(path):
            im = Image.open(path).convert("RGB")
            return sum(1 for y in range(20, 70) for x in range(40, im.width - 40)
                       if sum(im.getpixel((x, y))) < 400)
        self.assertGreater(dark(big), dark(small),
                           "预览里字号没有跟着画布缩放")


class TestSemicircleAndThermometerShapesUnchanged(unittest.TestCase):
    """闸口：半圆 15、温度计 39，描边与缩放都不新增元素。"""

    def test_semicircle_shape_count_is_fifteen(self):
        spec = build_pagespec(_points([10, 3, 3, 3, 3]), "t",
                              template_name="semicircle", frame=True)
        d = mkdtemp()
        path = os.path.join(d, "s.pptx")
        render_pptx_arc(spec, path)
        self.assertEqual(len(_shape_names(path)), 15)
        self.assertEqual(len(spec.elements), 15)

    def test_thermometer_shape_count_is_thirty_nine(self):
        title, rows = load_points(DB_PATH, chart_key="heat_ratio_top5")
        spec = build_pagespec(rows, title, template_name="thermometer",
                              frame=True)
        d = mkdtemp()
        path = os.path.join(d, "t.pptx")
        render_pptx_thermo(spec, path)
        self.assertEqual(len(_shape_names(path)), 39)
        self.assertEqual(len(spec.elements), 39)

    def test_placeholder_card_text_still_fits_its_frame(self):
        # 小卡片（2.80 in 宽）缩放后会撞到 6 pt 下限——确认它没有溢出边框，
        # 也没有被裁掉（溢出要停下来问用户改布局，不是自己动版面）。
        r = run_selected(values=[10, 3, 2, 2, 2, 1], semantic="占比构成",
                         out_root=mkdtemp(), group_name="step21")
        with open(r["pagespec"], encoding="utf-8") as fh:
            doc = json.load(fh)
        pad = doc["layout"]["frame"]["pad_in"]
        fx, fy, fw, fh = doc["frame_bbox"]
        for el in doc["elements"]:
            self.assertGreaterEqual(el["x_in"], fx - 1e-6, el["id"])
            self.assertGreaterEqual(el["y_in"], fy - 1e-6, el["id"])
            self.assertLessEqual(el["x_in"] + el["w_in"], fx + fw + 1e-6, el["id"])
            self.assertLessEqual(el["y_in"] + el["h_in"], fy + fh + 1e-6, el["id"])
        self.assertAlmostEqual(pad, 0.3, places=6)


if __name__ == "__main__":
    unittest.main()
