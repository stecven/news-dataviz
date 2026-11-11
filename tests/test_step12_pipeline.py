"""步骤 12：把选型器接进现有流水线（用户 m03536）。

只验证「接口接得上」：selector.select() 的输出 → build_pagespec() 的输入 →
render。不新增选型规则、不改 selector / solve / render。

三件事：①两组真实数据跑通全链路 ②6 项占比走「无适用图形」分支不崩溃
③把 selector 输出字段与 build_pagespec 输入逐项对照，不静默绕过。
"""
import json
import os
import unittest

from loop import pipeline
from loop.data_source import DB_PATH, load_points
from loop.selector import SEMANTIC_COMPARE, SEMANTIC_OTHER, SEMANTIC_SHARE
from tests.scratch import mkdtemp

# 接口对照表允许的三种状态（用户 m03536 原文口径）。
STATUS_DIRECT = "直接可用"
STATUS_CONVERT = "需转换"
STATUS_MISSING = "缺失"
ALLOWED_STATUS = {STATUS_DIRECT, STATUS_CONVERT, STATUS_MISSING}


def _pts(values, unit="占比"):
    return [{"seq": i + 1, "label": f"项{i + 1}", "value": float(v), "unit": unit}
            for i, v in enumerate(values)]


class TestCompareEndToEnd(unittest.TestCase):
    """heat_ratio_top5（语义＝比较大小）→ 温度计 → 出图。"""

    def setUp(self):
        self.out = mkdtemp("pipe-cmp-")
        self.r = pipeline.run_selected(
            chart_key="heat_ratio_top5", semantic=SEMANTIC_COMPARE,
            out_root=self.out)

    def test_selector_picked_thermometer(self):
        self.assertEqual(self.r["selected_template"], "thermometer")
        self.assertEqual(self.r["status"], "rendered")

    def test_pagespec_and_preview_written(self):
        self.assertTrue(os.path.isfile(self.r["pagespec"]))
        self.assertTrue(os.path.isfile(self.r["preview"]))
        self.assertGreater(os.path.getsize(self.r["preview"]), 5000)

    def test_rendered_spec_is_a_thermometer_with_37_elements(self):
        with open(self.r["pagespec"], encoding="utf-8") as f:
            doc = json.load(f)
        self.assertEqual(doc["layout"]["template"], "thermometer")
        self.assertEqual(len(doc["elements"]), 39)   # 37 内容 + frame + title_band

    def test_raw_data_reaches_the_spec_unchanged(self):
        """数值忠实度：选型器不得改动数据，渲染用的是 DB 原值。"""
        _title, pts = load_points(DB_PATH, chart_key="heat_ratio_top5")
        with open(self.r["pagespec"], encoding="utf-8") as f:
            doc = json.load(f)
        got = sorted((e["binding"]["seq"], e["binding"]["value"])
                     for e in doc["elements"] if e["role"] == "liquid")
        self.assertEqual(got, [(p["seq"], p["value"]) for p in pts])

    def test_selection_is_recorded_next_to_the_artifacts(self):
        """rationale/rejected 在 PageSpec 里没有字段，不能悄悄丢掉。"""
        self.assertTrue(os.path.isfile(self.r["selection"]))
        with open(self.r["selection"], encoding="utf-8") as f:
            sel = json.load(f)
        self.assertEqual(sel["selected_template"], "thermometer")
        self.assertTrue(sel["rationale"])
        self.assertEqual([x["template"] for x in sel["rejected"]], ["semicircle"])


class TestShareEndToEnd(unittest.TestCase):
    """heat_age（语义＝占比构成，5 项）→ 半圆图 → 出图。"""

    def setUp(self):
        self.out = mkdtemp("pipe-share-")
        self.r = pipeline.run_selected(
            chart_key="heat_age", semantic=SEMANTIC_SHARE, out_root=self.out)

    def test_selector_picked_semicircle(self):
        self.assertEqual(self.r["selected_template"], "semicircle")
        self.assertEqual(self.r["status"], "rendered")

    def test_pagespec_and_preview_written(self):
        self.assertTrue(os.path.isfile(self.r["pagespec"]))
        self.assertTrue(os.path.isfile(self.r["preview"]))

    def test_rendered_spec_is_a_semicircle_with_13_elements(self):
        with open(self.r["pagespec"], encoding="utf-8") as f:
            doc = json.load(f)
        self.assertEqual(doc["layout"]["template"], "semicircle")
        self.assertEqual(len(doc["elements"]), 15)   # 13 内容 + frame + title_band

    def test_arcs_still_close_at_180_degrees(self):
        with open(self.r["pagespec"], encoding="utf-8") as f:
            doc = json.load(f)
        sectors = [e for e in doc["elements"] if e["role"] == "sector"]
        total = sum(e["geometry"]["theta"] for e in sectors)
        self.assertAlmostEqual(total, 180.0, places=9)


