"""P1 Task 4：``chart`` 字段 + 严格写出（``dump_layout`` / ``write_layout_atomic``）。

对应验收：

* 写出时补齐 ``version`` / ``theme``（theme = ``palette.summary()`` 原样）
                                            → ``test_dump_layout_fills_version_and_theme``
* 写出的文档必须过严格 schema（schema ↔ dataclass 不漂移）→
  ``test_dump_layout_output_passes_strict_schema``（Review Focus #5）
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
                           load_layout, write_layout_atomic)
from loop.layout import PageLayoutSpec
from loop.models import ElementSpec, PageSpec
from loop.palette import summary as palette_summary
from loop.schema_check import validate_doc
from tests.contract_fixtures import LEGACY_DIR

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
