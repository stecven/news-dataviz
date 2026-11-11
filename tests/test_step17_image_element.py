# -*- coding: utf-8 -*-
"""第五层接线：让 PageSpec 能承载图片图元，render.py 能把它画出来。

用户 m04220 的五件事，逐条对应到下面的 TestCase：

1. PageSpec 扩图元类型 + 承载 local_path 的字段、老 JSON 仍可读
   → ``TestModel``
2. render.py 遇 image 类型用 add_picture 画，shape.name 仍为 el.id
   → ``TestRender``
3. pipeline 的 no_applicable 分支拼进占位图并出图
   → ``TestPipelineFallback``
4. 端到端 6 项占比 → 占位图 → 画得出来
   → ``TestEndToEnd``
5. 正常分支不受影响 / 文件不存在要报错
   → ``TestNoRegression``、``TestMissingFile``
"""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from loop.models import ElementSpec, PageSpec, Scale  # noqa: E402
from loop.render import render_pptx  # noqa: E402
from loop.verify import read_shapes  # noqa: E402
import tests.scratch as scratch  # noqa: E402

TINY_PNG = os.path.join(ROOT, "assets", "placeholders", "placeholder_todo.png")


def _spec_with(elements, w=10.0, h=6.0):
    return PageSpec(width_in=w, height_in=h, chart_key="k", chart_title="t",
                    scale=Scale(v_max=1.0, h_in=0.0, unit="n/a"),
                    elements=list(elements), constraints=[], layout={})


class TestModel(unittest.TestCase):
    def test_image_element_round_trips_through_json(self):
        el = ElementSpec(id="placeholder_1", type="image", role="placeholder",
                         x_in=4.0, y_in=3.0, w_in=2.0, h_in=2.0,
                         image_path="assets/placeholders/placeholder_todo.png")
        spec = _spec_with([el])
        back = PageSpec.from_dict(json.loads(json.dumps(spec.to_dict())))
        self.assertEqual(len(back.elements), 1)
        got = back.elements[0]
        self.assertEqual(got.type, "image")
        self.assertEqual(got.image_path, "assets/placeholders/placeholder_todo.png")
        self.assertEqual((got.x_in, got.y_in, got.w_in, got.h_in), (4.0, 3.0, 2.0, 2.0))

    def test_image_path_defaults_to_none_so_old_elements_still_load(self):
        el = ElementSpec(id="a", type="rect", role="track",
                         x_in=0.0, y_in=0.0, w_in=1.0, h_in=1.0)
        self.assertIsNone(el.image_path)

    def test_old_pagespec_json_without_the_new_field_is_still_readable(self):
        old = {
            "width_in": 10.0, "height_in": 6.0,
            "chart_key": "k", "chart_title": "t",
            "scale": {"v_max": 1.0, "h_in": 3.0, "unit": "倍(超)"},
            "elements": [
                {"id": "title", "type": "text", "role": "title",
                 "x_in": 0.5, "y_in": 0.5, "w_in": 9.0, "h_in": 0.5, "text": "标题"},
            ],
            "semantic_tags": [], "constraints": [], "layout": {},
        }
        spec = PageSpec.from_dict(old)
        self.assertEqual(spec.elements[0].type, "text")
        self.assertIsNone(spec.elements[0].image_path)

    def test_image_path_is_not_reusing_binding(self):
        """binding 载数据点、image_path 载文件路径，两者不能混用。"""
        el = ElementSpec(id="p", type="image", role="placeholder",
                         x_in=0.0, y_in=0.0, w_in=1.0, h_in=1.0,
                         image_path="x.png")
        self.assertIsNone(el.binding)
        self.assertEqual(el.image_path, "x.png")


class TestRender(unittest.TestCase):
    def setUp(self):
        self.tmp = scratch.mkdtemp()
        self.pptx = os.path.join(self.tmp, "a.pptx")

    def test_image_element_becomes_a_picture_shape_readable_by_name(self):
        el = ElementSpec(id="placeholder_1", type="image", role="placeholder",
                         x_in=4.0, y_in=3.0, w_in=2.0, h_in=2.0,
                         image_path="assets/placeholders/placeholder_todo.png")
        render_pptx(_spec_with([el]), self.pptx)
        shapes = read_shapes(self.pptx)
        self.assertIn("placeholder_1", shapes)
        got = shapes["placeholder_1"]
        self.assertEqual(got["left"], int(4.0 * 914400))
        self.assertEqual(got["top"], int(3.0 * 914400))
        self.assertEqual(got["width"], int(2.0 * 914400))
        self.assertEqual(got["height"], int(2.0 * 914400))

    def test_other_element_types_still_render_next_to_an_image(self):
        els = [
            ElementSpec(id="bg", type="rect", role="bg",
                        x_in=0.0, y_in=0.0, w_in=10.0, h_in=6.0, fill="EEEEEE"),
            ElementSpec(id="placeholder_1", type="image", role="placeholder",
                        x_in=4.0, y_in=3.0, w_in=2.0, h_in=2.0,
                        image_path="assets/placeholders/placeholder_todo.png"),
            ElementSpec(id="cap", type="text", role="caption",
                        x_in=4.0, y_in=5.2, w_in=2.0, h_in=0.3, text="占位"),
        ]
        render_pptx(_spec_with(els), self.pptx)
        shapes = read_shapes(self.pptx)
        self.assertEqual(set(shapes), {"bg", "placeholder_1", "cap"})
        self.assertEqual(shapes["cap"]["text"], "占位")


