"""Task 4：编排器 build_loop 的端到端验收。

覆盖：产物齐全、PageSpec 往返等价、db 只读、override 生效且不写库、
改数据全组重算（反削顶回归）、量程说明与真值文本一致、以及用户
m00260 约束 #2 的两场景 V_max 11→14 / 10.0 柱 2.727→2.143 in。
"""
import hashlib
import json
import os
import unittest

from pptx.util import Inches

from tests.scratch import mkdtemp
from loop.models import PageSpec
from loop.data_source import DB_PATH
from loop.build_loop import build_loop
from loop.render import render_pptx
from loop.verify import read_shapes


def _sha(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


class TestBuildLoop(unittest.TestCase):
    def test_base_outputs_exist_and_spec_roundtrips(self):
        r = build_loop(mkdtemp())
        for k in ("pagespec", "pptx", "png"):
            self.assertTrue(os.path.getsize(r[k]) > 0, k)
        with open(r["pagespec"], encoding="utf-8") as f:
            d = json.load(f)
        self.assertEqual(PageSpec.from_dict(d).to_dict(), r["spec"].to_dict())
        self.assertEqual(d["scale"]["v_max"], 11.0)
        self.assertEqual(len(d["elements"]), 39)   # 37 内容 + frame + title_band

    def test_db_sha256_unchanged_after_full_loop(self):
        before = _sha(DB_PATH)
        build_loop(mkdtemp())
        self.assertEqual(_sha(DB_PATH), before)

    def test_override_is_in_memory_only_and_db_sha256_unchanged(self):
        before = _sha(DB_PATH)
        r = build_loop(mkdtemp(), overrides={1: 12.0})
        self.assertEqual(_sha(DB_PATH), before)
        self.assertEqual(r["spec"].scale.v_max, 14.0)
        self.assertEqual(_sha(DB_PATH), before)

    def test_override_repaint_changes_all_liquid_emus(self):
        b = build_loop(mkdtemp())
        o = build_loop(mkdtemp(), overrides={1: 12.0})
        bs = read_shapes(b["pptx"])
        os_ = read_shapes(o["pptx"])
        self.assertEqual(o["spec"].scale.v_max, 14.0)
        self.assertNotEqual(bs["liquid_1"]["height"], os_["liquid_1"]["height"])
        self.assertAlmostEqual(os_["liquid_1"]["height"],
                               Inches(3.0 * 12.0 / 14.0), delta=1)
        self.assertNotEqual(bs["liquid_2"]["height"], os_["liquid_2"]["height"])
        self.assertAlmostEqual(os_["liquid_2"]["height"],
                               Inches(3.0 * 3.0 / 14.0), delta=1)

    # 审查发现：pagespec.json 只写不读，"可编辑源" 名不副实。
    # 验收：从磁盘 JSON 读回、人工改一个数值、经 render_from_spec 重绘，
    # 液柱 EMU 必须跟着变。
    def test_pagespec_json_can_be_edited_and_rerendered(self):
        from loop.build_loop import render_from_spec
        r = build_loop(mkdtemp())
        with open(r["pagespec"], encoding="utf-8") as f:
            d = json.load(f)
        for e in d["elements"]:
            if e["id"] == "liquid_1":
                e["h_in"] = 1.5                      # 人改规格
                e["y_in"] = 4.30 - 1.5
        edited = PageSpec.from_dict(d)
        out2 = os.path.join(os.path.dirname(r["pptx"]), "edited.pptx")
        render_pptx(edited, out2)
        self.assertEqual(read_shapes(out2)["liquid_1"]["height"], Inches(1.5))
        self.assertEqual(len(read_shapes(out2)), 39)
        # 公开入口：改完的规格走 render_from_spec 也应产出同尺寸 PPTX + 预览图
        out3 = mkdtemp(prefix="rerender-")
        a = render_from_spec(edited, out3)
        self.assertEqual(read_shapes(a["pptx"])["liquid_1"]["height"], Inches(1.5))
        self.assertGreater(os.path.getsize(a["png"]), 1000)

    def test_scale_vmax_text_visible_in_spec_and_pptx(self):
        r = build_loop(mkdtemp())
        texts = "\n".join(s["text"] for s in read_shapes(r["pptx"]).values())
        self.assertIn("满格约 11倍", texts)
        self.assertIn("10倍", texts)
        values = [e["text"] for e in r["spec"].to_dict()["elements"]
                  if e["role"] == "value"]
        self.assertEqual(values, ["10倍", "3倍", "3倍", "3倍", "3倍"])

    # 用户 m00260 追加约束 #2：把最大值推到 12.0，V_max 必须 11→14，
    # 且「未改动、仍为 10.0」的那根柱必须按新量程缩到 2.143 in。
    # 两场景隔离：{1:12.0} 证明范围扩展；{2:12.0} 让 seq=1 保持 10.0
    # 以验证 2.727→2.143（同一 override 下无法两者兼得，见计划 Ruling #2）。
    def test_vmax_11_to_14_and_10x_bar_rescales_to_2_143(self):
        b = build_loop(mkdtemp())
        r1 = build_loop(mkdtemp(), overrides={1: 12.0})
        r2 = build_loop(mkdtemp(), overrides={2: 12.0})
        self.assertEqual(b["spec"].scale.v_max, 11.0)
        self.assertEqual(r1["spec"].scale.v_max, 14.0)
        self.assertEqual(r2["spec"].scale.v_max, 14.0)
        bh = read_shapes(b["pptx"])["liquid_1"]["height"]
        h1 = read_shapes(r1["pptx"])["liquid_1"]["height"]
        h2 = read_shapes(r2["pptx"])["liquid_1"]["height"]
        self.assertAlmostEqual(bh, Inches(3.0 * 10.0 / 11.0), delta=1)   # 2.727 in
        self.assertAlmostEqual(h1, Inches(3.0 * 12.0 / 14.0), delta=1)   # 2.571 in
        self.assertAlmostEqual(h2, Inches(3.0 * 10.0 / 14.0), delta=1)   # 2.143 in


if __name__ == "__main__":
    unittest.main()
