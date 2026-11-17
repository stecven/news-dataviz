"""P1 Task 1：老样本几何指纹基线。

对应验收：

* 指纹对同一文档是确定的                       → ``test_fingerprint_is_deterministic``
* 指纹只看几何，新增外观/元数据字段不动它        → ``test_fingerprint_ignores_presentation_fields``
* 基线恰好覆盖 ``out/demo`` 下每一份 pagelayout → ``test_baseline_covers_every_demo_layout``
* 盘上每份文档的指纹与基线逐字节一致             → ``test_fingerprint_matches_baseline_for_every_document``
* 两份夹具可读、无版本号、结构如任务书所述         → ``test_legacy_fixture_documents_are_readable_json_and_versionless``

读 ``out/demo`` 的用例在目录缺失（fresh clone）时 ``skipTest``；
读已入库夹具的用例**不**跳过 —— 它是夹具本身的判据。
"""
import copy
import json
import os
import unittest

from tests import contract_fixtures as cf

#: 两份入库夹具（``out/`` 不入库，它们才是长期可复现的证据）。
AUTO_LAYOUT_FIXTURE = "auto_layout.pagelayout.json"
PLAIN_FIXTURE = "_plain.pagelayout.json"


def _load(fixture: str) -> dict:
    with open(os.path.join(cf.LEGACY_DIR, fixture), encoding="utf-8") as fh:
        return json.load(fh)


class TestLegacyGeometryFingerprints(unittest.TestCase):

    def test_fingerprint_is_deterministic(self):
        doc = _load(AUTO_LAYOUT_FIXTURE)
        self.assertEqual(cf.fingerprint_sha(doc), cf.fingerprint_sha(doc))

    def test_fingerprint_ignores_presentation_fields(self):
        doc = _load(AUTO_LAYOUT_FIXTURE)
        before = cf.fingerprint_sha(doc)

        # 本计划要新增的外观与元数据字段：塞进去指纹必须纹丝不动。
        dressed = copy.deepcopy(doc)
        dressed["version"] = "1.0"
        dressed["theme"] = {"palette": {}}
        for card in dressed.get("cards") or []:
            for el in (card.get("spec") or {}).get("elements") or []:
                el["lines"] = ["x"]
                el["font_pt"] = 9.0
                el["editable"] = True
        self.assertEqual(cf.fingerprint_sha(dressed), before)

        # 几何必须是指纹的敏感项：挪动一个元素 0.001 英寸（任务书裁定：
        # 不用 1e-9，那会被 round(...,6) 抹平，测试就成了假绿）。
        moved = copy.deepcopy(doc)
        target = None
        for card in moved.get("cards") or []:
            for el in (card.get("spec") or {}).get("elements") or []:
                if el.get("x_in") is not None:
                    target = el
                    break
            if target is not None:
                break
        self.assertIsNotNone(target, "夹具里应当有带 x_in 的元素")
        original_x = target["x_in"]
        target["x_in"] = round(original_x + 0.001, 6)
        self.assertNotEqual(target["x_in"], original_x, "扰动必须是可见的")
        self.assertNotEqual(cf.fingerprint_sha(moved), before)

    def test_baseline_covers_every_demo_layout(self):
        if not os.path.isdir(cf.DEMO_ROOT):
            self.skipTest("out/demo 未生成")
        self.assertEqual(set(cf.load_baseline()), set(cf.demo_layout_paths()))

    def test_fingerprint_matches_baseline_for_every_document(self):
        if not os.path.isdir(cf.DEMO_ROOT):
            self.skipTest("out/demo 未生成")
        baseline = cf.load_baseline()
        paths = cf.demo_layout_paths()
        self.assertTrue(paths, "out/demo 存在时不该一份 pagelayout 都没有")
        for rel in paths:
            with open(os.path.join(cf.REPO_ROOT, rel), encoding="utf-8") as fh:
                doc = json.load(fh)
            self.assertEqual(cf.fingerprint_sha(doc), baseline[rel]["sha256"], rel)

    def test_legacy_fixture_documents_are_readable_json_and_versionless(self):
        auto = _load(AUTO_LAYOUT_FIXTURE)
        plain = _load(PLAIN_FIXTURE)
        for doc in (auto, plain):
            self.assertIsNone(doc.get("version"))
        self.assertNotIn("images", plain)
        self.assertEqual(len(auto["cards"]), 2)
        self.assertEqual(len(auto["blocks"]), 4)


if __name__ == "__main__":
    unittest.main()
