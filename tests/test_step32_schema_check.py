"""P1 Task 2：pagelayout.json 的 JSON Schema 与受限子集校验器。

schema 描述的是**目标 1.0 契约**，不是对历史样本的描述 —— 历史样本没有
``version`` / ``theme``，六份连 ``images`` 键都不存在，所以它们今天必然校验失败。
这不是缺陷，是 Spec §7 V5 的可执行版本。

对应验收：

* schema 只用到校验器支持的关键字                    → ``test_schema_uses_only_supported_keywords``
* 最小合法 1.0 文档零错误                            → ``test_minimal_valid_document_has_no_errors``
* 元素级错误带 ``$.cards[0].spec.elements[1].x_in`` 路径 → ``test_element_level_path_is_reported``
* 缺顶层必填键被报出（且只报一条）                     → ``test_missing_required_top_level_key_is_reported``
* 图元词汇表以外的 ``type`` 被拒                       → ``test_unknown_element_type_is_rejected``
* 未知键只在 ``additionalProperties: false`` 处被拒     → ``test_unknown_key_rejected_only_where_additional_properties_is_false``
* 历史样本全红，含 ``$.version`` 与 ``$.images``        → ``test_legacy_document_fails_strict_schema``
* 非对象文档在 ``$`` 上报错（根节点有 ``type: object``）→ ``test_non_object_document_is_reported``
* ``card.spec`` 缺 ``PageSpec.from_dict`` 硬要的键被报出 → ``test_page_missing_required_key_is_reported``
* ``enum`` / ``default`` 的取值位不再下探               → ``test_unsupported_keywords_does_not_descend_into_opaque_values``
* 非 ``#/$defs/`` 的 ``$ref`` 在编写期就被拦             → ``test_unsupported_keywords_rejects_cross_document_ref``

本文件自带最小文档构造器 ``_minimal_doc()``，**不读** ``out/``（``out/`` 不入库，
fresh clone 上没有它）。读已入库夹具的那条**不**跳过 —— 夹具本身就是判据。
"""
import json
import os
import unittest

from loop import schema_check
from tests.contract_fixtures import LEGACY_DIR

#: 库内最完整的老样本（有卡片、元素、geometry 的复合图元）与最小老样本。
AUTO_LAYOUT_FIXTURE = "auto_layout.pagelayout.json"
PLAIN_FIXTURE = "_plain.pagelayout.json"


def _load_legacy(fixture: str) -> dict:
    with open(os.path.join(LEGACY_DIR, fixture), encoding="utf-8") as fh:
        return json.load(fh)


def _minimal_doc() -> dict:
    """一份最小但完整的 1.0 文档：覆盖 schema 的每一层，外加 1.0 的全部新字段。

    每次调用都新建（调用方可以随便改，测试之间不串味）。
    ``...elements[0]`` 是 rect、``...elements[1]`` 是 text，两条错误路径断言都
    依赖这两个下标真实存在。
    """
    return {
        "version": "1.0",
        "theme": {"palette": {"neutral_dark": "1F1F1F"},
                  "font_pt_clamp": [6.0, 18.0]},
        "width_in": 10.0, "height_in": 15.0,
        "margin_in": 0.4, "gutter_in": 0.3,
        "column_count": 1, "column_gutter_in": 0.2,
        "rows": [{"kind": "cards", "y_in": 0.4, "h_in": 6.0,
                  "items": ["card_1"], "cards": ["card_1"],
                  "blocks": [], "images": []}],
        "cards": [{
            "name": "card_1", "kind": "thermometer",
            "x_in": 0.4, "y_in": 0.4, "w_in": 9.2, "h_in": 6.0,
            "row": 0, "column_span": 1,
            "spec": {
                "width_in": 9.2, "height_in": 6.0,
                "chart_key": "heat_ratio_top5", "chart_title": "示例卡",
                "scale": {"v_max": 11.0, "h_in": 3.0, "unit": "倍(超)",
                          "factor": 0.2727272727, "domain": [0.0, 11.0]},
                "elements": [
                    {"id": "frame_1", "type": "rect", "role": "frame",
                     "x_in": 0.0, "y_in": 0.0, "w_in": 9.2, "h_in": 6.0,
                     "fill": "FFFFFF", "text": None, "binding": None,
                     "geometry_expr": None,
                     "geometry": {"border": "1F1F1F"},
                     "image_path": None, "lines": None,
                     "font_pt": None, "editable": None},
                    {"id": "title_1", "type": "text", "role": "title",
                     "x_in": 0.2, "y_in": 0.2, "w_in": 4.0, "h_in": 0.4,
                     "fill": None, "text": "示例标题", "binding": None,
                     "geometry_expr": None, "geometry": {"align": "left"},
                     "image_path": None, "lines": ["示例标题"],
                     "font_pt": 12.0, "editable": True},
                ],
                "semantic_tags": ["thermometer"],
                "constraints": [],
                "layout": {"kind": "thermometer"},
                "content_bbox": [0.0, 0.0, 9.2, 6.0],
                "frame_bbox": [0.0, 0.0, 9.2, 6.0],
                "chart": {"kind": "thermometer",
                          "series": [{"label": "甲", "value": 1.0}],
                          "encoding": {"x": "label", "y": "value"}},
            },
        }],
        "blocks": [{"name": "blk_1", "style": "body", "align": "left",
                    "text": "正文", "x_in": 0.4, "y_in": 7.0,
                    "w_in": 9.2, "h_in": 1.0, "row": 1, "column_span": 1,
                    "columns": 1, "column_gutter_in": 0.2,
                    "lines": ["正文"], "line_groups": [["正文"]]}],
        "images": [{"name": "img_1", "path": "assets/icons/x.png",
                    "style": "icon", "align": "center",
                    "x_in": 0.4, "y_in": 8.2, "w_in": 2.0, "h_in": 2.0,
                    "row": 2, "column_span": 1,
                    "asset_id": 1, "tag": "weather", "semantic": "icon",
                    "rect": [0.0, 0.0, 2.0, 2.0]}],
    }


