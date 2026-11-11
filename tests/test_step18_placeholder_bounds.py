"""步骤 18：占位图分支的边界兜底（用户 m04449）。

背景：占位图分支是流水线里**唯一**一条既不走约束求解、也不走 `validate_spec`
的路径。`PLACEHOLDER_TOP_IN = 3.0` 是绝对常量，画布从 6 in 变 4 in 时
底部 5.20 溢出 1.20 in，而 status 仍是 no_applicable、不报错。

本文件的验收口径（用户 m04449 原文）：H=4.0 / H=3.0 下「要么产出物中 image
元素全在画布内、要么明确报错」，**不能出现 status 成功但画面溢出**。

因此每个尺寸都做三层断言：
1. 元素盒在画布内（几何）；
2. 落盘的 pagespec.json 与 PPTX 里读回的盒也在画布内（产物，不是内存对象）；
3. 调整是否发生、发生时有记录（不静默）。
"""
import json
import os
import unittest

from loop.pipeline import (_fit_placeholder, _is_inside,
                           _build_fallback_spec, run_selected,
                           PLACEHOLDER_TOP_IN, PLACEHOLDER_W_IN,
                           PLACEHOLDER_H_IN, FIT_MARGIN_IN)
from loop.asset_lookup import find_fallback_assets
from loop.verify import read_shapes

SEM = "占比构成"
SIX = [10, 3, 2, 2, 2, 1]          # 6 项占比 → 必然 no_applicable
EMU = 914400


def _tmp():
    from tests.scratch import mkdtemp as _mk
    return _mk("s18_")


def _elem_box(doc):
    """占位图（image）元素在**落盘坐标**里的盒。

    用户 m04818 之后占位图也是一张带框的卡片：doc["elements"] 里除 image 外
    还有 frame / title_band / title / scale_note 四个 chrome 元素，画布尺寸也
    由「内容 bbox + 内边距」决定，所以这里按 type 取图元、按 frame_bbox 取画布。
    """
    imgs = [e for e in doc["elements"] if e["type"] == "image"]
    assert len(imgs) == 1, f"占位图分支应只有一张图，实际 {len(imgs)}"
    e = imgs[0]
    return (e["x_in"], e["y_in"], e["w_in"], e["h_in"])


def _canvas(doc):
    """卡片画布尺寸（= frame_bbox 的宽高，用户 m04888 的设计）。"""
    fb = doc["frame_bbox"]
    return (fb[2], fb[3])


def _unframed(spec_or_doc):
    """拆框回求解坐标，用于断言「fit 之后、包框之前」的盒。"""
    from loop.models import PageSpec
    from loop.frame import unwrap
    spec = (spec_or_doc if isinstance(spec_or_doc, PageSpec)
            else PageSpec.from_dict(spec_or_doc))
    return unwrap(spec)


def _inside_box(box, w, h):
    x, y, bw, bh = box
    return (x >= -1e-9 and y >= -1e-9
            and x + bw <= w + 1e-9 and y + bh <= h + 1e-9)


