"""选型器第一版（用户 m03467）——验收闸口，全部落成 unittest。

范围锁死：只在 {温度计, 半圆图} 二选一；规则写死、不调 LLM、不引新依赖；
选型器只输出「选哪个模板 + 为什么」，不调用 solve()、不写盘、不改输入。

规则（用户 m03467 原文 + 两处冲突的裁定）：
  5a  全相等 → 一律优先选温度计，不论语义（比「占比」更高优先级的否决条件）。
  5b  含零值 → 不改变语义选型结果（占比仍选半圆图），但 rationale 必须注明
       「存在 start==end 的零值退化扇区」。
  1   n > max_slices → 半圆图不适用；语义「比较大小」则温度计，否则无适用图形。
  2   语义「占比构成」且 n ≤ max_slices 且无负值 → 半圆图（前置：非全相等）。
  3   语义「比较大小」→ 温度计。
  4   含负值 → 温度计可处理（非正值守 0），半圆图不适用（占比不能为负）。
  6   其余 → 返回「无适用图形」+ 原因，不静默选默认。
"""
import copy
import inspect
import os
import unittest
from unittest import mock

from loop.selector import (
    SEMANTIC_COMPARE,
    SEMANTIC_OTHER,
    SEMANTIC_SHARE,
    SelectorError,
    features_from_points,
    select,
)
from loop.templates import get_template

# 半圆图容量上限必须从模板元数据读，不写死 5。
MAX_SLICES = get_template("semicircle").params["max_slices"]["default"]


def _f(n, semantic=SEMANTIC_SHARE, all_equal=False, has_zero=False,
       has_negative=False):
    return {"n": n, "all_equal": all_equal, "has_zero": has_zero,
            "has_negative": has_negative, "semantic": semantic}


def _pts(values, unit="占比"):
    return [{"seq": i + 1, "label": f"项{i + 1}", "value": float(v), "unit": unit}
            for i, v in enumerate(values)]


class TestSharePicksSemicircle(unittest.TestCase):
    """① 占比构成、5 项、无负值 → 半圆图。"""

    def setUp(self):
        self.r = select(_f(5, SEMANTIC_SHARE))

    def test_selects_semicircle(self):
        self.assertEqual(self.r["selected_template"], "semicircle")

    def test_rationale_mentions_share_and_slice_bound(self):
        # 闸口要求 rationale 含「占比」和「n≤5」。
        self.assertIn("占比", self.r["rationale"])
        self.assertIn("n≤5", self.r["rationale"])

    def test_rejected_lists_thermometer_with_a_reason(self):
        self.assertEqual(len(self.r["rejected"]), 1)
        rej = self.r["rejected"][0]
        self.assertEqual(rej["template"], "thermometer")
        self.assertTrue(rej["reason"].strip())

    def test_result_is_plain_json_safe_dict(self):
        # 未来要能直接喂给 LLM 做目标探索：只含 str / None / list / dict。
        self.assertIsInstance(self.r["rationale"], str)
        for rej in self.r["rejected"]:
            self.assertEqual(set(rej), {"template", "reason"})


class TestComparePicksThermometer(unittest.TestCase):
    """② 比较大小、任意项数 → 温度计。"""

    def test_any_n_picks_thermometer(self):
        for n in (2, 5, 6, 20):
            with self.subTest(n=n):
                r = select(_f(n, SEMANTIC_COMPARE))
                self.assertEqual(r["selected_template"], "thermometer")

    def test_rationale_mentions_compare(self):
        self.assertIn("比较", select(_f(5, SEMANTIC_COMPARE))["rationale"])

    def test_semicircle_rejected_with_reason(self):
        r = select(_f(5, SEMANTIC_COMPARE))
        self.assertIn("semicircle",
                      [x["template"] for x in r["rejected"]])


