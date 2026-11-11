"""多栏图文混排 0.1（用户 m06230）的验收测试。

闸口（用户原文）：
1. 文本块在 2 栏布局下，实际宽度与高度计算严格匹配，不溢出栏宽、不越出画布。
2. 跨栏的文本或卡片，严格对齐左右边距。
3. 同行的卡片和文字不会交叠，总高超出画布抛 ``LayoutOverflowError``。
4. 兜底默认配图生效（测试验证）。
5. 全量测试仍全绿（566+），不破坏原有单栏逻辑（向后兼容）。
"""
import json
import os
import unittest
from unittest import mock

from PIL import Image

from loop import compose, text_flow
from loop.compose import build_flow
from loop.layout import (CardSpec, LayoutFitError, LayoutOverflowError,
                         LayoutSpec, TextBlock, flow_layout, page_spec_path)
from loop.palette import LINE_HEIGHT_RATIO, font_size
from loop.render_page import render_layout
from tests.scratch import mkdtemp

W, H = 10.0, 15.0
MARGIN, GUTTER, COL_GUTTER = 0.4, 0.3, 0.2
PX = 100  # preview.py 的 PX_PER_IN

#: 一段能命中 heat_ratio_top5（取暖·品类·环比增速）的稿子。
COPY_HIT = ("取暖电器换季热销。入冬以来成交额环比走高。"
            "从细分品类看，取暖电器的成交额环比增速居前，欧式快热炉领跑。")

#: 一段很长、折成两栏后每栏都还有好几行的正文。
COPY_LONG = ("分年龄看，各年龄段消费者的取暖电器成交额占比不同，中年群体贡献了最大的"
             "份额，年轻群体的增速更快，但基数还小。把两件事分开看更清楚：谁的盘子大"
             "是占比问题，谁长得快是增速问题，新闻里常把两者混着说。")


def _layout(**kw):
    opts = dict(width_in=W, height_in=H, margin_in=MARGIN, gutter_in=GUTTER,
                column_count=2, column_gutter_in=COL_GUTTER)
    opts.update(kw)
    return LayoutSpec(**opts)


def _write_spec(page, out_dir):
    """``render_layout`` 只出图，规格由调用方落盘（与演示脚本一致）。"""
    with open(page_spec_path(out_dir), "w", encoding="utf-8") as fh:
        json.dump(page.to_dict(), fh, ensure_ascii=False, indent=2)


def _overlap(a, b):
    return (a.x_in < b.x_in + b.w_in - 1e-9 and b.x_in < a.x_in + a.w_in - 1e-9
            and a.y_in < b.y_in + b.h_in - 1e-9
            and b.y_in < a.y_in + a.h_in - 1e-9)


def _no_applicable(rationale="无适用图形：分项过多（MAX_SLICES）"):
    """让选型器「判不适用」，用来验兜底政策（真实库里 12 组数据都是 5 项）。"""
    return {"selected_template": None, "rationale": rationale, "rejected": []}


class TestColumnsArithmetic(unittest.TestCase):
    def test_column_width_and_slots(self):
        layout = _layout()
        self.assertAlmostEqual(layout.usable_width_in, 9.2, places=6)
        self.assertAlmostEqual(layout.column_width_in, 4.5, places=6)
        self.assertAlmostEqual(layout.span_width_in(1), 4.5, places=6)
        self.assertAlmostEqual(layout.span_width_in(2), 9.2, places=6)
        self.assertAlmostEqual(layout.slot_x_in(0), 0.4, places=6)
        self.assertAlmostEqual(layout.slot_x_in(1), 5.1, places=6)

    def test_three_columns_divide_the_same_usable_width(self):
        layout = _layout(column_count=3)
        self.assertAlmostEqual(layout.column_width_in,
                               (9.2 - 2 * COL_GUTTER) / 3, places=6)
        self.assertAlmostEqual(layout.span_width_in(3), 9.2, places=6)

    def test_bad_column_settings_are_rejected(self):
        for kw in ({"column_count": 0}, {"column_count": 4},
                   {"column_gutter_in": -0.1}, {"max_card_height_ratio": 0.0},
                   {"max_card_height_ratio": 1.5}):
            with self.subTest(**kw):
                with self.assertRaises(ValueError):
                    _layout(**kw)

    def test_bad_spans_are_rejected(self):
        with self.assertRaises(ValueError):
            TextBlock("x", "body", column_span=0)
        with self.assertRaises(ValueError):
            TextBlock("x", "body", columns=4)
        with self.assertRaises(ValueError):
            CardSpec("c", "thermometer", chart_key="heat_ratio_top5",
                     column_span=5)


