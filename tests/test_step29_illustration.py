"""图文并茂 1.0（用户 m06471）：素材库接进自动编排。

验收闸口逐条对应：

* 自动编排生成的流中含 ``ImageBlock``            → ``TestComposePicksIllustration``
* 图片按比例缩放不变形、不与文字/卡片重叠          → ``TestImageGeometry`` / ``TestPlacement``
* 仍合多栏规则（占 1 栏就严格等于栏宽）            → ``TestPlacement``
* 素材库查不到不阻塞排版                          → ``TestMissingAssetDoesNotBlock``
* 不改单卡模块、向后兼容                          → ``TestBackwardCompatible``
"""
import json
import os
import unittest
from unittest import mock

from PIL import Image

from loop.asset_lookup import find_assets_by_semantic
from loop.compose import build_flow
from loop.data_source import DB_PATH
from loop.layout import (CardSpec, ImageBlock, LayoutOverflowError, LayoutSpec,
                         PlacedImage, TextBlock, fit_rect_in, flatten,
                         flow_layout, image_box, image_size_in, page_spec_path)
from loop.render_page import render_layout
from loop.verify import read_shapes
from tests.scratch import mkdtemp

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 素材库里真实存在的两张图标：正方、RGBA。
PEOPLE = find_assets_by_semantic("占比构成", DB_PATH)[0]
RADIATOR = find_assets_by_semantic("比较大小", DB_PATH)[0]
PEOPLE_PATH = os.path.join(ROOT, PEOPLE["local_path"])


def _copy_asset(row, basis: str) -> ImageBlock:
    return ImageBlock(row["local_path"], style="icon",
                      asset_id=row["asset_id"], tag=row["tag"],
                      semantic=basis, name=f"illustration_{row['asset_id']}")


class TestImageBlock(unittest.TestCase):
    """插图块自身的定义与校验。"""

    def test_path_is_required(self):
        with self.assertRaises(ValueError):
            ImageBlock("")

    def test_defaults_and_name_from_file(self):
        block = ImageBlock(PEOPLE["local_path"])
        self.assertEqual(block.style, "icon")
        self.assertEqual(block.align, "center")
        self.assertEqual(block.column_span, 1)
        self.assertEqual(block.name, os.path.splitext(
            os.path.basename(PEOPLE["local_path"]))[0])

    def test_bad_style_align_span_are_rejected(self):
        for kwargs in ({"style": "sticker"}, {"align": "justify"},
                       {"column_span": 0}, {"column_span": 4},
                       {"max_height_in": 0}):
            with self.assertRaises(ValueError, msg=kwargs):
                ImageBlock(PEOPLE["local_path"], **kwargs)

    def test_aspect_comes_from_the_file_not_from_the_caller(self):
        """宽高比必须读文件 —— 猜错就是重叠或留白。"""
        width_in, height_in = image_size_in(PEOPLE_PATH)
        self.assertEqual(ImageBlock(PEOPLE["local_path"]).aspect,
                         width_in / height_in)
        with Image.open(PEOPLE_PATH) as im:
            self.assertEqual((im.width, im.height), (400, 400))

    def test_styles_cover_the_two_documented_values(self):
        from loop.layout import IMAGE_STYLES
        self.assertEqual(tuple(IMAGE_STYLES), ("icon", "cover"))


