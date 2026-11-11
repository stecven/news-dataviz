"""Step 19：统一色板 + 文本角色字号表（用户 m04549）。

验收闸口（用户原文）：
- 渲染层不再有硬编码的颜色值和 Pt(10)；
- 色板与字号表有单一来源，改一处全流水线生效；
- 半圆五色相邻可区分、文本与背景对比度足够；
- 全量测试仍全绿，未改 solve/selector/models/pipeline 逻辑。

本文件按「先写测试」的顺序建立，RED 时这些断言应全部失败。
"""
import os
import re
import unittest

from loop import palette as P

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RENDER_FILES = ("loop/render.py", "loop/render_arc.py",
                "loop/render_thermo.py", "loop/preview.py")

#: 渲染层允许出现的十六进制色值白名单：只能是「引用表达式」而不是字面量。
_HEX_LITERAL = re.compile(r"""["'](?:#[0-9A-Fa-f]{3,8}|[0-9A-Fa-f]{6})["']""")


def _read(rel: str) -> str:
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


class TestPaletteDefinition(unittest.TestCase):
    """色板本身的形状：角色齐全、色值合法、取色不静默。"""

    def test_user_six_roles_plus_the_two_added_ones(self):
        # 用户 m04549 原定 6 个 + 裁定补的 accent_3 + 实现必须补的 neutral_mid
        for role in ("primary", "secondary", "neutral_dark", "neutral_light",
                     "accent_1", "accent_2", "accent_3", "neutral_mid", "surface"):
            self.assertIn(role, P.PALETTE, f"色板缺少角色 {role}")

    def test_every_value_is_six_hex_digits(self):
        for role, value in P.PALETTE.items():
            self.assertRegex(value, r"^[0-9A-F]{6}$", f"{role} 色值格式不对")

    def test_unknown_role_raises_instead_of_defaulting(self):
        # 拼错角色名必须炸，不能静默画成某个颜色
        with self.assertRaises(KeyError) as cm:
            P.color("primaryy")
        self.assertIn("primaryy", str(cm.exception))

    def test_role_aliases_resolve_to_palette_roles(self):
        self.assertEqual(P.color("liquid"), P.PALETTE["primary"])
        self.assertEqual(P.color("track"), P.PALETTE["surface"])
        self.assertEqual(P.color("text"), P.PALETTE["neutral_dark"])

    def test_sector_colors_follow_fixed_order(self):
        # 半圆取色必须确定：同一份数据每跑一次颜色一致
        seq = P.sector_colors()
        self.assertEqual(len(seq), 5)
        self.assertEqual(seq, [P.PALETTE[r] for r in P.SECTOR_ROLES])
        self.assertEqual(P.sector_colors(3), seq[:3])


class TestContrastGates(unittest.TestCase):
    """用户闸口：相邻扇区可区分、文本与背景对比度足够。"""

    def test_adjacent_sectors_are_distinguishable(self):
        seq = P.sector_colors()
        for i in range(len(seq)):
            a, b = seq[i], seq[(i + 1) % len(seq)]
            d = P.delta_e(a, b)
            self.assertGreaterEqual(
                d, P.MIN_ADJACENT_DELTA_E,
                f"扇区 {i+1}/{i+2} 色差过小 ΔE={d:.1f}")

    def test_all_sector_pairs_not_just_adjacent(self):
        # 循环配色时首尾也相邻，上面已覆盖；这里保证任意两色不至于撞车
        seq = P.sector_colors()
        for i in range(len(seq)):
            for j in range(i + 1, len(seq)):
                d = P.delta_e(seq[i], seq[j])
                self.assertGreater(d, 10.0, f"扇区 {i+1} 与 {j+1} 太像 ΔE={d:.1f}")

    def test_text_on_canvas_and_light_neutral_meets_aa(self):
        for bg in ("surface", "neutral_light"):
            r = P.contrast_ratio(P.PALETTE["neutral_dark"], P.PALETTE[bg])
            self.assertGreaterEqual(
                r, P.MIN_TEXT_CONTRAST,
                f"文本色在 {bg} 上对比度 {r:.2f} 不足")

    def test_check_separation_reports_no_problem(self):
        self.assertEqual(P.check_separation(), [])