class TestGeometryHelpers(unittest.TestCase):
    """俩 helper 是这次补丁的核心，先单测它们，别让 pipeline 的集成测试背锅。"""

    def _el(self, x, y, w=2.2, h=2.2):
        asset = find_fallback_assets()[0]
        spec = _unframed(_build_fallback_spec(asset, "t", 100.0, 100.0))  # 大画布
        e = next(x for x in spec.elements if x.type == "image")
        e.x_in, e.y_in, e.w_in, e.h_in = x, y, w, h
        return e

    def test_inside_detects_four_edges(self):
        self.assertTrue(_is_inside(self._el(1, 1), 10, 6))
        self.assertFalse(_is_inside(self._el(-0.1, 1), 10, 6))     # 左
        self.assertFalse(_is_inside(self._el(1, -0.1), 10, 6))     # 上
        self.assertFalse(_is_inside(self._el(8.9, 1), 10, 6))      # 右
        self.assertFalse(_is_inside(self._el(1, 4.9), 10, 6))      # 下

    def test_inside_on_exact_edge_is_inside(self):
        # 贴着边界不算越界（与 C1 的 +1e-9 容差同口径）
        self.assertTrue(_is_inside(self._el(0, 0), 2.2, 2.2))
        self.assertTrue(_is_inside(self._el(10 - 2.2, 6 - 2.2), 10, 6))

    def test_fit_leaves_inside_element_untouched(self):
        el = self._el(3.9, 3.0)
        rec = _fit_placeholder(el, 10.0, 6.0)
        self.assertFalse(rec["adjusted"])
        self.assertEqual((el.x_in, el.y_in, el.w_in, el.h_in),
                         (3.9, 3.0, 2.2, 2.2))
        # before == after，调用方能靠这个判断「没被动过」
        self.assertEqual(rec["before"], rec["after"])

    def test_fit_shrinks_and_centers_on_short_canvas(self):
        el = self._el(3.9, PLACEHOLDER_TOP_IN)
        rec = _fit_placeholder(el, 10.0, 4.0)
        self.assertTrue(rec["adjusted"])
        self.assertTrue(_is_inside(el, 10.0, 4.0))
        # 水平仍然居中、垂直也居中（缩后放到画布正中）
        self.assertAlmostEqual(el.x_in + el.w_in / 2, 5.0, places=6)
        self.assertAlmostEqual(el.y_in + el.h_in / 2, 2.0, places=6)
        # 等比：w/h 比例不变
        self.assertAlmostEqual(el.w_in / el.h_in, 1.0, places=6)

    def test_fit_respects_margin(self):
        el = self._el(3.9, 3.0)
        _fit_placeholder(el, 10.0, 3.0, margin_in=FIT_MARGIN_IN)
        self.assertGreaterEqual(el.y_in, FIT_MARGIN_IN - 1e-9)
        self.assertLessEqual(el.y_in + el.h_in, 3.0 - FIT_MARGIN_IN + 1e-9)

    def test_fit_raises_when_canvas_smaller_than_margins(self):
        el = self._el(0, 0)
        with self.assertRaises(ValueError) as cm:
            _fit_placeholder(el, 0.8, 6.0)   # 2*0.5 = 1.0 > 0.8
        self.assertIn("cannot hold a placeholder", str(cm.exception))


