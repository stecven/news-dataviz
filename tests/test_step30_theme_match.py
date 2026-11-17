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
from loop.layout import (ImageBlock, LayoutOverflowError, LayoutSpec,
                         flow_layout, page_spec_path)
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
        # 两张插图都留在页面上（用户 m05920）：升到整行的温度计自己占一行，它旁边
        # 那张插图顺延到下一行、与**退回单栏**的正文并排，不再白占一整行 —— 整页
        # 因此装得下，用不着丢图。
        self.assertEqual([img["name"] for img in page["images"]],
                         ["illustration_17", "illustration_26"])
        with open(os.path.join(out, "flow.json"), encoding="utf-8") as fh:
            flow = json.load(fh)
        self.assertIn("themes", flow)
        self.assertTrue(any(it["kind"] == "image" for it in flow["flow"]))
        self.assertEqual([n["images"] for n in flow["notes"]
                          if n["kind"] == "illustration_tucked"],
                         [["illustration_17"]])
        self.assertEqual([n for n in flow["notes"]
                          if n["kind"] == "illustration_dropped"], [])
        # 选图阶段选中的两张插图都真的排上了页 —— 主题命中的暖气片没被布局丢掉。
        matched = {m["dataset_key"]: m for m in flow["matches"]}
        self.assertEqual(matched["heat_ratio_top5"]["illustration"],
                         "illustration_17")
        self.assertEqual(matched["heat_ratio_top5"]["illustration_basis"], "theme")
        self.assertEqual(matched["heat_age"]["illustration"], "illustration_26")

    def test_to_dict_carries_themes(self):
        data = self.result.to_dict()
        self.assertIn("themes", data)
        matched = {m["dataset_key"]: m for m in data["matches"]}
        self.assertEqual(matched["heat_age"]["illustration_basis"], "chart_semantic")


class TestLayoutStructureUnchanged(unittest.TestCase):
    """排版结构没动：只换了插图来源。

    整版要从**生产入口** ``compose_page`` 取。用户 m05920 之后，2 栏 15 in 的版面
    在「温度计升到整行」时，原本并排在它右边的那张插图只能顺延到下一行、白占一整
    行（整页 15.49 in > 15.00 in）；编排层先试**收拢**（把这张插图收进下一行、让
    紧随其后的那段正文退回单栏填空栏），收不拢才丢图。

    手动 ``flow_layout(build_flow(...).flow)`` 是**不带收拢与丢图策略**的低层路径，
    照旧如实抛 ``LayoutOverflowError``（下面有一条用例守着这个分工）。
    """

    def setUp(self):
        self.layout = LayoutSpec(column_count=2)
        self.out = mkdtemp()
        self.page = compose_page(COPY, self.out, column_count=2).page

    def test_low_level_path_still_reports_the_overflow(self):
        # 丢图是**编排层**的政策：手动排版没有这份政策，装不下就得报错 ——
        # 绝不为了让页面装下而压扁卡片或缩小字号（用户 m05779）。
        with self.assertRaises(LayoutOverflowError):
            flow_layout(self.layout, build_flow(COPY, layout=self.layout).flow)

    def test_title_still_spans_the_full_width(self):
        title = [b for b in self.page.blocks if b.block.style == "title"][0]
        self.assertEqual(title.x_in, self.layout.margin_in)
        self.assertEqual(title.w_in, self.layout.usable_width_in)

    def test_two_column_paragraphs_keep_the_full_page_width(self):
        # 块内分栏本身没动：声明了 2 栏的段落照样占满整行 9.2 in。这段演示文字只
        # 有一行，均衡分栏后只落在第 1 栏（``balance_lines`` 丢掉空栏，所以
        # ``line_groups`` 是 1）—— 这里验的是**声明与宽度**；真的分成两组的用例
        # 在 ``tests/test_step27_multicol.py``。
        split = [b for b in self.page.blocks if b.block.columns > 1]
        self.assertTrue(split)
        for block in split:
            self.assertEqual(block.block.columns, 2)
            self.assertEqual(block.w_in, self.layout.usable_width_in)

    def test_tucked_illustration_narrows_the_paragraph_beside_it(self):
        # 收拢的代价是**明确**的：那一段正文从整行 2 栏退回单栏 4.5 in，去填插图
        # 旁边空出来的那一栏（用户 m05920）。不这么做，插图就白占一整行、整页装
        # 不下，只能丢掉主题命中的那张图。
        image = self.page.image("illustration_17")
        beside = [b for b in self.page.blocks
                  if abs(b.y_in - image.y_in) < 1e-6]
        self.assertEqual(len(beside), 1)          # 与插图同行
        self.assertEqual(beside[0].block.columns, 1)
        self.assertEqual(beside[0].w_in, self.layout.column_width_in)
        self.assertGreater(beside[0].h_in, 0)

    def test_card_and_illustration_share_a_row(self):
        # 行里存的是**名字**（``rows[i]["cards"]``/``["images"]``），要回查坐标。
        # 升到整行的温度计独占一行；另一张插图照旧与它配对的卡片并排：卡左图右。
        shared = [row for row in self.page.rows
                  if row.get("cards") and row.get("images")]
        self.assertTrue(shared)
        for row in shared:
            self.assertEqual(len(row["cards"]), 1)
            card = self.page.card(row["cards"][0])
            image = self.page.image(row["images"][0])
            self.assertAlmostEqual(card.y_in, image.y_in, places=6)
            self.assertLess(card.x_in, image.x_in)

    def test_promoted_card_sits_alone_and_centred(self):
        # 温度计升到整行后确实独占一行（这一行没有插图并排，否则它旁边那张插图就
        # 不会被挤到下一行，也就没有 m05920 这个问题了）；而且记录的是**真实外
        # 框**、居中留白（用户 m05779 口径 (a)），不是分配的格子宽。
        alone = [row for row in self.page.rows if not row.get("images")
                 and row.get("cards")]
        self.assertEqual([row["cards"] for row in alone], [["heat_ratio_top5"]])
        card = self.page.card("heat_ratio_top5")
        self.assertLess(card.w_in, self.layout.usable_width_in)
        expected_x = self.layout.margin_in + (self.layout.usable_width_in
                                              - card.w_in) / 2.0
        self.assertAlmostEqual(card.x_in, expected_x, places=6)

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


