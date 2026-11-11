"""自动化编排 0.1（用户 m06157）：从一段新闻稿 + 数据仓库自动生成排版流。

只做「自动生成流」，不碰单卡渲染与卡片内部约束。三条规则，全部是朴素规则、
没有模型、没有网络：

1. **拆段**：按空行/换行切段；若整篇只有一段，再按 ``。！？`` 断句。
2. **认标题与导语**：第一段短（≤ ``TITLE_MAX_CHARS``）或没有句末标点 → 整段
   当标题；否则取它的第一句当标题、余下句子并回导语。标题之后的 1 段当导语，
   其余段落依次进入正文。
3. **配数据**：把每个 ``chart_title`` 解析成
   ``(地区, 品类, 维度, 指标)`` 四个侧面，再拿段落去比：

   * 段落必须同时提到**品类**（取暖电器/除湿烘干电器/加热电器）、**指标**
     （占比/环比增速）与**维度或地区**，缺一不配 —— 这是为了防止「取暖」
     两个字一出现就把八组数据全勾上；
   * 带地区的数据组（湖南/江苏/上海…）**必须**在段落里看到那个地名才配，
     否则同一段会同时命中「湖南取暖电器…」和通用的「取暖电器…」；
   * 多个候选时按侧面加权取最高分，平分时优先**不带地区**的通用组，再按
     chart_key 排序，保证结果确定。

   ``占比`` → 语义「占比构成」，``环比增速`` → 语义「比较大小」，交给选型器
   （``loop.selector``）决定用温度计还是半圆图。

匹配不上一律退化为纯文本页，不崩溃；匹配上了但选型器判「不适用」的兜底
策略由 ``on_unapplicable`` 决定（``"skip"`` 只留文字并记一条 note，
``"placeholder"`` 配一张占位图）—— 这是本模块唯一有政策选择的地方，默认
保守（不静默画图）。
"""
import dataclasses
import json
import os
import re
import sqlite3

from loop.asset_lookup import (find_assets_by_semantic, find_assets_by_theme,
                               semantic_theme_terms)
from loop.data_source import DB_PATH, load_points
from loop.layout import (CardSpec, ImageBlock, LayoutSpec, TextBlock,
                         build_card, flow_layout, page_spec_path)
from loop.selector import (SEMANTIC_COMPARE, SEMANTIC_SHARE,
                           features_from_points, select)

#: 第一段短于这个字数就整段当标题。
TITLE_MAX_CHARS = 34

#: 段落里出现这些地名才算命中对应的地区数据组。
REGIONS = ("贵州", "湖南", "江苏", "上海", "四川", "广东", "浙江",
           "重庆", "青海", "内蒙古", "湖北", "陕西")

#: chart_title → 品类侧面（键是标题里的写法，值是段落里可能出现的写法）。
CATEGORY_FORMS = {
    "取暖电器": ("取暖电器", "取暖"),
    "除湿烘干电器": ("除湿烘干电器", "除湿烘干", "除湿", "烘干"),
    "加热电器": ("加热电器", "加热"),
}

#: 维度侧面：chart_title 里的写法 → (键, 段落里可能出现的写法)。
DIMENSIONS = {
    "age": ("年龄段", ("年龄段", "年龄")),
    "province": ("省份", ("省份", "地区", "地域")),
    "category": ("细分品类", ("细分品类", "品类")),
}

#: 指标侧面：``占比`` 属占比构成语义，``环比增速`` 属比较语义。
METRICS = (
    ("占比", SEMANTIC_SHARE, ("占比", "构成", "份额")),
    ("环比增速", SEMANTIC_COMPARE, ("环比增速", "环比", "增速", "增长")),
)


@dataclasses.dataclass(frozen=True)
class Dataset:
    """数据仓库里的一组数据（chart_points 里一个 chart_key）。"""

    key: str
    title: str
    region: str | None
    category: str | None
    dimension: str | None
    metric: str | None
    semantic: str

    def facets(self) -> dict:
        return {"region": self.region, "category": self.category,
                "dimension": self.dimension, "metric": self.metric,
                "semantic": self.semantic}


