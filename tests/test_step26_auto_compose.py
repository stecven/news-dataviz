"""自动化编排 0.1（用户 m06157）：拆段、认标题、配数据、组流、退化。"""
import json
import os
import unittest
from unittest import mock

from loop import compose
from loop.compose import (Dataset, build_flow, compose_page, load_catalog,
                          match_dataset, parse_title, score_dataset,
                          split_paragraphs, split_title_lead)
from loop.layout import CardSpec, LayoutSpec, TextBlock
from tests.scratch import mkdtemp

COPY = """取暖电器换季热销：五类小家电增速领跑

入冬以来取暖电器进入销售旺季，平台数据显示成交额环比明显走高。

从细分品类看，取暖电器的成交额环比增速以欧式快热炉、电油汀等品类居前。

分年龄看，各年龄段消费者的取暖电器成交额占比差异并不悬殊。"""

PLAIN = """换季消费观察

这是一篇没有引用任何数据的短评，只谈季节变化与生活习惯。

降温比往年来得早，人们提前添置了过冬用品。"""


class TestParagraphSplitting(unittest.TestCase):

    def test_blank_lines_and_newlines_both_split(self):
        self.assertEqual(split_paragraphs("甲\n\n乙\n丙"), ["甲", "乙", "丙"])

    def test_single_block_falls_back_to_sentences(self):
        self.assertEqual(split_paragraphs("甲。乙！丙？"),
                         ["甲。", "乙！", "丙？"])

    def test_empty_text_is_rejected(self):
        with self.assertRaises(ValueError):
            split_paragraphs("   \n  ")


class TestTitleAndLead(unittest.TestCase):

    def test_short_first_paragraph_is_the_title(self):
        title, lead, body = split_title_lead(["取暖电器换季热销", "导语", "正文"])
        self.assertEqual(title, "取暖电器换季热销")
        self.assertEqual(lead, "导语")
        self.assertEqual(body, ["正文"])

    def test_long_first_paragraph_lends_its_first_sentence(self):
        first = "取暖电器换季热销。平台数据显示成交额环比走高。"
        title, lead, body = split_title_lead([first, "第二段"])
        self.assertEqual(title, "取暖电器换季热销。")
        self.assertIn("平台数据显示成交额环比走高。", lead)
        self.assertEqual(body, ["第二段"])

    def test_lead_paragraph_count_is_configurable(self):
        _, lead, body = split_title_lead(["标题", "导语一", "导语二", "正文"],
                                         lead_paragraphs=2)
        self.assertEqual(lead, "导语一导语二")
        self.assertEqual(body, ["正文"])

    def test_empty_input_is_rejected(self):
        with self.assertRaises(ValueError):
            split_title_lead([])


class TestCatalog(unittest.TestCase):

    def test_parse_title_reads_four_facets(self):
        parsed = parse_title("湖南取暖电器细分品类成交额环比增速TOP5")
        self.assertEqual(parsed["region"], "湖南")
        self.assertEqual(parsed["category"], "取暖电器")
        self.assertEqual(parsed["dimension"], "category")
        self.assertEqual(parsed["metric"], "环比增速")
        self.assertEqual(parsed["semantic"], compose.SEMANTIC_COMPARE)

    def test_share_titles_map_to_share_semantics(self):
        self.assertEqual(parse_title("各年龄段消费者取暖电器成交额占比")["semantic"],
                         compose.SEMANTIC_SHARE)

    def test_real_catalog_is_non_empty_and_all_have_semantics(self):
        catalog = load_catalog()
        self.assertGreaterEqual(len(catalog), 10)
        for dataset in catalog:
            self.assertIsNotNone(dataset.semantic, dataset.key)

    def test_catalog_membership_is_stable(self):
        keys = {d.key for d in load_catalog()}
        self.assertIn("heat_ratio_top5", keys)
        self.assertIn("heat_age", keys)


class TestMatching(unittest.TestCase):

    def setUp(self):
        self.catalog = load_catalog()

    def _match(self, paragraph, used=()):
        return match_dataset(paragraph, self.catalog, set(used))

    def test_growth_paragraph_binds_to_the_growth_dataset(self):
        dataset, score, hits = self._match(
            "从细分品类看，取暖电器的成交额环比增速居前。")
        self.assertEqual(dataset.key, "heat_ratio_top5")
        self.assertGreater(score, 0)
        self.assertEqual(hits["metric"], "环比增速")

    def test_share_paragraph_binds_to_the_age_dataset(self):
        dataset, _, hits = self._match(
            "分年龄看，各年龄段消费者的取暖电器成交额占比差异不大。")
        self.assertEqual(dataset.key, "heat_age")
        self.assertEqual(hits["dimension"], "年龄段")

    def test_category_alone_is_not_enough(self):
        """只提「取暖电器」不提指标 → 不配（否则八组数据全被勾上）。"""
        dataset, score, _ = self._match("取暖电器进入销售旺季，销量走高。")
        self.assertIsNone(dataset)
        self.assertEqual(score, 0.0)

    def test_region_dataset_needs_its_region(self):
        generic, _, _ = self._match("取暖电器细分品类成交额环比增速居前。")
        self.assertEqual(generic.key, "heat_ratio_top5")
        hunan, _, _ = self._match("湖南取暖电器细分品类成交额环比增速居前。")
        self.assertEqual(hunan.key, "hn_heat_ratio")

    def test_used_dataset_is_not_reused(self):
        """唯一够得上的组用过之后宁可不配，也不回头复用它。"""
        paragraph = "取暖电器细分品类成交额环比增速居前。"
        dataset, _, _ = self._match(paragraph)
        self.assertEqual(dataset.key, "heat_ratio_top5")
        again, score, _ = self._match(paragraph, used={"heat_ratio_top5"})
        self.assertIsNone(again)
        self.assertEqual(score, 0.0)

    def test_dataset_without_any_hint_does_not_match(self):
        self.assertEqual(score_dataset("今天天气不错。", self.catalog[0])[0], 0.0)

    def test_scoring_prefers_the_generic_group_on_a_tie(self):
        """同一段同时够得上通用组与地区组时，没提地名就选通用组。"""
        dataset, _, _ = self._match("取暖电器成交额占比TOP5省份出炉。")
        self.assertIn(dataset.key, ("heat_share_prov", "heat_age", "gz_heat_share"))
        self.assertIsNone(dataset.region)