class TestThreeCanvases(unittest.TestCase):
    """H=6 / 4 / 3 三档端到端。这是 m04449 的主验收。"""

    def _run(self, h):
        out = _tmp()
        r = run_selected(values=SIX, semantic=SEM, out_root=out,
                         group_name=f"h{int(h)}", height_in=h)
        return r, out

    def _read_doc(self, r):
        with open(r["pagespec"], encoding="utf-8") as f:
            return json.load(f)

    def test_h6_is_unchanged_regression(self):
        """H=6 上占位图不被挪动：拆框坐标仍是 (3.9, 3.0, 2.2, 2.2)，无调整。"""
        r, _ = self._run(6.0)
        doc = self._read_doc(r)
        self.assertFalse(r["placeholder_fit"]["adjusted"])
        self.assertEqual(r["placeholder_fit"]["before"], [3.9, 3.0, 2.2, 2.2])
        self.assertEqual(r["placeholder_fit"]["after"], [3.9, 3.0, 2.2, 2.2])
        # 拆框后（求解坐标）图元原样
        e = next(x for x in _unframed(doc).elements if x.type == "image")
        self.assertEqual((e.x_in, e.y_in, e.w_in, e.h_in), (3.9, 3.0, 2.2, 2.2))
        # 落盘画布 = 内容 bbox + 2×pad（用户 m04888 的 A 方案）
        w, h = _canvas(doc)
        self.assertAlmostEqual(w, 2.2 + 2 * 0.3, places=6)
        self.assertAlmostEqual(h, (1.45 - 0.0) + 2.2 + 0.3, places=6)
        self.assertTrue(_inside_box(_elem_box(doc), w, h))
        self.assertTrue(os.path.exists(r["preview"]))

    def test_h4_element_and_artifact_are_inside(self):
        r, _ = self._run(4.0)
        doc = self._read_doc(r)
        self.assertTrue(r["placeholder_fit"]["adjusted"])
        # 求解坐标里（包框前的 10×4 画布）必须真的落进去了
        e = next(x for x in _unframed(doc).elements if x.type == "image")
        self.assertTrue(_inside_box((e.x_in, e.y_in, e.w_in, e.h_in), 10.0, 4.0),
                        f"H=4 的 image 盒仍越界 {[e.x_in, e.y_in, e.w_in, e.h_in]}")
        # 产物层：PPTX 里读回的盒也必须落在卡片画布内
        w, h = _canvas(doc)
        shp = read_shapes(r["pptx"])["placeholder_1"]
        self.assertLessEqual((shp["top"] + shp["height"]) / EMU, h + 1e-6)
        self.assertLessEqual((shp["left"] + shp["width"]) / EMU, w + 1e-6)
        self.assertGreaterEqual(shp["top"] / EMU, -1e-6)

    def test_h3_element_and_artifact_are_inside(self):
        r, _ = self._run(3.0)
        doc = self._read_doc(r)
        e = next(x for x in _unframed(doc).elements if x.type == "image")
        self.assertTrue(_inside_box((e.x_in, e.y_in, e.w_in, e.h_in), 10.0, 3.0),
                        "H=3 的 image 盒仍越界")
        w, h = _canvas(doc)
        shp = read_shapes(r["pptx"])["placeholder_1"]
        self.assertLessEqual((shp["top"] + shp["height"]) / EMU, h + 1e-6)
        self.assertGreaterEqual(shp["top"] / EMU, -1e-6)

    def test_short_canvases_report_the_adjustment_not_silently(self):
        """调整必须留痕：`placeholder_fit` 有 before/after 且 adjusted=True。"""
        for h in (4.0, 3.0):
            with self.subTest(h=h):
                r, _ = self._run(h)
                fit = r["placeholder_fit"]
                self.assertTrue(fit["adjusted"], f"H={h} 没记录调整")
                self.assertEqual(fit["before"], [3.9, PLACEHOLDER_TOP_IN,
                                                 PLACEHOLDER_W_IN,
                                                 PLACEHOLDER_H_IN])
                self.assertNotEqual(fit["before"], fit["after"])
                self.assertIn("越界", r["message"])
                self.assertIn("缩进", r["message"])
                # 落盘的 layout 里也有一份，读 pagespec 的人不会漏掉
                doc = self._read_doc(r)
                self.assertIn("placeholder_fit", doc["layout"])
                self.assertTrue(doc["layout"]["placeholder_fit"]["adjusted"])

    def test_status_stays_no_applicable_on_all_three(self):
        """兜底不改选型结论：三档都是 no_applicable，不静默变成 rendered。"""
        for h in (6.0, 4.0, 3.0):
            with self.subTest(h=h):
                r, _ = self._run(h)
                self.assertEqual(r["status"], "no_applicable")
                self.assertIsNone(r["selected_template"])


