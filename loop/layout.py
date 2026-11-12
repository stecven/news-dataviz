"""自由布局引擎 0.1（用户 m05945）：把一组卡片流式排进一张整版画布。

范围（本轮刻意不做）
--------------------
* 只做**流式排版**：按输入顺序从左到右、从上到下放，不做多栏对齐、不做力导向。
* 只排**纯卡片**：不和正文文本、大标题混排。
* **不改卡片内部**：卡片自己的坐标由 build_pagespec 决定，本模块只分配外部坐标。
* 放不下就**整体换行**——绝不截断卡片。

尺寸从哪来
----------
两种，按 `CardSpec` 是否给了 `width_in` / `height_in` 决定：

* 没给 → 调 `build_pagespec` 不传 target，用卡片「按内容长大」的自然尺寸；
* 给了 → 当 target 传给 `build_pagespec`，由第 23 步的适配器缩进去。

自然尺寸比可用宽度还宽时（温度计卡片就有 10.52 in，10 in 的版面装不下），
要么在 `CardSpec` 里给预设尺寸，要么把 `LayoutSpec.fit_oversized` 打开——
打开后引擎按可用宽度等比缩一张，而不是把卡片截断。
"""
import dataclasses
import functools
import os
from dataclasses import dataclass, field

from PIL import Image

from loop import palette, text_flow
from loop.fit import BoundaryError
from loop.models import ElementSpec, PageSpec, Scale
from loop.selector import SEMANTIC_OTHER

#: 插图版式：``icon`` 不铺满、按比例居中留白（装饰插图，默认）；
#: ``cover`` 铺满分配的盒子（会裁切超出的部分，本轮未用上，留给后续）。
IMAGE_STYLES = ("icon", "cover")


@functools.lru_cache(maxsize=256)
def _resolve_image(path: str) -> str:
    """把 ``assets/icons/x.png`` 这类仓库相对路径解成可打开的绝对路径。"""
    from loop.render import resolve_image_path
    return resolve_image_path(path)


@functools.lru_cache(maxsize=256)
def image_size_in(path: str) -> tuple:
    """图片的像素尺寸（按 100 px/in 折算成英寸）。

    插图的高度必须由**真实宽高比**推出来：不能变形，也不能让排版层凭一个
    猜的宽高比算高度（猜错就是重叠或留白）。只读文件头，不解码整张图。
    """
    with Image.open(_resolve_image(path)) as pic:
        w, h = pic.size
    if w <= 0 or h <= 0:
        raise ValueError(f"image has zero extent: {path} ({w}x{h})")
    return (w / 100.0, h / 100.0)


def fit_rect_in(box_w: float, box_h: float, aspect: float,
                align: str = "center") -> tuple:
    """在 ``box_w × box_h`` 里按 ``aspect``（宽/高）居中放一张图。

    返回 ``(dx, dy, w, h)`` —— 相对盒子左上角的偏移与图片真实绘制尺寸。
    图片永远不变形：只缩不放，两个方向同时按同一个比例。
    """
    if aspect <= 0:
        raise ValueError(f"aspect must be > 0, got {aspect!r}")
    if box_w <= 0 or box_h <= 0:
        raise ValueError(f"box must be positive, got {box_w}×{box_h}")
    w = min(box_w, box_h * aspect)
    h = w / aspect
    if align == "left":
        dx = 0.0
    elif align == "right":
        dx = box_w - w
    else:
        dx = (box_w - w) / 2.0
    return (round(dx, 6), round((box_h - h) / 2.0, 6), round(w, 6), round(h, 6))


class LayoutFitError(Exception):
    """卡片被缩到读不了（用户 m05995 的保底防线）。

    溢出策略默认「缩」——但缩不能无限：宽度逼着缩之后，如果说明文字连
    ``palette.MIN_FONT_PT``（6pt）都不到，那就不是「排得下」而是「糊成一团」，
    此时必须报错，让人去改版面或换预设尺寸，而不是交出一张看不清的版面。
    """

    def __init__(self, card: str, detail: str, min_pt=None, floor_pt=None):
        self.card = card
        self.detail = detail
        self.min_pt = min_pt
        self.floor_pt = floor_pt
        bits = [f"卡片 {card} 缩得太小，已无法阅读", detail]
        if min_pt is not None and floor_pt is not None:
            bits.append(f"说明文字仅 {min_pt:.1f}pt，低于下限 {floor_pt:g}pt")
        super().__init__("：".join(bits))


class LayoutOverflowError(Exception):
    """整版装不下这组卡片。

    带 ``placed``（已经排好的卡片）与 ``remaining``（排不下的卡片描述），
    调用方据此知道「差多少」——不做静默越界，也不悄悄缩水。
    """

    def __init__(self, reason: str, placed=(), remaining=(), needed_h=None,
                 page_h=None):
        self.reason = reason
        self.placed = list(placed)
        self.remaining = list(remaining)
        self.needed_h = needed_h
        self.page_h = page_h
        bits = [reason]
        if needed_h is not None and page_h is not None:
            bits.append(f"已用高度 {needed_h:.2f} in > 可用 {page_h:.2f} in")
        if remaining:
            names = "、".join(getattr(c, "name", str(c)) for c in remaining)
            bits.append(f"排不下：{names}")
        super().__init__("：".join(bits))


