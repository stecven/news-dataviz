"""S6 桥接 0.1（用户 m06731）：文本主题 → 素材库 semantic_tags 配图。

验收闸口逐条对应：

* 文本提到「取暖电器」时配暖气片而非 people/percent → ``TestComposeThemeFlow``
* 文本不含主题词时降级为图表语义匹配               → ``TestPickIllustration``
* 主题图被占用时降级（用户 m06739 裁定）           → ``TestPickIllustration``
* 排版结构不变，仅插图来源变化                     → ``TestLayoutStructureUnchanged``
* 全量 639+ 全绿                                   → 本文件

词表不另编：``load_theme_terms`` 反向从 ``tag_vocabulary`` 里**真挂了可检索素材**的
semantic 标签（含别名）导出，所以「查得到的主题」与「有图可配的主题」是同一集合。
"""
import json
import os
import unittest
from unittest import mock

from loop.asset_lookup import find_assets_by_theme, find_assets_by_semantic
from loop.compose import (THEME_MIN_CHARS, _pick_illustration, build_flow,
                          compose_page, extract_theme, load_theme_terms)
from loop.data_source import DB_PATH
from loop.layout import ImageBlock, LayoutSpec, flow_layout, page_spec_path
from tests.scratch import mkdtemp

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 演示稿：两段正文分别提到「取暖电器」（品类）与「年龄段 + 取暖电器」。
COPY = """取暖电器换季热销

随着气温下降，取暖电器进入销售旺季。

分品类看，取暖电器各细分品类的成交额环比增速差异明显。

分年龄段看，各年龄段消费者对取暖电器的偏好不同，成交额占比也各不相同。
"""

#: 只提图表语义、一个主题词都没有的稿子：用来验降级。
#: 三段起步 —— ``split_title_lead`` 会吃掉标题与导语，只有正文段才配数据。
NO_THEME = """加热电器品类增速一览

随着季节变化，加热电器市场出现波动。

分品类看，加热电器各细分品类的成交额环比增速情况。
"""

TERMS = load_theme_terms(DB_PATH)


class TestThemeVocabulary(unittest.TestCase):
    """主题词表从库里反向导出，不手编。"""

    def test_terms_are_loaded_from_the_database(self):
        self.assertGreaterEqual(len(TERMS), 19)
        for word, tag in TERMS.items():
            self.assertIsInstance(word, str)
            self.assertIsInstance(tag, str)
            self.assertTrue(tag)

    def test_no_single_character_words(self):
        # 「冷」「雪」「火」这类单字词面命中太吵，一律不收。
        self.assertEqual([w for w in TERMS if len(w) < THEME_MIN_CHARS], [])

    def test_canonical_labels_are_present(self):
        tags = set(TERMS.values())
        for tag in ("取暖电器", "人群", "温度", "百分比", "暖气片"):
            self.assertIn(tag, tags)

    def test_aliases_are_included(self):
        self.assertEqual(TERMS.get("年龄段"), "人群")
        self.assertEqual(TERMS.get("散热器"), "暖气片")
        self.assertEqual(TERMS.get("电暖器"), "取暖电器")

    def test_canonical_label_wins_over_alias(self):
        # ``setdefault`` 先登记正式标签，别名不会把它改写掉。
        self.assertEqual(TERMS.get("取暖电器"), "取暖电器")
        self.assertEqual(TERMS.get("人群"), "人群")

    def test_every_term_can_find_at_least_one_asset(self):
        # 词表只收「有图可配」的标签，所以每条词面都必须查得到素材。
        missing = [w for w in TERMS if not find_assets_by_theme(w, DB_PATH)]
        self.assertEqual(missing, [])

    def test_unreadable_database_yields_empty_dict(self):
        with mock.patch("loop.compose.semantic_theme_terms",
                        side_effect=RuntimeError("boom")):
            self.assertEqual(load_theme_terms(DB_PATH), {})


class TestExtractTheme(unittest.TestCase):
    """段落 → 主题标签。"""

    def test_title_yields_heating_appliance(self):
        self.assertEqual(extract_theme("取暖电器换季热销", TERMS), "取暖电器")

    def test_longest_term_wins(self):
        # 「取暖电器」(4 字) 压过别名「年龄段」(3 字) —— 裁定里那段演示的路径。
        text = "分年龄段看，各年龄段消费者对取暖电器的偏好不同。"
        self.assertEqual(extract_theme(text, TERMS), "取暖电器")

    def test_alias_only_yields_its_canonical_label(self):
        self.assertEqual(extract_theme("分年龄段看，消费者的偏好不同。", TERMS), "人群")

    def test_unknown_text_yields_none(self):
        self.assertIsNone(extract_theme("今天天气不错。", TERMS))

    def test_single_character_words_are_ignored(self):
        # 「冷」是「寒冷」的别名，但只有 1 个字，不收。
        self.assertIsNone(extract_theme("今天很冷。", TERMS))

    def test_empty_terms_yields_none(self):
        self.assertIsNone(extract_theme("取暖电器", {}))

    def test_exact_tag_is_matched_without_alias(self):
        self.assertEqual(extract_theme("雪花纷飞的季节", TERMS), "雪花")


