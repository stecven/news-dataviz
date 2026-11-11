"""图文混排 0.1（用户 m06055）：文本块 + 文字与卡片共用的流式排版。"""
import json
import os
import unittest

from loop import palette, text_flow
from loop.layout import (CardSpec, LayoutOverflowError, LayoutSpec, PlacedBlock,
                         TextBlock, flow_layout, flatten)
from loop.render_page import render_layout
from tests.scratch import mkdtemp

TITLE = "取暖电器换季热销"
LEAD = "入冬以来取暖电器进入销售旺季，成交额环比增速明显高于其他小家电。"


def _cards():
    return [
        CardSpec("thermo", "thermometer", chart_key="heat_ratio_top5",
                 title="增速TOP5", width_in=9.2, height_in=4.2),
        CardSpec("semi", "semicircle", chart_key="heat_age",
                 title="年龄占比", width_in=4.45, height_in=4.6),
        CardSpec("ph", "placeholder", title="无适用图形",
                 width_in=4.45, height_in=3.4),
    ]


def _flow(height_in=15.0, items=None, margin_in=0.4):
    layout = LayoutSpec(width_in=10.0, height_in=height_in,
                        margin_in=margin_in, gutter_in=0.3)
    return flow_layout(layout, items if items is not None else (
        [TextBlock(TITLE, "title", "center"), TextBlock(LEAD, "body")]
        + _cards()))


class TestTextBlockDefinition(unittest.TestCase):

    def test_style_and_align_are_validated(self):
        with self.assertRaises(ValueError) as ctx:
            TextBlock("正文", "huge")
        self.assertIn("huge", str(ctx.exception))
        with self.assertRaises(ValueError):
            TextBlock("正文", "body", "justify")
        with self.assertRaises(ValueError):
            TextBlock("", "body")

    def test_style_names_come_from_the_font_scale(self):
        """样式名就是色板字号表里那几个设计角色，不另立一套。"""
        for style in text_flow.BLOCK_STYLES:
            self.assertIn(style, palette.FONT_SIZES)

    def test_height_is_lines_times_line_height_plus_padding(self):
        """一行正文的手算高度 = 11pt × 1.35 / 72 + 上下各 0.05 in。"""
        line_h = 11 * 1.35 / 72
        one = text_flow.block_height_in("短", "body", 9.2, 1.0)
        self.assertAlmostEqual(one, line_h + 0.1, places=6)
        text = "一" * 200
        lines = len(text_flow.wrap(text, "body", 9.2, 1.0))
        self.assertGreater(lines, 1)
        self.assertAlmostEqual(text_flow.block_height_in(text, "body", 9.2, 1.0),
                               lines * line_h + 0.1, places=6)

    def test_narrower_box_uses_more_lines(self):
        text = "取暖电器换季热销成交额环比增长明显" * 3
        wide = text_flow.wrap(text, "body", 9.2, 1.0)
        narrow = text_flow.wrap(text, "body", 3.0, 1.0)
        self.assertGreater(len(narrow), len(wide))
        for line in narrow:
            self.assertLessEqual(len(line), len(text))

    def test_explicit_newline_is_a_hard_break(self):
        lines = text_flow.wrap("第一段\n第二段", "body", 9.2, 1.0)
        self.assertEqual(lines, ["第一段", "第二段"])

    def test_non_positive_width_is_rejected(self):
        with self.assertRaises(ValueError):
            text_flow.wrap("正文", "body", 0.0)


class TestMixedFlowPlacement(unittest.TestCase):

    def test_text_blocks_take_the_whole_usable_width(self):
        page = _flow()
        for b in page.blocks:
            self.assertAlmostEqual(b.x_in, page.margin_in, places=9)
            self.assertAlmostEqual(b.w_in, page.width_in - 2 * page.margin_in,
                                   places=9)

    def test_text_and_cards_never_share_a_row(self):
        """0.1 采用上下型排布：文本独占整行，不与卡片抢同一行。"""
        page = _flow()
        for b in page.blocks:
            for c in page.cards:
                self.assertNotEqual(b.row, c.row)

    def test_no_two_items_overlap(self):
        page = _flow()
        items = [(v.x_in, v.y_in, v.x_in + v.w_in, v.y_in + v.h_in)
                 for _, v in page.items()]
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                ax0, ay0, ax1, ay1 = items[i]
                bx0, by0, bx1, by1 = items[j]
                self.assertFalse(ax0 < bx1 - 1e-9 and bx0 < ax1 - 1e-9
                                 and ay0 < by1 - 1e-9 and by0 < ay1 - 1e-9,
                                 f"item {i} 与 item {j} 重叠")

    def test_gutters_are_exact(self):
        """行带之间的垂直间隔严格等于 gutter（文本行与卡片行一视同仁）。"""
        page = _flow()
        rows = sorted(page.rows, key=lambda r: r["y_in"])
        for prev, nxt in zip(rows, rows[1:]):
            self.assertAlmostEqual(prev["y_in"] + prev["h_in"]
                                   + page.gutter_in, nxt["y_in"], places=6)

    def test_horizontal_neighbours_are_a_gutter_apart(self):
        page = _flow()
        by_row = {}
        for c in page.cards:
            by_row.setdefault(c.row, []).append(c)
        pairs = 0
        for cards in by_row.values():
            cards.sort(key=lambda c: c.x_in)
            for left, right in zip(cards, cards[1:]):
                self.assertAlmostEqual(left.x_in + left.w_in + page.gutter_in,
                                       right.x_in, places=6)
                pairs += 1
        self.assertGreaterEqual(pairs, 1, "演示里应有一行并排两张卡片")

    def test_everything_stays_inside_the_page(self):
        page = _flow()
        for _, v in page.items():
            self.assertGreaterEqual(v.x_in, page.margin_in - 1e-9)
            self.assertGreaterEqual(v.y_in, page.margin_in - 1e-9)
            self.assertLessEqual(v.x_in + v.w_in,
                                 page.width_in - page.margin_in + 1e-9)
            self.assertLessEqual(v.y_in + v.h_in,
                                 page.height_in - page.margin_in + 1e-9)

    def test_blocks_carry_their_wrapped_lines(self):
        page = _flow()
        for b in page.blocks:
            self.assertIsInstance(b, PlacedBlock)
            self.assertTrue(b.lines)
            self.assertAlmostEqual(
                b.h_in, len(b.lines) * text_flow.line_height_in(
                    b.block.style, b.scale) + 2 * text_flow.BLOCK_PAD_IN,
                places=6)


