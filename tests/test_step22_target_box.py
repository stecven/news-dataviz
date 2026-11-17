"""第 22 步：单卡片适配外部边界（用户 m05768）。

「内容决定画布」逆转为「外部给边界、内部自适应」：传 target_width_in /
target_height_in 时，卡片必须装进这个格子；不传时行为与之前逐位一致。

契约升级（用户裁定 (a)，分支 fix/staggered-layout）：装进格子从「正好填满」
升级为「**等比适配进**」——画布与几何按同一个比例 ``s`` 缩，外框 = 内容 bbox
+ 固定 chrome（1.75 in，不随 ``s`` 缩）。于是三条不变量取代了旧的
「``spec.width_in == target``」：

1. 真实外框**不超过**格子（每边容差 1e-6），``frame_bbox`` 记的就是这个真实
   外框，而不是分配的格子；
2. **等比**落在图形上：图形内容外框（去掉文字与 chrome）的宽高比与设计尺度
   完全一致（容差 1e-3）。外框宽高比会变，因为 chrome 固定不缩——被拉伸的
   从来是几何，不是铬；
3. 保持等比 + 字号读得清就装不下的格子抛 :class:`FitRequirement`（「格子太
   窄、给我更宽的地方」的内部信号，版式层据此升栏），而不是把卡片压扁或
   静默溢出。
"""

import json
import os
import unittest

from loop import palette
from loop.data_source import DB_PATH, load_points
from loop.fit import FitRequirement, available_box, chrome_height_in
from loop.frame import CHROME_ROLES, validate_frame
from loop.pipeline import run_selected
from loop.scaffold import build_pagespec
from loop.selector import SEMANTIC_COMPARE, SEMANTIC_SHARE
from loop.solve import build_skeleton, solve, validate_spec
from loop.templates import get_template
from tests.scratch import mkdtemp

TOL = 0.01


def _rows(chart_key):
    _, points = load_points(DB_PATH, chart_key=chart_key)
    return points


def _inside(spec, w, h):
    out = []
    for e in spec.elements:
        if (e.x_in < -1e-6 or e.y_in < -1e-6
                or e.x_in + e.w_in > w + 1e-6 or e.y_in + e.h_in > h + 1e-6):
            out.append(e.id)
    return out


def _graphic_bbox(spec):
    """图形内容外框 (x, y, w, h)：去掉文字与 chrome，只留几何元素。

    「等比」量在这里而不是量 ``spec.width_in/height_in``：外框含固定高度的
    chrome（标题带 + 说明行 + 内边距 1.75 in），chrome 不随 ``s`` 缩，所以
    外框宽高比在缩放后必然变化；几何元素的外框才是「被拉伸」会立刻显形的地方。
    """
    xs, ys = [], []
    for e in spec.elements:
        if e.type == "text" or e.role in CHROME_ROLES:
            continue
        xs += [e.x_in, e.x_in + e.w_in]
        ys += [e.y_in, e.y_in + e.h_in]
    if not xs:
        raise AssertionError(f"卡片 {spec} 里没有图形元素")
    return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)