class TestNoApplicableBranch(unittest.TestCase):
    """6 项占比：选型器返回 selected_template=None，流水线不得崩溃/静默兜底。"""

    def setUp(self):
        self.out = mkdtemp("pipe-six-")
        self.r = pipeline.run_selected(
            values=[10, 3, 2, 2, 2, 1], semantic=SEMANTIC_SHARE,
            chart_title="6 项占比（临时构造）", out_root=self.out)

    def test_status_is_no_applicable_not_rendered(self):
        self.assertEqual(self.r["status"], "no_applicable")
        self.assertIsNone(self.r["selected_template"])

    def test_no_applicable_draws_a_placeholder_not_a_default_chart(self):
        """行为在 m04220 变了：不再「什么都不画」，而是画出占位图兜底。

        关键约束没变：**不能**静默选个默认图形（见 test_does_not_fall_back）。
        现在断言的是「画出来的东西是占位图，不是图形」。
        """
        self.assertIsNotNone(self.r["pagespec"])
        with open(self.r["pagespec"], encoding="utf-8") as f:
            doc = json.load(f)
        self.assertTrue(doc["elements"])
        # 包框后还有 frame / title_band / title / scale_note 四个 chrome 元素，
        # 但**内容**元素必须只有那一张占位图（不能混进任何图形）。
        self.assertEqual([e["type"] for e in doc["elements"]
                          if e["role"] not in ("frame", "title_band",
                                               "title", "subtitle", "scale_note")],
                         ["image"])
        self.assertEqual(doc["layout"]["kind"], "fallback_placeholder")
        self.assertIsNone(doc["layout"]["template"])
        self.assertTrue(os.path.exists(self.r["preview"]))
        self.assertTrue(os.path.exists(self.r["pptx"]))

    def test_message_is_readable_and_mentions_fallback(self):
        msg = self.r["message"]
        self.assertIn("fallback_used", msg)
        self.assertIn("6", msg)

    def test_does_not_fall_back_to_a_default_chart(self):
        """反证：若静默选了温度计，这里会看到 selected_template。"""
        self.assertNotIn(self.r["selected_template"],
                         ("thermometer", "semicircle"))

    def test_rejected_lists_both_templates_with_reasons(self):
        self.assertEqual(sorted(x["template"] for x in self.r["rejected"]),
                         ["semicircle", "thermometer"])
        for x in self.r["rejected"]:
            self.assertTrue(x["reason"])


class TestNoApplicableForUnknownSemantic(unittest.TestCase):
    def test_other_semantic_is_no_applicable_and_does_not_raise(self):
        out = mkdtemp("pipe-other-")
        r = pipeline.run_selected(values=[1, 2, 3], semantic=SEMANTIC_OTHER,
                                  chart_title="t", out_root=out)
        self.assertEqual(r["status"], "no_applicable")
        self.assertIsNone(r["selected_template"])


class TestInterfaceMap(unittest.TestCase):
    """selector 输出字段 vs build_pagespec 输入，逐项对照，不许悄悄绕过。"""

    def test_every_selector_output_field_is_mapped(self):
        keys = {row["selector_field"] for row in pipeline.INTERFACE_MAP}
        self.assertEqual(
            keys, {"selected_template", "rationale", "rejected"})

    def test_every_status_value_is_one_of_the_three(self):
        for row in pipeline.INTERFACE_MAP:
            self.assertIn(row["status"], ALLOWED_STATUS, msg=row["selector_field"])

    def test_every_row_explains_itself(self):
        for row in pipeline.INTERFACE_MAP:
            self.assertTrue(row["note"].strip(), msg=row["selector_field"])

    def test_converted_and_missing_rows_name_a_concrete_destination(self):
        """「需转换／缺失」必须写清落到哪里，否则就是被悄悄绕过。"""
        for row in pipeline.INTERFACE_MAP:
            if row["status"] in (STATUS_CONVERT, STATUS_MISSING):
                self.assertTrue(row["destination"].strip(),
                                msg=row["selector_field"])
                self.assertNotEqual(row["destination"], "-")

    def test_no_row_claims_a_build_pagespec_kwarg_that_does_not_exist(self):
        import inspect
        from loop.scaffold import build_pagespec

        accepted = set(inspect.signature(build_pagespec).parameters)
        for row in pipeline.INTERFACE_MAP:
            dest = row["destination"]
            if row["status"] == STATUS_DIRECT and dest.startswith("build_pagespec("):
                continue          # 已带括号的整调用，另有断言覆盖
            if row["status"] == STATUS_DIRECT and dest not in ("-", ""):
                self.assertIn(dest, accepted, msg=row["selector_field"])

    def test_the_table_records_the_known_gaps(self):
        """这三处缺口是本轮实测发现的，必须留在表里。"""
        gaps = {r["selector_field"] + "|" + r["status"]
                for r in pipeline.INTERFACE_MAP}
        self.assertIn("rationale|" + STATUS_MISSING, gaps)
        self.assertIn("rejected|" + STATUS_MISSING, gaps)
        self.assertIn("selected_template|" + STATUS_DIRECT, gaps)


class TestPipelineDiscipline(unittest.TestCase):
    def test_source_does_not_touch_solve_render_or_selector_internals(self):
        import inspect

        src = inspect.getsource(pipeline)
        # 不为选型器复制规则，也不绕过它自己判模板
        self.assertNotIn("max_slices", src)
        self.assertNotIn("all_equal", src)
        self.assertNotIn("has_negative", src)
        # 只经 build_pagespec 出规格，不直接调 solve()
        self.assertNotIn("from loop.solve import", src)
        self.assertNotIn("build_skeleton(", src)
        self.assertNotIn("render_pptx", src)

    def test_inputs_are_not_mutated(self):
        values = [0.08, 0.32, 0.32, 0.17, 0.11]
        snapshot = list(values)
        pipeline.run_selected(values=values, semantic=SEMANTIC_SHARE,
                              chart_title="t", out_root=mkdtemp("pipe-mut-"))
        self.assertEqual(values, snapshot)

    def test_pipeline_reports_the_semantic_it_was_given(self):
        out = mkdtemp("pipe-sem-")
        r = pipeline.run_selected(chart_key="heat_age", semantic=SEMANTIC_SHARE,
                                  out_root=out)
        self.assertEqual(r["semantic"], SEMANTIC_SHARE)


if __name__ == "__main__":
    unittest.main()