@dataclasses.dataclass
class Match:
    """一个段落配上了一组数据。"""

    paragraph: str
    dataset_key: str
    chart_title: str
    template: str | None
    rationale: str
    score: float
    card_name: str | None
    #: 配到的装饰插图名（图文并茂 1.0）；没配到就是 None。
    illustration: str | None = None
    #: 这段文字抽出的主题标签（S6 桥接 0.1）；没抽到就是 None。
    theme: str | None = None
    #: 插图是**按什么**选出来的：``"theme"`` / ``"chart_semantic"`` / None。
    illustration_basis: str | None = None

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class ComposeResult:
    """自动编排结果。"""

    flow: list
    matches: list
    notes: list
    page: object = None
    outputs: dict = dataclasses.field(default_factory=dict)
    #: 每段文字抽出的主题（``{段落文本: 主题标签}``，没抽到是 None）。
    themes: dict = dataclasses.field(default_factory=dict)

    def flow_summary(self) -> list:
        """按顺序列出流里的每一项（给汇报用）。"""
        out = []
        for item in self.flow:
            if isinstance(item, TextBlock):
                out.append({"kind": "text", "style": item.style,
                            "chars": len(item.text),
                            "theme": self.themes.get(item.text),
                            "text": item.text[:24]})
            elif isinstance(item, ImageBlock):
                out.append({"kind": "image", "name": item.name,
                            "path": item.path, "asset_id": item.asset_id,
                            "semantic": item.semantic, "tag": item.tag,
                            "matched_by": ("theme" if item.tag != item.semantic
                                           else "chart_semantic")})
            else:
                out.append({"kind": "card", "name": item.name,
                            "template": item.kind, "chart_key": item.chart_key})
        return out

    def to_dict(self) -> dict:
        return {"flow": self.flow_summary(),
                "matches": [m.to_dict() for m in self.matches],
                "notes": list(self.notes),
                "themes": dict(self.themes),
                "outputs": dict(self.outputs),
                "page": self.page.to_dict() if self.page is not None else None}


# ---------------------------------------------------------------- 标题解析

def parse_title(title: str) -> dict:
    """把 chart_title 解析成（地区, 品类, 维度, 指标, 语义）五个侧面。"""
    region = next((r for r in REGIONS if r in title), None)
    category = next((c for c in CATEGORY_FORMS if c in title), None)
    dimension = None
    for key, (written, _forms) in DIMENSIONS.items():
        if written in title:
            dimension = key
            break
    metric = None
    semantic = None
    for written, sem, _forms in METRICS:
        if written in title:
            metric, semantic = written, sem
            break
    return {"region": region, "category": category, "dimension": dimension,
            "metric": metric, "semantic": semantic}


def _contains_any(text: str, forms) -> str | None:
    return next((f for f in forms if f in text), None)


def load_catalog(db_path: str = DB_PATH) -> list:
    """读数据仓库里全部数据组（只读，不写库）。"""
    uri = "file:" + db_path.replace("?", "%3f").replace("#", "%23") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        rows = conn.execute(
            "SELECT chart_key, chart_title FROM chart_points "
            "GROUP BY chart_key ORDER BY chart_key").fetchall()
    finally:
        conn.close()
    catalog = []
    for key, title in rows:
        facets = parse_title(title or "")
        if facets["semantic"] is None:
            continue                        # 认不出指标的组不参与匹配
        catalog.append(Dataset(key=key, title=title, **facets))
    return catalog


# ---------------------------------------------------------------- 文本拆解

_SENTENCE_END = "。！？!?"


def split_sentences(paragraph: str) -> list:
    """按句末标点断句（保留标点）。"""
    out, cur = [], ""
    for ch in paragraph:
        cur += ch
        if ch in _SENTENCE_END:
            out.append(cur.strip())
            cur = ""
    if cur.strip():
        out.append(cur.strip())
    return out