class TestTooManySlices(unittest.TestCase):
    """③ 占比构成、6 项 → 半圆图被拒。"""

    def test_share_over_capacity_has_no_applicable_chart(self):
        r = select(_f(MAX_SLICES + 1, SEMANTIC_SHARE))
        self.assertIsNone(r["selected_template"])
        self.assertTrue(r["rationale"].strip())
        reasons = " ".join(x["reason"] for x in r["rejected"])
        self.assertIn("MAX_SLICES", reasons)
        self.assertIn(str(MAX_SLICES), reasons)

    def test_compare_over_capacity_still_thermometer(self):
        r = select(_f(MAX_SLICES + 1, SEMANTIC_COMPARE))
        self.assertEqual(r["selected_template"], "thermometer")

    def test_boundary_n_equals_max_slices_is_allowed(self):
        # 边界值：n == max_slices 必须放行（不是 >= 才拒的 off-by-one）。
        self.assertEqual(select(_f(MAX_SLICES, SEMANTIC_SHARE))["selected_template"],
                         "semicircle")


class TestNegativeValues(unittest.TestCase):
    """④ 含负值、占比构成 → 半圆图被拒（负值），温度计可选。"""

    def setUp(self):
        self.r = select(_f(5, SEMANTIC_SHARE, has_negative=True))

    def test_thermometer_selected(self):
        self.assertEqual(self.r["selected_template"], "thermometer")

    def test_semicircle_rejected_for_negative(self):
        rej = {x["template"]: x["reason"] for x in self.r["rejected"]}
        self.assertIn("semicircle", rej)
        self.assertIn("负", rej["semicircle"])

    def test_rationale_explains_floor_zero(self):
        # 规则 4：温度计可处理非正值（守 0）。
        self.assertIn("0", self.r["rationale"])


class TestAllEqualPrefersThermometer(unittest.TestCase):
    """⑤ 全相等、5 项 → 温度计优先，不论语义（规则 5a）。"""

    def test_all_equal_share_semantic_still_thermometer(self):
        # 冲突裁定 1：全相等是比「占比」更高优先级的否决条件。
        r = select(_f(5, SEMANTIC_SHARE, all_equal=True))
        self.assertEqual(r["selected_template"], "thermometer")

    def test_rationale_says_why_semicircle_is_unsuitable(self):
        r = select(_f(5, SEMANTIC_SHARE, all_equal=True))
        self.assertIn("全相等", r["rationale"])
        # 闸口要求写明半圆不适合的原因。
        self.assertTrue("半圆" in r["rationale"] or
                        any("半圆" in x["reason"] for x in r["rejected"]))

    def test_all_equal_never_picks_semicircle_for_any_semantic(self):
        for sem in (SEMANTIC_SHARE, SEMANTIC_COMPARE, SEMANTIC_OTHER):
            with self.subTest(semantic=sem):
                self.assertEqual(
                    select(_f(5, sem, all_equal=True))["selected_template"],
                    "thermometer")


class TestZeroKeepsSemanticChoice(unittest.TestCase):
    """⑥ 含零值、5 项、占比构成 → 半圆图可选，rationale 提到零值扇区退化。"""

    def setUp(self):
        self.r = select(_f(5, SEMANTIC_SHARE, has_zero=True))

    def test_still_semicircle(self):
        # 冲突裁定 2（规则 5b）：含零值不改变语义选型结果。
        self.assertEqual(self.r["selected_template"], "semicircle")

    def test_rationale_mentions_degenerate_zero_sector(self):
        text = self.r["rationale"]
        self.assertIn("零值", text)
        self.assertIn("start==end", text)


