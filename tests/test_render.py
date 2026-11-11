import os
import unittest

from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.util import Inches

from tests.scratch import mkdtemp
from loop.data_source import DB_PATH, load_points
from loop.scaffold import build_pagespec
from loop.render import render_pptx
from loop.preview import render_preview
from loop.verify import read_shapes


class TestRenderPptx(unittest.TestCase):
    def setUp(self):
        self.d = mkdtemp(prefix="render-")
        _, pts = load_points(DB_PATH)
        self.spec = build_pagespec(pts)
        self.pptx = os.path.join(self.d, "loop1.pptx")
        render_pptx(self.spec, self.pptx)

    def test_five_named_liquid_shapes_are_native_autoshapes(self):
        shapes = read_shapes(self.pptx)
        liqs = [n for n in shapes if n.startswith("liquid_")]
        self.assertEqual(len(liqs), 5)
        for n in liqs:
            self.assertEqual(shapes[n]["shape_type"], MSO_SHAPE_TYPE.AUTO_SHAPE)
            self.assertNotEqual(shapes[n]["shape_type"], MSO_SHAPE_TYPE.PICTURE)

    def test_liquid_emu_height_matches_spec_and_is_less_than_full_track(self):
        h = read_shapes(self.pptx)["liquid_1"]["height"]
        self.assertAlmostEqual(h, Inches(3.0 * 10.0 / 11.0), delta=1)
        self.assertLess(h, Inches(3.0))

    def test_cjk_labels_are_not_mangled(self):
        texts = "\n".join(s["text"] for s in read_shapes(self.pptx).values())
        self.assertIn("欧式快热炉", texts)
        self.assertIn("满格约 11倍", texts)

    def test_text_boxes_have_word_wrap_enabled(self):
        from pptx import Presentation
        boxes = [sh for sh in Presentation(self.pptx).slides[0].shapes
                 if sh.has_text_frame and sh.name.startswith("label_")]
        self.assertEqual(len(boxes), 5)
        self.assertTrue(all(sh.text_frame.word_wrap for sh in boxes))

    def test_second_render_replaces_shapes_not_appends(self):
        render_pptx(self.spec, self.pptx)
        self.assertEqual(len(read_shapes(self.pptx)), 37)

    def test_preview_png_is_nonblank(self):
        # 审查发现：纯白 1000×600 PNG 也有 3164 字节，按文件大小 >1000 会漏判。
        # 改为像素级断言：必须出现红色液柱像素，且非白像素足够多。
        from PIL import Image
        png = os.path.join(self.d, "preview.png")
        render_preview(self.spec, png)
        # 报纸原版配色：液柱 E8A08C（暖珊瑚），不是纯红；
        # 断言液柱色像素足够多，避免「没画出来」也通过。
        img = Image.open(png).convert("RGB")
        px = list(img.get_flattened_data()) if hasattr(img, "get_flattened_data") else list(img.getdata())
        liquid = sum(1 for r, g, b in px
                     if abs(r - 0xE8) <= 12 and abs(g - 0xA0) <= 12
                     and abs(b - 0x8C) <= 12)
        nonwhite = sum(1 for p in px if p != (255, 255, 255))
        self.assertGreater(liquid, 1000, "预览里没有液柱像素")
        self.assertGreater(nonwhite, 10000, "预览几乎全白，形状没有画出来")