class TestOverflow(unittest.TestCase):

    def test_content_taller_than_the_page_raises(self):
        with self.assertRaises(LayoutOverflowError) as ctx:
            _flow(height_in=6.0)
        self.assertIn("thermo", str(ctx.exception))

    def test_oversized_text_block_raises(self):
        with self.assertRaises(LayoutOverflowError) as ctx:
            _flow(items=[TextBlock("标题", "title", width_in=20.0)])
        self.assertIn("可用宽度", str(ctx.exception))

    def test_tall_text_block_alone_can_overflow(self):
        """排版层算出的块高超过可用高度就报错，不静默截断。"""
        text = "正文" * 1000                      # 10×6 版面下约 33 行
        self.assertGreater(text_flow.block_height_in(text, "body", 9.2, 1.0),
                           6.0 - 2 * 0.4)
        with self.assertRaises(LayoutOverflowError) as ctx:
            _flow(height_in=6.0, items=[TextBlock(text, "body")])
        self.assertIn("文本块", str(ctx.exception))


class TestFlattenAndRender(unittest.TestCase):

    def test_blocks_are_flattened_as_text_elements(self):
        spec = flatten(_flow())
        blocks = [e for e in spec.elements
                  if (e.geometry or {}).get("block")]
        self.assertEqual(len(blocks), 2)
        for e in blocks:
            self.assertTrue(e.id.startswith("t"))
            self.assertTrue(e.geometry["lines"])
            self.assertTrue(e.geometry["align"])
            self.assertEqual(e.type, "text")
        self.assertEqual([e.role for e in blocks], ["title", "body"])
        self.assertAlmostEqual(blocks[0].x_in, blocks[1].x_in, places=9)

    def test_render_outputs_a_full_page(self):
        page = _flow()
        out = mkdtemp(prefix="newspaper_")
        res = render_layout(page, out)
        self.assertTrue(os.path.isfile(res["preview"]))
        self.assertTrue(res["pptx"].endswith(".pptx"))

        from PIL import Image
        with Image.open(res["preview"]) as img:
            self.assertEqual(img.size, (1000, 1500))
            # 标题块区域里必须有深色像素（字真的画出来了）
            title = page.block(page.blocks[0].name)
            box = (int(title.x_in * 100), int(title.y_in * 100),
                   int((title.x_in + title.w_in) * 100),
                   int((title.y_in + title.h_in) * 100))
            # 用直方图数深色像素（getdata 在 Pillow 14 起被弃用）
            hist = img.convert("L").crop(box).histogram()
            dark = sum(hist[:100])
            self.assertGreater(dark, 200, "标题块区域几乎没有字")
            # 卡片区自己也有字，但不该被正文块覆盖：
            # 正文块与卡片的外接盒不重叠（重排后仍然成立）
            for b in page.blocks:
                for c in page.cards:
                    self.assertFalse(
                        b.x_in < c.x_in + c.w_in - 1e-9
                        and c.x_in < b.x_in + b.w_in - 1e-9
                        and b.y_in < c.y_in + c.h_in - 1e-9
                        and c.y_in < b.y_in + b.h_in - 1e-9,
                        f"文本块 {b.name} 压在卡片 {c.name} 上")

    def test_pptx_contains_one_textbox_per_block(self):
        from loop.verify import read_shapes
        page = _flow()
        out = mkdtemp(prefix="newspaper_pptx_")
        res = render_layout(page, out)
        shapes = read_shapes(res["pptx"])
        spec = flatten(page)
        for e in spec.elements:
            self.assertIn(e.id, shapes)
        block_ids = [e.id for e in spec.elements
                     if (e.geometry or {}).get("block")]
        self.assertEqual(len(block_ids), 2)
        # 折好的行真的进了 PPTX 文本（不是交给 PowerPoint 自己折）
        first = shapes[block_ids[0]]["text"]
        self.assertIn("取暖", first)


class TestBackwardCompatible(unittest.TestCase):

    def test_cards_only_flow_still_works(self):
        page = _flow(items=_cards())
        self.assertEqual(len(page.blocks), 0)
        self.assertEqual(len(page.cards), 3)
        self.assertEqual([r["kind"] for r in page.rows],
                         ["cards"] * len(page.rows))


if __name__ == "__main__":
    unittest.main()
