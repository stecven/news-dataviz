"""P1 Task 7：回归复判与交付（本计划唯一的「几何一个字节没变」硬判据）。

对应验收：

* 几何逐份与基线一致（Step 3 重新生成之后才有意义）
                     → ``test_every_demo_layout_regenerates_geometrically_identical``
* 重新生成后的文档过严格 schema、``version == "1.0"``、``theme`` 非空，
  **并且盘上文件的原始字节就带着这两样**（Step 0 落盘接线的判据）
                     → ``test_regenerated_documents_are_contract_conformant``
* 卡片内每个 text 元素重新生成后仍带非空 ``lines`` 与正数 ``font_pt``
                     → ``test_card_text_elements_carry_lines_and_font_pt_after_regeneration``

两条**刻意**的写法，改之前先读 ``task-7-brief.md`` 的 T7-A / T7-B：

1. 几何指纹只比 ``tests/contract_fixtures.fingerprint_sha`` 抽出来的**几何**
   （画布 / 卡片框 / 元素框 / 整版块 / 插图），``version`` / ``theme`` /
   ``lines`` / ``font_pt`` 这些本计划新增的东西增减都**不该**让它变 —— 所以
   「重新生成了带两键的产物」与「几何没变」可以同时成立，且这正是 T7-A 的
   前提（接 ``dump_layout`` 不改任何几何数字）。
2. 第二条要断言**盘上字节**而不只是 ``dump_layout`` 的返回值：返回值只证明
   「写出侧有能力补两键」（Task 4 / Task 6 已各自钉过），证明不了「生产路径
   真的走了它」。``out/demo`` 是 gitignore 的，fresh clone 上没有 —— 三个用例
   在目录缺失时 ``skipTest``，与 ``tests/test_step31_contract_fixtures.py`` 同
   口径（那边断的也是 ``out/demo`` 的盘上字节）。

``EXPECTED_MIN_TESTS`` 是**全量**基线（719 + 本文件 3 个 method = 722），记在
这里供交付报告核对；``EXPECTED_CONTRACT_VERSION`` 则被下面的断言直接使用。
"""
import json
import os
import unittest

from loop.contract import dump_layout, load_layout
from loop.schema_check import validate_doc
from tests import contract_fixtures as cf

#: 全量基线：Task 6 关闭时 719，加本文件 3 个 test method = 722。
EXPECTED_MIN_TESTS = 722

#: 1.0 契约版本（``loop.contract.CONTRACT_VERSION`` 的字面值，独立钉一份）。
EXPECTED_CONTRACT_VERSION = "1.0"


def _load_disk(rel: str) -> dict:
    """读 ``out/demo/**`` 里一份产物的**原始盘上字节**（不经任何宽松读回）。"""
    with open(os.path.join(cf.REPO_ROOT, rel), encoding="utf-8") as fh:
        return json.load(fh)


class TestContractDelivery(unittest.TestCase):

    def setUp(self):
        if not os.path.isdir(cf.DEMO_ROOT):
            self.skipTest("out/demo 未生成（fresh clone；先跑 scripts/build_*_demo.py）")
        self.paths = cf.demo_layout_paths()
        self.assertTrue(self.paths, "out/demo 存在时不该一份 pagelayout 都没有")

    def test_every_demo_layout_regenerates_geometrically_identical(self):
        """本计划唯一的「几何一个字节没变」判据（Step 3 之后跑才有意义）。

        基线是 ``fb21187`` 重定的「当前 main 代码重生成的 11 份产物指纹」，
        所以它红了只可能意味着一件事：真碰了 ``loop/layout.py`` 或
        ``loop/models.py`` 的几何计算。**红了不许重写基线**（T7-B / R30）。
        """
        baseline = cf.load_baseline()
        for rel in self.paths:
            with self.subTest(path=rel):
                self.assertIn(rel, baseline, "基线未覆盖这份产物")
                self.assertEqual(cf.fingerprint_sha(_load_disk(rel)),
                                 baseline[rel]["sha256"], rel)

    def test_regenerated_documents_are_contract_conformant(self):
        """逐份：读得进来 → 写得出去 → 过严格 schema，且**盘上字节**已带两键。"""
        for rel in self.paths:
            with self.subTest(path=rel):
                read = load_layout(os.path.join(cf.REPO_ROOT, rel))
                doc = dump_layout(read.layout)
                self.assertEqual(validate_doc(doc), [])
                self.assertEqual(doc["version"], EXPECTED_CONTRACT_VERSION)
                self.assertTrue(doc["theme"], "$.theme 不该为空")

                # 盘上字节：重新生成之后这两条必须同时成立，否则说明 Step 0
                # 的落盘接线没生效（写出侧有能力 ≠ 生产路径走了它）。
                on_disk = _load_disk(rel)
                self.assertEqual(on_disk.get("version"), EXPECTED_CONTRACT_VERSION,
                                 f"{rel}: 盘上 version 仍是 {on_disk.get('version')!r}")
                self.assertTrue(on_disk.get("theme"),
                                f"{rel}: 盘上 theme 仍是 {on_disk.get('theme')!r}")

    def test_card_text_elements_carry_lines_and_font_pt_after_regeneration(self):
        """每张卡片的每个 text 元素都带非空 ``lines`` 与正数 ``font_pt``。

        这是 Spec §4 D10 落到**盘上**的判据：三个渲染端照抄 ``lines`` /
        ``font_pt`` 的前提是它们真的被写进了产物。
        """
        seen = 0
        for rel in self.paths:
            doc = _load_disk(rel)
            for card in doc.get("cards") or []:
                for el in (card.get("spec") or {}).get("elements") or []:
                    if el.get("type") != "text":
                        continue
                    seen += 1
                    with self.subTest(path=rel, card=card.get("name"),
                                      element=el.get("id")):
                        self.assertIsInstance(el.get("lines"), list)
                        self.assertTrue(el["lines"], "lines 不该是空 list")
                        self.assertIsInstance(el.get("font_pt"), (int, float))
                        self.assertGreater(el["font_pt"], 0)
        self.assertGreater(seen, 0, "11 份产物里至少该有一个 text 元素")


if __name__ == "__main__":
    unittest.main()
