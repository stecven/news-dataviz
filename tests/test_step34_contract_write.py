"""P1 Task 4：``chart`` 字段 + 严格写出（``dump_layout`` / ``write_layout_atomic``）。

对应验收：

* 写出时补齐 ``version`` / ``theme``（theme = ``palette.summary()`` 原样）
                                            → ``test_dump_layout_fills_version_and_theme``
* 写出的文档必须过严格 schema（schema ↔ dataclass 不漂移）→
  ``test_dump_layout_output_passes_strict_schema``（Review Focus #5；两份老夹具
  + ``out/demo/**`` 历史样本）
* 1.0 新字段的**真实载荷**（dict 形态 ``chart``、非空 ``lines``）也过严格 schema，
  并用两条 schema 变异做负向对照                        →
  ``test_dump_layout_accepts_full_1_0_payload``
* 校验失败抛 ``ContractError``，消息里带错误路径        →
  ``test_dump_layout_raises_contract_error_with_element_path``
* 原子写失败不留 ``.tmp``、不动目标字节                  →
  ``test_write_layout_atomic_leaves_no_tmp_on_failure``
* 新字段一律可空、按位置构造仍可用                      →
  ``test_new_fields_default_to_none_and_models_construction_is_backward_compatible``
* 新字段必须留在 dataclass **末尾**                     →
  ``test_new_fields_are_last_in_dataclass``
* ``$defs.scale`` 的 ``required`` 收紧闭环「假阴性」     →
  ``test_scale_required_closes_the_last_crash_path``
* ``chart`` 在两条构造路径上都活着（消重判据）           →
  ``test_chart_survives_both_readers``

夹具路径一律取自 ``tests.contract_fixtures.LEGACY_DIR``，不硬编码目录。
两份老样本缺 ``version`` / ``theme`` / ``images``，**故意**过不了严格 schema，
所以 dump 用例都是「先 ``load_layout`` 读进来、再 ``dump_layout`` 写出去」。
"""
import json
import os
import tempfile
import unittest
from dataclasses import fields

from loop.contract import (ContractError, _spec_from_dict, dump_layout,
                           load_layout, load_layout_json, write_layout_atomic)
from loop.layout import PageLayoutSpec
from loop.models import ElementSpec, PageSpec
from loop.palette import summary as palette_summary
from loop.schema_check import load_schema, validate_doc
from tests.contract_fixtures import LEGACY_DIR, REPO_ROOT, demo_layout_paths

#: 两份入库夹具（``out/`` 不入库，它们才是长期可复现的证据）。
AUTO_LAYOUT_FIXTURE = "auto_layout.pagelayout.json"
PLAIN_FIXTURE = "_plain.pagelayout.json"


def _load(fixture: str) -> dict:
    with open(os.path.join(LEGACY_DIR, fixture), encoding="utf-8") as fh:
        return json.load(fh)


def _layout(fixture: str) -> PageLayoutSpec:
    return load_layout(os.path.join(LEGACY_DIR, fixture)).layout