class TestBlockColumns(unittest.TestCase):
    def test_columns_narrow_the_wrap_width(self):
        """块内分栏先按**栏宽**折行，再均分到各栏 —— 不是先按整块宽折行。"""
        inner = text_flow.inner_column_width_in(9.2, 2, COL_GUTTER)
        self.assertAlmostEqual(inner, 4.5, places=6)
        narrow = text_flow.wrap_columns(COPY_LONG, "body", inner, 1, 1.0)
        two = text_flow.wrap_columns(COPY_LONG, "body", 9.2, 2, 1.0, COL_GUTTER)
        self.assertEqual(len(two), 2)
        # 均分不丢字、不重复：两栏行数之和等于按栏宽折出来的行数。
        self.assertEqual(sum(len(g) for g in two), len(narrow[0]))
        self.assertEqual(two[0] + two[1], narrow[0])
        self.assertTrue(all(g for g in two), "不能把字全塞进第一栏")
        self.assertLessEqual(abs(len(two[0]) - len(two[1])), 1)

    def test_narrow_column_wraps_into_more_lines(self):
        wide = text_flow.wrap_columns(COPY_LONG, "body", 9.2, 1, 1.0)
        narrow = text_flow.wrap_columns(COPY_LONG, "body", 4.5, 1, 1.0)
        self.assertGreater(len(narrow[0]), len(wide[0]))

    def test_reading_order_is_preserved(self):
        lines = [f"第{i}行" for i in range(5)]
        groups = text_flow.balance_lines(lines, 2)
        self.assertEqual(groups[0] + groups[1], lines)
        self.assertEqual(text_flow.balance_lines(["一行"], 2), [["一行"]])

    def test_height_is_the_tallest_column(self):
        two = text_flow.wrap_columns(COPY_LONG, "body", 9.2, 2, 1.0, COL_GUTTER)
        expected = (max(len(g) for g in two) * font_size("body")
                    * LINE_HEIGHT_RATIO / 72.0 + 2 * text_flow.BLOCK_PAD_IN)
        self.assertAlmostEqual(
            text_flow.columns_height_in(two, "body", 1.0), expected, places=6)

    def test_block_height_matches_the_formula(self):
        layout = _layout()
        block = TextBlock(COPY_LONG, "body", column_span=2, columns=2)
        page = flow_layout(layout, [block])
        placed = page.blocks[0]
        groups = text_flow.wrap_columns(COPY_LONG, "body",
                                        layout.span_width_in(2), 2, 1.0,
                                        COL_GUTTER)
        self.assertEqual(len(placed.line_groups), len(groups))
        self.assertAlmostEqual(placed.h_in,
                               text_flow.columns_height_in(groups, "body", 1.0),
                               places=6)
        self.assertAlmostEqual(placed.w_in, layout.span_width_in(2), places=6)

    def test_zero_width_is_rejected(self):
        with self.assertRaises(ValueError):
            text_flow.inner_column_width_in(0.2, 2, COL_GUTTER)
        with self.assertRaises(ValueError):
            text_flow.wrap_columns("x", "body", 0.0)