@dataclass
class CardSpec:
    """一张卡片的描述。「放什么」由调用方给，「多大」由引擎或预设给。"""

    name: str
    kind: str                      # thermometer / semicircle / placeholder
    chart_key: str | None = None
    values: list | None = None
    semantic: str = SEMANTIC_OTHER
    title: str | None = None
    #: 预设尺寸（给定时当 target 传下去）；不给就用自然尺寸。
    #: **多栏模式下会被忽略**：跨栏宽由栏位几何决定，预设的宽度不再说了算。
    width_in: float | None = None
    height_in: float | None = None
    #: 占几栏（多栏图文混排 0.1）。占满 ``column_count`` 栏 = 整行宽。
    column_span: int = 1
    #: 占位图卡片写在图上的原因（不适用档兜底时用）。
    note: str | None = None

    def __post_init__(self):
        if self.kind not in ("thermometer", "semicircle", "placeholder"):
            raise ValueError(f"unknown card kind: {self.kind!r}")
        if (self.width_in is None) != (self.height_in is None):
            raise ValueError(
                f"{self.name}: width_in and height_in must be given together")
        if not 1 <= self.column_span <= 3:
            raise ValueError(f"{self.name}: column_span must be 1..3, "
                             f"got {self.column_span!r}")


@dataclass
class TextBlock:
    """版面级文本块（图文混排 0.1，用户 m06055）。

    样式名直接借用色板字号表的设计角色（title/subtitle/body/label/note），
    所以标题、正文、说明的字号天然遵循既有规范，不另立一套。
    ``width_in`` 默认占满可用宽度（上下型排布：文本独占整行）。
    """

    text: str
    style: str = "body"
    align: str = "left"
    width_in: float | None = None
    name: str | None = None
    #: 占几栏（多栏图文混排 0.1）。标题常设成占满全部栏 = 跨栏标题。
    column_span: int = 1
    #: 块内均分几栏（报纸式分栏正文）。1 = 单栏；>1 时折行宽度按栏内净宽算，
    #: 折好的行按行数均衡分到各栏，块高取最长一栏。
    columns: int = 1

    def __post_init__(self):
        from loop.text_flow import ALIGNS, BLOCK_STYLES
        if self.style not in BLOCK_STYLES:
            raise ValueError(f"unknown text style: {self.style!r} "
                             f"(expected one of {BLOCK_STYLES})")
        if self.align not in ALIGNS:
            raise ValueError(f"unknown align: {self.align!r} "
                             f"(expected one of {ALIGNS})")
        if not self.text:
            raise ValueError("text block needs non-empty text")
        if not 1 <= self.column_span <= 3:
            raise ValueError(f"column_span must be 1..3, got {self.column_span!r}")
        if not 1 <= self.columns <= 3:
            raise ValueError(f"columns must be 1..3, got {self.columns!r}")
        if self.name is None:
            head = self.text.strip().splitlines()[0] if self.text.strip() else "block"
            self.name = head[:12]


@dataclass
class ImageBlock:
    """版面级插图块（图文并茂 1.0，用户 m06471）。

    与 ``TextBlock`` / ``CardSpec`` **平级**，作为流的一项参与排版——排版引擎
    照常给它分配 x/y/w/h，它自己只声明「用哪张图、占几栏、对齐方式」。

    宽高比从**文件本身**读（``image_size_in``），不由调用方猜：高度算错就是
    重叠或留白。高度不够装下整张图时按比例缩、居中留白，永不变形。
    """

    path: str
    style: str = "icon"
    align: str = "center"
    name: str | None = None
    #: 显式宽度（英寸）。不给就按栏位算（单栏 = 一栏宽，跨栏 = 跨栏宽）。
    width_in: float | None = None
    #: 占几栏。1 = 与同栏的卡片并排；= column_count = 整行通栏。
    column_span: int = 1
    #: 高度上限（英寸）。不给就用 ``LayoutSpec.max_image_height_in``。
    max_height_in: float | None = None
    #: 出自哪条素材（只作溯源，渲染不用）。
    asset_id: int | None = None
    tag: str | None = None
    semantic: str | None = None

    def __post_init__(self):
        if not self.path:
            raise ValueError("image block needs a path")
        if self.style not in IMAGE_STYLES:
            raise ValueError(f"unknown image style: {self.style!r} "
                             f"(expected one of {IMAGE_STYLES})")
        if self.align not in ("left", "center", "right"):
            raise ValueError(f"unknown align: {self.align!r}")
        if not 1 <= self.column_span <= 3:
            raise ValueError(f"column_span must be 1..3, "
                             f"got {self.column_span!r}")
        if self.max_height_in is not None and self.max_height_in <= 0:
            raise ValueError("max_height_in must be > 0, "
                             f"got {self.max_height_in!r}")
        if self.name is None:
            self.name = os.path.splitext(os.path.basename(self.path))[0]

    @property
    def aspect(self) -> float:
        w, h = image_size_in(self.path)
        return w / h


@dataclass
class PlacedBlock:
    """排好位置的文本块（含折好的行，供两个渲染器照抄）。"""

    block: TextBlock
    x_in: float
    y_in: float
    w_in: float
    h_in: float
    row: int
    lines: list = field(default_factory=list)
    scale: float = 1.0
    #: 块内分栏后的行分组（``len(...) == block.columns``）；渲染器照抄。
    line_groups: list = field(default_factory=list)
    #: 块内分栏的栏间距（渲染器按它算每栏的 x）。
    column_gutter_in: float = 0.0

    @property
    def name(self) -> str:
        return self.block.name

    def to_dict(self) -> dict:
        return {"name": self.name, "style": self.block.style,
                "align": self.block.align, "text": self.block.text,
                "x_in": self.x_in, "y_in": self.y_in,
                "w_in": self.w_in, "h_in": self.h_in, "row": self.row,
                "column_span": self.block.column_span,
                "columns": self.block.columns,
                "column_gutter_in": self.column_gutter_in,
                "lines": list(self.lines),
                "line_groups": [list(g) for g in self.line_groups]}

    @classmethod
    def from_dict(cls, d: dict) -> "PlacedBlock":
        """``to_dict`` 的左逆：从扁平 dict 重建 ``TextBlock`` + 外盒坐标。

        ``TextBlock.width_in``（预设宽度）不在 ``to_dict`` 里 —— 落位之后它已经
        被 ``w_in`` 取代，所以读不回来也不丢契约里的任何键。
        """
        return cls(
            block=TextBlock(
                text=d["text"], style=d.get("style", "body"),
                align=d.get("align", "left"), name=d.get("name"),
                column_span=d.get("column_span", 1),
                columns=d.get("columns", 1)),
            x_in=d["x_in"], y_in=d["y_in"], w_in=d["w_in"], h_in=d["h_in"],
            row=d["row"], lines=list(d.get("lines", [])),
            column_gutter_in=d.get("column_gutter_in", 0.0),
            line_groups=[list(g) for g in d.get("line_groups", [])])