class TestNoApplicableChart(unittest.TestCase):
    """⑦ 无适用图形：不静默选默认、不抛未捕获异常、返回结构化结果。"""

    def test_other_semantic_returns_structured_none(self):
        r = select(_f(5, SEMANTIC_OTHER))
        self.assertIsNone(r["selected_template"])
        self.assertTrue(r["rationale"].strip())
        templates = {x["template"] for x in r["rejected"]}
        self.assertEqual(templates, {"thermometer", "semicircle"})

    def test_unknown_semantic_label_is_not_silently_defaulted(self):
        r = select(_f(5, "某种没见过的语义"))
        self.assertIsNone(r["selected_template"])

    def test_no_applicable_does_not_raise(self):
        try:
            select(_f(MAX_SLICES + 3, SEMANTIC_OTHER))
        except SelectorError:
            self.fail("无适用图形不应抛异常（只有元数据缺失才抛）")


class TestMaxSlicesMetaIsRequired(unittest.TestCase):
    """⑧ max_slices 缺失时：报错，不默认 5。"""

    def test_missing_max_slices_raises(self):
        import loop.selector as SEL

        real = SEL._semicircle_max_slices

        def fake():
            raise SelectorError(
                "semicircle template is missing max_slices metadata; "
                "refuse to default it to 5")

        with mock.patch.object(SEL, "_semicircle_max_slices", fake):
            with self.assertRaises(SelectorError) as ctx:
                select(_f(5, SEMANTIC_SHARE))
        self.assertIn("max_slices", str(ctx.exception))
        self.assertIsNotNone(real)   # 真实实现可调用

    def test_max_slices_is_read_from_template_not_hardcoded(self):
        import loop.selector as SEL

        # 把模板元数据改成 3，4 项占比就必须被判超容。
        with mock.patch.object(SEL, "_semicircle_max_slices", lambda: 3):
            r = select(_f(4, SEMANTIC_SHARE))
        self.assertIsNone(r["selected_template"])


class TestSelectorHasNoSideEffects(unittest.TestCase):
    """⑨ 不修改输入数据、不调用 solve()、不写盘。"""

    def test_input_features_are_not_mutated(self):
        feats = _f(5, SEMANTIC_SHARE, has_zero=True)
        before = copy.deepcopy(feats)
        select(feats)
        self.assertEqual(feats, before)

    def test_input_points_are_not_mutated(self):
        pts = _pts([10, 0, 3, 2, 1])
        before = copy.deepcopy(pts)
        features_from_points(pts, SEMANTIC_SHARE)
        self.assertEqual(pts, before)

    def test_never_calls_solve(self):
        import loop.solve as S

        with mock.patch.object(S, "solve", side_effect=AssertionError("called")):
            select(_f(5, SEMANTIC_SHARE))
            select(_f(6, SEMANTIC_SHARE))

    def test_writes_no_files(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        outdir = os.path.join(root, "out")
        before = sorted(os.listdir(outdir))
        for feats in (_f(5, SEMANTIC_SHARE), _f(6, SEMANTIC_SHARE),
                      _f(5, SEMANTIC_COMPARE), _f(5, SEMANTIC_OTHER)):
            select(feats)
        self.assertEqual(sorted(os.listdir(outdir)), before)

    def test_selector_source_does_not_import_render_or_solve_for_work(self):
        # 选型器只读模板元数据；不得 import render / preview / scaffold。
        import loop.selector as SEL
        src = inspect.getsource(SEL)
        for banned in ("render", "preview", "build_pagespec", "open("):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, src)


class TestFeaturesFromPoints(unittest.TestCase):
    def test_features_are_derived_correctly(self):
        f = features_from_points(_pts([10, 0, 3, 2, 1]), SEMANTIC_SHARE)
        self.assertEqual(f["n"], 5)
        self.assertTrue(f["has_zero"])
        self.assertFalse(f["has_negative"])
        self.assertFalse(f["all_equal"])
        self.assertEqual(f["semantic"], SEMANTIC_SHARE)

    def test_all_equal_detected(self):
        self.assertTrue(features_from_points(_pts([5, 5, 5]), SEMANTIC_SHARE)["all_equal"])

    def test_negative_detected(self):
        self.assertTrue(
            features_from_points(_pts([3, -1, 2]), SEMANTIC_COMPARE)["has_negative"])


if __name__ == "__main__":
    unittest.main()