class TestMulticolPlacement(unittest.TestCase):
    def _page(self):
        layout = _layout()
        flow = [
            TextBlock("跨栏标题", "title", "center", column_span=2),
            TextBlock("左栏导语，占一栏。", "body", column_span=1),
            TextBlock("右栏结尾，占一栏。", "body", column_span=1),
            TextBlock("跨栏并分两栏的正文，" + COPY_LONG, "body",
                      column_span=2, columns=2),
            CardSpec("semi", "semicircle", chart_key="heat_age",
                     title="年龄占比", column_span=1),
            CardSpec("ph", "placeholder", title="占位", column_span=1),
        ]
        return layout, flow_layout(layout, flow)

    def test_spanning_items_align_to_both_margins(self):
        layout, page = self._page()
        title = page.block("跨栏标题")
        self.assertAlmostEqual(title.x_in, MARGIN, places=6)
        self.assertAlmostEqual(title.x_in + title.w_in, W - MARGIN, places=6)
        body = [b for b in page.blocks if b.block.columns == 2][0]
        self.assertAlmostEqual(body.x_in, MARGIN, places=6)
        self.assertAlmostEqual(body.x_in + body.w_in, W - MARGIN, places=6)
        self.assertAlmostEqual(body.w_in, layout.span_width_in(2), places=6)

    def test_single_column_items_sit_in_their_own_slots(self):
        layout, page = self._page()
        lead = page.block("左栏导语，占一栏。")
        tail = page.block("右栏结尾，占一栏。")
        self.assertAlmostEqual(lead.x_in, layout.slot_x_in(0), places=6)
        self.assertAlmostEqual(tail.x_in, layout.slot_x_in(1), places=6)
        self.assertAlmostEqual(lead.w_in, layout.column_width_in, places=6)
        self.assertAlmostEqual(tail.w_in, layout.column_width_in, places=6)
        # 并排两项之间的空隙是**栏间距**，不是行内的 gutter。
        self.assertAlmostEqual(tail.x_in - (lead.x_in + lead.w_in),
                               COL_GUTTER, places=6)

    def test_side_by_side_cards_fill_both_columns(self):
        layout, page = self._page()
        semi, ph = page.card("semi"), page.card("ph")
        self.assertAlmostEqual(semi.y_in, ph.y_in, places=6)
        self.assertAlmostEqual(semi.x_in, layout.slot_x_in(0), places=6)
        self.assertAlmostEqual(ph.x_in, layout.slot_x_in(1), places=6)
        self.assertAlmostEqual(ph.x_in + ph.w_in, W - MARGIN, places=6)
        self.assertAlmostEqual(semi.h_in, ph.h_in, places=6)

    def test_vertical_pitch_is_the_flow_gutter(self):
        _, page = self._page()
        title = page.block("跨栏标题")
        next_y = min(o.y_in for o in page.blocks + page.cards
                     if o.y_in > title.y_in + 1e-9)
        self.assertAlmostEqual(next_y, title.y_in + title.h_in + GUTTER,
                               places=6)

    def test_rows_record_their_mixture(self):
        _, page = self._page()
        kinds = [r["kind"] for r in page.rows]
        self.assertEqual(kinds[0], "text")
        self.assertIn("cards", kinds)
        row = [r for r in page.rows if r["kind"] == "row"][0]
        self.assertEqual(len(row["blocks"]), 2)
        self.assertEqual(row["cards"], [])

    def test_everything_stays_inside_the_canvas_and_never_overlaps(self):
        _, page = self._page()
        boxes = list(page.cards) + list(page.blocks)
        for o in boxes:
            self.assertGreaterEqual(o.x_in, MARGIN - 1e-9, o.name)
            self.assertGreaterEqual(o.y_in, MARGIN - 1e-9, o.name)
            self.assertLessEqual(o.x_in + o.w_in, W - MARGIN + 1e-9, o.name)
            self.assertLessEqual(o.y_in + o.h_in, H - MARGIN + 1e-9, o.name)
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                self.assertFalse(_overlap(a, b), f"{a.name} 与 {b.name} 交叠")

    def test_cross_column_card_uses_the_whole_row(self):
        layout = _layout()
        flow = [CardSpec("thermo", "thermometer", chart_key="heat_ratio_top5",
                         title="增速", column_span=2)]
        page = flow_layout(layout, flow)
        card = page.card("thermo")
        self.assertAlmostEqual(card.w_in, layout.span_width_in(2), places=6)
        self.assertLessEqual(card.h_in, layout.max_card_height_in + 1e-9)

    def test_narrow_column_card_grows_taller_instead_of_failing(self):
        """单栏宽度被钉死时，高度可以顶到上限，图形不至于因为「扁」而被拒。"""
        layout = _layout()
        page = flow_layout(layout, [CardSpec("semi", "semicircle",
                                             chart_key="heat_age",
                                             title="占比", column_span=1)])
        semi = page.card("semi")
        self.assertAlmostEqual(semi.w_in, layout.column_width_in, places=6)
        self.assertAlmostEqual(semi.h_in, layout.max_card_height_in, places=6)
        self.assertLess(semi.w_in / semi.h_in, 7.15 / 5.85)  # 比自然比例更方