class TestPickIllustration(unittest.TestCase):
    """决策树：theme → chart_semantic → None，且被占用的图不重复放。"""

    def test_theme_hit_is_used_first(self):
        block, basis = _pick_illustration("取暖电器", "占比构成", DB_PATH, set())
        self.assertEqual(basis, "theme")
        self.assertEqual(block.tag, "取暖电器")
        self.assertEqual(block.asset_id, 17)          # radiator_soft
        self.assertTrue(block.path.endswith(".png"))

    def test_used_theme_asset_degrades_to_chart_semantic(self):
        # 用户 m06739 裁定：主题图被占用 → 降级到图表语义，不报错、不硬塞第二张。
        used = {17}
        block, basis = _pick_illustration("取暖电器", "占比构成", DB_PATH, used)
        self.assertEqual(basis, "chart_semantic")
        self.assertNotEqual(block.asset_id, 17)
        self.assertEqual(block.semantic, "占比构成")

    def test_unknown_theme_degrades_to_chart_semantic(self):
        block, basis = _pick_illustration("并不存在的主题", "比较大小", DB_PATH, set())
        self.assertEqual(basis, "chart_semantic")
        self.assertEqual(block.asset_id, 17)          # 比较大小 的首选就是暖气片

    def test_both_unknown_yields_none(self):
        block, basis = _pick_illustration("并不存在的主题", "也不存在", DB_PATH, set())
        self.assertIsNone(block)
        self.assertIsNone(basis)

    def test_no_theme_falls_back(self):
        block, basis = _pick_illustration(None, "占比构成", DB_PATH, set())
        self.assertEqual(basis, "chart_semantic")
        self.assertIsNotNone(block)

    def test_second_pick_never_reuses_an_asset_id(self):
        used = set()
        first, _ = _pick_illustration("占比构成", None, DB_PATH, used)
        second, _ = _pick_illustration("占比构成", None, DB_PATH, used)
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertNotEqual(first.asset_id, second.asset_id)

    def test_unreadable_database_yields_none(self):
        with mock.patch("loop.compose.find_assets_by_theme",
                        side_effect=RuntimeError("boom")), \
                mock.patch("loop.compose.find_assets_by_semantic",
                           side_effect=RuntimeError("boom")):
            block, basis = _pick_illustration("取暖电器", "占比构成", DB_PATH, set())
        self.assertIsNone(block)
        self.assertIsNone(basis)

    def test_block_is_an_image_block(self):
        block, _ = _pick_illustration("取暖电器", "占比构成", DB_PATH, set())
        self.assertIsInstance(block, ImageBlock)
        self.assertEqual(block.style, "icon")
        self.assertEqual(block.column_span, 1)


class TestComposeThemeFlow(unittest.TestCase):
    """端到端：文字主题决定配图，两段都提同一主题时第二段降级。"""

    def setUp(self):
        self.layout = LayoutSpec(column_count=2)
        self.result = build_flow(COPY, layout=self.layout)

    def _images(self):
        return [it for it in self.result.flow if isinstance(it, ImageBlock)]

    def test_flow_contains_two_illustrations(self):
        self.assertEqual(len(self._images()), 2)

    def test_first_illustration_is_the_theme_match(self):
        block = self._images()[0]
        self.assertEqual(block.tag, "取暖电器")
        self.assertEqual(block.asset_id, 17)          # radiator_soft，不是 people
        self.assertNotIn(block.asset_id, (26, 27))    # 绝不是 people / percent

    def test_second_illustration_degrades_to_chart_semantic(self):
        first, second = self._images()
        self.assertEqual(second.asset_id, 26)         # people（占比构成 的首选）
        self.assertNotEqual(first.asset_id, second.asset_id)

    def test_matches_record_theme_and_basis(self):
        by_key = {m.dataset_key: m for m in self.result.matches}
        self.assertEqual(by_key["heat_ratio_top5"].theme, "取暖电器")
        self.assertEqual(by_key["heat_ratio_top5"].illustration_basis, "theme")
        self.assertEqual(by_key["heat_age"].theme, "取暖电器")
        self.assertEqual(by_key["heat_age"].illustration_basis, "chart_semantic")

    def test_themes_are_recorded_for_every_paragraph(self):
        title = "取暖电器换季热销"
        self.assertEqual(self.result.themes.get(title), "取暖电器")
        for paragraph in self.result.themes:
            self.assertIn(paragraph, COPY)

    def test_flow_summary_reports_how_each_image_was_matched(self):
        images = [it for it in self.result.flow_summary() if it["kind"] == "image"]
        self.assertEqual([it["matched_by"] for it in images],
                         ["theme", "chart_semantic"])
        texts = [it for it in self.result.flow_summary() if it["kind"] == "text"]
        self.assertEqual(texts[0]["theme"], "取暖电器")

    def test_text_without_theme_falls_back_to_chart_semantic(self):
        result = build_flow(NO_THEME, layout=self.layout)
        images = [it for it in result.flow if isinstance(it, ImageBlock)]
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0].semantic, "比较大小")
        self.assertIsNone(result.matches[0].theme)
        self.assertEqual(result.matches[0].illustration_basis, "chart_semantic")
        self.assertEqual(result.matches[0].dataset_key, "heat_ratio_top5_prov")

    def test_unreadable_theme_table_still_illustrates_by_chart_semantic(self):
        # 词表读不了 → 每段 theme 都是 None，插图全部回落到图表语义，排版照旧。
        with mock.patch("loop.compose.semantic_theme_terms",
                        side_effect=RuntimeError("boom")):
            result = build_flow(COPY, layout=self.layout)
        self.assertTrue(result.matches)               # 卡片照旧
        self.assertEqual({m.theme for m in result.matches}, {None})
        self.assertEqual({m.illustration_basis for m in result.matches},
                         {"chart_semantic"})
        self.assertEqual(len([it for it in result.flow
                              if isinstance(it, ImageBlock)]), 2)

    def test_compose_page_writes_the_page_and_the_flow(self):
        out = mkdtemp()
        result = compose_page(COPY, out, column_count=2)
        self.assertTrue(os.path.exists(os.path.join(out, "preview.png")))
        with open(page_spec_path(out), encoding="utf-8") as fh:
            page = json.load(fh)
        self.assertEqual(len(page["images"]), 2)
        with open(os.path.join(out, "flow.json"), encoding="utf-8") as fh:
            flow = json.load(fh)
        self.assertIn("themes", flow)
        self.assertTrue(any(it["kind"] == "image" for it in flow["flow"]))

    def test_to_dict_carries_themes(self):
        data = self.result.to_dict()
        self.assertIn("themes", data)
        matched = {m["dataset_key"]: m for m in data["matches"]}
        self.assertEqual(matched["heat_age"]["illustration_basis"], "chart_semantic")