class TestImageGeometry(unittest.TestCase):
    """``fit_rect_in`` / ``image_box``：只缩不放、永不变形。"""

    def test_fit_rect_never_upscales(self):
        dx, dy, w, h = fit_rect_in(4.0, 4.0, aspect=0.5)
        self.assertAlmostEqual(w, 2.0)
        self.assertAlmostEqual(h, 4.0)
        self.assertAlmostEqual(w / h, 0.5)

    def test_fit_rect_centres_and_aligns(self):
        self.assertEqual(fit_rect_in(4.0, 2.0, aspect=1.0, align="center")[0],
                         1.0)
        self.assertEqual(fit_rect_in(4.0, 2.0, aspect=1.0, align="left")[0], 0.0)
        self.assertEqual(fit_rect_in(4.0, 2.0, aspect=1.0, align="right")[0],
                         2.0)

    def test_fit_rect_stays_inside_its_box(self):
        for box_w, box_h, aspect in ((4.0, 3.0, 1.0), (2.0, 5.0, 1.5),
                                     (3.0, 3.0, 0.25)):
            dx, dy, w, h = fit_rect_in(box_w, box_h, aspect)
            self.assertGreaterEqual(dx, -1e-9)
            self.assertGreaterEqual(dy, -1e-9)
            self.assertLessEqual(dx + w, box_w + 1e-9)
            self.assertLessEqual(dy + h, box_h + 1e-9)
            # 尺寸四舍五入到 1e-6 in，比值只保证到小数点后 5 位。
            self.assertAlmostEqual(w / h, aspect, places=5)

    def test_image_box_height_follows_the_aspect(self):
        layout = LayoutSpec(width_in=10.0, height_in=15.0)
        block = _copy_asset(PEOPLE, "占比构成")
        box_w, box_h, rect = image_box(block, layout, 4.5)
        self.assertAlmostEqual(box_w, 4.5)
        # people.png 是正方形：4.5 宽就想要 4.5 高，但被 max_image_height 压住。
        self.assertAlmostEqual(box_h, layout.max_image_height_in)
        self.assertAlmostEqual(rect[2] / rect[3], block.aspect)
        self.assertLessEqual(rect[3], box_h + 1e-9)

    def test_explicit_max_height_wins_over_the_layout_default(self):
        layout = LayoutSpec(width_in=10.0, height_in=15.0)
        block = _copy_asset(PEOPLE, "占比构成")
        _, box_h, rect = image_box(block, layout, 4.0)
        capped = ImageBlock(block.path, max_height_in=1.0)
        _, box_h2, rect2 = image_box(capped, layout, 4.0)
        # 默认上限 = 可用高度 14.2 × 0.2；正方形图 4.0 宽想要 4.0 高，被压住。
        self.assertAlmostEqual(layout.max_image_height_in, 2.84)
        self.assertAlmostEqual(box_h, 2.84)
        self.assertAlmostEqual(box_h2, 1.0)
        self.assertAlmostEqual(rect2[3], 1.0)
        self.assertAlmostEqual(rect2[2], 1.0)

    def test_max_height_ratio_is_validated(self):
        with self.assertRaises(ValueError):
            LayoutSpec(max_image_height_ratio=0.0)
        with self.assertRaises(ValueError):
            LayoutSpec(max_image_height_ratio=1.5)