class TestMissingFile(unittest.TestCase):
    def test_missing_image_raises_instead_of_silently_skipping(self):
        el = ElementSpec(id="ghost", type="image", role="placeholder",
                         x_in=0.0, y_in=0.0, w_in=1.0, h_in=1.0,
                         image_path="assets/placeholders/does_not_exist.png")
        with self.assertRaises(FileNotFoundError) as ctx:
            render_pptx(_spec_with([el]),
                        os.path.join(scratch.mkdtemp(), "a.pptx"))
        msg = str(ctx.exception)
        self.assertIn("ghost", msg)
        self.assertIn("does_not_exist.png", msg)

    def test_missing_image_path_field_raises_too(self):
        el = ElementSpec(id="no_path", type="image", role="placeholder",
                         x_in=0.0, y_in=0.0, w_in=1.0, h_in=1.0)
        with self.assertRaises(ValueError):
            render_pptx(_spec_with([el]),
                        os.path.join(scratch.mkdtemp(), "a.pptx"))


class TestPipelineFallback(unittest.TestCase):
    def test_no_applicable_now_renders_a_placeholder_instead_of_nothing(self):
        from loop.pipeline import run_selected
        out = os.path.join(scratch.mkdtemp(), "pipeline")
        res = run_selected(values=[10, 3, 2, 2, 2, 1], semantic="占比构成",
                           out_root=out, group_name="six")
        self.assertEqual(res["status"], "no_applicable")
        self.assertIsNone(res["selected_template"])
        self.assertIsNotNone(res["pagespec"], "该落 pagespec.json 了")
        self.assertIsNotNone(res["pptx"])
        self.assertIsNotNone(res["preview"])
        self.assertTrue(os.path.exists(res["preview"]))
        self.assertTrue(os.path.exists(res["pptx"]))

    def test_fallback_pagespec_contains_exactly_one_image_element(self):
        from loop.pipeline import run_selected
        out = os.path.join(scratch.mkdtemp(), "pipeline")
        res = run_selected(values=[10, 3, 2, 2, 2, 1], semantic="占比构成",
                           out_root=out, group_name="six")
        with open(res["pagespec"], encoding="utf-8") as f:
            doc = json.load(f)
        imgs = [e for e in doc["elements"] if e["type"] == "image"]
        self.assertEqual(len(imgs), 1, "本轮不做多占位图轮换")
        self.assertTrue(imgs[0]["image_path"])
        self.assertTrue(os.path.exists(
            os.path.join(ROOT, imgs[0]["image_path"].replace("/", os.sep))))

    def test_fallback_pptx_holds_the_picture_shape(self):
        from loop.pipeline import run_selected
        out = os.path.join(scratch.mkdtemp(), "pipeline")
        res = run_selected(values=[10, 3, 2, 2, 2, 1], semantic="占比构成",
                           out_root=out, group_name="six")
        shapes = read_shapes(res["pptx"])
        # 用户 m04818 之后占位图也是带框的卡片：框 + 标题带 + 标题 + 说明 + 图 = 5
        self.assertEqual(len(shapes), 5,
                         f"期望 chrome(4) + 占位图(1)，实际 {sorted(shapes)}")
        self.assertIn("placeholder_1", shapes)
        self.assertIn("frame", shapes)
        self.assertIn("title_band", shapes)
        from pptx.enum.shapes import MSO_SHAPE_TYPE
        self.assertEqual(shapes["placeholder_1"]["shape_type"],
                         MSO_SHAPE_TYPE.PICTURE)

    def test_selection_json_still_written_alongside(self):
        from loop.pipeline import run_selected
        out = os.path.join(scratch.mkdtemp(), "pipeline")
        res = run_selected(values=[10, 3, 2, 2, 2, 1], semantic="占比构成",
                           out_root=out, group_name="six")
        self.assertTrue(os.path.exists(res["selection"]))
        with open(res["selection"], encoding="utf-8") as f:
            sel = json.load(f)
        self.assertIsNone(sel["selected_template"])
        self.assertTrue(sel["rationale"])

    def test_fallback_uses_the_first_placeholder_deterministically(self):
        from loop.asset_lookup import find_fallback_assets
        from loop.pipeline import run_selected
        rows = find_fallback_assets()
        expected = os.path.join(ROOT, rows[0]["local_path"].replace("/", os.sep))
        out = os.path.join(scratch.mkdtemp(), "pipeline")
        res = run_selected(values=[10, 3, 2, 2, 2, 1], semantic="占比构成",
                           out_root=out, group_name="six")
        with open(res["pagespec"], encoding="utf-8") as f:
            doc = json.load(f)
        got = [e for e in doc["elements"] if e["type"] == "image"][0]["image_path"]
        self.assertEqual(os.path.join(ROOT, got.replace("/", os.sep)), expected)


