"""D.2 step 1 — 规格模型扩展（只加可选字段，不推翻 PageSpec）。

Step 1 says load_points() 不变；本步只给声明式规格模型补 B 节「新增清单」
里的字段。关键回归契约：已交付的 out/loop1/pagespec.json 没有任何新字段，
扩展后的 from_dict() 仍必须读得进来（设计文档 B 节末行）。
"""
import json
import unittest
from dataclasses import asdict

from loop.models import Scale, ElementSpec, PageSpec

# Step 1 的回归契约针对「交付时那份没有新字段的 pagespec.json」。后续步骤
# 会把 out/loop1/pagespec.json 重新生成成带 constraints/layout 的新格式，
# 故这里把旧格式钉成一份固定样本，避免测试依赖会被覆盖的产物文件。
_OLD_FORMAT_DOC = {
    "width_in": 10.0, "height_in": 6.0,
    "chart_key": "heat_ratio_top5",
    "chart_title": "取暖电器细分品类成交额环比增速TOP5",
    "scale": {"v_max": 11.0, "h_in": 3.0, "unit": "倍(超)"},
    "semantic_tags": [],
    "elements": [
        {"id": f"e{i}", "type": "rect", "role": "track",
         "x_in": 0.0, "y_in": 0.0, "w_in": 0.5, "h_in": 3.0,
         "fill": "F1F1F1", "text": None, "binding": None}
        for i in range(27)
    ],
}


class TestOptionalFieldsRoundtrip(unittest.TestCase):
    def test_scale_gains_factor_and_domain_optional_fields(self):
        # 会被这个测试抓到的生产变更：Scale 丢了 factor/domain，或 from_dict
        # 忘了把二者读回来（B 节：scale 需补 factor、domain 声明）。
        s = Scale(11.0, 3.0, "倍(超)", factor=3.0 / 11.0, domain=[0.0, 11.0])
        self.assertEqual(asdict(Scale(**asdict(s))), asdict(s))
        self.assertAlmostEqual(s.factor, 3.0 / 11.0)
        self.assertEqual(s.domain, [0.0, 11.0])

    def test_scale_new_fields_default_to_none(self):
        s = Scale(11.0, 3.0, "倍(超)")
        self.assertIsNone(s.factor)
        self.assertIsNone(s.domain)

    def test_element_gains_geometry_expr_and_geometry_optional_fields(self):
        # geometry_expr 存求解表达式（E.1 ④）；geometry 存非 bbox 的求解结果
        # （半圆 start/end angle、cx/cy/R）。二者都不能被 to_dict 丢掉。
        e = ElementSpec(
            "liquid_1", "rect", "liquid", 0.8, 1.57, 0.5, 2.727,
            geometry_expr="h_in = scale.factor * binding.value",
            geometry={"computed_h_in": 2.727},
        )
        d = asdict(e)
        self.assertEqual(asdict(ElementSpec(**d)), d)
        self.assertEqual(e.geometry_expr, "h_in = scale.factor * binding.value")
        self.assertEqual(e.geometry, {"computed_h_in": 2.727})

    def test_element_new_fields_default_to_none(self):
        e = ElementSpec("t", "text", "title", 0, 0, 1, 1)
        self.assertIsNone(e.geometry_expr)
        self.assertIsNone(e.geometry)

    def test_pagespec_gains_constraints_and_layout_optional_fields(self):
        spec = PageSpec(
            10.0, 6.0, "k", "t", Scale(11.0, 3.0, ""),
            constraints=[{"id": "C1", "kind": "bound"}],
            layout={"orient": "horizontal", "margin": 0.5, "gap_min": 0.5},
        )
        self.assertEqual(PageSpec.from_dict(spec.to_dict()).to_dict(), spec.to_dict())
        self.assertEqual(spec.constraints, [{"id": "C1", "kind": "bound"}])
        self.assertEqual(spec.layout["gap_min"], 0.5)

    def test_pagespec_new_fields_default_to_empty(self):
        spec = PageSpec(10.0, 6.0, "k", "t", Scale(11.0, 3.0, ""))
        self.assertEqual(spec.constraints, [])
        self.assertEqual(spec.layout, {})


class TestBackwardCompatibility(unittest.TestCase):
    def test_old_pagespec_json_still_loads_with_defaults(self):
        # 钉死「无任何新字段」的旧格式样本；不读会被后续步骤覆盖的产物文件。
        d = json.loads(json.dumps(_OLD_FORMAT_DOC))
        self.assertNotIn("constraints", d)
        self.assertNotIn("layout", d)
        self.assertNotIn("factor", d["scale"])
        self.assertNotIn("geometry_expr", d["elements"][0])
        spec = PageSpec.from_dict(d)
        self.assertEqual(spec.constraints, [])
        self.assertEqual(spec.layout, {})
        self.assertEqual(len(spec.elements), 27)
        self.assertIsNone(spec.elements[0].geometry_expr)
        self.assertIsNone(spec.elements[0].geometry)
        self.assertIsNone(spec.scale.factor)
        self.assertEqual(PageSpec.from_dict(spec.to_dict()).to_dict(), spec.to_dict())