class TestPlacement(unittest.TestCase):
    """落位：栏宽、并排、居中、不重叠。"""

    def setUp(self):
        self.layout = LayoutSpec(width_in=10.0, height_in=15.0, margin_in=0.4,
                                 gutter_in=0.3, column_count=2,
                                 column_gutter_in=0.2)

    def test_span_one_image_is_exactly_one_column_wide(self):
        page = flow_layout(self.layout, [_copy_asset(PEOPLE, "占比构成")])
        placed = page.images[0]
        self.assertAlmostEqual(placed.w_in, self.layout.column_width_in)
        self.assertAlmostEqual(placed.w_in, 4.5)

    def test_full_span_image_is_exactly_the_usable_width(self):
        block = _copy_asset(PEOPLE, "占比构成")
        block.column_span = 2
        page = flow_layout(self.layout, [block])
        self.assertAlmostEqual(page.images[0].w_in,
                               self.layout.usable_width_in)
        self.assertAlmostEqual(page.images[0].x_in, self.layout.margin_in)

    def test_image_sits_beside_a_one_column_card_in_the_same_row(self):
        page = flow_layout(self.layout, [
            CardSpec("heat_age", "semicircle", chart_key="heat_age",
                     column_span=1),
            _copy_asset(PEOPLE, "占比构成"),
        ])
        card, image = page.cards[0], page.images[0]
        self.assertAlmostEqual(card.y_in, image.y_in)
        self.assertEqual(card.row, image.row)
        # 左边一栏放卡片、右边一栏放插图，间隙正好是栏间距。
        self.assertAlmostEqual(card.x_in, self.layout.margin_in)
        self.assertAlmostEqual(image.x_in,
                               card.x_in + card.w_in
                               + self.layout.column_gutter_in)

    def test_row_height_is_the_taller_of_the_two(self):
        page = flow_layout(self.layout, [
            CardSpec("heat_age", "semicircle", chart_key="heat_age",
                     column_span=1),
            _copy_asset(PEOPLE, "占比构成"),
        ])
        card, image = page.cards[0], page.images[0]
        self.assertGreater(card.h_in, image.h_in)
        self.assertAlmostEqual(page.rows[0]["h_in"],
                               max(card.h_in, image.h_in))

    def test_short_image_is_centred_inside_a_taller_row(self):
        page = flow_layout(self.layout, [
            CardSpec("heat_age", "semicircle", chart_key="heat_age",
                     column_span=1),
            _copy_asset(PEOPLE, "占比构成"),
        ])
        image = page.images[0]
        expected = (page.rows[0]["h_in"] - image.h_in) / 2
        self.assertAlmostEqual(image.rect[1], expected, places=6)
        # 盒子仍是分配的整高，绘制矩形才居中 —— 盒子高度决定行高。
        self.assertAlmostEqual(image.rect[1] + image.rect[3]
                               + (page.rows[0]["h_in"] - image.h_in
                                  - image.rect[1]), page.rows[0]["h_in"])

    def test_nothing_overlaps_anything(self):
        page = flow_layout(self.layout, [
            TextBlock("取暖电器换季热销", "title", "center", column_span=2),
            CardSpec("heat_age", "semicircle", chart_key="heat_age",
                     column_span=1),
            _copy_asset(PEOPLE, "占比构成"),
            CardSpec("heat_ratio_top5", "thermometer",
                     chart_key="heat_ratio_top5", column_span=2),
        ])
        boxes = [("image", page.images[0].x_in, page.images[0].y_in,
                  page.images[0].w_in, page.images[0].h_in)]
        for placed in page.cards:
            boxes.append((placed.name, placed.x_in, placed.y_in,
                          placed.w_in, placed.h_in))
        for placed in page.blocks:
            boxes.append((placed.name, placed.x_in, placed.y_in,
                          placed.w_in, placed.h_in))
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                ox = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
                oy = min(a[2] + a[4], b[2] + b[4]) - max(a[2], b[2])
                self.assertFalse(ox > 1e-9 and oy > 1e-9,
                                 f"{a[0]} 与 {b[0]} 重叠了")

    def test_image_never_leaves_the_canvas(self):
        page = flow_layout(self.layout, [_copy_asset(PEOPLE, "占比构成")])
        image = page.images[0]
        self.assertGreaterEqual(image.x_in, self.layout.margin_in - 1e-9)
        self.assertLessEqual(image.x_in + image.w_in,
                             self.layout.width_in - self.layout.margin_in
                             + 1e-9)

    def test_single_column_layout_also_places_images(self):
        layout = LayoutSpec(width_in=10.0, height_in=15.0)   # column_count=1
        page = flow_layout(layout, [
            CardSpec("heat_age", "semicircle", chart_key="heat_age"),
            _copy_asset(PEOPLE, "占比构成"),
        ])
        self.assertEqual(len(page.images), 1)
        self.assertAlmostEqual(page.images[0].w_in, layout.usable_width_in)
        # 单栏里插图自己占一行，落在卡片下方。
        self.assertGreater(page.images[0].y_in, page.cards[0].y_in)

    def test_span_beyond_the_column_count_is_rejected(self):
        block = _copy_asset(PEOPLE, "占比构成")
        block.column_span = 3
        with self.assertRaises(LayoutOverflowError):
            flow_layout(LayoutSpec(width_in=10.0, height_in=15.0), [block])