class TestNoRegression(unittest.TestCase):
    def test_thermometer_spec_has_no_image_element(self):
        from loop.scaffold import build_pagespec
        pts = [{"seq": i + 1, "label": f"p{i}", "value": v, "unit": "倍(超)"}
               for i, v in enumerate([10, 8, 4, 2, 1])]
        spec = build_pagespec(pts, "t", template_name="thermometer")
        self.assertEqual([e for e in spec.elements if e.type == "image"], [])

    def test_semicircle_spec_has_no_image_element(self):
        from loop.scaffold import build_pagespec
        pts = [{"seq": i + 1, "label": f"p{i}", "value": v, "unit": "占比"}
               for i, v in enumerate([10, 3, 3, 3, 3])]
        spec = build_pagespec(pts, "t", template_name="semicircle")
        self.assertEqual([e for e in spec.elements if e.type == "image"], [])

    def test_pipeline_normal_branch_has_no_image_element(self):
        from loop.pipeline import run_selected
        out = os.path.join(scratch.mkdtemp(), "pipeline")
        res = run_selected(chart_key="heat_ratio_top5", semantic="比较大小",
                           out_root=out)
        self.assertEqual(res["status"], "rendered")
        with open(res["pagespec"], encoding="utf-8") as f:
            doc = json.load(f)
        self.assertEqual([e for e in doc["elements"] if e["type"] == "image"], [])

    def test_old_loop1_pagespec_still_renders(self):
        old = os.path.join(ROOT, "out", "loop1", "pagespec.json")
        if not os.path.exists(old):
            self.skipTest("老产物不在工作区")
        from loop.build_loop import render_from_spec
        with open(old, encoding="utf-8") as f:
            spec = PageSpec.from_dict(json.load(f))
        out = scratch.mkdtemp()
        artifacts = render_from_spec(spec, out)
        self.assertTrue(os.path.exists(artifacts["pptx"]))
        self.assertEqual(len(read_shapes(artifacts["pptx"])), len(spec.elements))


class TestEndToEnd(unittest.TestCase):
    def test_six_item_share_draws_a_placeholder_and_preview_is_not_blank(self):
        """验收闸口最重要的一条：预览图里真能看到占位图。

        注意断言口径：占位图是**线条图**（虚线框 + 三个点），不是实心色块，
        整张图里非白像素只占很小比例。所以必须只在占位图所在的盒子里数，
        而且判据是「非白」而不是「大片灰」——早先用全局 stride=7 数灰像素，
        只命中 20 个，原因不是没画出来，而是采样跳过了细线。
        """
        from PIL import Image
        from loop.pipeline import run_selected
        out = os.path.join(scratch.mkdtemp(), "pipeline")
        res = run_selected(values=[10, 3, 2, 2, 2, 1], semantic="占比构成",
                           out_root=out, group_name="six")
        self.assertEqual(res["status"], "no_applicable")
        img = Image.open(res["preview"]).convert("RGB")

        # 占位图盒直接从落盘的 pagespec 读，不自己按常量推——包框后画布尺寸
        # 已由「内容 bbox + 内边距」决定（用户 m04888），常量推不出坐标。
        import json
        with open(res["pagespec"], encoding="utf-8") as f:
            doc = json.load(f)
        e = next(x for x in doc["elements"] if x["type"] == "image")
        px = 100  # loop.preview.PX_PER_IN
        x0, y0 = int(e["x_in"] * px), int(e["y_in"] * px)
        x1, y1 = int((e["x_in"] + e["w_in"]) * px), int((e["y_in"] + e["h_in"]) * px)
        nonwhite = 0
        for x in range(x0, x1):
            for y in range(y0, y1):
                r, g, b = img.getpixel((x, y))
                if not (r > 250 and g > 250 and b > 250):
                    nonwhite += 1
        self.assertGreater(nonwhite, 1000,
                           f"预览的占位图盒 ({x0},{y0})-({x1},{y1}) 里几乎空白："
                           f"nonwhite={nonwhite}")
