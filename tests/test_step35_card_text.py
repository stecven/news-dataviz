"""P1 Task 5：卡片内文本的折行结果与字号写进契约（Spec §4 D10）。

对应验收：

* 排版层的折行与 PNG 预览 ``_draw_text`` **同口径**（一条不等就失败）
  → ``test_wrap_matches_preview_for_every_card_text_element``
* 写进契约的 ``lines`` 是**全量**折行，不截到 4 行（4 行是渲染裁切，不是数据）
  → ``test_lines_are_not_truncated_to_four``
* ``font_pt`` 由 ``palette.scaled_font_size(role, scale)`` 唯一决定
  → ``test_font_pt_equals_palette_scaled_font_size``
* 重复标注幂等，且第二次不重算折行
  → ``test_annotation_is_idempotent``
* 非文本 / 空文本 / 非正盒宽的元素保持 ``lines is None`` 且不抛
  → ``test_non_text_and_empty_text_keep_lines_none``
* ``flow_layout`` 出来的卡片**真的**带上了折行（接线接上了）
  → ``test_flow_layout_annotates_every_card``

为什么用「记录式 draw 替身」而不是改 ``preview.py``
--------------------------------------------------
契约要冻结的是「预览**实际画出来的行**」。``_draw_text`` 只通过 ``textlength``
量宽、通过 ``text`` 画行，所以喂它一个只实现这两个方法的假 draw，就能把它的
折行结果原样录下来——``preview.py`` 一行都不用动，也不会把「为了让两边相等」
变成执行者能自己决定的事（Spec §4 D10 的前提是两条路径本来就同口径）。

夹具路径一律取自 ``tests.contract_fixtures.LEGACY_DIR``，不硬编码目录。
"""
import os
import unittest
from unittest import mock

from loop import card_text, palette, preview, text_flow
from loop.contract import load_layout
from loop.layout import CardSpec, LayoutSpec, flow_layout
from loop.models import ElementSpec, PageSpec, Scale
from tests.contract_fixtures import LEGACY_DIR

#: 两份入库夹具（``out/`` 不入库，它们才是长期可复现的证据）。
AUTO_LAYOUT_FIXTURE = "auto_layout.pagelayout.json"
PLAIN_FIXTURE = "_plain.pagelayout.json"
FIXTURES = (PLAIN_FIXTURE, AUTO_LAYOUT_FIXTURE)

#: 真实的 role → 基础字号（pt），来自 ``palette.FONT_SIZES`` 经 ``ROLE_TO_FONT``。
BASE_FONT_PT = {"title": 20, "scale_note": 8, "label": 9, "value": 11,
                "legend": 9, "center": 14}


class _Recorder:
    """假 draw：``_draw_text`` 只用 ``textlength`` 量宽、用 ``text`` 画行。"""

    def __init__(self, font):
        self.font, self.drawn = font, []

    def textlength(self, text, font=None):
        return (font or self.font).getlength(text)

    def text(self, xy, text, fill=None, font=None):
        self.drawn.append(text)


def _preview_lines(el, scale):
    """让 ``preview._draw_text`` 真的画一遍，录下它**画出的行**（内部已截到 4 行）。"""
    px = int(round(palette.scaled_font_size(el.role, scale)
                   * preview._PX_PER_PT))
    rec = _Recorder(preview._font(px))
    box = (0, 0, el.w_in * preview.PX_PER_IN, el.h_in * preview.PX_PER_IN)
    preview._draw_text(rec, box, el.text, el.role, "center", scale)
    return rec.drawn


def _fixture_layout(fixture: str):
    return load_layout(os.path.join(LEGACY_DIR, fixture)).layout


def _card_text_elements(layout):
    """``(card, element, scale)``：卡片的 ``type == "text"`` 且 ``text`` 非空。"""
    for card in layout.cards:
        scale = palette.spec_scale(card.spec)
        for el in card.spec.elements:
            if el.type == "text" and el.text:
                yield card, el, scale


#: 夹具样本太短（实测最长折行只有 1 行），只比夹具的话「把折行改坏」也能全绿。
#: 补一条**真的会折行**的长文本，让两条路径在「逐字折行」这件事上正面对撞。
_SYNTHETIC_LONG = "某省上半年规模以上工业增加值同比增长百分之七点三创近三年新高"


def _synthetic_text_elements():
    """(el, scale)：构造会折成 4 行以上的文本元素 + 若干不同 role / 盒宽的样本。"""
    out = []
    for role in ("title", "value", "label", "legend", "scale_note", "center"):
        for w in (2.0, 1.2, 0.8, 3.5):
            out.append((ElementSpec(
                id=f"syn_{role}_{w}", type="text", role=role,
                x_in=0.0, y_in=0.0, w_in=w, h_in=0.6, text=_SYNTHETIC_LONG), 1.0))
    # 一个「首字符就比盒宽还宽」的极端盒宽：两条路径都该把它单成一行的行。
    out.append((ElementSpec(id="syn_narrow", type="text", role="title",
                            x_in=0.0, y_in=0.0, w_in=0.05, h_in=0.6,
                            text="一二三四五六"), 1.0))
    return out