@dataclass
class PlacedImage:
    """排好位置的插图：外盒坐标 + 盒内真实绘制矩形 + 溯源信息。"""

    block: ImageBlock
    x_in: float
    y_in: float
    w_in: float
    h_in: float
    row: int
    #: ``(dx, dy, w, h)`` —— 相对外盒左上角的绘制矩形（永不变形、居中留白）。
    rect: tuple = (0.0, 0.0, 0.0, 0.0)
    scale: float = 1.0

    @property
    def name(self) -> str:
        return self.block.name

    def to_dict(self) -> dict:
        return {"name": self.name, "path": self.block.path,
                "style": self.block.style, "align": self.block.align,
                "x_in": self.x_in, "y_in": self.y_in,
                "w_in": self.w_in, "h_in": self.h_in, "row": self.row,
                "column_span": self.block.column_span,
                "asset_id": self.block.asset_id, "tag": self.block.tag,
                "semantic": self.block.semantic,
                "rect": list(self.rect)}

    @classmethod
    def from_dict(cls, d: dict) -> "PlacedImage":
        """``to_dict`` 的左逆：从扁平 dict 重建 ``ImageBlock`` + 外盒坐标。

        ``ImageBlock.max_height_in``（高度上限）是**排版输入**，不在
        ``to_dict`` 里 —— 落位后它已由 ``h_in`` / ``rect`` 表达。
        """
        return cls(
            block=ImageBlock(
                path=d["path"], style=d.get("style", "icon"),
                align=d.get("align", "center"), name=d.get("name"),
                column_span=d.get("column_span", 1),
                asset_id=d.get("asset_id"), tag=d.get("tag"),
                semantic=d.get("semantic")),
            x_in=d["x_in"], y_in=d["y_in"], w_in=d["w_in"], h_in=d["h_in"],
            row=d["row"], rect=tuple(d.get("rect", (0.0, 0.0, 0.0, 0.0))))


@dataclass
class PlacedCard:
    """排好位置的卡片：外部坐标 + 卡片自己的规格。"""

    card: CardSpec
    spec: PageSpec
    x_in: float
    y_in: float
    w_in: float
    h_in: float
    row: int

    @property
    def name(self) -> str:
        return self.card.name

    def to_dict(self) -> dict:
        return {"name": self.name, "kind": self.card.kind,
                "x_in": self.x_in, "y_in": self.y_in,
                "w_in": self.w_in, "h_in": self.h_in, "row": self.row,
                "column_span": self.card.column_span,
                "spec": self.spec.to_dict()}

    @classmethod
    def from_dict(cls, d: dict, where: str = "$.cards[]",
                  warnings: list | None = None) -> "PlacedCard":
        """``to_dict`` 的左逆：重建 ``CardSpec`` 外框 + 内部 ``PageSpec``。

        ``CardSpec`` 的 ``title`` / ``values`` 等排版输入不在 ``to_dict`` 里
        （它们只用来生成 ``spec``），所以这里只恢复契约记下来的那几个键。
        """
        sink = [] if warnings is None else warnings
        return cls(
            card=CardSpec(name=d["name"], kind=d["kind"],
                          column_span=d.get("column_span", 1)),
            spec=_spec_from_dict(d["spec"], f"{where}.spec", sink),
            x_in=d["x_in"], y_in=d["y_in"], w_in=d["w_in"], h_in=d["h_in"],
            row=d["row"])


@dataclass
class LayoutSpec:
    """整版画布与间距。"""

    width_in: float = 10.0
    height_in: float = 15.0
    margin_in: float = 0.4
    gutter_in: float = 0.3
    #: 自然尺寸比可用宽度还宽时，是否按可用宽度等比缩一张（默认缩）。
    #: 用户 m05995 拍板：默认缩，但缩到读不了时抛 LayoutFitError。
    fit_oversized: bool = True
    #: 同一行的卡片是否拉成等高（用户 m05995）。False 时保留各自高度，
    #: 行内较矮卡片下方会留白 —— 就是 0.1 暴露的问题。
    equal_height: bool = True
    #: 分几栏（多栏图文混排 0.1）。1 = 单栏（0.1~0.4 的行为），最多 3 栏。
    column_count: int = 1
    #: 栏与栏之间的水平间距（英寸）。与行距 ``gutter_in`` 是两件事。
    column_gutter_in: float = 0.2
    #: 单张卡片最高不超过可用高度的这个比例 —— 这是**版面政策**，不是渲染细节：
    #: 一页要放两三张图再配文字，让一张图吃掉整版高度后面就排不下了。
    max_card_height_ratio: float = 0.35
    #: 一张插图最高不超过可用高度的这个比例（图文并茂 1.0）。插图是**装饰**，
    #: 让它长满整栏会把正文挤走，所以比卡片更保守。
    max_image_height_ratio: float = 0.2

    def __post_init__(self):
        if not 1 <= self.column_count <= 3:
            raise ValueError("column_count must be 1..3, "
                             f"got {self.column_count!r}")
        if self.column_gutter_in < 0:
            raise ValueError("column_gutter_in must be >= 0")
        if not 0 < self.max_card_height_ratio <= 1:
            raise ValueError("max_card_height_ratio must be in (0, 1], "
                             f"got {self.max_card_height_ratio!r}")
        if not 0 < self.max_image_height_ratio <= 1:
            raise ValueError("max_image_height_ratio must be in (0, 1], "
                             f"got {self.max_image_height_ratio!r}")

    @property
    def usable_width_in(self) -> float:
        return self.width_in - 2 * self.margin_in

    @property
    def usable_height_in(self) -> float:
        return self.height_in - 2 * self.margin_in

    @property
    def column_width_in(self) -> float:
        """单栏净宽。"""
        return ((self.usable_width_in
                 - (self.column_count - 1) * self.column_gutter_in)
                / self.column_count)

    @property
    def max_card_height_in(self) -> float:
        return self.usable_height_in * self.max_card_height_ratio

    @property
    def max_image_height_in(self) -> float:
        return self.usable_height_in * self.max_image_height_ratio

    def span_width_in(self, span: int) -> float:
        """跨 ``span`` 栏的总宽（含栏间空隙）。"""
        if not 1 <= span <= self.column_count:
            raise ValueError(f"span must be 1..{self.column_count}, got {span!r}")
        return span * self.column_width_in + (span - 1) * self.column_gutter_in

    def slot_x_in(self, slot: int) -> float:
        """第 ``slot`` 栏的左边界（0 基）。"""
        return self.margin_in + slot * (self.column_width_in
                                        + self.column_gutter_in)