class TestSchemaCheck(unittest.TestCase):

    def test_schema_uses_only_supported_keywords(self):
        self.assertEqual(
            schema_check.unsupported_keywords(schema_check.load_schema()), [])

    def test_minimal_valid_document_has_no_errors(self):
        self.assertEqual(schema_check.validate_doc(_minimal_doc()), [])

    def test_element_level_path_is_reported(self):
        doc = _minimal_doc()
        doc["cards"][0]["spec"]["elements"][1]["x_in"] = "0.4"

        errors = schema_check.validate_doc(doc)

        self.assertEqual(len(errors), 1, errors)
        self.assertEqual(errors[0]["path"],
                         "$.cards[0].spec.elements[1].x_in")
        # 类型不对就不再往下探：错误消息要能自己说清期望与实际。
        self.assertIn("number", errors[0]["message"])
        self.assertIn("str", errors[0]["message"])

    def test_missing_required_top_level_key_is_reported(self):
        doc = _minimal_doc()
        del doc["images"]

        errors = schema_check.validate_doc(doc)

        self.assertEqual(len(errors), 1, errors)
        self.assertEqual(errors[0]["path"], "$.images")

    def test_unknown_element_type_is_rejected(self):
        doc = _minimal_doc()
        doc["cards"][0]["spec"]["elements"][0]["type"] = "donut"

        errors = schema_check.validate_doc(doc)

        paths = [e["path"] for e in errors]
        self.assertIn("$.cards[0].spec.elements[0].type", paths)
        self.assertEqual(errors[0]["path"],
                         "$.cards[0].spec.elements[0].type")

    def test_unknown_key_rejected_only_where_additional_properties_is_false(self):
        doc = _minimal_doc()
        doc["cards"][0]["spec"]["elements"][0]["bogus"] = 1
        paths = [e["path"] for e in schema_check.validate_doc(doc)]
        self.assertIn("$.cards[0].spec.elements[0].bogus", paths)

        # 顶层故意不设 additionalProperties: false（可扩展的元信息位）。
        open_doc = _minimal_doc()
        open_doc["bogus"] = 1
        self.assertEqual(schema_check.validate_doc(open_doc), [])

    def test_legacy_document_fails_strict_schema(self):
        doc = _load_legacy(PLAIN_FIXTURE)

        errors = schema_check.validate_doc(doc)

        paths = [e["path"] for e in errors]
        self.assertTrue(paths, "历史样本今天必须校验失败（Spec §7 V5）")
        self.assertIn("$.version", paths)
        self.assertIn("$.images", paths)

        # 老样本只许因为「缺 1.0 新增的必填键」而红，**不许**因为未知键而红。
        # 这条把 R1 的裁定钉住：$defs 里设了 additionalProperties: false 的层级
        # 必须声明样本里真实出现的每一个键，否则契约对今天的数据就是废的。
        for fixture in (PLAIN_FIXTURE, AUTO_LAYOUT_FIXTURE):
            with self.subTest(fixture=fixture):
                unknown = [e for e in schema_check.validate_doc(
                    _load_legacy(fixture)) if e["message"] == "unknown key"]
                self.assertEqual(unknown, [], unknown)

    def test_non_object_document_is_reported(self):
        # 根节点有 "type": "object"，所以整份文档类型不对时错误报在 ``$`` 上；
        # 否则 ``required`` / ``properties`` 只对 dict 生效，会静默返回 []。
        for doc in ([], "x", 3):
            with self.subTest(doc=doc):
                errors = schema_check.validate_doc(doc)
                self.assertEqual(len(errors), 1, errors)
                self.assertEqual(errors[0]["path"], "$")
                self.assertIn("object", errors[0]["message"])

    def test_page_missing_required_key_is_reported(self):
        # card.spec 就是消费端（JS 渲染器）拿到的那份 PageSpec。
        # PageSpec.from_dict（loop/models.py:70-74）对这 5 个键是硬取，
        # 契约必须同样硬要，否则会放过一份结构性残缺的 spec。
        doc = _minimal_doc()
        del doc["cards"][0]["spec"]["chart_key"]

        errors = schema_check.validate_doc(doc)

        self.assertEqual(len(errors), 1, errors)
        self.assertEqual(errors[0]["path"], "$.cards[0].spec.chart_key")
        self.assertEqual(errors[0]["message"], "required key is missing")

    def test_unsupported_keywords_does_not_descend_into_opaque_values(self):
        # enum / default 的「取值」是数据不是关键字：里面出现什么键都无所谓。
        inline = {"$defs": {"element": {"type": "object",
                                        "default": {"kind": "thermometer"},
                                        "enum": [{"kind": "x"}]}}}
        self.assertEqual(schema_check.unsupported_keywords(inline), [])

    def test_unsupported_keywords_rejects_cross_document_ref(self):
        # $ref 不是「在集合里就免检」：前缀必须自己校验，只有 #/$defs/ 是允许形态。
        bad = {"$defs": {"element": {"$ref": "other.json#/x"}}}
        self.assertEqual(schema_check.unsupported_keywords(bad),
                         ["$.$defs.element.$ref"])

        good = {"$defs": {"element": {"$ref": "#/$defs/scale"}}}
        self.assertEqual(schema_check.unsupported_keywords(good), [])


if __name__ == "__main__":
    unittest.main()