def _spec(elements, w_in=4.0, h_in=3.0):
    return PageSpec(width_in=w_in, height_in=h_in, chart_key="probe",
                    chart_title="probe", scale=Scale(v_max=100.0, h_in=2.0,
                                                     unit="%"),
                    elements=elements)


class TestCardTextWrap(unittest.TestCase):

    def test_wrap_matches_preview_for_every_card_text_element(self):
        # Review Focus #3 / Spec §4 D10 的判据。**一条不等就停下报告**，
        # 不许反过来去改 preview.py / text_flow.py 把两边「统一」
        # ——那代表「两条折行实现同口径」这个前提不成立，得用户拍板。
        #
        # 口径边界（评审补丁 C）：等价性只在**无结尾空段落**的输入上成立。
        # ``preview._draw_text`` 结尾是 ``if cur: lines.append(cur)``
        # （``loop/preview.py:158``），会丢掉落尾空行：``"a\n"`` 在排版层是
        # ``["a", ""]``、在预览是 ``["a"]``。真换行本身（``"\n"``，len 1 的
        # 字符，不是反斜杠+n）两边一致。结尾空段落要不要统一属用户拍板，
        # 不在本 Task 范围；**不许**改 ``preview.py``（R14）。
        checked = cards_seen = longest = 0
        for fixture in FIXTURES:
            layout = _fixture_layout(fixture)
            for card, el, scale in _card_text_elements(layout):
                cards_seen = max(cards_seen, len(layout.cards))
                checked += 1
                mine = card_text.wrap_element(el, scale)
                longest = max(longest, len(mine))
                theirs = _preview_lines(el, scale)
                # 逐字折行不该丢字：把行拼回去必须等于原文去掉真换行
                # （``\n`` 是段落分隔，折行只在段落内部发生）。
                self.assertEqual("".join(mine), (el.text or "").replace("\n", ""),
                                 f"{fixture} / {card.name} / {el.id}: 折行丢了字")
                if mine[:4] != theirs:
                    self.fail(
                        f"{fixture} / 卡片 {card.name} / 元素 {el.id} "
                        f"(role={el.role}, w_in={el.w_in}, scale={scale}): "
                        f"排版层折行与预览 _draw_text 不等\n"
                        f"  card_text.wrap_element(...) = {mine!r}\n"
                        f"  preview._draw_text 画出     = {theirs!r}")
        # 空夹具会让这条静默通过（``_plain`` 一张卡片也没有）。
        self.assertGreater(checked, 0, "两份夹具里一个卡片文本元素都没有")

        # 夹具样本最长只有 1 行 —— 上面的比对其实没碰到「折行」。所以再用
        # 会折成 4 行以上的长文本正面对撞一次；同时钉住「预览截 4 行、
        # 排版层给全量」这件事。
        synthetic_longest = 0
        for el, scale in _synthetic_text_elements():
            mine = card_text.wrap_element(el, scale)
            theirs = _preview_lines(el, scale)
            synthetic_longest = max(synthetic_longest, len(mine))
            # 同上：第 5 行起也必须是真内容，拼回去不许丢字（钉住「:4 之后塞垃圾」）。
            self.assertEqual("".join(mine), (el.text or "").replace("\n", ""),
                             f"合成样本 {el.id}: 折行丢了字")
            if mine[:4] != theirs:
                self.fail(
                    f"合成样本 {el.id} (role={el.role}, w_in={el.w_in}): "
                    f"排版层折行与预览 _draw_text 不等\n"
                    f"  card_text.wrap_element(...) = {mine!r}\n"
                    f"  preview._draw_text 画出     = {theirs!r}")
        self.assertGreater(synthetic_longest, 4,
                           "合成长文本没折出 4 行以上，这条对撞没有意义")

    def test_lines_are_not_truncated_to_four(self):
        # 4 行是 ``preview._draw_text`` 的**渲染裁切**（``lines[:4]``），
        # 不该出现在契约里——契约存的是折行全量。
        #
        # 只比夹具是不够的（评审实测）：夹具最长折行只有 **1** 行，把
        # ``lines`` 截到 1/2/3/4/5 行都抓不到。所以夹具那圈继续作为
        # 「真实数据也全量」的锚，另外再用 ``_synthetic_text_elements()``
        # （本文件现成的、会折成 4 行以上的样本，非捏造夹具数据）跑一圈，
        # 并断言**确实折出 4 行以上**——不然这条对撞没有意义。
        checked = longest = 0
        for fixture in FIXTURES:
            layout = _fixture_layout(fixture)
            annotated = card_text.annotate_layout(layout)
            for card, el, scale in _card_text_elements(annotated):
                checked += 1
                longest = max(longest, len(el.lines))
                self.assertEqual(el.lines, card_text.wrap_element(el, scale),
                                 f"{fixture} / {card.name} / {el.id}: "
                                 f"契约里的 lines 不是全量折行")
                self.assertEqual("".join(el.lines), (el.text or "").replace("\n", ""),
                                 f"{fixture} / {card.name} / {el.id}: "
                                 f"契约里的 lines 丢了字（第 5 行起也得是真内容）")
        self.assertGreater(checked, 0, "两份夹具里一个卡片文本元素都没有")

        for el, scale in _synthetic_text_elements():
            got = card_text.annotate_card_text(_spec([el]), scale).elements[0].lines
            longest = max(longest, len(got))
            self.assertEqual(got, card_text.wrap_element(el, scale), el.id)
            self.assertEqual("".join(got), (el.text or "").replace("\n", ""), el.id)
        self.assertGreater(longest, 4, "样本没折出 4 行以上，这条对撞没有意义")

    def test_font_pt_equals_palette_scaled_font_size(self):
        # 基础字号先钉住：role → FONT_SIZES 经 ROLE_TO_FONT。
        for role, pt in BASE_FONT_PT.items():
            self.assertEqual(palette.scaled_font_size(role, 1.0), pt, role)

        checked = 0
        for fixture in FIXTURES:
            layout = card_text.annotate_layout(_fixture_layout(fixture))
            for card in layout.cards:
                scale = palette.spec_scale(card.spec)
                for el in card.spec.elements:
                    if el.lines is None:
                        continue
                    checked += 1
                    # 唯一口径：contract 里的 font_pt 就是色板的缩放结果。
                    self.assertEqual(
                        el.font_pt, palette.scaled_font_size(el.role, scale),
                        f"{fixture} / {card.name} / {el.id}")
                    # 「基础 pt × scale 再 round(…,2)」在**未触到钳位**时成立；
                    # 触到 [MIN_FONT_PT, MAX_FONT_PT] 时以钳位后的值为准
                    # （``heat_age`` 的 note 类 role：8 × 0.6074 = 4.86 < 6.0）。
                    raw = round(palette.font_size(el.role) * scale, 2)
                    expect = max(palette.MIN_FONT_PT,
                                 min(palette.MAX_FONT_PT, raw))
                    self.assertEqual(el.font_pt, expect,
                                     f"{fixture} / {card.name} / {el.id}")
        self.assertGreater(checked, 0, "没有任何元素被标注")

    def test_annotation_is_idempotent(self):
        for fixture in FIXTURES:
            once = card_text.annotate_layout(_fixture_layout(fixture))
            # 第二次标注不许再算折行：``wrap_element`` 一旦被调到就炸。
            with mock.patch.object(card_text, "wrap_element",
                                   side_effect=AssertionError(
                                       "二次标注又重算了折行")):
                twice = card_text.annotate_layout(once)
            self.assertEqual(twice.to_dict(), once.to_dict(), fixture)

    def test_non_text_and_empty_text_keep_lines_none(self):
        def el(_id, _type, **kw):
            kw.setdefault("role", "label")
            kw.setdefault("w_in", 1.0)
            kw.setdefault("h_in", 0.3)
            return ElementSpec(id=_id, type=_type, x_in=0.0, y_in=0.0, **kw)

        elements = [
            el("r", "rect", fill="FFFFFF"),
            el("e", "ellipse"),
            el("a", "arc"),
            el("t", "ticks"),
            el("o", "outline"),
            el("c", "chart"),
            el("empty", "text", text=""),
            el("none", "text", text=None),
            el("zero", "text", w_in=0.0, text="盒宽为 0 也要活着回来"),
            el("neg", "text", w_in=-1.5, text="负盒宽同样不许抛"),
        ]
        out = card_text.annotate_card_text(_spec(elements), 1.0)
        for before, after in zip(elements, out.elements):
            self.assertIsNone(after.lines, before.id)
            self.assertIsNone(after.font_pt, before.id)
        # 未被标注的规格原样带过（不改坐标、不改其它字段）。
        self.assertEqual([e.__dict__ for e in out.elements],
                         [e.__dict__ for e in elements])

    def test_flow_layout_annotates_every_card(self):
        # 这条钉住「接线真的接上了」：card_text 单测全绿但忘了改
        # ``flow_layout`` 是这一步最可能的失误。走公开入口 ``flow_layout``。
        page = flow_layout(LayoutSpec(), [
            CardSpec("thermo", "thermometer", chart_key="heat_ratio_top5",
                     title="热力比", width_in=9.2, height_in=4.6),
            CardSpec("ph", "placeholder", title="占位", width_in=4.45,
                     height_in=4.6),
        ])
        self.assertTrue(page.cards, "没有卡片就没什么可断言的")

        annotated = 0
        for card in page.cards:
            scale = palette.spec_scale(card.spec)
            for el in card.spec.elements:
                if el.type != "text" or not el.text:
                    continue
                annotated += 1
                self.assertIsNotNone(el.lines, f"{card.name} / {el.id}")
                self.assertTrue(el.lines, f"{card.name} / {el.id}")
                self.assertEqual(el.lines, text_flow.wrap(el.text, el.role,
                                                          el.w_in, scale),
                                 f"{card.name} / {el.id}")
                self.assertIsNotNone(el.font_pt, f"{card.name} / {el.id}")
        self.assertGreater(annotated, 0, "卡片里没有带文本的元素")


if __name__ == "__main__":
    unittest.main()