class TestFlowAssembly(unittest.TestCase):

    def test_flow_is_title_first_then_text_and_cards(self):
        # 第 29 步（图文并茂 1.0）起，配到数据的段落后面会多一项 `ImageBlock`
        # （素材库的装饰插图），所以这里的期望里含 ImageBlock —— 标题仍在最前，
        # 且每张卡片都紧跟自己的插图。
        result = build_flow(COPY)
        self.assertIsInstance(result.flow[0], TextBlock)
        self.assertEqual(result.flow[0].style, "title")
        self.assertEqual([type(x).__name__ for x in result.flow],
                         ["TextBlock", "TextBlock", "TextBlock", "CardSpec",
                          "ImageBlock", "TextBlock", "CardSpec", "ImageBlock"])
        self.assertIsInstance(result.flow[1], TextBlock)
        self.assertEqual(result.flow[1].style, "body")

    def test_matched_cards_use_the_selector_decision(self):
        result = build_flow(COPY)
        cards = [x for x in result.flow if isinstance(x, CardSpec)]
        self.assertEqual([c.chart_key for c in cards],
                         ["heat_ratio_top5", "heat_age"])
        self.assertEqual([c.kind for c in cards], ["thermometer", "semicircle"])
        for match in result.matches:
            self.assertTrue(match.rationale)

    def test_cards_get_a_preset_box_that_fits_the_page(self):
        layout = LayoutSpec(width_in=10.0, height_in=15.0)
        result = build_flow(COPY, layout=layout)
        for card in [x for x in result.flow if isinstance(x, CardSpec)]:
            self.assertIsNotNone(card.width_in)
            self.assertLessEqual(card.width_in, layout.usable_width_in + 1e-9)
            # 高度上限是版面政策（用户 m06230 把它从本模块挪进了 LayoutSpec）。
            self.assertLessEqual(card.height_in,
                                 layout.max_card_height_in + 1e-9)

    def test_no_manual_flow_needed_only_text_and_db(self):
        """闸口：只传 text（+db）就能拿到整版 PageLayoutSpec。"""
        out = mkdtemp(prefix="autolayout_")
        result = compose_page(COPY, out)
        self.assertIsNotNone(result.page)
        self.assertEqual(len(result.page.cards), 2)
        self.assertEqual(len(result.page.blocks), 4)
        self.assertTrue(os.path.isfile(result.outputs["preview"]))
        self.assertTrue(os.path.isfile(os.path.join(out, "flow.json")))
        with open(os.path.join(out, "flow.json"), encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertEqual(doc["flow"][0]["kind"], "text")
        self.assertEqual(doc["flow"][0]["style"], "title")


class TestDegradation(unittest.TestCase):

    def test_text_without_data_degrades_to_a_plain_page(self):
        result = compose_page(PLAIN, mkdtemp(prefix="plain_"))
        self.assertEqual(result.matches, [])
        self.assertTrue(all(isinstance(x, TextBlock) for x in result.flow))
        self.assertEqual(len(result.page.cards), 0)
        self.assertEqual(len(result.page.blocks), 3)
        self.assertEqual(result.notes[0]["kind"], "no_data_matched")
        self.assertTrue(os.path.isfile(result.outputs["preview"]))

    def test_plain_page_has_no_notes_about_unapplicable(self):
        self.assertEqual([n for n in compose_page(
            PLAIN, mkdtemp(prefix="plain2_")).notes
            if n["kind"] == "not_applicable"], [])


class TestUnapplicablePolicy(unittest.TestCase):

    """选型器判「不适用」时的兜底策略（本轮唯一有政策选择的地方）。"""

    SIX = [{"seq": i, "label": f"第{i}项", "value": float(i), "unit": "%"}
           for i in range(1, 7)]

    def _flow(self, policy):
        with mock.patch.object(compose, "load_points",
                               return_value=("各年龄段消费者取暖电器成交额占比",
                                             self.SIX)):
            return build_flow(COPY, on_unapplicable=policy)

    def test_skip_policy_keeps_the_text_and_records_a_note(self):
        result = self._flow("skip")
        self.assertIn("not_applicable", [n["kind"] for n in result.notes])
        self.assertEqual([c.kind for c in result.flow if isinstance(c, CardSpec)],
                         ["thermometer"])
        skipped = [m for m in result.matches if m.template is None]
        self.assertEqual([m.dataset_key for m in skipped], ["heat_age"])
        self.assertIn("MAX_SLICES", skipped[0].rationale.upper())

    def test_placeholder_policy_still_draws_a_card(self):
        result = self._flow("placeholder")
        cards = [x for x in result.flow if isinstance(x, CardSpec)]
        self.assertEqual([c.kind for c in cards], ["thermometer", "placeholder"])

    def test_unknown_policy_is_rejected(self):
        with self.assertRaises(ValueError):
            build_flow(COPY, on_unapplicable="whatever")


if __name__ == "__main__":
    unittest.main()