def split_paragraphs(text: str) -> list:
    """按空行/换行拆段；只有一段时再按句末标点断句合并。"""
    if not text or not text.strip():
        raise ValueError("compose needs non-empty text")
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text.strip())]
    paragraphs = []
    for block in blocks:
        for line in block.split("\n"):
            line = line.strip()
            if line:
                paragraphs.append(line)
    if len(paragraphs) == 1:
        paragraphs = split_sentences(paragraphs[0])
    return paragraphs


def split_title_lead(paragraphs: list, lead_paragraphs: int = 1):
    """返回 (标题, 导语, 正文段落列表)。

    第一段整段当标题的条件：只有一句且不超 ``TITLE_MAX_CHARS`` 个字。有两句
    以上但首句够短（报纸标题常是一句短句＋一句说明），取首句当标题、余下句子
    并回导语；首句也长就整段当标题，宁可不拆。标题之后的
    ``lead_paragraphs`` 段并成导语。
    """
    if not paragraphs:
        raise ValueError("compose needs at least one paragraph")
    first = paragraphs[0]
    rest = list(paragraphs[1:])
    sentences = split_sentences(first)
    if len(sentences) > 1 and len(sentences[0]) <= TITLE_MAX_CHARS:
        title = sentences[0]
        rest = ["".join(sentences[1:]).strip()] + rest
    else:
        title = first
    lead_parts = [p for p in rest[:lead_paragraphs] if p]
    body = rest[lead_paragraphs:]
    return title, "".join(lead_parts).strip(), body


# ---------------------------------------------------------------- 数据匹配

def score_dataset(paragraph: str, dataset: Dataset) -> tuple:
    """段落与数据组的匹配打分。返回 (score, 命中说明)；0 分表示不配。"""
    if dataset.region and dataset.region not in paragraph:
        return 0.0, {}
    hits = {}
    cat_forms = CATEGORY_FORMS.get(dataset.category, ())
    hits["category"] = _contains_any(paragraph, cat_forms)
    dim_forms = DIMENSIONS.get(dataset.dimension, (None, ()))[1]
    hits["dimension"] = _contains_any(paragraph, dim_forms)
    metric_forms = next((forms for written, _sem, forms in METRICS
                         if written == dataset.metric), ())
    hits["metric"] = _contains_any(paragraph, metric_forms)
    hits["region"] = dataset.region if dataset.region and dataset.region in paragraph else None
    # 品类 + 指标 +（维度 或 地区）是配上的最低要求
    if not (hits["category"] and hits["metric"]
            and (hits["dimension"] or hits["region"])):
        return 0.0, hits
    score = 3.0 * bool(hits["category"]) + 2.0 * bool(hits["metric"])
    score += 3.0 * bool(hits["dimension"]) + 4.0 * bool(hits["region"])
    return score, hits


def match_dataset(paragraph: str, catalog: list, used: set):
    """挑出这一段最合适的数据组（已用过的除外）。"""
    best, best_score, best_hits = None, 0.0, {}
    for dataset in catalog:
        if dataset.key in used:
            continue
        score, hits = score_dataset(paragraph, dataset)
        if score <= 0:
            continue
        # 平分时：通用组（无地区）优先，再按 key 排序，保证确定性
        rank = (score, 0 if dataset.region is None else 1)
        if best is None or rank > best[0]:
            best, best_score, best_hits = (rank, dataset), score, hits
    if best is None:
        return None, 0.0, {}
    return best[1], best_score, best_hits


# ---------------------------------------------------------------- 组流

def _free_width_preset(card: CardSpec, layout: LayoutSpec,
                       width_in: float) -> tuple:
    """把卡片等比放进一个**指定宽度**的盒子，返回 ``(宽, 高)``。"""
    spec = build_card(card, layout)
    nat_w = max(spec.width_in, 1e-6)
    nat_h = max(spec.height_in, 1e-6)
    ratio = min(1.0, width_in / nat_w, layout.max_card_height_in / nat_h)
    return (round(nat_w * ratio, 6), round(nat_h * ratio, 6))


