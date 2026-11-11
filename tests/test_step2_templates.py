"""D.2 step 2 — TemplateSpec 注册表（选模板 → 产出不含绝对坐标的模板规格）。

本步只验「模板本身」：注册表、五件套、坐标无关、占位条目。真正的
solve() 与 E.3 复用/失败路径留到第 3–6 步，本文件不写它们的测试。
"""
import json
import os
import unittest

from tests.scratch import mkdtemp

# 设计文档 E.3 #3 点名的旧硬编码坐标字面量（0.8 / 1.30 / 4.30 / 5.05 / 5.40 / 1.8）。
FORBIDDEN_COORDS = (0.8, 1.30, 4.30, 5.05, 5.40, 1.8)
GEOM_FIELDS = ("x_in", "y_in", "w_in", "h_in")


def _numbers(obj):
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        yield float(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _numbers(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _numbers(v)


class TestRegistry(unittest.TestCase):
    def test_registry_lists_two_implemented_and_four_placeholders(self):
        from loop import templates as T
        names = T.list_templates()
        self.assertEqual(set(names), {
            "thermometer", "semicircle", "icon_progress", "radial_nodes",
            "point_map", "dual_thermometer",
        })
        implemented = {n for n in names if T.TEMPLATES[n].implemented}
        self.assertEqual(implemented, {"thermometer", "semicircle"})

    def test_unknown_template_raises_valueerror(self):
        from loop import templates as T
        with self.assertRaisesRegex(ValueError, "unknown"):
            T.get_template("no_such_chart")

    def test_four_other_chart_types_are_registered_but_not_implemented(self):
        # 用户硬要求 ①：其余 4 类不实现。选中时必须显式报错，不能静默产出。
        from loop import templates as T
        for name in ("icon_progress", "radial_nodes", "point_map", "dual_thermometer"):
            with self.subTest(name=name):
                self.assertFalse(T.TEMPLATES[name].implemented)
                with self.assertRaises(NotImplementedError):
                    T.get_template(name)

    def test_semicircle_data_shape_and_not_applicable_rule(self):
        from loop import templates as T
        s = T.get_template("semicircle")
        self.assertIn("占比", s.data_shape)
        self.assertIn("5", s.not_applicable_when)
        self.assertEqual(T.get_template("thermometer").data_shape, "比较")


class TestFiveSections(unittest.TestCase):
    def test_both_templates_carry_all_five_sections(self):
        # E.1 五件套：参数 schema / 适用数据形态 / 确定性硬约束 / 输出规格片段 / 渲染适配器。
        from loop import templates as T
        for name in ("thermometer", "semicircle"):
            with self.subTest(name=name):
                t = T.get_template(name)
                self.assertTrue(t.params, "① 参数 schema 为空")
                self.assertTrue(t.data_shape, "② 适用数据形态为空")
                self.assertTrue(t.constraints, "③ 确定性硬约束为空")
                self.assertTrue(t.marks, "④ 输出规格片段为空")
                self.assertTrue(t.renderer, "⑤ 渲染适配器为空")

    def test_template_roundtrip(self):
        from loop import templates as T
        for name in ("thermometer", "semicircle"):
            with self.subTest(name=name):
                t = T.get_template(name)
                self.assertEqual(T.TemplateSpec.from_dict(t.to_dict()).to_dict(),
                                 t.to_dict())

    def test_renderer_ids_match_the_two_adapters(self):
        from loop import templates as T
        self.assertEqual(T.get_template("thermometer").renderer, "pptx_basic")
        self.assertEqual(T.get_template("semicircle").renderer, "pptx_arc")


class TestCoordinateFree(unittest.TestCase):
    def test_exported_templates_contain_no_absolute_coordinate_literals(self):
        # E.3 #3：导出的模板里不出现旧硬编码坐标字面量。
        from loop import templates as T
        for name in ("thermometer", "semicircle"):
            with self.subTest(name=name):
                d = T.export_template(name)
                for num in _numbers(d):
                    for bad in FORBIDDEN_COORDS:
                        self.assertNotAlmostEqual(num, bad, places=9,
                                                  msg=f"{name}: 出现绝对坐标字面量 {bad}")

    def test_all_mark_geometry_fields_are_parameter_references(self):
        # 更强的坐标无关保证：marks 的 x/y/w/h 全是 "@参数名" 字符串，
        # 任何一个裸数字（绝对坐标）都会让本测试失败。
        from loop import templates as T
        for name in ("thermometer", "semicircle"):
            with self.subTest(name=name):
                d = T.export_template(name)
                for m in d["marks"]:
                    for f in GEOM_FIELDS:
                        self.assertIsInstance(m[f], str, f"{name}/{m['id']}/{f}")
                        self.assertTrue(m[f].startswith("@"),
                                        f"{name}/{m['id']}/{f} = {m[f]!r}")

    def test_all_numbers_live_in_named_params_or_linear_coefficients(self):
        # 模板 JSON 「只含约束标识符与参数名」：数值只允许出现在
        # params 的 default，以及 constraints 的线性系数 / rhs。
        from loop import templates as T
        for name in ("thermometer", "semicircle"):
            with self.subTest(name=name):
                d = T.export_template(name)
                for m in d["marks"]:
                    self.assertEqual(list(_numbers(m)), [],
                                     f"{name}/{m['id']}: marks 里出现裸数字")
                self.assertTrue(d["params"])
                for pname, p in d["params"].items():
                    self.assertIn("default", p, f"{name}/params/{pname}")
                    self.assertIn("unit", p, f"{name}/params/{pname}")

    def test_exported_template_file_is_valid_json_and_coordinate_free(self):
        # E.3 #3 字面要求「导出的 thermometer.template.json / semicircle.template.json」。
        from loop import templates as T
        d = mkdtemp(prefix="tpl-")
        for name in ("thermometer", "semicircle"):
            path = os.path.join(d, f"{name}.template.json")
            T.export_template_file(name, path)
            with open(path, encoding="utf-8") as f:
                loaded = json.load(f)
            self.assertEqual(loaded, T.export_template(name))
            for num in _numbers(loaded):
                for bad in FORBIDDEN_COORDS:
                    self.assertNotAlmostEqual(num, bad, places=9)


class TestConstraintDeclarations(unittest.TestCase):
    def test_constraint_ids_are_declared_and_c9_is_excluded(self):
        # C9（标签避让，非线性）明确排除在本子集外（C.2 / D.3）。
        from loop import templates as T
        for name in ("thermometer", "semicircle"):
            with self.subTest(name=name):
                ids = {c["id"] for c in T.get_template(name).constraints}
                self.assertTrue(ids)
                self.assertNotIn("C9", ids)
                self.assertTrue(all(i.startswith("C") or i == "DATA" for i in ids))

    def test_semicircle_declares_c1_c4_c5_for_reuse(self):
        # E.3 #3：半圆模板成功复用温度计的 C1/C4/C5 原语（声明层）。
        from loop import templates as T
        ids = {c["id"] for c in T.get_template("semicircle").constraints}
        self.assertTrue({"C1", "C4", "C5"}.issubset(ids))
