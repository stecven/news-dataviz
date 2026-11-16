"""自由布局 0.1 的验收测试（用户 m05945）。

三组：流式分配的坐标与间距、溢出的明确报错、整版渲染产物。

**契约升级（用户裁定，本次修复）**：卡片在格子内**严格等比缩放**，装不下就
升栏；``PlacedCard.w_in/h_in`` 记的是**等比缩放后的真实外框**（可以小于格子），
``x_in`` 是外框在格子里**居中**后的位置。因此「卡片占满整行」「贴齐栏边」不再
成立；「间距 == gutter」改按**格子**量（外框居中后可见间隙只会更宽）。
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
        """口径：``(x_in, y_in)`` 是**画出来的**位置，``(w_in, h_in)`` 是**真实外框**。

        契约升级（等比居中留白）后，卡片被等比适配进分配的格子，外框通常比
        格子小一圈，再在格子里水平居中；所以：

        * thermo 的格子是 9.2×4.6，等比适配后只画到 7.3456×4.572711（chrome
          固定 1.75 in 不缩放，所以外框不是格子的纯比例子集），居中后
          x = 0.4 + (9.2-7.3456)/2 = 1.3272，y 仍是行顶 0.4（顶端对齐）；
        * semi 的格子 4.45×4.6 画到 4.4475×4.585，水平留白只有 0.00125；
        * ph 的格子 4.45×4.6 正好画满，位置与留白前的旧值相同。
        """
        page = _page()
        boxes = {"thermo": (0.4, 0.4, 9.2, 4.6),
                 "semi": (0.4, 5.3, 4.45, 4.6),
                 "ph": (5.15, 5.3, 4.45, 4.6)}
        for c in page.cards:
            bx, by, bw, bh = boxes[c.name]
            self.assertLessEqual(c.w_in, bw + 1e-9, c.name)
            self.assertLessEqual(c.h_in, bh + 1e-9, c.name)
            # 水平居中 ⇒ 两侧留白相等（不等就说明记错了口径）
            self.assertAlmostEqual(c.x_in - bx, (bx + bw) - (c.x_in + c.w_in),
                                   places=6, msg=c.name)
            # 顶端对齐 ⇒ y 就是行顶，不做垂直居中
            self.assertAlmostEqual(c.y_in, by, places=6, msg=c.name)
        got = {c.name: (round(c.x_in, 6), round(c.y_in, 6),
                        round(c.w_in, 6), round(c.h_in, 6)) for c in page.cards}
        self.assertEqual(got["thermo"], (1.3272, 0.4, 7.3456, 4.572711))
        self.assertEqual(got["semi"], (0.40125, 5.3, 4.4475, 4.585))
        self.assertEqual(got["ph"], (5.15, 5.3, 4.45, 4.6))

    def test_gaps_are_exactly_the_gutter(self):
        """间隙按**格子**量（游标推进量），不按卡片外框量。

        契约升级后卡片在格子里居中留白：外框之间的可见间距 = gutter + 两侧
        留白，所以必然 ≥ gutter 且通常更宽（semi/ph 之间可见 0.30125）。版面
        真正保证的仍是「格子与格子之间正好一个 gutter」。
        """
        page = _page()
        semi, ph = page.card("semi"), page.card("ph")
        # 横向：把居中留白从外框坐标反推回格子边界，再量格子的间隙
        semi_box_right = (semi.x_in + semi.w_in
                          + (semi.card.width_in - semi.w_in) / 2)
        ph_box_left = ph.x_in - (ph.card.width_in - ph.w_in) / 2
        self.assertAlmostEqual(ph_box_left - semi_box_right, 0.3, places=6)
        # 纵向：行高按格子高推进，行与行之间正好一个 gutter
        self.assertAlmostEqual(
            page.rows[1]["y_in"] - (page.rows[0]["y_in"] + page.rows[0]["h_in"]),
            0.3, places=6)
        # 可见间距只会更宽（留白），绝不会窄到重叠
        self.assertGreaterEqual(ph.x_in - (semi.x_in + semi.w_in), 0.3 - 1e-9)

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
        """超宽卡片等比缩进格子，不报错——缩的是**真实外框**，不是格子。

        thermo 自然宽 10.52 in，格子 9.2 in：升级后不再「撑满 9.2」，而是
        等比适配（这里受格子高 4.6 限制）画到 7.3456×4.572711。
        """
        page = _page(fit_oversized=True)
        thermo = page.card("thermo")
        self.assertLess(thermo.w_in, 10.52)          # 确实缩了
        self.assertGreater(thermo.w_in, 0.0)
        self.assertLessEqual(thermo.w_in, 9.2 + 1e-9)   # 装得进格子
        self.assertLessEqual(thermo.h_in, 4.6 + 1e-9)

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
        """落位 JSON 里记的是**真实外框**：PlacedCard.w_in 与内嵌 spec 一致。

        格子宽（9.2）只用于定位与居中，不再写进落位记录；x_in 是「格子左边
        界 + 居中留白」＝ 0.4 + (9.2-7.3456)/2。
        """
        page = _page()
        out = mkdtemp()
        path = os.path.join(out, "pagelayout.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(page.to_dict(), fh, ensure_ascii=False)
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertEqual(len(doc["cards"]), 3)
        self.assertEqual(doc["cards"][2]["x_in"], 5.15)
        thermo = doc["cards"][0]
        self.assertEqual(thermo["spec"]["width_in"], 7.3456)
        self.assertEqual(thermo["w_in"], thermo["spec"]["width_in"])
        self.assertAlmostEqual(thermo["x_in"], 0.4 + (9.2 - 7.3456) / 2,
                               places=6)


if __name__ == "__main__":
    unittest.main()