def _preset(card: CardSpec, layout: LayoutSpec) -> tuple:
    """按内容自然尺寸推一个预设盒子（等比缩到可用宽度/最高限制内）。

    高度上限来自 ``LayoutSpec.max_card_height_ratio``（用户 m06230：这条政策
    从本模块挪进版面规格，编排层不再自己定死一个数）。
    """
    return _free_width_preset(card, layout, layout.usable_width_in)


def _card_span(card: CardSpec, layout: LayoutSpec) -> int:
    """卡片占几栏：放得下单栏就用单栏（好和别的卡并排），否则占满整行。"""
    if layout.column_count == 1:
        return 1
    natural = build_card(card, layout)
    if natural.width_in <= layout.column_width_in + 1e-9:
        return 1
    return layout.column_count


#: 单栏版面里「图表 + 插图」并排时，图表占可用宽度的这个比例
#: （剩下减去 gutter 就是插图宽度）。图表是主角，所以给它多半。
ILLUSTRATED_CARD_SHARE = 0.66


#: 主题词最短长度。单字词面（「冷」「雪」「火」）命中太吵，直接不要。
THEME_MIN_CHARS = 2


def load_theme_terms(db_path: str = DB_PATH) -> dict:
    """主题词表：``{词面: 规范标签}``（S6 桥接 0.1）。

    词表从 ``tag_vocabulary`` 的 ``semantic`` 标签导出、且只收**真正挂在可检索
    素材上**的词（``semantic_theme_terms``）—— 反向匹配，不从零编一份主题词表。
    单字词面（「冷」「雪」）在这里就丢掉：表就是「能用的词」，``extract_theme``
    里那道同样的长度检查只是给外部自定义词表兜底。
    库读不了就退回空表：没有主题也能排版，只是插图回到按图表语义选。
    """
    try:
        terms = semantic_theme_terms(db_path)
    except Exception:
        return {}
    return {w: t for w, t in terms.items() if len(w) >= THEME_MIN_CHARS}


def extract_theme(text: str, terms: dict) -> str | None:
    """从一段文字里抽主题标签；命中多个词面时取**最长的**那个。

    「分年龄看，各年龄段消费者的取暖电器成交额占比不同」同时命中「取暖电器」
    （4 字）与「年龄段」（人群 的别名，3 字）——取长的，因为这段真正在讲的是
    取暖电器。长度并列时按词面字典序，保证同样的稿子永远得到同样的结果。
    """
    best = None
    for word, tag in terms.items():
        if len(word) < THEME_MIN_CHARS or word not in text:
            continue
        key = (-len(word), word)
        if best is None or key < best[0]:
            best = (key, tag)
    return best[1] if best else None


def _rows_for_tag(tag: str, db_path: str) -> list:
    """按标签查素材；库读不了当查不到（不抛给排版层）。"""
    try:
        return find_assets_by_theme(tag, db_path)
    except Exception:
        return []