class TestOverflow(unittest.TestCase):
    def test_too_much_content_raises_instead_of_clipping(self):
        layout = _layout(height_in=3.0)
        flow = [CardSpec("thermo", "thermometer", chart_key="heat_ratio_top5",
                         title="增速", column_span=2),
                CardSpec("semi", "semicircle", chart_key="heat_age",
                         title="占比", column_span=1)]
        with self.assertRaises((LayoutOverflowError, LayoutFitError)):
            flow_layout(layout, flow)

    def test_span_wider_than_the_grid_is_rejected(self):
        layout = _layout(column_count=1)
        flow = [CardSpec("thermo", "thermometer", chart_key="heat_ratio_top5",
                         title="增速", column_span=3)]
        with self.assertRaises(LayoutOverflowError):
            flow_layout(layout, flow)


class TestFallbackPolicy(unittest.TestCase):
    """用户 m06230 第①件：兜底默认从 skip 改成 placeholder 并写明原因。"""

    def test_placeholder_is_now_the_default(self):
        with mock.patch("loop.compose.select", return_value=_no_applicable()):
            result = build_flow(COPY_HIT, layout=_layout())
        kinds = [x.kind for x in result.flow if isinstance(x, CardSpec)]
        self.assertEqual(kinds, ["placeholder"])

    def test_skip_policy_still_available(self):
        with mock.patch("loop.compose.select", return_value=_no_applicable()):
            result = build_flow(COPY_HIT, layout=_layout(),
                                on_unapplicable="skip")
        self.assertEqual([x.kind for x in result.flow if isinstance(x, CardSpec)],
                         [])
        self.assertIn("skip", [n.get("policy") for n in result.notes])

    def test_bad_policy_is_rejected(self):
        with self.assertRaises(ValueError):
            build_flow(COPY_HIT, layout=_layout(), on_unapplicable="whatever")

    def test_note_explains_the_reason(self):
        """理由来自选型器的真实拒选文案（不是编的字符串）。"""
        from loop.selector import (SEMANTIC_OTHER, features_from_points, select)

        def _pts(values):
            return [{"seq": i + 1, "label": f"L{i + 1}", "value": v, "unit": "%"}
                    for i, v in enumerate(values)]

        six = select(features_from_points(_pts([10, 3, 2, 2, 2, 1]),
                                          compose.SEMANTIC_SHARE))
        other = select(features_from_points(_pts([10, 3, 2, 2, 1]),
                                            SEMANTIC_OTHER))
        self.assertIsNone(six["selected_template"])
        self.assertIsNone(other["selected_template"])
        self.assertEqual(compose._fallback_note(six["rationale"]),
                         "示意图：分项过多，建议看表格。")
        self.assertIn("暂时没有合适的图形",
                      compose._fallback_note(other["rationale"]))
        # 另两条是防御性分支（当前规则下选型器不会给出这两种理由）。
        self.assertIn("完全相同", compose._fallback_note("无适用图形：全相等"))
        self.assertIn("负值", compose._fallback_note("无适用图形：含负值"))

    def test_reason_is_rendered_into_the_placeholder_card(self):
        out = mkdtemp(prefix="multicol_fb_")
        with mock.patch("loop.compose.select", return_value=_no_applicable()):
            result = build_flow(COPY_HIT, layout=_layout())
        page = flow_layout(_layout(), result.flow)
        _write_spec(page, out)
        rendered = render_layout(page, out)
        doc = rendered["flat_spec"].to_dict()
        notes = [e["text"] for e in doc["elements"]
                 if e.get("role") == "scale_note"]
        self.assertTrue(any("表格" in t for t in notes), notes)

    def test_compose_page_renders_the_placeholder(self):
        out = mkdtemp(prefix="multicol_auto_")
        with mock.patch("loop.compose.select", return_value=_no_applicable()):
            result = compose.compose_page(COPY_HIT, out, width_in=W,
                                          height_in=H, column_count=2)
        self.assertEqual(result.page.cards[0].card.kind, "placeholder")
        self.assertTrue(os.path.isfile(result.outputs["preview"]))
        self.assertTrue(os.path.isfile(result.outputs["pptx"]))