@dataclass
class PageLayoutSpec:
    """整版规格：画布 + 每张卡片的最终外部坐标 + 内部子 PageSpec。"""

    width_in: float
    height_in: float
    margin_in: float
    gutter_in: float
    cards: list = field(default_factory=list)
    blocks: list = field(default_factory=list)
    images: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    column_count: int = 1
    column_gutter_in: float = 0.2
    #: 契约版本（1.0 新样本写 ``"1.0"``；0.x 老样本没有这个键 → None）。
    #: **留在字段末尾**：按位置构造 PageLayoutSpec 的调用方不受影响。
    version: str | None = None
    #: 主题（``loop/palette.py::summary()`` 的原样产物；老样本没有 → None）。
    theme: dict | None = None

    def to_dict(self) -> dict:
        return {"width_in": self.width_in, "height_in": self.height_in,
                "margin_in": self.margin_in, "gutter_in": self.gutter_in,
                "column_count": self.column_count,
                "column_gutter_in": self.column_gutter_in,
                "rows": list(self.rows),
                "cards": [c.to_dict() for c in self.cards],
                "blocks": [b.to_dict() for b in self.blocks],
                "images": [i.to_dict() for i in self.images],
                "version": self.version, "theme": self.theme}

    @classmethod
    def from_dict(cls, d: dict, warnings: list | None = None) -> "PageLayoutSpec":
        """宽松读回：缺键靠 dataclass 默认值兜底，子项逐个重建。

        ``cards`` 走 ``PlacedCard.from_dict``（它会调 ``_spec_from_dict``）——
        **不能**把卡片内层丢给 ``PageSpec.from_dict``：那份实现对图元做
        ``ElementSpec(**e)``，遇到未知键直接 ``TypeError``（``models.py:75``）。
        ``warnings`` 是**可选**的外置收集器：``load_layout_json`` 把未知图元键的
        告警收进 ``ReadResult.warnings``；不传时告警就地丢弃。
        """
        sink = [] if warnings is None else warnings
        return cls(
            width_in=d["width_in"], height_in=d["height_in"],
            margin_in=d["margin_in"], gutter_in=d["gutter_in"],
            cards=[PlacedCard.from_dict(c, f"$.cards[{i}]", sink)
                   for i, c in enumerate(d.get("cards", []))],
            blocks=[PlacedBlock.from_dict(b) for b in d.get("blocks", [])],
            images=[PlacedImage.from_dict(i) for i in d.get("images", [])],
            rows=d.get("rows", []),
            column_count=d.get("column_count", 1),
            column_gutter_in=d.get("column_gutter_in", 0.2),
            version=d.get("version"), theme=d.get("theme"))

    def card(self, name: str) -> PlacedCard:
        for c in self.cards:
            if c.name == name:
                return c
        raise KeyError(name)

    def block(self, name: str) -> PlacedBlock:
        for b in self.blocks:
            if b.name == name:
                return b
        raise KeyError(name)

    def image(self, name: str) -> PlacedImage:
        for i in self.images:
            if i.name == name:
                return i
        raise KeyError(name)

    def items(self) -> list:
        """按 y 再按 x 排序的全部版面项（卡片、文本块、插图混在一起）。"""
        out = ([("card", c) for c in self.cards]
               + [("text", b) for b in self.blocks]
               + [("image", i) for i in self.images])
        return sorted(out, key=lambda kv: (kv[1].y_in, kv[1].x_in))


# ---------------------------------------------------------------------------
# 造卡片
# ---------------------------------------------------------------------------
def _readable(spec: PageSpec, card: CardSpec, ratio: float, natural_w: float,
              usable_w: float) -> None:
    """宽度逼着缩之后，字号还读得出来吗？读不出来就抛 LayoutFitError。"""
    from loop import palette

    scale = palette.spec_scale(spec)
    min_pt = palette.font_size("note") * scale
    if min_pt + 1e-9 < palette.MIN_FONT_PT:
        raise LayoutFitError(
            card.name,
            f"可用宽度 {usable_w:.2f} in 只有自然宽度 {natural_w:.2f} in 的 "
            f"{ratio:.0%}，缩完字号（{scale:.2f}×）已经不可读",
            min_pt=min_pt, floor_pt=palette.MIN_FONT_PT)