class TestFlattenAndRender(unittest.TestCase):
    """摊平与渲染：PPTX 里是 PICTURE，PNG 里真的画了图。"""

    def setUp(self):
        self.layout = LayoutSpec(width_in=10.0, height_in=15.0, margin_in=0.4,
                                 gutter_in=0.3, column_count=2,
                                 column_gutter_in=0.2)
        self.page = flow_layout(self.layout, [
            CardSpec("heat_age", "semicircle", chart_key="heat_age",
                     column_span=1),
            _copy_asset(PEOPLE, "占比构成"),
        ])

    def test_flatten_emits_an_image_element_with_its_draw_rect(self):
        flat = flatten(self.page)
        images = [e for e in flat.elements if e.type == "image"]
        self.assertEqual(len(images), 1)
        el = images[0]
        self.assertTrue(el.id.startswith("i0_"))
        self.assertEqual(el.role, "illustration")
        self.assertEqual(el.image_path, PEOPLE["local_path"])
        self.assertTrue(el.geometry["block"])
        self.assertEqual(len(el.geometry["image_rect"]), 4)
        self.assertEqual(el.geometry["semantic"], "占比构成")
        self.assertEqual(flat.layout["image_count"], 1)

    def test_rendered_pptx_contains_a_picture_and_a_written_spec(self):
        out = mkdtemp(prefix="illus_render_")
        rendered = render_layout(self.page, out)
        shapes = read_shapes(rendered["pptx"])
        pictures = [n for n, s in shapes.items() if s["shape_type"] == 13]
        self.assertTrue(any(n.startswith("i0_") for n in pictures),
                        f"没有画进图片：{sorted(shapes)}")
        self.assertEqual(rendered["flat_spec"].layout["image_count"], 1)

    def test_png_paints_the_asset_inside_its_rect(self):
        out = mkdtemp(prefix="illus_png_")
        rendered = render_layout(self.page, out)
        image = self.page.images[0]
        dx, dy, dw, dh = image.rect
        box = (round((image.x_in + dx) * 100), round((image.y_in + dy) * 100),
               round((image.x_in + dx + dw) * 100),
               round((image.y_in + dy + dh) * 100))
        with Image.open(rendered["preview"]) as im:
            crop = im.convert("RGB").crop(box)
        colours = crop.getcolors(maxcolors=1 << 24) or []
        # 源图主色是 (96,120,190)；白底上必须出现接近它的像素。
        blue = sum(n for n, c in colours
                   if abs(c[0] - 96) < 12 and abs(c[1] - 120) < 12
                   and abs(c[2] - 190) < 12)
        self.assertGreater(blue, 500, f"插图区没画出素材：{box}")

    def test_drawn_rect_preserves_the_source_aspect(self):
        image = self.page.images[0]
        _, _, dw, dh = image.rect
        self.assertAlmostEqual(dw / dh, ImageBlock(PEOPLE["local_path"]).aspect,
                               places=6)