class TestNoSilentOverflow(unittest.TestCase):
    """变异测试：把这次补丁拆掉，必须变红。

    做法不是改源码（那会污染工作区），而是构造「没有 fit」的规格，
    再确认产物层检查确实能抓到越界——即测试的判据本身有效。
    """

    def test_unfitted_h4_spec_really_overflows(self):
        """反证：跳过 _fit_placeholder 的同一份盒，确实越界 1.20 in。"""
        asset = find_fallback_assets()[0]
        spec = _unframed(_build_fallback_spec(asset, "t", 10.0, 6.0))
        e = next(x for x in spec.elements if x.type == "image")
        self.assertTrue(_is_inside(e, 10.0, 6.0))
        # 把画布改成 4 in，不做 fit —— 这就是补丁前的状态
        self.assertFalse(_is_inside(e, 10.0, 4.0))
        self.assertAlmostEqual(e.y_in + e.h_in - 4.0, 1.2, places=6)

    def test_fit_is_actually_called_by_build_fallback_spec(self):
        """若 `_build_fallback_spec` 删掉 fit 调用，H=4 会露出 5.2 的底。"""
        asset = find_fallback_assets()[0]
        spec = _build_fallback_spec(asset, "t", 10.0, 4.0)
        # 返回的是包框后的卡片；fit 记录在 layout 里，几何断言要拆框看
        bare = _unframed(spec)
        e = next(x for x in bare.elements if x.type == "image")
        self.assertTrue(_is_inside(e, 10.0, 4.0),
                        f"build_fallback_spec 在 H=4 上产出了越界盒 "
                        f"({e.x_in},{e.y_in},{e.w_in},{e.h_in})")
        self.assertAlmostEqual(e.y_in + e.h_in, 3.1, places=6)
        fit = spec.layout["placeholder_fit"]
        self.assertTrue(fit["adjusted"])

    def test_no_canvas_size_produces_status_ok_with_overflow(self):
        """扫一圈画布高度：任何一档都不允许「status 成功但盒越界」。"""
        for h in (6.0, 5.0, 4.5, 4.0, 3.5, 3.0, 2.5, 2.0, 1.5):
            with self.subTest(h=h):
                out = _tmp()
                r = run_selected(values=SIX, semantic=SEM, out_root=out,
                                 group_name=f"sweep{str(h).replace('.', '_')}",
                                 height_in=h)
                with open(r["pagespec"], encoding="utf-8") as f:
                    doc = json.load(f)
                box = _elem_box(doc)
                cw, ch = _canvas(doc)
                self.assertTrue(_inside_box(box, cw, ch),
                                f"h={h}: 盒 {box} 越界卡片 {cw}×{ch}")
                if h < 2.0 - 2 * FIT_MARGIN_IN:
                    self.fail("这一档本该报错，却没报——检查画布过小分支")

    def test_too_small_canvas_raises_instead_of_pretending(self):
        """画布连 2×margin 都放不下时，明确报错，不假装成功。"""
        with self.assertRaises(ValueError) as cm:
            out = _tmp()
            run_selected(values=SIX, semantic=SEM, out_root=out,
                         group_name="tiny", height_in=0.9)
        self.assertIn("cannot hold a placeholder", str(cm.exception))


class TestOtherBranchesUntouched(unittest.TestCase):
    """范围锁死自查：另两个分支的产物不该被这次补丁影响。"""

    def test_thermometer_branch_has_no_placeholder_fit(self):
        out = _tmp()
        r = run_selected(chart_key="heat_ratio_top5", semantic="比较大小",
                         out_root=out, group_name="thermo")
        self.assertEqual(r["status"], "rendered")
        self.assertNotIn("placeholder_fit", r)
        with open(r["pagespec"], encoding="utf-8") as f:
            doc = json.load(f)
        self.assertNotIn("placeholder_fit", doc["layout"])
        self.assertFalse(any(e["type"] == "image" for e in doc["elements"]))

    def test_semicircle_branch_has_no_placeholder_fit(self):
        out = _tmp()
        r = run_selected(chart_key="heat_age", semantic="占比构成",
                         out_root=out, group_name="semi")
        self.assertEqual(r["status"], "rendered")
        self.assertNotIn("placeholder_fit", r)
        with open(r["pagespec"], encoding="utf-8") as f:
            doc = json.load(f)
        self.assertNotIn("placeholder_fit", doc["layout"])


if __name__ == "__main__":
    unittest.main()