def build_card(card: CardSpec, layout: LayoutSpec, frame: bool = True,
               stretch_to_in: float | None = None) -> PageSpec:
    """按卡片描述造一张卡片规格；尺寸规则见模块 docstring。

    ``stretch_to_in``（用户 m05995 的等高拉伸）：把卡片按给定高度重造，
    宽度取卡片自己的宽度。fit 引擎是**等比**缩放所有长度参数，所以拉高
    只会让内容整体放大到宽度允许的上限，不会把图形压扁/拉长。
    """
    from loop.data_source import DB_PATH, load_points
    from loop.scaffold import build_pagespec

    target_w = card.width_in
    target_h = card.height_in

    if card.kind == "placeholder":
        from loop.pipeline import _build_fallback_spec
        from loop.asset_lookup import find_fallback_assets
        assets = find_fallback_assets()
        if not assets:
            raise LookupError("no fallback asset in the database")
        title = card.title or "无适用图形"
        if target_w is None and stretch_to_in is None:
            return _build_fallback_spec(assets[0], title, note=card.note)
        return _build_fallback_spec(assets[0], title,
                                    target_width_in=target_w,
                                    target_height_in=target_h if stretch_to_in is None
                                    else stretch_to_in,
                                    note=card.note)

    if card.values is not None:
        points = []
        for i, v in enumerate(card.values, start=1):
            points.append({"seq": i, "value": float(v), "label": f"第{i}项",
                           "unit": "%" if card.kind == "semicircle" else "倍(超)",
                           "label_full": f"第{i}项"})
    else:
        key = card.chart_key or "heat_ratio_top5"
        _, points = load_points(DB_PATH, chart_key=key)

    def _make(tw, th):
        from loop.fit import BoundaryError
        try:
            return build_pagespec(points, card.title or card.name,
                                  template_name=card.kind, frame=frame,
                                  target_width_in=tw, target_height_in=th)
        except BoundaryError as exc:
            # 单卡适配器说「这个格子物理上装不下」→ 在排版层就是
            # 「这张卡片被逼得太小」，换成排版层能理解的错误类型。
            raise LayoutFitError(
                card.name,
                f"{tw:.2f}×{th:.2f} in 的格子低于这张图的最小可行尺寸 "
                f"{exc.min_size[0]:.2f}×{exc.min_size[1]:.2f} in（{exc.problems[0] if exc.problems else '内容装不下'}）",
                min_pt=None, floor_pt=None) from exc

    if stretch_to_in is not None:
        if target_w is None:
            natural = build_pagespec(points, card.title or card.name,
                                     template_name=card.kind, frame=frame)
            target_w = natural.width_in
        return _make(target_w, stretch_to_in)

    if target_w is None:
        natural = build_pagespec(points, card.title or card.name,
                                 template_name=card.kind, frame=frame)
        if not layout.fit_oversized:
            return natural
        if natural.width_in <= layout.usable_width_in + 1e-9:
            return natural
        # 自然尺寸比整版还宽：按可用宽度等比缩，不截断；缩到读不了就报错。
        ratio = layout.usable_width_in / natural.width_in
        spec = _make(layout.usable_width_in,
                     natural.height_in * ratio)
        _readable(spec, card, ratio, natural.width_in, layout.usable_width_in)
        return spec

    return _make(target_w, target_h)


# ---------------------------------------------------------------------------
# 流式排版
# ---------------------------------------------------------------------------
def card_box(card: CardSpec, layout: LayoutSpec, span: int | None = None) -> tuple:
    """算一张卡片的落位盒子 ``(宽, 高)``。

    * ``span`` 给定（多栏模式）：**宽度严格等于跨栏宽** —— 跨栏卡片因此左右
      都贴着边距，不会缩成一条缝；高度按自然比例换算，并受
      ``max_card_height_ratio`` 上限约束（超了就压到上限，宽度不动，卡片内部
      的适配器会把内容居中，多出来的高度是留白而不是变形）。
    * ``span`` 为 None（单栏自由行）：回到 0.1~0.4 的等比缩放 —— 宽度和高度
      一起按 ``min(1, 可用宽/自然宽, 高度上限/自然高)`` 缩。
    """
    free = dataclasses.replace(card, width_in=None, height_in=None)
    natural = build_card(free, layout)
    nat_w = max(natural.width_in, 1e-6)
    nat_h = max(natural.height_in, 1e-6)
    cap = layout.max_card_height_in
    if span is None:
        if not layout.fit_oversized:
            # 关掉「缩一张」就是让超宽卡片照实落位，由调用方拿到越界报错。
            return round(nat_w, 6), round(nat_h, 6)
        s = min(1.0, layout.usable_width_in / nat_w, cap / nat_h)
        return round(nat_w * s, 6), round(nat_h * s, 6)
    w = layout.span_width_in(span)
    return round(w, 6), round(min(nat_h * (w / nat_w), cap), 6)


def _span_of(item) -> int:
    return int(getattr(item, "column_span", 1) or 1)


def _rows_for(items: list, layout: LayoutSpec) -> list:
    """把版面项切成行。

    * 单栏（``column_count == 1``）：沿用 0.1~0.4 的行为，**按宽度**塞行 ——
      卡片宽度是自己带的预设或自然宽，一行能塞几张就塞几张。
    * 多栏：**按栏位**塞行，一项占 ``column_span`` 个栏位；剩下的栏位放不下
      这一项就收行。所以「占 2 栏的卡片」在 2 栏版面上必然独占整行。
    """
    rows: list = []
    if layout.column_count == 1:
        cur: list = []
        used_w = 0.0
        for item in items:
            span = _span_of(item)
            if span != 1:
                raise LayoutOverflowError(
                    f"{getattr(item, 'name', item)} 声明跨 {span} 栏，"
                    f"但整版只有 1 栏")
            w = _free_width(item, layout)
            if cur and used_w + w > layout.usable_width_in + 1e-9:
                rows.append(cur)
                cur, used_w = [], 0.0
            cur.append(item)
            used_w += w + (layout.gutter_in if used_w else 0.0)
        if cur:
            rows.append(cur)
        return rows

    cur, used = [], 0
    for item in items:
        span = _span_of(item)
        if span > layout.column_count:
            raise LayoutOverflowError(
                f"{getattr(item, 'name', item)} 声明跨 {span} 栏，"
                f"但整版只有 {layout.column_count} 栏")
        if cur and used + span > layout.column_count:
            rows.append(cur)
            cur, used = [], 0
        cur.append(item)
        used += span
    if cur:
        rows.append(cur)
    return rows


