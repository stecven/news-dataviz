"""P1 Task 3：``pagelayout.json`` 读回入口（宽松）与四个 ``from_dict``。

对应验收：

* 老样本缺 ``version`` / ``images`` 也能读，缺什么降级成 warning → ``test_legacy_plain_layout_reads_without_raising``
* 卡片、整版块一个不少，卡片内 spec 完整                       → ``test_legacy_auto_layout_reads_all_cards_and_blocks``
* ``from_dict`` 是 ``to_dict`` 的左逆（不丢键、幂等）           → ``test_roundtrip_superset_and_idempotent``
* 1.0 新增可空键在输出里存在且为 ``None``                       → ``test_new_nullable_keys_present_with_none``
* 未知图元键降级成 warning，不抛 ``TypeError``                  → ``test_unknown_element_key_becomes_warning_not_crash``
* 读回**不**做页面级平移、不重新取整                            → ``test_geometry_is_not_translated_on_read``

夹具路径一律取自 ``tests.contract_fixtures.LEGACY_DIR``，不硬编码目录。
"""
import json
import os
import unittest

from loop.contract import load_layout, load_layout_json
from loop.layout import PageLayoutSpec
from tests.contract_fixtures import LEGACY_DIR

#: 两份入库夹具（``out/`` 不入库，它们才是长期可复现的证据）。
AUTO_LAYOUT_FIXTURE = "auto_layout.pagelayout.json"
PLAIN_FIXTURE = "_plain.pagelayout.json"


def _load(fixture: str) -> dict:
    with open(os.path.join(LEGACY_DIR, fixture), encoding="utf-8") as fh:
        return json.load(fh)


def _assert_superset(case: unittest.TestCase, sub, sup, path: str = "$") -> None:
    """``sub`` 里出现的**每个**键，``sup`` 必须存在且递归等值。

    读回不许丢字段：老文档写出来的东西，再读回来必须原样还在。
    """
    if isinstance(sub, dict):
        case.assertIsInstance(sup, dict, path)
        for key, value in sub.items():
            case.assertIn(key, sup, f"{path}.{key} 读回后丢了")
            _assert_superset(case, value, sup[key], f"{path}.{key}")
    elif isinstance(sub, list):
        case.assertIsInstance(sup, list, path)
        case.assertEqual(len(sub), len(sup), f"{path} 长度变了")
        for i, (a, b) in enumerate(zip(sub, sup)):
            _assert_superset(case, a, b, f"{path}[{i}]")
    else:
        case.assertEqual(sub, sup, path)


class TestContractReadEntry(unittest.TestCase):

    def test_legacy_plain_layout_reads_without_raising(self):
        result = load_layout(os.path.join(LEGACY_DIR, PLAIN_FIXTURE))
        self.assertIsNone(result.version)
        self.assertTrue(any("images" in w for w in result.warnings),
                        result.warnings)
        self.assertTrue(any("version" in w for w in result.warnings),
                        result.warnings)

    def test_legacy_auto_layout_reads_all_cards_and_blocks(self):
        layout = load_layout(os.path.join(LEGACY_DIR, AUTO_LAYOUT_FIXTURE)).layout
        self.assertEqual(len(layout.cards), 2)
        self.assertEqual(len(layout.blocks), 4)
        for card in layout.cards:
            self.assertTrue(card.spec.elements, card.name)
        card = layout.card("heat_ratio_top5")
        self.assertEqual(card.card.kind, "thermometer")
        self.assertEqual(card.w_in, 8.937504)

    def test_roundtrip_superset_and_idempotent(self):
        for fixture in (PLAIN_FIXTURE, AUTO_LAYOUT_FIXTURE):
            with self.subTest(fixture=fixture):
                doc = _load(fixture)
                d1 = PageLayoutSpec.from_dict(doc).to_dict()
                _assert_superset(self, doc, d1)
                self.assertEqual(PageLayoutSpec.from_dict(d1).to_dict(), d1)

    def test_new_nullable_keys_present_with_none(self):
        d1 = PageLayoutSpec.from_dict(_load(AUTO_LAYOUT_FIXTURE)).to_dict()
        self.assertIsNone(d1["version"])
        for card in d1["cards"]:
            for element in card["spec"]["elements"]:
                for key in ("lines", "font_pt", "editable"):
                    self.assertIn(key, element)
                    self.assertIsNone(element[key])

    def test_unknown_element_key_becomes_warning_not_crash(self):
        doc = _load(AUTO_LAYOUT_FIXTURE)
        doc["cards"][0]["spec"]["elements"][0]["beep"] = 1
        result = load_layout_json(doc)
        self.assertTrue(any("beep" in w for w in result.warnings),
                        result.warnings)

    def test_geometry_is_not_translated_on_read(self):
        layout = load_layout(os.path.join(LEGACY_DIR, AUTO_LAYOUT_FIXTURE)).layout
        card = layout.card("heat_ratio_top5")
        self.assertEqual(card.x_in, 0.4)
        self.assertEqual(card.y_in, 2.3875)
        frames = [e for e in card.spec.elements if e.role == "frame"]
        self.assertTrue(frames)
        self.assertEqual(frames[0].x_in, 0.0)
        self.assertEqual(frames[0].y_in, 0.0)

        xs = [c.x_in for c in layout.cards]
        xs += [b.x_in for b in layout.blocks]
        xs += [i.x_in for i in layout.images]
        for c in layout.cards:
            xs += [e.x_in for e in c.spec.elements]
        self.assertNotEqual(min(xs), 0.4,
                            "整版最小 x 被平移到了左边距，说明读回时动了几何")


if __name__ == "__main__":
    unittest.main()
