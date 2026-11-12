"""卡片内文本：把折行结果与字号写进契约（Spec §4 D10）。

为什么折行结果要进契约
----------------------
同一段卡片内文本，PPTX 端点靠 ``word_wrap``、PNG 端点靠 ``preview._draw_text``
逐字折行 —— 两个后端各折一次，结果就可能不一样（一个 3 行、一个 4 行），
网页端照抄哪个都不对。所以折行由求解层算一次、写进元素（``lines`` /
``font_pt``，Spec §5.6 的三个新字段之二），三个渲染端只是照抄：
PPTX 关掉自动换行按行插换行，PNG 逐行画，网页端直接排。

本模块是**唯一**调用 ``text_flow.wrap`` 给卡片元素折行的地方 —— 唯一出口
才好钉住「契约里的行数与预览画出的行数同口径」（见
``tests/test_step35_card_text.py::test_wrap_matches_preview_for_every_card_text_element``）。

注入点
------
``loop/layout.py::flow_layout`` 在构造 ``PlacedCard`` 时调
``annotate_card_text(spec, palette.spec_scale(spec))``。缩放比一律走
``palette.spec_scale``（``flatten()`` 用的也是它），不另立一套。
"""
from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from loop import palette, text_flow
from loop.models import ElementSpec, PageSpec

if TYPE_CHECKING:                       # 只在类型检查时导入：运行期导入
    from loop.layout import PageLayoutSpec   # 会与 layout → card_text 成环。


def wrap_element(el: ElementSpec, scale: float) -> list:
    """把元素文本按**自己的盒宽**折行。折行口径的唯一出口。"""
    return text_flow.wrap(el.text, el.role, el.w_in, scale)


def annotate_card_text(spec: PageSpec, scale: float) -> PageSpec:
    """把卡片内文本的折行结果与字号写进元素（Spec §4 D10）。

    跳过三种情况并保持 lines=None：非 text 元素、text 为空、盒宽 <= 0。
    最后一种不是"防御性编程"——卡片几何由求解器产出，求解失败的卡片可能带
    过期尺寸，读图纸的人宁可看到 None 也不该看到异常。

    返回**新的** PageSpec；一个元素都没标注时原样返回入参（幂等的依据）。
    """
    out = []
    changed = False
    for el in spec.elements:
        if (el.type == "text" and el.text and el.lines is None and el.w_in > 0):
            out.append(replace(el, lines=wrap_element(el, scale),
                               font_pt=palette.scaled_font_size(el.role, scale)))
            changed = True
        else:
            out.append(el)
    return replace(spec, elements=out) if changed else spec


def annotate_layout(layout: PageLayoutSpec) -> PageLayoutSpec:
    """对整版里每张卡片各自标注；整版文本块**不动**。

    每张卡片用自己的缩放比（``palette.spec_scale(card.spec)``）——同一份报纸里
    大卡片小卡片字号不同，折行宽度也随之不同，共用一个缩放比会把行折错。

    整版块（``layout.blocks``）不进这里：它们的折行早在排版时就写进了
    ``PlacedBlock.lines``，``flatten()`` 再把同一份写进 ``geometry["lines"]``。
    """
    cards = []
    changed = False
    for card in layout.cards:
        spec = annotate_card_text(card.spec, palette.spec_scale(card.spec))
        if spec is card.spec:
            cards.append(card)
        else:
            cards.append(replace(card, spec=spec))
            changed = True
    return replace(layout, cards=cards) if changed else layout
