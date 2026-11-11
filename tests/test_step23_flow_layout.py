"""自由布局 0.1 的验收测试（用户 m05945）。

三组：流式分配的坐标与间距、溢出的明确报错、整版渲染产物。
"""
import json
import os
import unittest

from PIL import Image
from pptx import Presentation

from loop.layout import (CardSpec, LayoutOverflowError, LayoutSpec, flatten,
                         flow_layout)
from loop.render_page import render_layout
from loop.verify import read_shapes
from tests.scratch import mkdtemp

THREE = [
    ("thermo", "thermometer", "heat_ratio_top5", 9.2, 4.6),
    ("semi", "semicircle", "heat_age", 4.45, 4.6),
    ("ph", "placeholder", None, 4.45, 4.6),
]


def _cards(rows=THREE):
    out = []
    for name, kind, key, w, h in rows:
        out.append(CardSpec(name, kind, chart_key=key, title=name,
                            width_in=w, height_in=h))
    return out


def _page(**kw):
    return flow_layout(LayoutSpec(**kw), _cards())


class TestFlowPlacement(unittest.TestCase):
    def test_three_cards_land_in_two_rows(self):
        page = _page()
        self.assertEqual([c.name for c in page.cards], ["thermo", "semi", "ph"])
        self.assertEqual([c.row for c in page.cards], [0, 1, 1])
        self.assertEqual(len(page.rows), 2)

    def test_exact_coordinates(self):
        page = _page()
        got = {c.name: (c.x_in, c.y_in, c.w_in, c.h_in) for c in page.cards}
        self.assertEqual(got["thermo"], (0.4, 0.4, 9.2, 4.6))
        self.assertEqual(got["semi"], (0.4, 5.3, 4.45, 4.6))
        self.assertEqual(got["ph"], (5.15, 5.3, 4.45, 4.6))

    def test_gaps_are_exactly_the_gutter(self):
        page = _page()
        semi, ph = page.card("semi"), page.card("ph")
        self.assertAlmostEqual(ph.x_in - (semi.x_in + semi.w_in), 0.3, places=6)
        self.assertAlmostEqual(semi.y_in - (page.card("thermo").y_in
                                            + page.card("thermo").h_in),
                               0.3, places=6)

    def test_every_card_is_inside_the_page(self):
        page = _page()
        for c in page.cards:
            self.assertGreaterEqual(c.x_in, page.margin_in - 1e-9)
            self.assertGreaterEqual(c.y_in, page.margin_in - 1e-9)
            self.assertLessEqual(c.x_in + c.w_in,
                                 page.width_in - page.margin_in + 1e-9)
            self.assertLessEqual(c.y_in + c.h_in,
                                 page.height_in - page.margin_in + 1e-9)

    def test_no_two_cards_overlap(self):
        page = _page()
        for i, a in enumerate(page.cards):
            for b in page.cards[i + 1:]:
                overlap = (a.x_in < b.x_in + b.w_in - 1e-9
                           and b.x_in < a.x_in + a.w_in - 1e-9
                           and a.y_in < b.y_in + b.h_in - 1e-9
                           and b.y_in < a.y_in + a.h_in - 1e-9)
                self.assertFalse(overlap, f"{a.name} 与 {b.name} 重叠")

    def test_cards_are_top_aligned_in_their_row(self):
        page = _page()
        self.assertEqual(page.card("semi").y_in, page.card("ph").y_in)