class TestComposePicksIllustration(unittest.TestCase):
    """自动编排：流里有插图、素材来自素材库、顺序照用权重。"""

    COPY = ("取暖电器换季热销：五类小家电增速领跑\n"
            "入冬以来取暖电器进入销售旺季，平台成交额环比走高，多个细分品类出现两位数增长。\n"
            "从细分品类看，取暖电器的成交额环比增速居前，欧式快热炉等品类领跑。\n"
            "分年龄看，各年龄段消费者的取暖电器成交额占比不同，中年群体是主力。")

    def test_flow_contains_image_blocks_next_to_their_cards(self):
        layout = LayoutSpec(width_in=10.0, height_in=15.0, margin_in=0.4,
                            gutter_in=0.3, column_count=2,
                            column_gutter_in=0.2)
        flow = build_flow(self.COPY, layout=layout).flow
        images = [x for x in flow if isinstance(x, ImageBlock)]
        cards = [x for x in flow if isinstance(x, CardSpec)]
        self.assertEqual(len(cards), 2)
        self.assertEqual(len(images), 2)
        for image in images:
            self.assertTrue(os.path.exists(os.path.join(ROOT, image.path)))
            self.assertEqual(image.column_span, 1)
            self.assertIsNotNone(image.asset_id)

    def test_each_card_is_followed_by_its_illustration(self):
        layout = LayoutSpec(width_in=10.0, height_in=15.0, column_count=2)
        flow = build_flow(self.COPY, layout=layout).flow
        for i, item in enumerate(flow):
            if isinstance(item, CardSpec) and flow[i + 1:i + 2]:
                self.assertIsInstance(flow[i + 1], ImageBlock)

    def test_illustration_paths_come_from_the_library_order(self):
        """顺序照用 ``v_asset_search`` 的排序，调用方不再自己排。"""
        layout = LayoutSpec(width_in=10.0, height_in=15.0, column_count=2)
        flow = build_flow(self.COPY, layout=layout).flow
        for item in (x for x in flow if isinstance(x, ImageBlock)):
            expected = find_assets_by_semantic(item.semantic, DB_PATH)
            self.assertEqual(item.asset_id, expected[0]["asset_id"])
            # 库里存的是 Windows 路径，编排器统一成 POSIX 分隔符。
            self.assertEqual(item.path,
                             expected[0]["local_path"].replace("\\", "/"))

    def test_one_page_never_reuses_the_same_asset(self):
        layout = LayoutSpec(width_in=10.0, height_in=15.0, column_count=2)
        flow = build_flow(self.COPY, layout=layout).flow
        used = [x.asset_id for x in flow if isinstance(x, ImageBlock)]
        self.assertEqual(len(used), len(set(used)))

    def test_the_match_records_which_illustration_it_got(self):
        layout = LayoutSpec(width_in=10.0, height_in=15.0, column_count=2)
        result = build_flow(self.COPY, layout=layout)
        names = {x.name for x in result.flow if isinstance(x, ImageBlock)}
        matched = {m.illustration for m in result.matches if m.illustration}
        self.assertEqual(names, matched)
        self.assertTrue(matched)

    def test_placeholder_cards_get_no_illustration(self):
        """选型器判不适用 → 占位图，占位图本身就是一张图，不再配插图。"""
        real = [{"selected_template": None, "rationale": "分项过多",
                 "rejected": [{"template": "semicircle",
                               "reason": "MAX_SLICES"}]}]
        layout = LayoutSpec(width_in=10.0, height_in=15.0, column_count=2)
        with mock.patch("loop.compose.select", side_effect=lambda f: real[0]):
            flow = build_flow(self.COPY, layout=layout).flow
        cards = [x for x in flow if isinstance(x, CardSpec)]
        self.assertTrue(cards)
        self.assertTrue(all(c.kind == "placeholder" for c in cards))
        self.assertEqual([x for x in flow if isinstance(x, ImageBlock)], [])

    def test_multi_column_keeps_the_card_at_one_column_so_the_image_fits(self):
        """多栏里卡片让出一栏给插图，两者都占 1 栏、并排一行。"""
        layout = LayoutSpec(width_in=10.0, height_in=15.0, column_count=2)
        flow = build_flow(self.COPY, layout=layout).flow
        pairs = [(flow[i], flow[i + 1]) for i in range(len(flow) - 1)
                 if isinstance(flow[i], CardSpec)
                 and isinstance(flow[i + 1], ImageBlock)]
        self.assertEqual(len(pairs), 2)
        for card, image in pairs:
            self.assertEqual(card.column_span, 1)
            self.assertEqual(image.column_span, 1)

    def test_single_column_splits_the_row_instead_of_wasting_one(self):
        """单栏没有第二条栏位：把这一行切成「图表 66% + 插图 34%」。"""
        from loop.compose import ILLUSTRATED_CARD_SHARE
        layout = LayoutSpec(width_in=10.0, height_in=15.0)   # column_count=1
        flow = build_flow(self.COPY, layout=layout).flow
        cards = [x for x in flow if isinstance(x, CardSpec)]
        images = [x for x in flow if isinstance(x, ImageBlock)]
        self.assertTrue(cards and images)
        self.assertIsNotNone(cards[0].width_in)
        self.assertIsNotNone(images[0].width_in)
        self.assertAlmostEqual(
            cards[0].width_in + images[0].width_in + layout.gutter_in,
            layout.usable_width_in, places=6)
        self.assertAlmostEqual(cards[0].width_in,
                               round(layout.usable_width_in
                                     * ILLUSTRATED_CARD_SHARE, 6), places=6)


class TestMissingAssetDoesNotBlock(unittest.TestCase):
    """素材库查不到 → 静默跳过，只排图表，不抛异常。"""

    COPY = ("取暖电器换季热销：五类小家电增速领跑\n"
            "从细分品类看，取暖电器的成交额环比增速居前。\n"
            "分年龄看，各年龄段消费者的取暖电器成交额占比不同。")

    def test_empty_library_result_yields_no_image_but_still_lays_out(self):
        layout = LayoutSpec(width_in=10.0, height_in=15.0, margin_in=0.4,
                            gutter_in=0.3, column_count=2,
                            column_gutter_in=0.2)
        with mock.patch("loop.compose.find_assets_by_semantic", return_value=[]), \
                mock.patch("loop.compose.find_assets_by_theme", return_value=[]):
            flow = build_flow(self.COPY, layout=layout).flow
        self.assertEqual([x for x in flow if isinstance(x, ImageBlock)], [])
        page = flow_layout(layout, flow)          # 不抛异常
        self.assertGreaterEqual(len(page.cards), 1)
        self.assertEqual(page.images, [])

    def test_a_broken_library_does_not_block_either(self):
        layout = LayoutSpec(width_in=10.0, height_in=15.0, column_count=2)
        with mock.patch("loop.compose.find_assets_by_semantic",
                        side_effect=sqlite3_error()), \
                mock.patch("loop.compose.find_assets_by_theme",
                           side_effect=sqlite3_error()):
            flow = build_flow(self.COPY, layout=layout).flow
        self.assertEqual([x for x in flow if isinstance(x, ImageBlock)], [])
        self.assertTrue([x for x in flow if isinstance(x, CardSpec)])

    def test_non_icon_and_missing_paths_are_skipped(self):
        from loop.compose import _pick_illustration
        rows = [{"asset_id": 15, "kind": "page_image",
                 "local_path": "assets/page.png", "tag": "占比构成"},
                {"asset_id": 16, "kind": "icon", "local_path": "",
                 "tag": "占比构成"},
                {"asset_id": 26, "kind": "icon",
                 "local_path": PEOPLE["local_path"], "tag": "占比构成"}]
        with mock.patch("loop.compose.find_assets_by_semantic",
                        return_value=rows):
            # 无主题（``None``）时只走图表语义那条路 —— S6 之后签名多了一个 theme。
            block, basis = _pick_illustration(None, "占比构成", DB_PATH, set())
        self.assertIsNotNone(block)
        self.assertEqual(block.asset_id, 26)
        self.assertEqual(basis, "chart_semantic")

    def test_used_assets_are_not_picked_twice(self):
        """同一页里不重复用同一张图标：第二段拿了 26，第三段只能退到 27。"""
        from loop.compose import _pick_illustration
        used = set()
        first, _ = _pick_illustration(None, "占比构成", DB_PATH, used)
        second, _ = _pick_illustration(None, "占比构成", DB_PATH, used)
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertNotEqual(first.asset_id, second.asset_id)
        self.assertEqual(used, {first.asset_id, second.asset_id})