def _free_width(item, layout: LayoutSpec) -> float:
    """单栏自由行里这项打算占多宽（用于按宽度塞行）。"""
    if isinstance(item, TextBlock):
        return item.width_in or layout.usable_width_in
    if isinstance(item, ImageBlock):
        if item.width_in is not None:
            return item.width_in
        if layout.column_count > 1:
            return layout.span_width_in(item.column_span)
        return layout.usable_width_in
    if item.width_in is not None:
        return item.width_in
    return card_box(item, layout, span=None)[0]


def image_box(block: ImageBlock, layout: LayoutSpec,
              width_in: float) -> tuple:
    """插图的 ``(盒宽, 盒高, 绘制矩形)``。

    宽度由栏位（或可用宽度）钉死；高度按**真实宽高比**推，但不超过
    ``max_height_in`` / ``LayoutSpec.max_image_height_in``。高度被压住时
    图片按比例缩小、在盒内居中留白 —— 绝不变形，也绝不越出分配的盒子。
    """
    cap = (float(block.max_height_in) if block.max_height_in is not None
           else layout.max_image_height_in)
    w = float(width_in)
    h = min(w / block.aspect, cap)
    return (round(w, 6), round(h, 6), fit_rect_in(w, h, block.aspect,
                                                 block.align))