class TestContractWriteEntry(unittest.TestCase):

    def test_dump_layout_fills_version_and_theme(self):
        doc = dump_layout(_layout(AUTO_LAYOUT_FIXTURE))

        self.assertEqual(doc["version"], "1.0")
        self.assertEqual(doc["theme"], palette_summary())
        self.assertEqual(doc["theme"]["role_to_font"]["value"], "body")
        self.assertEqual(doc["theme"]["font_sizes"]["title"], 20)
        self.assertEqual(doc["theme"]["font_pt_clamp"], [6.0, 24.0])
        self.assertEqual(doc["theme"]["base_canvas_in"], [10.0, 6.0])

    def test_dump_layout_output_passes_strict_schema(self):
        # 这是 schema ↔ dataclass 不漂移的判据：写出侧必须在严格校验下为真。
        for fixture in (PLAIN_FIXTURE, AUTO_LAYOUT_FIXTURE):
            with self.subTest(fixture=fixture):
                self.assertEqual(validate_doc(dump_layout(_layout(fixture))), [])
        # 顺手把网撒宽：``out/demo/**`` 的历史样本（fresh clone 上是空列表，
        # 照样跑）。它们的 dump 里同样可能有非空 1.0 载荷。
        for rel in demo_layout_paths():
            with self.subTest(demo=rel):
                layout = load_layout(os.path.join(REPO_ROOT, rel)).layout
                self.assertEqual(validate_doc(dump_layout(layout)), [])

    def test_dump_layout_accepts_full_1_0_payload(self):
        # 两份老夹具的 dump 里既没有非空 ``lines``、也没有 dict 形态的 ``chart``，
        # 所以「过严格 schema」只钉得住「字段没了 / 改名了 / 不接受 None」，
        # 钉不住 1.0 新字段的**真实载荷形状**：把 schema 里这俩改成 string，
        # 旧判据照样全绿（见报告 §P2 的探针）。这里把真载荷灌进去。
        doc = _load(AUTO_LAYOUT_FIXTURE)
        doc["cards"][0]["spec"]["chart"] = {"kind": "thermometer", "unit": "%"}
        element = doc["cards"][0]["spec"]["elements"][0]
        element["lines"] = ["第一行", "第二行"]
        element["font_pt"] = 12.0
        element["editable"] = True

        out = dump_layout(load_layout_json(doc).layout)

        # 正向：真载荷必须过。
        self.assertEqual(validate_doc(out), [])

        # 负向对照（必须，否则上面那条是可空过的）：只改内存里这一份 schema，
        # 校验器必须报错——证明它**真的在看**这两个字段的形状。
        # ``load_schema()`` 每次都重新读文件，所以改它不会污染别的用例。
        chart_mut = load_schema()
        chart_mut["$defs"]["page"]["properties"]["chart"] = {
            "type": ["string", "null"]}
        chart_errors = validate_doc(out, schema=chart_mut)
        self.assertTrue(chart_errors, "schema 的 chart 改成 string 后仍全绿：钉不住 chart 载荷")
        self.assertIn("$.cards[0].spec.chart",
                      [e["path"] for e in chart_errors])

        lines_mut = load_schema()
        lines_mut["$defs"]["element"]["properties"]["lines"] = {
            "type": ["string", "null"]}
        lines_errors = validate_doc(out, schema=lines_mut)
        self.assertTrue(lines_errors, "schema 的 lines 改成 string 后仍全绿：钉不住 lines 载荷")
        self.assertIn("$.cards[0].spec.elements[0].lines",
                      [e["path"] for e in lines_errors])

    def test_dump_layout_raises_contract_error_with_element_path(self):
        layout = _layout(AUTO_LAYOUT_FIXTURE)
        layout.cards[0].spec.elements[0].x_in = "x"

        with self.assertRaises(ContractError) as ctx:
            dump_layout(layout)

        self.assertIn("$.cards[0].spec.elements[0].x_in", str(ctx.exception))

    def test_write_layout_atomic_leaves_no_tmp_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "pagelayout.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("KEEP")
            with open(path, "rb") as fh:
                before = fh.read()

            # ``object()`` 不能 JSON 序列化：json.dump 失败 → 原样抛。
            with self.assertRaises(TypeError):
                write_layout_atomic(path, {"bad": object()})

            self.assertFalse(os.path.exists(path + ".tmp"))
            with open(path, "rb") as fh:
                self.assertEqual(fh.read(), before)

    def test_new_fields_default_to_none_and_models_construction_is_backward_compatible(self):
        # 改版前按位置构造 ElementSpec(...) 的调用方不受影响。
        element = ElementSpec("a", "rect", "liquid", 0, 0, 1, 1)
        self.assertIsNone(element.lines)
        self.assertIsNone(element.font_pt)
        self.assertIsNone(element.editable)

        spec = _load(AUTO_LAYOUT_FIXTURE)["cards"][0]["spec"]
        spec["chart"] = {"kind": "thermometer"}
        back = PageSpec.from_dict(spec)
        self.assertEqual(back.chart, {"kind": "thermometer"})
        self.assertEqual(back.to_dict()["chart"], {"kind": "thermometer"})

    def test_new_fields_are_last_in_dataclass(self):
        # 把 loop/models.py 的「新增字段一律放在末尾」注释变成可执行约束。
        self.assertEqual([f.name for f in fields(ElementSpec)][-3:],
                         ["lines", "font_pt", "editable"])
        self.assertEqual([f.name for f in fields(PageSpec)][-1], "chart")
        self.assertEqual([f.name for f in fields(PageLayoutSpec)][-2:],
                         ["version", "theme"])

    def test_scale_required_closes_the_last_crash_path(self):
        doc = _load(AUTO_LAYOUT_FIXTURE)
        del doc["cards"][0]["spec"]["scale"]["unit"]

        errors = validate_doc(doc)
        hit = [e for e in errors if e["path"] == "$.cards[0].spec.scale.unit"]
        self.assertTrue(hit, errors)
        self.assertEqual(hit[0]["message"], "required key is missing")

        # 证明这是**真**假阴性：schema 放过 → 消费端运行时 TypeError。
        with self.assertRaises(TypeError):
            PageSpec.from_dict(doc["cards"][0]["spec"])

    def test_chart_survives_both_readers(self):
        spec = _load(AUTO_LAYOUT_FIXTURE)["cards"][0]["spec"]
        spec["chart"] = {"kind": "thermometer", "unit": "%"}

        direct = PageSpec.from_dict(spec).to_dict()["chart"]
        loose = _spec_from_dict(spec, "$.cards[0].spec", []).to_dict()["chart"]

        self.assertEqual(direct, {"kind": "thermometer", "unit": "%"})
        self.assertEqual(direct, loose)
        self.assertIsNotNone(direct)


if __name__ == "__main__":
    unittest.main()