def _pick_illustration(theme: str | None, semantic: str | None, db_path: str,
                       used: set) -> tuple:
    """挑一张装饰插图：**主题优先、图表语义兜底、都不行跳过**（S6 桥接 0.1）。

    决策树（用户 m06739 拍板）：

    1. 有主题 → 按主题（``semantic`` 标签）查，取该档里第一个没用过的素材；
    2. 主题查不到、或主题那档的图本页已经用过 → **降级**按 ``chart_semantic`` 查；
    3. 两边都查不到（或查到的也用过）→ 返回 ``(None, None)`` —— 这一处不配图，
       排版照走。少一张插图是遗憾，排不出整版是事故。

    每一步都只取**没用过**的 ``asset_id``：同一页贴两张一样的图标，比少一张更
    难看。返回 ``(block, basis)``，``basis`` 是 ``"theme"`` / ``"chart_semantic"``
    / ``None``，给汇报用。

    结果顺序**照用视图的排序**（weight 降序、同权重按 id），调用方不再自己排
    一遍：权重就是 S4 表达「同一档里谁更适合当配图」的方式。
    """
    for basis, tag in (("theme", theme), ("chart_semantic", semantic)):
        if not tag:
            continue
        for row in _rows_for_tag(tag, db_path):
            if row.get("kind") != "icon":
                continue
            asset_id = row.get("asset_id")
            if asset_id in used:
                continue
            path = (row.get("local_path") or "").replace("\\", "/")
            if not path:
                continue
            used.add(asset_id)
            block = ImageBlock(path=path, style="icon", column_span=1,
                               asset_id=asset_id, tag=row.get("tag") or tag,
                               semantic=semantic or tag,
                               name=f"illustration_{asset_id}")
            return block, basis
    return None, None


def _fallback_note(rationale: str) -> str:
    """把选型器的拒选理由翻成一句读者能懂的话，写进占位图（用户 m06230）。"""
    if "MAX_SLICES" in rationale or "max_slices" in rationale:
        return "示意图：分项过多，建议看表格。"
    if "全相等" in rationale:
        return "示意图：各项数值完全相同，看表格更清楚。"
    if "含负值" in rationale:
        return "示意图：这组数据含负值，不适合这种画法。"
    return "示意图：这组数据暂时没有合适的图形，先占个位。"


def build_flow(text: str, *, layout: LayoutSpec | None = None,
               db_path: str = DB_PATH, catalog: list | None = None,
               on_unapplicable: str = "placeholder") -> ComposeResult:
    """把一段稿子编排成混合流（不改库、不渲染）。"""
    if on_unapplicable not in ("skip", "placeholder"):
        raise ValueError("on_unapplicable must be 'skip' or 'placeholder': "
                         f"{on_unapplicable!r}")
    layout = layout or LayoutSpec()
    catalog = catalog if catalog is not None else load_catalog(db_path)
    paragraphs = split_paragraphs(text)
    title, lead, body = split_title_lead(paragraphs)

    span = layout.column_count
    flow: list = [TextBlock(title, "title", "center", column_span=span)]
    if lead:
        flow.append(TextBlock(lead, "body"))

    # 主题词表从库里反着导（只收真挂了素材的 semantic 标签），库读不了就是空表。
    terms = load_theme_terms(db_path)
    themes: dict = {title: extract_theme(title, terms)}
    if lead:
        themes[lead] = extract_theme(lead, terms)

    matches, notes, used = [], [], set()
    used_assets: set = set()
    for paragraph in body:
        dataset, score, hits = match_dataset(paragraph, catalog, used)
        theme = extract_theme(paragraph, terms)
        themes[paragraph] = theme
        if dataset is None:
            flow.append(TextBlock(paragraph, "body"))
            continue
        points = load_points(db_path, dataset.key)[1]
        decision = select(features_from_points(points, dataset.semantic))
        template = decision["selected_template"]
        rationale = decision["rationale"]
        used.add(dataset.key)
        if template is None:
            notes.append({"kind": "not_applicable", "dataset": dataset.key,
                          "paragraph": paragraph[:24],
                          "reason": rationale,
                          "policy": on_unapplicable})
            if on_unapplicable == "skip":
                flow.append(TextBlock(paragraph, "body"))
                matches.append(Match(paragraph, dataset.key, dataset.title,
                                     None, rationale, score, None))
                continue
            template = "placeholder"
        # 插图只在「真的画了图表」时配：占位图本身就是一张图，再配一张很怪。
        # 选图决策树（S6 桥接 0.1，用户 m06739 拍板）：主题优先 → 被占用/查不到
        # 就降级按图表语义 → 还是不行就这一处不配图，排版照走。
        if template == "placeholder":
            illustration, basis = None, None
        else:
            illustration, basis = _pick_illustration(theme, dataset.semantic,
                                                     db_path, used_assets)
        card = CardSpec(name=dataset.key, kind=template,
                        chart_key=dataset.key, semantic=dataset.semantic,
                        title=dataset.title,
                        note=(_fallback_note(rationale)
                              if template == "placeholder" else None))
        if illustration is not None and layout.column_count > 1:
            # 多栏：段落独占一整行（内部按栏折行），下一行留给
            # 「图表 1 栏 + 插图 1 栏」并排 —— 报纸里图文咬合的样子。
            flow.append(TextBlock(paragraph, "body",
                                  column_span=layout.column_count,
                                  columns=layout.column_count))
            # 要和插图并排就必须退到单栏（否则卡片吃满整行，插图只能掉下一行）。
            card.column_span = 1
            illustration.column_span = 1
            card.width_in, card.height_in = _preset(card, layout)
        elif illustration is not None:
            # 单栏：没有第二条栏位，就把这一行**自己切成两段**（图表宽一些，
            # 插图窄一些）。行高是两者较大者，插图通常矮于图表，所以并排
            # 不多占一行的高度 —— 插图等于白搭。
            flow.append(TextBlock(paragraph, "body"))
            card_w = round(layout.usable_width_in * ILLUSTRATED_CARD_SHARE, 6)
            illustration.width_in = round(
                layout.usable_width_in - card_w - layout.gutter_in, 6)
            card.column_span = 1
            card.width_in, card.height_in = _free_width_preset(card, layout,
                                                               card_w)
        else:
            flow.append(TextBlock(paragraph, "body"))
            card.column_span = _card_span(card, layout)
            card.width_in, card.height_in = _preset(card, layout)
        flow.append(card)
        if illustration is not None:
            flow.append(illustration)
        matches.append(Match(paragraph, dataset.key, dataset.title, template,
                             rationale, score, card.name,
                             illustration.name if illustration else None,
                             theme=theme, illustration_basis=basis))

    if not matches:
        notes.append({"kind": "no_data_matched",
                      "reason": "稿子里没有提到任何数据组，退化为纯文本页",
                      "paragraphs": len(body)})
    return ComposeResult(flow=flow, matches=matches, notes=notes, themes=themes)