class TestBackwardCompatible(unittest.TestCase):
    def test_single_column_flow_is_unchanged(self):
        layout = LayoutSpec(width_in=W, height_in=H, margin_in=MARGIN,
                            gutter_in=GUTTER)
        flow = [TextBlock("标题", "title", "center"),
                TextBlock("正文一段。", "body"),
                CardSpec("thermo", "thermometer", chart_key="heat_ratio_top5",
                         title="增速", width_in=9.2, height_in=4.6)]
        page = flow_layout(layout, flow)
        title = page.blocks[0]
        self.assertAlmostEqual(title.x_in, MARGIN, places=6)
        self.assertAlmostEqual(title.w_in, 9.2, places=6)
        self.assertAlmostEqual(page.blocks[1].y_in,
                               MARGIN + title.h_in + GUTTER, places=6)
        self.assertAlmostEqual(page.card("thermo").w_in, 9.2, places=6)
        self.assertEqual(page.column_count, 1)

    def test_default_layout_is_one_column(self):
        layout = LayoutSpec()
        self.assertEqual(layout.column_count, 1)
        self.assertAlmostEqual(layout.column_gutter_in, 0.2, places=6)

    def test_single_column_layout_uses_the_full_width(self):
        """单栏版面里 span=1 就是整幅可用宽度；span 超栏数是明确的错误。"""
        layout = LayoutSpec(width_in=W, height_in=H, margin_in=MARGIN,
                            gutter_in=GUTTER)
        page = flow_layout(layout, [TextBlock("标题", "title", "center"),
                                    TextBlock(COPY_LONG, "body")])
        for o in page.blocks:
            self.assertAlmostEqual(o.x_in, MARGIN, places=6)
            self.assertAlmostEqual(o.w_in, layout.usable_width_in, places=6)
        with self.assertRaises(LayoutOverflowError):
            flow_layout(layout, [TextBlock("标题", "title", "center",
                                           column_span=2)])

    def test_max_card_height_ratio_is_a_layout_policy(self):
        loose = build_flow(COPY_HIT, layout=_layout(max_card_height_ratio=1.0))
        tight = build_flow(COPY_HIT, layout=_layout(max_card_height_ratio=0.25))
        hi = max(c.height_in for c in loose.flow if isinstance(c, CardSpec))
        lo = max(c.height_in for c in tight.flow if isinstance(c, CardSpec))
        self.assertLess(lo, hi)
        self.assertFalse(hasattr(compose, "MAX_CARD_HEIGHT_RATIO"),
                         "高度政策应只存在于 LayoutSpec")