def flow_layout(layout: LayoutSpec, cards: list) -> PageLayoutSpec:
    """按顺序流式排版（多栏图文混排 0.1）。

    ``cards`` 可以是混合列表，元素是 ``CardSpec`` 或 ``TextBlock``
    （0.3 起名字保留了历史，参数含义已是「版面项」）。

    规则：

    * 版面按行推进，行内按**栏位**自左到右放；一项占 ``column_span`` 个栏位，
      占满一行就收行；整版只有 1 栏时退回「按宽度塞行」的老行为。
    * 单栏文本块的折行宽度就是栏宽；``columns > 1`` 的文本块在**自己盒内**
      再均分成若干栏（折行按栏内净宽算，块高取最长一栏）—— 跨栏正文靠这个。
    * 卡片宽度在多栏模式下由栏位几何决定（``card_box``），所以跨栏卡片严格
      左右贴边距。
    * 文本块与卡片上下相邻，**永不共享一行**（不做两侧环绕）；收行时按行高把
      较矮的卡片拉高（等高），文本块不参与拉伸。
    * 任何一步越过下边距都抛 ``LayoutOverflowError``，不静默越界。
    """
    usable_w = layout.usable_width_in
    if usable_w <= 0:
        raise LayoutOverflowError(
            f"margin {layout.margin_in:g} in leaves no usable width on "
            f"{layout.width_in:g} in", page_h=layout.usable_height_in)
    if layout.column_width_in <= 0:
        raise LayoutOverflowError(
            f"{layout.column_count} 栏 + 栏间距 {layout.column_gutter_in:g} in "
            f"放不进可用宽度 {usable_w:.2f} in")

    page_scale = palette.canvas_scale(layout.width_in, layout.height_in)

    placed: list = []
    placed_blocks: list = []
    placed_images: list = []
    rows_out: list = []
    cursor_y = layout.margin_in
    row_index = 0

    def _box_of(item, layout_):
        """返回 (spec, w, h, extra)：文本块的 extra 是折行分组、插图的 extra
        是盒内绘制矩形，卡片是 None。"""
        if isinstance(item, TextBlock):
            w = item.width_in or layout_.span_width_in(_span_of(item))
            if w > layout_.usable_width_in + 1e-9:
                raise LayoutOverflowError(
                    f"文本块 {item.name} 宽 {w:.2f} in > 可用宽度 "
                    f"{layout_.usable_width_in:.2f} in", placed=placed,
                    remaining=[item], page_h=layout_.usable_height_in)
            groups = (text_flow.wrap_columns(item.text, item.style, w,
                                             item.columns, page_scale,
                                             layout_.column_gutter_in)
                      if item.columns > 1
                      else text_flow.wrap_columns(item.text, item.style, w, 1,
                                                  page_scale))
            h = round(text_flow.columns_height_in(groups, item.style, page_scale), 6)
            return None, w, h, groups
        if isinstance(item, ImageBlock):
            w = (item.width_in if item.width_in is not None
                 else layout_.span_width_in(_span_of(item)))
            if w > layout_.usable_width_in + 1e-9:
                raise LayoutOverflowError(
                    f"插图 {item.name} 宽 {w:.2f} in > 可用宽度 "
                    f"{layout_.usable_width_in:.2f} in", placed=placed,
                    remaining=[item], page_h=layout_.usable_height_in)
            w, h, rect = image_box(item, layout_, w)
            return None, w, h, rect
        span = _span_of(item) if layout_.column_count > 1 else None
        if span is None and item.width_in is not None:
            w, h = item.width_in, item.height_in
            spec = build_card(
                dataclasses.replace(item, width_in=w, height_in=h), layout_)
        else:
            w, h = card_box(item, layout_, span=span)
            spec, h = _build_card_fitted(item, layout_, w, h)
        return spec, w, h, None

    def _build_card_fitted(item, layout_, w, h):
        """按 (w, h) 造卡片；装不下就把高度顶到上限再试一次，返回 (spec, h)。

        多栏版面里单栏卡片的**宽度是被钉死的**（恰好一栏宽），高度按自然比例
        换算。碰到「宽而扁」的格子，宽度够、高度不够，图形会因为内部元素挤在
        一起而拒收 —— 这不是物理极限，把高度用到 ``max_card_height_in``（宽度
        不变、内容居中、多出来的是留白）通常就够了。两次都装不下才抛，这样
        「极小尺寸装不下」的报错语义不变。
        """
        try:
            spec = build_card(
                dataclasses.replace(item, width_in=w, height_in=h), layout_)
            return spec, h
        except (LayoutFitError, BoundaryError) as exc:
            cap = round(layout_.max_card_height_in, 6)
            if h >= cap - 1e-9:
                raise
            try:
                spec = build_card(
                    dataclasses.replace(item, width_in=w, height_in=cap),
                    layout_)
            except (LayoutFitError, BoundaryError):
                raise exc
            return spec, cap

    def _flush(items: list, y: float) -> float:
        """收掉一行：等高拉伸 → 落坐标 → 返回下一行的 y。"""
        nonlocal row_index
        if not items:
            return y
        boxes = [_box_of(it, layout) for it in items]
        heights = [b[2] for b in boxes]
        max_h = max(heights)
        if layout.equal_height:
            for idx, it in enumerate(items):
                spec, w, h, groups = boxes[idx]
                if spec is None or h >= max_h - 1e-9:
                    continue
                spec = build_card(dataclasses.replace(it, width_in=w,
                                                      height_in=max_h), layout)
                boxes[idx] = (spec, w, max_h, groups)
            max_h = max(b[2] for b in boxes)
        if y + max_h > layout.height_in - layout.margin_in + 1e-9:
            raise LayoutOverflowError(
                "换行后高度也装不下："
                + "、".join(f"{'文本块' if isinstance(it, TextBlock) else '卡片'} "
                            f"{it.name}" for it in items),
                placed=placed, remaining=[it for it in items],
                needed_h=y + max_h + layout.margin_in, page_h=layout.height_in)
        slot = 0
        x_cursor = layout.margin_in
        for idx, item in enumerate(items):
            spec, w, h, groups = boxes[idx]
            span = _span_of(item)
            if layout.column_count > 1:
                x = layout.slot_x_in(slot)
            else:
                if w > layout.usable_width_in + 1e-9:
                    raise LayoutOverflowError(
                        f"{getattr(item, 'name', item)} 宽 {w:.2f} in > 可用宽度 "
                        f"{layout.usable_width_in:.2f} in（整版 {layout.width_in:g} in "
                        f"去掉两侧 {layout.margin_in:g} in）",
                        placed=placed, remaining=[item],
                        page_h=layout.usable_height_in)
                x = x_cursor
            if isinstance(item, TextBlock):
                placed_blocks.append(PlacedBlock(
                    block=item, x_in=round(x, 6), y_in=round(y, 6),
                    w_in=round(w, 6), h_in=round(h, 6), row=row_index,
                    lines=[ln for g in groups for ln in g], scale=page_scale,
                    line_groups=[list(g) for g in groups],
                    column_gutter_in=(layout.column_gutter_in
                                      if item.columns > 1 else 0.0)))
            elif isinstance(item, ImageBlock):
                dx, dy, dw, dh = groups
                if layout.equal_height and h < max_h - 1e-9:
                    # 行里最高的那项（通常是卡片）决定了行高；插图不拉伸，
                    # 但要在行带里垂直居中，否则看起来像掉在行顶。
                    dy = round(dy + (max_h - h) / 2.0, 6)
                placed_images.append(PlacedImage(
                    block=item, x_in=round(x, 6), y_in=round(y, 6),
                    w_in=round(w, 6), h_in=round(h, 6), row=row_index,
                    rect=(dx, dy, dw, dh), scale=page_scale))
            else:
                placed.append(PlacedCard(
                    card=item, spec=spec, x_in=round(x, 6), y_in=round(y, 6),
                    w_in=round(w, 6), h_in=round(h, 6), row=row_index))
            slot += span if layout.column_count > 1 else 0
            x_cursor = round(x_cursor + w + layout.gutter_in, 6)
        rows_out.append({"kind": ("text" if len(items) == 1
                                  and isinstance(items[0], TextBlock)
                                  else "cards" if all(isinstance(it, CardSpec)
                                                      for it in items)
                                  else "row"),
                         "y_in": round(y, 6),
                         "h_in": round(max_h, 6),
                         "items": [it.name for it in items],
                         "cards": [it.name for it in items
                                   if isinstance(it, CardSpec)],
                         "blocks": [it.name for it in items
                                    if isinstance(it, TextBlock)],
                         "images": [it.name for it in items
                                    if isinstance(it, ImageBlock)]})
        row_index += 1
        return round(y + max_h + layout.gutter_in, 6)

    for row in _rows_for(cards, layout):
        cursor_y = _flush(row, cursor_y)

    return PageLayoutSpec(width_in=layout.width_in, height_in=layout.height_in,
                          margin_in=layout.margin_in,
                          gutter_in=layout.gutter_in, cards=placed,
                          blocks=placed_blocks, images=placed_images,
                          rows=rows_out,
                          column_count=layout.column_count,
                          column_gutter_in=layout.column_gutter_in)


#: 图元里存的是求解坐标系绝对值的键；平移整张卡片时必须一起搬。
ABS_X_KEYS = ("cx",)
ABS_Y_KEYS = ("cy", "cap_top", "tube_bottom")