class TestFontScale(unittest.TestCase):
    """字号表：5 个设计角色、层级递增、现有 role 全部有映射。"""

    def test_five_design_roles_all_present(self):
        for role in ("title", "subtitle", "body", "label", "note"):
            self.assertIn(role, P.FONT_SIZES)

    def test_sizes_are_strictly_descending(self):
        sizes = [P.FONT_SIZES[r] for r in
                 ("title", "subtitle", "body", "label", "note")]
        self.assertEqual(sizes, sorted(sizes, reverse=True))
        self.assertEqual(len(set(sizes)), len(sizes), "字号不能有并列档")

    def test_every_role_in_the_pipeline_has_a_mapping(self):
        # 全流水线实际出现过的文本 role（out/demo/end_to_end/*/pagespec.json 实测）
        used = {"title", "scale_note", "center", "label", "legend", "value"}
        for role in used:
            self.assertIn(role, P.ROLE_TO_FONT,
                          f"现有 role {role} 没有字号映射")

    def test_title_is_biggest_and_note_is_smallest(self):
        self.assertEqual(P.font_size("title"), max(P.FONT_SIZES.values()))
        self.assertEqual(P.font_size("scale_note"), min(P.FONT_SIZES.values()))

    def test_title_and_value_are_no_longer_the_same_size(self):
        # m04383 复盘的直接症状：标题和「10倍」同为 Pt(10)
        self.assertGreater(P.font_size("title"), P.font_size("value") * 1.5)

    def test_line_height_scales_with_font(self):
        self.assertGreater(P.line_height_px("title"),
                           P.line_height_px("scale_note"))

    def test_design_role_names_resolve_to_their_own_size(self):
        # 回归：font_size() 曾经只查 ROLE_TO_FONT，而映射表里没有
        # subtitle/body 这两个键，于是 14 pt 的副标题被静默降级成 note 的
        # 8 pt（缩水 43%），不报错也没人发现。设计角色名必须直查字号表。
        for role in ("title", "subtitle", "body", "label", "note"):
            self.assertEqual(P.font_size(role), P.FONT_SIZES[role],
                             f"设计角色 {role} 被错误地降级映射了")
        self.assertEqual(P.font_size("subtitle"), 14)
        self.assertEqual(P.font_size("body"), 11)


class TestRenderersUseSingleSource(unittest.TestCase):
    """闸口：渲染层不再硬编码颜色值与 Pt(10)。"""

    def test_no_hardcoded_hex_colour_literals(self):
        for rel in RENDER_FILES:
            src = _read(rel)
            hits = _HEX_LITERAL.findall(src)
            self.assertEqual(
                hits, [],
                f"{rel} 里仍有硬编码色值字面量：{hits}")

    def test_no_hardcoded_pt10_font_size(self):
        for rel in ("loop/render.py", "loop/render_arc.py",
                    "loop/render_thermo.py"):
            src = _read(rel)
            self.assertNotIn("Pt(10)", src, f"{rel} 仍有 Pt(10)")

    def test_renderers_import_the_palette_module(self):
        # 色板是单一来源，但取用路径有两条：适配器可以直接 `from loop import
        # palette`，也可以经由 `loop.text_style` 这个统一套样式的小模块拿到
        # 字号与文本色（避免平级适配器互相 import）。两条都算接上单一来源，
        # 硬编码才是被禁止的（由上一条字面量扫描把关）。
        for rel in RENDER_FILES:
            src = _read(rel)
            self.assertTrue(
                any(token in src for token in
                    ("loop.palette", "from loop import palette", "loop.text_style")),
                f"{rel} 没有从色板取色/取字号")

    def test_preview_font_comes_from_the_scale(self):
        src = _read("loop/preview.py")
        # 预览层原来写死 _font(14)，现在必须按 role 取
        self.assertNotIn("_font(14)", src)


class TestTemplatesDrawFromPalette(unittest.TestCase):
    """模板默认色必须等于色板里的角色色，改色板即改图。"""

    def test_thermometer_colours_match_palette(self):
        from loop.templates import get_template
        params = get_template("thermometer").params
        self.assertEqual(params["color_liquid"]["default"], P.PALETTE["primary"])
        self.assertEqual(params["color_track"]["default"], P.PALETTE["surface"])
        # 刻度线与外圈是「发丝线」档（原版报纸的浅暖灰 C9C9C9），不是占位图的
        # 中间调；两者同属中性色但用途不同，故是 neutral_hairline。
        self.assertEqual(params["color_outline"]["default"],
                         P.PALETTE["neutral_hairline"])
        self.assertEqual(params["color_tick"]["default"],
                         P.PALETTE["neutral_hairline"])

    def test_semicircle_sector_colours_are_the_palette_sequence(self):
        from loop.templates import get_template
        params = get_template("semicircle").params
        seq = P.sector_colors()
        for i, expected in enumerate(seq, start=1):
            self.assertEqual(params[f"color_sector_{i}"]["default"], expected)

    def test_text_size_param_matches_label_role(self):
        # 模板里的 text_size 是历史遗留的单一字号；它现在只作为 label 档的
        # 兼容默认值存在，必须与字号表一致，不能各说各话。
        from loop.templates import get_template
        for name in ("thermometer", "semicircle"):
            self.assertEqual(
                get_template(name).params["text_size"]["default"],
                P.FONT_SIZES["label"])


class TestPlaceholderDrawsFromPalette(unittest.TestCase):
    """占位图的三档灰也必须来自色板，不能各写一份。"""

    def test_placeholder_greys_are_palette_colours(self):
        import importlib.util
        rel = "scripts/make_placeholder.py"
        path = os.path.join(ROOT, *rel.split("/"))
        spec = importlib.util.spec_from_file_location("_mk_ph", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        def rgb(role):
            h = P.color(role)
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)

        self.assertEqual(mod.GREY_DARK, rgb("placeholder_stroke"))
        self.assertEqual(mod.GREY_MID, rgb("placeholder_mid"))
        self.assertEqual(mod.GREY_LIGHT, rgb("placeholder_light"))


if __name__ == "__main__":
    unittest.main()
