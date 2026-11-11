"""排版引擎 0.2 的验收测试：同行等高拉伸 + 溢出保底（用户 m05995）。

用两个不同高度的卡片（5.2 / 3.6）验证：行内较矮的那张被拉到行高，
两卡 y_in、h_in 一致，底部严格对齐，且拉伸后卡片内部不溢出。
"""
import unittest

from loop import palette
from loop.fit import CHROME_ROLES, text_problems
from loop.frame import validate_frame
from loop.layout import (CardSpec, LayoutFitError, LayoutOverflowError,
                         LayoutSpec, build_card, flow_layout)

ROWS = [
    ("thermo", "thermometer", "heat_ratio_top5", 9.2, 4.6),
    ("semi", "semicircle", "heat_age", 4.45, 5.2),
    ("ph", "placeholder", None, 4.45, 3.6),
]


def _cards(rows=ROWS):
    return [CardSpec(name, kind, chart_key=key, title=name,
                     width_in=w, height_in=h)
            for name, kind, key, w, h in rows]


class TestEqualHeight(unittest.TestCase):
    def test_short_card_is_stretched_to_the_row_height(self):
        page = flow_layout(LayoutSpec(equal_height=True), _cards())
        semi, ph = page.card("semi"), page.card("ph")
        self.assertEqual(semi.h_in, 5.2)
        self.assertEqual(ph.h_in, 5.2)

    def test_same_row_shares_y_and_height_and_bottom(self):
        page = flow_layout(LayoutSpec(equal_height=True), _cards())
        semi, ph = page.card("semi"), page.card("ph")
        self.assertAlmostEqual(semi.y_in, ph.y_in, places=6)
        self.assertAlmostEqual(semi.h_in, ph.h_in, places=6)
        self.assertAlmostEqual(semi.y_in + semi.h_in, ph.y_in + ph.h_in,
                               places=6)

    def test_unequal_mode_keeps_the_original_heights(self):
        page = flow_layout(LayoutSpec(equal_height=False), _cards())
        semi, ph = page.card("semi"), page.card("ph")
        self.assertEqual(semi.h_in, 5.2)
        self.assertEqual(ph.h_in, 3.6)
        self.assertNotEqual(semi.h_in, ph.h_in)

    def test_rows_still_separated_by_the_gutter(self):
        page = flow_layout(LayoutSpec(equal_height=True), _cards())
        top, semi = page.card("thermo"), page.card("semi")
        self.assertAlmostEqual(semi.y_in - (top.y_in + top.h_in), 0.3,
                               places=6)
        self.assertEqual(page.rows[1]["y_in"],
                         round(page.rows[0]["y_in"] + page.rows[0]["h_in"] + 0.3,
                               6))

    def test_stretching_does_not_change_the_row_membership(self):
        page = flow_layout(LayoutSpec(equal_height=True), _cards())
        self.assertEqual([c.name for c in page.cards], ["thermo", "semi", "ph"])
        self.assertEqual([c.row for c in page.cards], [0, 1, 1])

    def test_only_the_shorter_card_is_rebuilt(self):
        page = flow_layout(LayoutSpec(equal_height=True), _cards())
        # 行内最高的那张保持自己的尺寸；较矮的拉高后位置在设计上更靠下，
        # 但仍从行顶开始（顶端对齐），所以内容是在更高的盒子里放大。
        self.assertEqual(page.card("semi").w_in, 4.45)
        self.assertEqual(page.card("ph").w_in, 4.45)


class TestStretchedCardIsStillValid(unittest.TestCase):
    def test_stretched_card_passes_its_own_frame_check(self):
        page = flow_layout(LayoutSpec(equal_height=True), _cards())
        validate_frame(page.card("ph").spec)

    def test_stretched_card_has_no_text_overflow(self):
        page = flow_layout(LayoutSpec(equal_height=True), _cards())
        spec = page.card("ph").spec
        problems = text_problems(spec, palette.spec_scale(spec),
                                 skip=CHROME_ROLES)
        self.assertEqual(problems, [])

    def test_stretched_card_keeps_all_elements_inside_its_box(self):
        page = flow_layout(LayoutSpec(equal_height=True), _cards())
        c = page.card("ph")
        for e in c.spec.elements:
            self.assertGreaterEqual(e.x_in, -1e-9)
            self.assertGreaterEqual(e.y_in, -1e-9)
            self.assertLessEqual(e.x_in + e.w_in, c.spec.width_in + 1e-9)
            self.assertLessEqual(e.y_in + e.h_in, c.spec.height_in + 1e-9)

    def test_every_card_can_still_be_rendered(self):
        from loop.preview import render_preview
        from tests.scratch import mkdtemp
        page = flow_layout(LayoutSpec(equal_height=True), _cards())
        out = mkdtemp()
        import os
        for c in page.cards:
            render_preview(c.spec, os.path.join(out, f"{c.name}.png"))


class TestFitSafetyNet(unittest.TestCase):
    def test_narrow_page_raises_layout_fit_error(self):
        cards = [CardSpec("thermo", "thermometer", chart_key="heat_ratio_top5",
                          title="窄版温度计")]
        with self.assertRaises(LayoutFitError) as ctx:
            flow_layout(LayoutSpec(width_in=4.0, height_in=15.0), cards)
        msg = str(ctx.exception)
        self.assertIn("thermo", msg)
        self.assertIn("已无法阅读", msg)

    def test_fit_error_is_not_an_overflow_error(self):
        self.assertFalse(issubclass(LayoutFitError, LayoutOverflowError))

    def test_fit_error_carries_min_size_detail(self):
        cards = [CardSpec("thermo", "thermometer", chart_key="heat_ratio_top5",
                          title="窄版温度计")]
        try:
            flow_layout(LayoutSpec(width_in=4.0, height_in=15.0), cards)
            self.fail("expected LayoutFitError")
        except LayoutFitError as exc:
            self.assertEqual(exc.card, "thermo")
            self.assertIn("最小可行尺寸", exc.detail)

    def test_wide_enough_page_shrinks_without_error(self):
        """比版面宽的卡片缩进版面，不报错。

        缩是**等比**的，但先咬住哪条边取决于两条政策里更紧的一条：可用宽度
        （9.2 in）或高度上限（``max_card_height_ratio`` 0.35 → 4.97 in）。
        用户 m06230 把高度上限挪进 LayoutSpec 后它在这里也会生效，所以宽度
        不再恰好等于 9.2 —— 断言改成「哪条都没越界，且宽高仍成自然比例」。
        """
        cards = [CardSpec("thermo", "thermometer", chart_key="heat_ratio_top5",
                          title="温度计")]
        layout = LayoutSpec(width_in=10.0, height_in=15.0)
        natural = build_card(cards[0], layout)
        page = flow_layout(layout, cards)
        card = page.card("thermo")
        self.assertLessEqual(card.w_in, layout.usable_width_in + 1e-9)
        self.assertLessEqual(card.h_in, layout.max_card_height_in + 1e-9)
        ratio = card.w_in / natural.width_in
        self.assertAlmostEqual(card.h_in, natural.height_in * ratio, places=5)
        self.assertLess(card.w_in, layout.usable_width_in)

    def test_too_short_page_still_raises_overflow(self):
        rows = [("a", "semicircle", "heat_age", 9.2, 6.0),
                ("b", "semicircle", "heat_age", 9.2, 6.0)]
        with self.assertRaises(LayoutOverflowError):
            flow_layout(LayoutSpec(height_in=7.0), _cards(rows))


if __name__ == "__main__":
    unittest.main()