class TestRenderedColumns(unittest.TestCase):
    """像素级确认：正文真的分了两栏画出来，栏间没有字压线。"""

    @classmethod
    def setUpClass(cls):
        cls.out = mkdtemp(prefix="multicol_px_")
        layout = _layout()
        flow = [
            TextBlock("取暖电器换季热销", "title", "center", column_span=2),
            TextBlock("左栏导语占一栏。", "body", column_span=1),
            TextBlock("右栏结尾占一栏。", "body", column_span=1),
            TextBlock(COPY_LONG, "body", column_span=2, columns=2),
            CardSpec("semi", "semicircle", chart_key="heat_age",
                     title="年龄占比", column_span=1),
            CardSpec("ph", "placeholder", title="占位",
                     note="示意图：分项过多，建议看表格。", column_span=1),
        ]
        cls.layout = layout
        cls.page = flow_layout(layout, flow)
        _write_spec(cls.page, cls.out)
        cls.rendered = render_layout(cls.page, cls.out)
        cls.img = Image.open(cls.rendered["preview"]).convert("L")
        cls.px = cls.img.load()

    def _dark(self, x0, y0, x1, y1, thr=160):
        w, h = self.img.size
        n = 0
        for y in range(max(0, int(y0 * PX)), min(int(y1 * PX), h)):
            for x in range(max(0, int(x0 * PX)), min(int(x1 * PX), w)):
                if self.px[x, y] < thr:
                    n += 1
        return n

    def test_right_column_actually_gets_half_the_text(self):
        lead = self.page.block("左栏导语占一栏。")
        tail = self.page.block("右栏结尾占一栏。")
        self.assertGreater(self._dark(lead.x_in, lead.y_in,
                                      lead.x_in + lead.w_in, lead.y_in + lead.h_in), 50)
        self.assertGreater(self._dark(tail.x_in, tail.y_in,
                                      tail.x_in + tail.w_in, tail.y_in + tail.h_in), 50)

    def test_two_inner_columns_are_both_painted_with_a_clean_gutter(self):
        block = [b for b in self.page.blocks if b.block.columns == 2][0]
        inner = text_flow.inner_column_width_in(block.w_in, 2, COL_GUTTER)
        y0, y1 = block.y_in, block.y_in + block.h_in
        left = self._dark(block.x_in, y0, block.x_in + inner, y1)
        right = self._dark(block.x_in + inner + COL_GUTTER, y0,
                           block.x_in + block.w_in, y1)
        self.assertGreater(left, 50)
        self.assertGreater(right, 50)
        # 栏间 0.2 in 里不得有任何一个字压线。
        self.assertEqual(self._dark(block.x_in + inner, y0,
                                    block.x_in + inner + COL_GUTTER, y1), 0)

    def test_card_frames_sit_exactly_on_the_column_edges(self):
        """卡框的竖边正好落在左右边距与两条栏边界上。"""
        semi = self.page.card("semi")
        y0 = int(semi.y_in * PX) + 4
        y1 = int((semi.y_in + semi.h_in) * PX) - 4
        height = y1 - y0

        def vertical(x):
            return sum(1 for y in range(y0, y1) if self.px[x, y] < 220)

        def line_near(x, tol=2):
            return max(vertical(x + d) for d in range(-tol, tol + 1))

        self.assertGreater(line_near(int(round(MARGIN * PX))), height * 0.9)
        self.assertGreater(line_near(int(round((W - MARGIN) * PX))), height * 0.9)
        right_edge = int(round((MARGIN + self.layout.column_width_in) * PX))
        left_edge = int(round((MARGIN + self.layout.column_width_in
                               + COL_GUTTER) * PX))
        self.assertGreater(line_near(right_edge), height * 0.9, "左卡右缘")
        self.assertGreater(line_near(left_edge), height * 0.9, "右卡左缘")
        # 栏间距 0.2 in 必须真的是空白。
        self.assertEqual(vertical((right_edge + left_edge) // 2), 0)

    def test_rendered_pagespec_records_the_column_metadata(self):
        with open(page_spec_path(self.out), encoding="utf-8") as fh:
            layout_doc = json.load(fh)
        self.assertEqual(layout_doc["column_count"], 2)
        self.assertAlmostEqual(layout_doc["column_gutter_in"], COL_GUTTER)
        doc = self.rendered["flat_spec"].to_dict()
        self.assertEqual(doc["layout"]["column_count"], 2)
        blocks = [e for e in doc["elements"]
                  if (e.get("geometry") or {}).get("block")]
        multi = [b for b in blocks if len(b["geometry"]["line_groups"]) == 2]
        self.assertTrue(multi, "分两栏的文本块没有把 line_groups 写进规格")
        self.assertTrue(os.path.isfile(self.rendered["pptx"]))


if __name__ == "__main__":
    unittest.main()
