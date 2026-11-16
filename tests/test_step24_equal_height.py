"""排版引擎 0.2 的验收测试：同行顶端对齐 + 溢出保底（用户 m05995 / m0xxxx）。

契约升级（分支 fix/staggered-layout）：同行卡片**不再等高拉伸**。用两个不同
高度的卡片（semi 5.2 / ph 3.6 的格子）验证新语义：

* 同行各项 ``y_in`` 相同（顶端对齐），但各自保持自己等比适配后的高度；
* 行高推进仍等于「行内最高的格子 + gutter」，所以下一行的 ``y_in`` 没变；
* 矮的项下方是留白，底部对齐不再是契约；
* ``LayoutSpec.equal_height`` 字段保留作兼容读，但置 True 不再有任何效果
  （``TestEqualHeightIsDeprecated``）。
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


def _graphic_bbox(spec):
    """图形内容外框 (w, h)：去掉文字与固定 chrome，只留几何元素。

    「等比」要量在几何上：外框含固定 1.75 in 的 chrome，缩放后宽高比必然变。
    """
    xs, ys = [], []
    for e in spec.elements:
        if e.type == "text" or e.role in CHROME_ROLES:
            continue
        xs += [e.x_in, e.x_in + e.w_in]
        ys += [e.y_in, e.y_in + e.h_in]
    return max(xs) - min(xs), max(ys) - min(ys)


class TestTopAlignedRows(unittest.TestCase):
    def test_row_items_share_y_but_keep_their_own_heights(self):
        """顶端对齐的共同点是 y，不是高：同行两项高度必须各走各的。"""
        page = flow_layout(LayoutSpec(), _cards())
        semi, ph = page.card("semi"), page.card("ph")
        self.assertAlmostEqual(semi.y_in, ph.y_in, places=6)
        self.assertNotAlmostEqual(semi.h_in, ph.h_in, places=6)
        # semi 的格子是 4.45×5.2，等比适配后画到 4.4475×4.585
        self.assertAlmostEqual(semi.h_in, 4.585, places=6)
        # ph 的格子 4.45×3.6 正好画满，保持自然高度
        self.assertAlmostEqual(ph.h_in, 3.6, places=6)

    def test_short_card_leaves_blank_below_instead_of_being_stretched(self):
        """矮卡下方是留白：底部对齐已不是契约（旧版会把它拉到 5.2）。"""
        page = flow_layout(LayoutSpec(), _cards())
        semi, ph = page.card("semi"), page.card("ph")
        self.assertGreater(semi.y_in + semi.h_in, ph.y_in + ph.h_in)
        self.assertAlmostEqual((semi.y_in + semi.h_in) - (ph.y_in + ph.h_in),
                               4.585 - 3.6, places=6)

    def test_rows_advance_by_the_tallest_box_plus_gutter(self):
        """行高推进 = 行内最高的**格子**高 + gutter（所以下一行 y 与旧版一致）。"""
        page = flow_layout(LayoutSpec(), _cards())
        self.assertEqual(page.rows[0]["y_in"], 0.4)
        self.assertEqual(page.rows[0]["h_in"], 4.6)
        self.assertEqual(page.rows[1]["y_in"], round(0.4 + 4.6 + 0.3, 6))
        self.assertEqual(page.rows[1]["h_in"], 5.2)
        top, semi = page.card("thermo"), page.card("semi")
        # 可见间距 ≥ gutter（外框比格子小一圈，差额变成留白），绝不会重叠
        self.assertGreaterEqual(semi.y_in - (top.y_in + top.h_in), 0.3 - 1e-9)

    def test_row_membership_is_unchanged(self):
        page = flow_layout(LayoutSpec(), _cards())
        self.assertEqual([c.name for c in page.cards], ["thermo", "semi", "ph"])
        self.assertEqual([c.row for c in page.cards], [0, 1, 1])

    def test_cards_keep_their_own_width_inside_their_slots(self):
        """横向 likewise：格子宽 4.45，真实外框 ≤ 格子，不贴满也不越界。"""
        page = flow_layout(LayoutSpec(), _cards())
        semi, ph = page.card("semi"), page.card("ph")
        self.assertAlmostEqual(ph.w_in, 4.45, places=6)
        self.assertAlmostEqual(semi.w_in, 4.4475, places=6)
        self.assertLessEqual(semi.w_in, 4.45 + 1e-9)
        self.assertGreater(semi.x_in, 0.4)          # 居中留白：不再贴左栏边
        self.assertLess(ph.x_in, 5.15 + 1e-9)


class TestEqualHeightIsDeprecated(unittest.TestCase):
    """兼容性契约：``equal_height`` 字段还在，但已经不再改变版面。"""

    def test_flag_no_longer_changes_the_layout(self):
        off = flow_layout(LayoutSpec(equal_height=False), _cards())
        on = flow_layout(LayoutSpec(equal_height=True), _cards())
        self.assertEqual([(c.name, c.x_in, c.y_in, c.w_in, c.h_in)
                          for c in off.cards],
                         [(c.name, c.x_in, c.y_in, c.w_in, c.h_in)
                          for c in on.cards])
        # 也证明「不再拉平」：同行两项高度仍然不同
        self.assertNotEqual(off.card("semi").h_in, off.card("ph").h_in)
        self.assertEqual(len(off.rows), 2)

    def test_field_is_still_readable_for_backward_compatibility(self):
        self.assertTrue(LayoutSpec(equal_height=True).equal_height)
        self.assertFalse(LayoutSpec().equal_height)


class TestFittedCardIsStillValid(unittest.TestCase):
    def test_fitted_card_passes_its_own_frame_check(self):
        page = flow_layout(LayoutSpec(), _cards())
        validate_frame(page.card("ph").spec)

    def test_fitted_card_has_no_text_overflow(self):
        page = flow_layout(LayoutSpec(), _cards())
        spec = page.card("ph").spec
        problems = text_problems(spec, palette.spec_scale(spec),
                                 skip=CHROME_ROLES)
        self.assertEqual(problems, [])

    def test_fitted_card_keeps_all_elements_inside_its_box(self):
        page = flow_layout(LayoutSpec(), _cards())
        c = page.card("ph")
        for e in c.spec.elements:
            self.assertGreaterEqual(e.x_in, -1e-9)
            self.assertGreaterEqual(e.y_in, -1e-9)
            self.assertLessEqual(e.x_in + e.w_in, c.spec.width_in + 1e-9)
            self.assertLessEqual(e.y_in + e.h_in, c.spec.height_in + 1e-9)

    def test_every_card_can_still_be_rendered(self):
        from loop.preview import render_preview
        from tests.scratch import mkdtemp
        page = flow_layout(LayoutSpec(), _cards())
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
        （9.2 in）或高度上限（``max_card_height_ratio`` 0.35 → 4.97 in）。用户
        m06230 把高度上限挪进 LayoutSpec 后它在这里也会生效，所以宽度不再恰好
        等于 9.2；契约升级后又不再拉满格子，所以旧断言「宽高仍成自然比例」也
        要改口径——旧式子是拿**外框**比的，而外框含固定 1.75 in chrome，本来
        就不再等比。等比要落在图形上：两轴必须缩得一样多。
        """
        cards = [CardSpec("thermo", "thermometer", chart_key="heat_ratio_top5",
                          title="温度计")]
        layout = LayoutSpec(width_in=10.0, height_in=15.0)
        natural = build_card(cards[0], layout)
        page = flow_layout(layout, cards)
        card = page.card("thermo")
        # 两条政策都没越界，而且确实缩了
        self.assertLessEqual(card.w_in, layout.usable_width_in + 1e-9)
        self.assertLessEqual(card.h_in, layout.max_card_height_in + 1e-9)
        self.assertLess(card.w_in, natural.width_in)
        self.assertLess(card.h_in, natural.height_in)
        # 等比：图形外框两轴缩得一样多（只压一维就会对不上）
        nw, nh = _graphic_bbox(natural)
        fw, fh = _graphic_bbox(card.spec)
        self.assertAlmostEqual(fw / nw, fh / nh, places=6)
        self.assertLess(fw / nw, 1.0)
        # 等比 ⇒ 图形宽高比与自然尺度一致
        self.assertAlmostEqual(fw / fh, nw / nh, places=6)

    def test_too_short_page_still_raises_overflow(self):
        rows = [("a", "semicircle", "heat_age", 9.2, 6.0),
                ("b", "semicircle", "heat_age", 9.2, 6.0)]
        with self.assertRaises(LayoutOverflowError):
            flow_layout(LayoutSpec(height_in=7.0), _cards(rows))


if __name__ == "__main__":
    unittest.main()