def flatten(page: PageLayoutSpec) -> PageSpec:
    """把整版摊平成**一份** PageSpec：元素平移 + id 加卡片前缀。

    平移要把 geometry 里的绝对坐标一起搬（第 21 步的教训：外圈折线直接拿
    ``geometry.cx`` 当页面坐标），每张卡片的字号缩放记在 ``geometry._scale``，
    供整版渲染器按卡片各自的比例写字。

    文本块也摊进来（id 前缀 ``t{i}_``），折好的行写进
    ``geometry["lines"]`` —— 两个渲染器照抄同一份折行结果，不各自再算一次。
    """
    elements: list[ElementSpec] = []
    for i, c in enumerate(page.cards):
        card_scale = palette.spec_scale(c.spec)
        for e in c.spec.elements:
            geo = dict(e.geometry or {})
            for key in ABS_X_KEYS:
                if key in geo:
                    geo[key] = round(float(geo[key]) + c.x_in, 6)
            for key in ABS_Y_KEYS:
                if key in geo:
                    geo[key] = round(float(geo[key]) + c.y_in, 6)
            geo["_scale"] = card_scale
            elements.append(dataclasses.replace(
                e, id=f"c{i}_{e.id}",
                x_in=round(e.x_in + c.x_in, 6),
                y_in=round(e.y_in + c.y_in, 6),
                geometry=geo))

    for i, b in enumerate(page.blocks):
        groups = [list(g) for g in (b.line_groups or [b.lines])]
        elements.append(ElementSpec(
            id=f"t{i}_{b.block.name}", type="text", role=b.block.style,
            x_in=b.x_in, y_in=b.y_in, w_in=b.w_in, h_in=b.h_in,
            fill=None, text=b.block.text, binding=None, geometry_expr=None,
            geometry={"block": True, "lines": list(b.lines),
                      "line_groups": groups,
                      "column_gutter_in": b.column_gutter_in,
                      "align": b.block.align, "_scale": b.scale}))

    for i, im in enumerate(page.images):
        dx, dy, dw, dh = im.rect
        elements.append(ElementSpec(
            id=f"i{i}_{im.name}", type="image", role="illustration",
            x_in=im.x_in, y_in=im.y_in, w_in=im.w_in, h_in=im.h_in,
            fill=None, text=None, binding=None, geometry_expr=None,
            image_path=im.block.path,
            geometry={"block": True, "image_rect": [dx, dy, dw, dh],
                      "style": im.block.style, "align": im.block.align,
                      "asset_id": im.block.asset_id, "tag": im.block.tag,
                      "semantic": im.block.semantic, "_scale": im.scale}))

    return PageSpec(
        width_in=page.width_in, height_in=page.height_in,
        chart_key="page", chart_title="整版",
        scale=Scale(v_max=1.0, h_in=0.0, unit="n/a"),
        elements=elements, semantic_tags=[], constraints=[],
        layout={"kind": "flow", "template": None,
                "card_count": len(page.cards),
                "block_count": len(page.blocks),
                "image_count": len(page.images),
                "column_count": page.column_count,
                "column_gutter_in": page.column_gutter_in,
                "margin_in": page.margin_in, "gutter_in": page.gutter_in})


def page_spec_path(out_dir: str) -> str:
    return os.path.join(out_dir, "pagelayout.json")


# ---------------------------------------------------------------------------
# 读回（宽松）：pagelayout.json → dataclass
# ---------------------------------------------------------------------------
#: ``_element_from_dict`` 认得的图元键。照 ``ElementSpec`` 的字段逐个列出，
#: 故意**不**用 ``dataclasses.fields()``：未来新增的字段必须先在这里登记才会
#: 被读进来，否则降级成 warning —— 静默吃掉未来字段比报一声更糟。
ELEMENT_KEYS = ("id", "type", "role", "x_in", "y_in", "w_in", "h_in",
                "fill", "text", "binding", "geometry_expr", "geometry",
                "image_path", "lines", "font_pt", "editable")


def _element_from_dict(d: dict, where: str, warnings: list) -> ElementSpec:
    """显式挑已知键构造 ``ElementSpec``；未知键降级成 warning。

    ``ElementSpec(**d)``（``loop/models.py:75`` 的写法）遇到未来字段会
    ``TypeError``；读入口的口径是「老文档、未来文档都要能读」，所以这里挑键、
    记一条 ``f"{where}: 忽略未知键 {key!r}"``，不抛。
    """
    known = {key: d[key] for key in ELEMENT_KEYS if key in d}
    for key in d:
        if key not in ELEMENT_KEYS:
            warnings.append(f"{where}: 忽略未知键 {key!r}")
    return ElementSpec(**known)


def _spec_from_dict(d: dict, where: str, warnings: list) -> PageSpec:
    """``PageSpec.from_dict`` 的宽松版：``elements`` 走 ``_element_from_dict``。

    这是卡片内 spec 的**唯一**构造路径：原先那份 11 键复制品已删除 —— 它自己
    写着「两处必须同步」，而给 ``PageSpec`` 加第 12 个键（``chart``）正是会漂移
    的那种改动。宽松口径全靠注入口 ``element_factory`` 实现，其余键的读法与
    ``PageSpec.from_dict`` 是同一份代码。

    注入口保持 ``element_factory(e)`` 的**单参数**签名（既有
    ``PageSpec.from_dict(doc)`` 调用方行为不变）；图元下标由本地计数器补偿，
    所以告警路径仍是 ``$.cards[0].spec.elements[N]`` —— 少了这个下标，同一张
    卡片有多个图元时就报不出出事的那一个。
    """
    idx = 0

    def _element(e: dict) -> ElementSpec:
        nonlocal idx
        current = idx
        idx += 1
        return _element_from_dict(e, f"{where}.elements[{current}]", warnings)

    return PageSpec.from_dict(d, element_factory=_element)