class TestTargetCanvas(unittest.TestCase):
    """闸口：传入 target 时卡片等比适配进给定格子，且元素都在真实外框内。"""

    #: 保持等比 + 字号可读都装得下的格子（实测最小可行 ~4.77×3.51 / ~3.24×3.69）
    FIT_CASES = [
        ("thermometer", "heat_ratio_top5", 5.0, 4.0),
        ("semicircle", "heat_age", 4.0, 4.0),
    ]
    #: 装不下的格子：宽或高小于「最小可行尺寸」，必须拒绝而不是压扁
    TIGHT_CASES = [
        ("thermometer", "heat_ratio_top5", 7.0, 3.0),   # 宽够、高差 0.51
        ("semicircle", "heat_age", 3.0, 3.0),
        ("semicircle", "heat_age", 5.0, 2.5),           # 高差 1.19
    ]

    def test_boxes_that_fit_are_scaled_uniformly_inside_the_target(self):
        for name, key, tw, th in self.FIT_CASES:
            with self.subTest(template=name, target=(tw, th)):
                design = build_pagespec(_rows(key), "标题", template_name=name)
                spec = build_pagespec(_rows(key), "标题", template_name=name,
                                      target_width_in=tw, target_height_in=th)
                # ① 等比适配进格子：真实外框每边都不超过格子（旧的「正好等于
                #    格子」在升级后不再成立——格子装得下就留白，不硬撑）
                self.assertLessEqual(spec.width_in, tw + 1e-6)
                self.assertLessEqual(spec.height_in, th + 1e-6)
                # frame_bbox 记的是真实外框，不是分配的格子
                self.assertEqual(spec.frame_bbox,
                                 [0.0, 0.0, spec.width_in, spec.height_in])
                self.assertEqual(_inside(spec, spec.width_in, spec.height_in), [],
                                 "元素越出卡片真实外框")
                # ② 等比：图形外框的宽高比与设计尺度一致（被单轴拉伸就会变）
                _, _, dw, dh = _graphic_bbox(design)
                _, _, fw, fh = _graphic_bbox(spec)
                self.assertAlmostEqual(fw / fh, dw / dh, delta=1e-3,
                                       msg=f"{name} 图形被拉伸了")
                # 两个方向必须缩得一样多（同一个 s），不许一条边缩、一条边不缩
                s = spec.layout["frame"]["fit"]["scale"]
                self.assertGreater(s, 0.0)
                self.assertAlmostEqual(fw / dw, fh / dh, delta=1e-3,
                                       msg=f"{name} 两轴缩放比不一致")
                validate_frame(spec)
                validate_spec(spec)

    def test_tight_boxes_are_refused_instead_of_squashed(self):
        """装不下就报 FitRequirement：说清「大约需要多大的格子」。"""
        for name, key, tw, th in self.TIGHT_CASES:
            with self.subTest(template=name, target=(tw, th)):
                with self.assertRaises(FitRequirement) as cm:
                    build_pagespec(_rows(key), "标题", template_name=name,
                                   target_width_in=tw, target_height_in=th)
                err = cm.exception
                self.assertEqual(err.target, (tw, th))
                self.assertTrue(
                    err.need_width_in > tw + 1e-6 or err.need_height_in > th + 1e-6,
                    "拒绝的理由必须是「这个格子确实不够大」")
                self.assertIn("太窄", str(err))

    def test_placeholder_card_centres_inside_the_target(self):
        r = run_selected(values=[10, 3, 2, 2, 2, 1], semantic=SEMANTIC_SHARE,
                         out_root=mkdtemp("t22-"),
                         target_width_in=4.0, target_height_in=4.0)
        self.assertEqual(r["status"], "no_applicable")
        with open(r["pagespec"], encoding="utf-8") as f:
            doc = json.load(f)
        self.assertAlmostEqual(doc["width_in"], 4.0, delta=TOL)
        self.assertAlmostEqual(doc["height_in"], 4.0, delta=TOL)
        img = [e for e in doc["elements"] if e["type"] == "image"]
        self.assertEqual(len(img), 1)
        e = img[0]
        self.assertAlmostEqual(e["x_in"] + e["w_in"] / 2, 2.0, delta=TOL)
        # 占位图在格子里居中，且不越出框
        self.assertAlmostEqual(e["x_in"] + e["w_in"] / 2, 2.0, delta=TOL)
        # 纵向落在「标题带以下、下内边距以上」的内容带里
        band_top = 2 * 0.3 + 0.5 + 0.15
        self.assertGreaterEqual(e["y_in"], band_top - 1e-9)
        self.assertLessEqual(e["y_in"] + e["h_in"], 4.0 - 0.3 + 1e-9)
        self.assertGreaterEqual(e["x_in"], 0.0 - 1e-9)
        self.assertLessEqual(e["x_in"] + e["w_in"], 4.0 + 1e-9)
        self.assertLessEqual(e["y_in"] + e["h_in"], 4.0 + 1e-9)
        self.assertEqual(doc["content_bbox"] is not None, True)
        self.assertEqual(_inside(PageSpecLike(doc), 4.0, 4.0), [])

    def test_fonts_stay_inside_the_clamp(self):
        """紧格子里的字号被 6 pt 下限兜住——这正是「等比 + 字读得清」的边界。

        原来用 3×3 半圆，现在这个格子被拒（见上条），改用各模板实测的最小
        可行格子附近：缩放比 0.34–0.50，原始字号早已掉到 6 pt 以下，clamp
        必须真的在起作用，而不是永远取不到界线上的值。
        """
        for name, key, tw, th in (("thermometer", "heat_ratio_top5", 5.0, 4.0),
                                  ("semicircle", "heat_age", 4.5, 3.8)):
            with self.subTest(template=name, target=(tw, th)):
                spec = build_pagespec(_rows(key), "标题", template_name=name,
                                      target_width_in=tw, target_height_in=th)
                scale = palette.spec_scale(spec)
                self.assertLess(scale, 1.0)
                raw = []
                for e in spec.elements:
                    if e.type != "text":
                        continue
                    raw.append(palette.font_size(e.role) * scale)
                    pt = palette.scaled_font_size(e.role, scale)
                    self.assertGreaterEqual(pt, palette.MIN_FONT_PT)
                    self.assertLessEqual(pt, palette.MAX_FONT_PT)
                self.assertTrue(raw, "卡片里应该有文字元素")
                self.assertLess(min(raw), palette.MIN_FONT_PT,
                                "格子还不够紧，clamp 没被触发，这条测不到下限")

    def test_too_small_a_box_raises_instead_of_bursting_out(self):
        """极小格子必须拒绝：等比 + 可读字号下它装不下，不许压扁也不许溢出。

        异常类型从 ``BoundaryError`` 升级成 ``FitRequirement``：后者才是
        「换个更宽的格子就能装下」的信号，携带所需尺寸而不是 problems/min_size。
        """
        for name, key in (("thermometer", "heat_ratio_top5"),
                          ("semicircle", "heat_age")):
            with self.subTest(template=name):
                with self.assertRaises(FitRequirement) as cm:
                    build_pagespec(_rows(key), "标题", template_name=name,
                                   target_width_in=2.0, target_height_in=2.0)
                err = cm.exception
                self.assertEqual(err.target, (2.0, 2.0))
                # 必须说清「大约需要多大的格子」，而且确实比 2×2 大
                self.assertGreater(err.need_width_in, 2.0)
                self.assertGreater(err.need_height_in, 2.0)
                self.assertIn("太窄", str(err))