class TestLayoutStructureUnchanged(unittest.TestCase):
    """排版结构没动：只换了插图来源。"""

    def setUp(self):
        self.layout = LayoutSpec(column_count=2)
        self.page = flow_layout(self.layout,
                                build_flow(COPY, layout=self.layout).flow)

    def test_title_still_spans_the_full_width(self):
        title = [b for b in self.page.blocks if b.block.style == "title"][0]
        self.assertEqual(title.x_in, self.layout.margin_in)
        self.assertEqual(title.w_in, self.layout.usable_width_in)

    def test_paragraphs_are_still_split_into_two_columns(self):
        split = [b for b in self.page.blocks if len(b.line_groups) > 1]
        self.assertTrue(split)
        for block in split:
            self.assertEqual(len(block.line_groups), 2)
            self.assertEqual(block.w_in, self.layout.usable_width_in)

    def test_card_and_illustration_share_a_row(self):
        # 行里存的是**名字**（``rows[i]["cards"]``/``["images"]``），要回查坐标。
        for row in self.page.rows:
            names = row.get("images") or []
            if not names:
                continue
            self.assertEqual(len(row["cards"]), 1)
            card = self.page.card(row["cards"][0])
            image = self.page.image(names[0])
            self.assertAlmostEqual(card.y_in, image.y_in, places=6)
            self.assertLess(card.x_in, image.x_in)

    def test_nothing_overlaps_and_everything_is_inside_the_margins(self):
        boxes = [(c.x_in, c.y_in, c.w_in, c.h_in) for c in self.page.cards]
        boxes += [(b.x_in, b.y_in, b.w_in, b.h_in) for b in self.page.blocks]
        boxes += [(i.x_in, i.y_in, i.w_in, i.h_in) for i in self.page.images]
        for x, y, w, h in boxes:
            self.assertGreaterEqual(x, self.layout.margin_in - 1e-9)
            self.assertGreaterEqual(y, self.layout.margin_in - 1e-9)
            self.assertLessEqual(x + w, self.layout.width_in - self.layout.margin_in + 1e-9)
            self.assertLessEqual(y + h, self.layout.height_in - self.layout.margin_in + 1e-9)
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                ax, ay, aw, ah = boxes[i]
                bx, by, bw, bh = boxes[j]
                overlap_w = min(ax + aw, bx + bw) - max(ax, bx)
                overlap_h = min(ay + ah, by + bh) - max(ay, by)
                self.assertFalse(overlap_w > 1e-6 and overlap_h > 1e-6)

    def test_illustration_keeps_its_aspect_ratio(self):
        from loop.layout import fit_rect_in, image_size_in
        block = self.page.images[0]
        src_w, src_h = image_size_in(os.path.join(ROOT, block.block.path))
        aspect = src_w / src_h
        dx, dy, dw, dh = block.rect
        self.assertAlmostEqual(dw / dh, aspect, places=5)
        _, _, fitted_w, fitted_h = fit_rect_in(block.w_in, block.h_in, aspect)
        self.assertAlmostEqual(dw, fitted_w, places=5)
        self.assertAlmostEqual(dh, fitted_h, places=5)


if __name__ == "__main__":
    unittest.main()