class TestBackwardCompatible(unittest.TestCase):
    """不配插图的流与 0.1/0.2 行为一致；旧演示仍装得下。"""

    def test_a_flow_without_images_is_unchanged(self):
        layout = LayoutSpec(width_in=10.0, height_in=15.0, margin_in=0.4,
                            gutter_in=0.3, column_count=2,
                            column_gutter_in=0.2)
        flow = [TextBlock("取暖电器换季热销", "title", "center", column_span=2),
                TextBlock("入冬以来取暖电器进入销售旺季。", "body",
                          column_span=1),
                CardSpec("heat_age", "semicircle", chart_key="heat_age",
                         column_span=1)]
        page = flow_layout(layout, flow)
        self.assertEqual(page.images, [])
        self.assertEqual(len(page.cards), 1)
        self.assertEqual(len(page.blocks), 2)
        # 标题独占整行；导语与卡片分享下一行（各占 1 栏）。
        self.assertAlmostEqual(page.blocks[0].x_in, 0.4)
        self.assertAlmostEqual(page.blocks[0].y_in, 0.4)
        self.assertAlmostEqual(page.blocks[1].x_in, 0.4)
        self.assertAlmostEqual(page.cards[0].x_in, 5.1)

    def test_expected_flow_size_for_the_reference_copy(self):
        """图文并茂 1.0 之后：标题 + 导语 + 2 段正文 + 2 卡 + 2 插图 = 8 项。"""
        copy = ("取暖电器换季热销：五类小家电增速领跑\n"
                "入冬以来取暖电器进入销售旺季，多个细分品类出现两位数增长。\n"
                "从细分品类看，取暖电器的成交额环比增速居前。\n"
                "分年龄看，各年龄段消费者的取暖电器成交额占比不同。")
        layout = LayoutSpec(width_in=10.0, height_in=15.0, column_count=2)
        flow = build_flow(copy, layout=layout).flow
        self.assertEqual(sum(1 for x in flow if isinstance(x, TextBlock)), 4)
        self.assertEqual(sum(1 for x in flow if isinstance(x, CardSpec)), 2)
        self.assertEqual(sum(1 for x in flow if isinstance(x, ImageBlock)), 2)
        self.assertEqual(len(flow), 8)

    def test_page_dict_round_trips_the_image_fields(self):
        layout = LayoutSpec(width_in=10.0, height_in=15.0, column_count=2)
        page = flow_layout(layout, [_copy_asset(PEOPLE, "占比构成")])
        doc = page.to_dict()
        self.assertEqual(len(doc["images"]), 1)
        entry = doc["images"][0]
        for key in ("path", "style", "align", "column_span", "rect",
                    "asset_id", "semantic"):
            self.assertIn(key, entry)
        self.assertEqual(entry["semantic"], "占比构成")


def sqlite3_error():
    import sqlite3
    return sqlite3.OperationalError("database is locked")


if __name__ == "__main__":
    unittest.main()