def compose_page(text: str, out_dir: str, *, width_in: float = 10.0,
                 height_in: float = 15.0, margin_in: float = 0.4,
                 gutter_in: float = 0.3, db_path: str = DB_PATH,
                 on_unapplicable: str = "placeholder",
                 column_count: int = 1,
                 column_gutter_in: float = 0.2,
                 max_card_height_ratio: float = 0.35) -> ComposeResult:
    """自动编排 + 流式排版 + 整版渲染，产物落 ``out_dir``。"""
    from loop.render_page import render_layout

    layout = LayoutSpec(width_in=width_in, height_in=height_in,
                        margin_in=margin_in, gutter_in=gutter_in,
                        column_count=column_count,
                        column_gutter_in=column_gutter_in,
                        max_card_height_ratio=max_card_height_ratio)
    result = build_flow(text, layout=layout, db_path=db_path,
                        on_unapplicable=on_unapplicable)
    os.makedirs(out_dir, exist_ok=True)
    page = flow_layout(layout, result.flow)
    result.page = page
    with open(page_spec_path(out_dir), "w", encoding="utf-8") as fh:
        json.dump(page.to_dict(), fh, ensure_ascii=False, indent=2)
    rendered = render_layout(page, out_dir)
    result.outputs = {"preview": rendered["preview"], "pptx": rendered["pptx"],
                      "pagelayout": page_spec_path(out_dir)}
    with open(os.path.join(out_dir, "flow.json"), "w", encoding="utf-8") as fh:
        json.dump(result.to_dict(), fh, ensure_ascii=False, indent=2)
    return result