class TestOverflow(unittest.TestCase):
    def test_card_wider_than_the_page_raises(self):
        # 不给预设尺寸 = 用自然尺寸；温度计卡片自然宽 10.52 in > 可用 9.20 in。
        cards = [CardSpec("thermo", "thermometer",
                          chart_key="heat_ratio_top5", title="thermo")]
        with self.assertRaises(LayoutOverflowError) as ctx:
            flow_layout(LayoutSpec(fit_oversized=False), cards)
        msg = str(ctx.exception)
        self.assertIn("thermo", msg)
        self.assertIn("10.52", msg)
        self.assertIn("9.20", msg)

    def test_fit_oversized_shrinks_instead_of_refusing(self):
        page = _page(fit_oversized=True)
        thermo = page.card("thermo")
        self.assertAlmostEqual(thermo.w_in, 9.2, places=6)
        self.assertLess(thermo.w_in, 10.52)

    def test_row_that_runs_past_the_bottom_raises(self):
        rows = [("a", "semicircle", "heat_age", 4.45, 6.0),
                ("b", "semicircle", "heat_age", 4.45, 6.0),
                ("c", "semicircle", "heat_age", 4.45, 6.0)]
        with self.assertRaises(LayoutOverflowError) as ctx:
            flow_layout(LayoutSpec(height_in=8.0), _cards(rows))
        self.assertIn("8", str(ctx.exception))

    def test_error_carries_what_was_placed(self):
        rows = [("a", "semicircle", "heat_age", 9.2, 6.0),
                ("b", "semicircle", "heat_age", 9.2, 6.0)]
        try:
            flow_layout(LayoutSpec(height_in=7.0), _cards(rows))
            self.fail("expected LayoutOverflowError")
        except LayoutOverflowError as exc:
            self.assertEqual([c.name for c in exc.placed], ["a"])
            self.assertEqual([c.name for c in exc.remaining], ["b"])

    def test_zero_usable_width_raises(self):
        with self.assertRaises(LayoutOverflowError):
            flow_layout(LayoutSpec(margin_in=5.0), _cards())

    def test_width_and_height_must_be_given_together(self):
        with self.assertRaises(ValueError):
            CardSpec("x", "thermometer", chart_key="heat_ratio_top5",
                     width_in=4.0)


class TestFlatten(unittest.TestCase):
    def test_element_ids_are_prefixed_and_unique(self):
        page = _page()
        spec = flatten(page)
        ids = [e.id for e in spec.elements]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(ids), 39 + 15 + 5)
        self.assertTrue(any(i.startswith("c0_") for i in ids))
        self.assertTrue(any(i.startswith("c2_") for i in ids))

    def test_outline_geometry_is_translated_with_its_card(self):
        page = _page()
        spec = flatten(page)
        semi = page.card("semi")
        out = [e for e in spec.elements
               if e.id.startswith("c1_") and e.type == "outline"]
        self.assertFalse(out, "半圆卡片不该有外圈")
        thermo = page.card("thermo")
        out = [e for e in spec.elements if e.type == "outline"]
        self.assertTrue(out)
        for e in out:
            self.assertGreaterEqual(e.x_in, thermo.x_in - 1e-9)
            self.assertLessEqual(e.x_in + e.w_in,
                                 thermo.x_in + thermo.w_in + 1e-9)
            self.assertGreaterEqual(e.geometry["cx"], thermo.x_in - 1e-9)

    def test_flatten_records_the_page_canvas(self):
        spec = flatten(_page())
        self.assertEqual((spec.width_in, spec.height_in), (10.0, 15.0))
        self.assertEqual(spec.layout["kind"], "flow")


class TestPageRender(unittest.TestCase):
    def test_preview_is_the_whole_page_and_has_ink_in_every_card(self):
        page = _page()
        out = mkdtemp()
        res = render_layout(page, out)
        with Image.open(res["preview"]) as im:
            self.assertEqual(im.size, (1000, 1500))
            for c in page.cards:
                x0 = int(c.x_in * 100) + 3
                y0 = int(c.y_in * 100) + 3
                x1 = int((c.x_in + c.w_in) * 100) - 3
                y1 = int((c.y_in + c.h_in) * 100) - 3
                non_white = 0
                for y in range(y0, y1, 3):
                    for x in range(x0, x1, 3):
                        if im.getpixel((x, y)) != (255, 255, 255):
                            non_white += 1
                self.assertGreater(non_white, 50, f"{c.name} 卡片区域空白")

    def test_pptx_has_one_shape_per_element_named_after_the_card(self):
        page = _page()
        out = mkdtemp()
        res = render_layout(page, out)
        shapes = read_shapes(res["pptx"])
        spec = res["flat_spec"]
        self.assertEqual(len(shapes), len(spec.elements))
        names = set(shapes)
        for e in spec.elements:
            self.assertIn(e.id, names)
        prs = Presentation(res["pptx"])
        self.assertAlmostEqual(prs.slide_width / 914400, 10.0, places=3)
        self.assertAlmostEqual(prs.slide_height / 914400, 15.0, places=3)

    def test_page_layout_json_round_trips(self):
        page = _page()
        out = mkdtemp()
        path = os.path.join(out, "pagelayout.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(page.to_dict(), fh, ensure_ascii=False)
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertEqual(len(doc["cards"]), 3)
        self.assertEqual(doc["cards"][2]["x_in"], 5.15)
        self.assertEqual(doc["cards"][0]["spec"]["width_in"], 9.2)


if __name__ == "__main__":
    unittest.main()