class TestBackwardCompatible(unittest.TestCase):
    """闸口：不传 target 时原有的「按内容长大」逐位不变。"""

    def test_natural_thermometer_is_untouched(self):
        spec = build_pagespec(_rows("heat_ratio_top5"), "标题", frame=True)
        self.assertEqual(len(spec.elements), 39)
        self.assertEqual(spec.width_in, 10.52)
        self.assertEqual(spec.height_in, 5.85)

    def test_natural_semicircle_radius_is_untouched(self):
        spec = build_pagespec(_rows("heat_age"), "标题",
                              template_name="semicircle", frame=True)
        self.assertEqual(len(spec.elements), 15)
        # w_legend 新增后 10×6 上仍是「高度限制」，半径必须还是 2.05
        sector = [e for e in spec.elements if e.type == "arc"][0]
        self.assertAlmostEqual(sector.geometry["R"], 2.05, places=6)

    def test_legacy_pagespec_still_reads_and_renders(self):
        # 用户 m07603 决策一：样本改成读入库夹具（``cf.LEGACY_LOOP1_PAGESPEC``），
        # 不再看 ``out/loop1/``，于是干净检出上这条也会真跑而不是跳过。
        from loop.build_loop import render_from_spec
        from loop.models import PageSpec
        from tests import contract_fixtures as cf
        from tests.scratch import mkdtemp
        path = cf.LEGACY_LOOP1_PAGESPEC
        with open(path, encoding="utf-8") as f:
            spec = PageSpec.from_dict(json.load(f))
        self.assertEqual(len(spec.elements), 27)
        out = mkdtemp()
        render_from_spec(spec, out)
        for name in os.listdir(out):
            self.assertTrue(os.path.getsize(os.path.join(out, name)) > 1000,
                            name)


class TestWidthFloorForLegend(unittest.TestCase):
    """半圆图例列：宽画布上 R 不再吃满宽度，图例列有位置。"""

    def test_wide_canvas_keeps_a_legend_column(self):
        spec = build_pagespec(_rows("heat_age"), "标题", template_name="semicircle",
                              target_width_in=12.0, target_height_in=14.0)
        legends = [e for e in spec.elements if e.role == "legend"]
        self.assertEqual(len(legends), 5)
        for e in legends:
            self.assertGreaterEqual(e.w_in, 0.5 - 1e-9)

    def test_legend_text_fits_its_column(self):
        from loop.fit import text_problems
        spec = build_pagespec(_rows("heat_age"), "标题", template_name="semicircle",
                              target_width_in=12.0, target_height_in=14.0)
        self.assertEqual(text_problems(spec, palette.spec_scale(spec)), [])

    def test_narrow_tall_canvas_no_longer_leaves_zero_room(self):
        """12×14 曾经让 R 吃满宽度、图例只剩硬下限 0.5。"""
        tmpl = get_template("semicircle")
        _, points = load_points(DB_PATH, chart_key="heat_age")

        def solve_at(ov, w, h):
            sk = build_skeleton(tmpl, points, "heat_age", "标题", width_in=w,
                                height_in=h, param_overrides=ov, semantic_tags=[])
            return solve(sk, points)

        avail_w, _ = available_box(12.0, 14.0)
        spec = solve_at(None, avail_w, 14.0 - chrome_height_in())
        sector = [e for e in spec.elements if e.type == "arc"][0]
        self.assertLess(sector.geometry["R"] + 0.6, avail_w / 2,
                        "半径仍然吃满宽度，图例列会被挤没")


class PageSpecLike:
    """把 dict 版 pagespec 包成只有 elements/width_in 的最小白话对象。"""

    def __init__(self, doc):
        self.width_in = doc["width_in"]
        self.height_in = doc["height_in"]
        self.elements = [_El(e) for e in doc["elements"]]


class _El:
    def __init__(self, d):
        self.id = d["id"]
        self.x_in = d["x_in"]
        self.y_in = d["y_in"]
        self.w_in = d["w_in"]
        self.h_in = d["h_in"]


if __name__ == "__main__":
    unittest.main()