class TestSpilledIllustrationTuck(unittest.TestCase):
    """升栏卡片旁边的插图**收拢**进下一行的空栏，不再丢图（用户 m05920）。

    用户 m05779 之后，主题稿里温度计升到整行 → 原本并排在它右边的那张插图顺延到
    下一行、白占一整行 → 整页 15.49 in > 15.00 in，编排层只好丢掉**主题命中**的
    暖气片，留下降级候选 people（basis=chart_semantic）。m05920 改成先收拢：让这张
    插图与**退回单栏**的下一段正文并排，两张图都留下。收不拢才回到丢图那条路。
    """

    def setUp(self):
        self.layout = LayoutSpec(column_count=2)
        self.result = compose_page(COPY, mkdtemp(), column_count=2)

    def test_theme_illustration_survives_the_overflow(self):
        # 上游按主题选中的暖气片必须留在页面上 —— 这是这次修复的全部意义。
        self.assertEqual([img.block.name for img in self.result.page.images],
                         ["illustration_17", "illustration_26"])

    def test_tuck_is_recorded_as_a_tuck_not_a_drop(self):
        self.assertEqual([n["kind"] for n in self.result.notes],
                         ["illustration_tucked"])
        self.assertEqual(self.result.notes[0]["images"], ["illustration_17"])
        self.assertTrue(self.result.notes[0]["reason"])

    def test_page_size_contract_is_untouched(self):
        # 页面尺寸契约一个字没改：还是 10 × 15 in，靠重新分配版面装下的。
        self.assertEqual(self.result.page.width_in, 10.0)
        self.assertEqual(self.result.page.height_in, 15.0)
        for item in list(self.result.page.images) + list(self.result.page.cards):
            self.assertLessEqual(item.y_in + item.h_in,
                                 self.layout.height_in - self.layout.margin_in + 1e-6)

    def test_geometry_and_font_floor_are_untouched(self):
        # 收拢只挪位置，不碰图形：管身宽高比照旧是设计比（±5%，与验收探针同口径），
        # 卡片里每个文本元素的渲染字号仍在 6 pt 以上（用户 m04205 / m05779）。
        from loop.palette import MIN_FONT_PT
        card = self.result.page.card("heat_ratio_top5")
        tube = next(el for el in card.spec.elements if el.role == "track")
        self.assertAlmostEqual(tube.w_in / tube.h_in, 0.28 / 3.00,
                               delta=0.05 * (0.28 / 3.00))
        fonts = [el.font_pt for el in card.spec.elements
                 if el.type == "text" and el.text and el.font_pt is not None]
        self.assertTrue(fonts)
        self.assertGreaterEqual(min(fonts), MIN_FONT_PT - 1e-9)

    def test_drop_path_still_records_its_reason(self):
        # 收拢这条路被堵死时（这里把探针按「这一页没有可收拢的地方」伪造），编排层
        # 回到 m05779 的裁定 ②：丢插图，并且必须留下**可追踪的原因**。
        with mock.patch("loop.compose._tuck_spilled_illustrations",
                        return_value=([], [])):
            result = compose_page(COPY, mkdtemp(), column_count=2)
        self.assertEqual([img.block.name for img in result.page.images],
                         ["illustration_26"])
        dropped = [n for n in result.notes if n["kind"] == "illustration_dropped"]
        self.assertEqual([n["images"] for n in dropped], [["illustration_17"]])
        self.assertTrue(dropped[0]["reason"])


if __name__ == "__main__":
    unittest.main()
