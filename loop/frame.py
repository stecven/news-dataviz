"""图框 + 标题带（用户 m04818）：把「一张图表」包成一个完整的卡片。

为什么单独一个模块
------------------
图框不是「图形几何」，也不参与任何数据驱动的约束（C1–C8 只约束数据图形）。
它是一层 chrome：在坐标已经解完之后，围绕内容外接盒补一圈边距、一条标题带、
一个标题、一行面向读者的说明。把它独立出来有两个好处：

1. ``loop/solve.py`` 的求解器完全不认识图框，求解逻辑零改动；
2. ``validate_spec`` 只要「把图框拆掉、还原成内容坐标」就能沿用原有全部
   校验器（见 :func:`unwrap`），不需要给 C1/C6/C7 这些依赖画布尺寸的约束
   再加一套「框内坐标系」的分支。

坐标约定
--------
- **内容坐标**（content space）：求解器直接产出的那套坐标，画布 = ``width_in ×
  height_in``（温度计/半圆都是 10×6）。``loop/solve.py`` 的全部约束都活在这里。
- **卡片坐标**（frame space）：内容整体平移 + 加框之后的坐标，画布 = 框大小。

``PageSpec.width_in / height_in`` 在包框之后指的是**框**的大小（用户 m04818 裁定），
内容原来的画布尺寸记在 ``layout["frame"]["canvas"]``，内容外接盒记在
``PageSpec.content_bbox``，框的外接盒记在 ``PageSpec.frame_bbox``——版式引擎
两个尺寸都要，才能决定按框缩放还是按内容缩放。

留痕
----
``layout["frame"]`` 记录 ``origin``（内容坐标系原点在卡片里的位置）与 ``canvas``
（内容画布尺寸），这两个数让 :func:`unwrap` 能精确还原，不靠猜。
"""
from dataclasses import replace

from loop import palette
from loop.models import ElementSpec, PageSpec

# ---------------------------------------------------------------------------
# 规格（用户 m04818：内边距 0.3 in、标题带约 0.5 in）
# ---------------------------------------------------------------------------
#: 内容（含标题带）到框线的内边距。框图 = 内容外接盒 + 2 × PAD_IN。
PAD_IN = 0.3
#: 标题带高度。标题文字盒与之等高，20 pt 标题在其中垂直居中。
BAND_H_IN = 0.5
#: 标题带与说明之间的间距。
BAND_GAP_IN = 0.15
#: 说明行高（与模板参数 h_note 同口径）。
NOTE_H_IN = 0.3
#: 说明与图形区之间的间距。
NOTE_GAP_IN = 0.2
#: 标题 / 说明相对标题带左右边的额外内缩。带本身铺满内宽，
#: 但文字不能贴着带边——那是 PPT 占位符的观感，不是排版。
TEXT_INSET_IN = 0.15

#: 不属于「内容」的 role：标题/说明会被重新摆放，框与带本身就是 chrome。
CHROME_ROLES = ("frame", "title_band", "title", "subtitle", "scale_note")

FRAME_ID = "frame"
BAND_ID = "title_band"

#: ``ElementSpec.geometry`` 里按**绝对坐标**记录、必须跟着平移一起动的键。
#: 教训（用户 m05104）：只平移 x_in/y_in、不动 geometry 里的绝对坐标，会让
#: 直接读这些坐标的渲染器（外圈轮廓、扇区圆心）和 bbox 错开一个平移量——
#: 而且是「自洽地错」：unwrap 之后校验器重算出来的又跟它吻合，抓不到。
ABS_X_KEYS = ("cx",)
ABS_Y_KEYS = ("cy", "cap_top", "tube_bottom")

#: 框线颜色（色板单一来源）。用 neutral_mid 而不是发丝线，肉眼要看得见。
BORDER_ROLE = "neutral_mid"
#: 标题带填充色。中性浅灰，不改色板即可获得一条可见的带。
BAND_ROLE = "neutral_light"


def _shift_geometry(geometry: dict | None, dx: float, dy: float) -> dict | None:
    """把 geometry 里的绝对坐标整体平移 (dx, dy)；相对量（R / 角度）不动。"""
    if not geometry:
        return geometry
    out = dict(geometry)
    for k in ABS_X_KEYS:
        if isinstance(out.get(k), (int, float)):
            out[k] = round(float(out[k]) + dx, 6)
    for k in ABS_Y_KEYS:
        if isinstance(out.get(k), (int, float)):
            out[k] = round(float(out[k]) + dy, 6)
    return out


def content_bbox(elements) -> tuple[float, float, float, float]:
    """内容外接盒 (x0, y0, x1, y1)：排除标题/说明/框/带这些 chrome。

    空内容（理论上不会出现）抛 ValueError——静默返回全零会让图框缩成一个点。
    """
    boxes = [(e.x_in, e.y_in, e.x_in + e.w_in, e.y_in + e.h_in)
             for e in elements if e.role not in CHROME_ROLES]
    if not boxes:
        raise ValueError("cannot frame a spec with no content elements")
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def wrap(spec: PageSpec, note_text: str | None = None,
         subtitle_text: str | None = None,
         canvas_in: tuple[float, float] | None = None) -> PageSpec:
    """把求解结果包成「框 + 标题带 + 标题 + 说明」。

    内容**尺寸不变**（用户 m04818 选 A：图形一像素不动），只整体平移并加大
    画布。标题改成左对齐、贴框的内边距；说明同样左对齐落在标题带下面。

    ``note_text`` 为空时沿用原 scale_note 的文字；``subtitle_text`` 非空时在
    标题下再加一行副标题（目前只有占位图会用）。

    ``canvas_in``（用户 m05768）：给定时不按内容长大，而是把框**钉死在**这个
    尺寸上，内容在其中居中。这是「外部给定边界」那一层要用的口径；调用方
    （``loop/fit.py``）负责先确认内容装得下。
    """
    x0, y0, x1, y1 = content_bbox(spec.elements)
    content_w, content_h = x1 - x0, y1 - y0

    # 内容画布（求解时的画布）尺寸，留给 unwrap 与版式引擎。
    canvas_w, canvas_h = float(spec.width_in), float(spec.height_in)

    # 标题带在框内、四周留 PAD_IN；说明紧跟带下；图形区再往下。
    band_y = PAD_IN
    note_y = band_y + BAND_H_IN + BAND_GAP_IN
    content_y0 = note_y + NOTE_H_IN + NOTE_GAP_IN

    dx = PAD_IN - x0                      # 让内容左缘落在内边距上
    dy = content_y0 - y0                  # 让内容顶缘落在说明下方

    if canvas_in is None:
        frame_w = round(content_w + 2 * PAD_IN, 6)
        frame_h = round(content_y0 + content_h + PAD_IN, 6)
    else:
        # 外部给定边界（用户 m05768）：框钉死在给定尺寸，内容居中。
        frame_w = round(float(canvas_in[0]), 6)
        frame_h = round(float(canvas_in[1]), 6)
        avail_w = frame_w - 2 * PAD_IN
        avail_h = frame_h - content_y0 - PAD_IN
        if content_w > avail_w + 1e-6 or content_h > avail_h + 1e-6:
            raise ValueError(
                f"content {content_w:.4f}×{content_h:.4f} in does not fit "
                f"the given canvas {frame_w:g}×{frame_h:g} in "
                f"(available {avail_w:.4f}×{avail_h:.4f})")
        dx = PAD_IN + (avail_w - content_w) / 2.0 - x0
        dy = content_y0 + (avail_h - content_h) / 2.0 - y0
    inner_w = round(frame_w - 2 * PAD_IN, 6)

    text_x = PAD_IN + TEXT_INSET_IN
    text_w = inner_w - 2 * TEXT_INSET_IN
    by_id = {e.id: e for e in spec.elements}
    moved: list[ElementSpec] = []
    for e in spec.elements:
        if e.role in ("frame", "title_band"):
            continue                      # 已经包过框的规格，不重复包
        moved.append(replace(e, x_in=round(e.x_in + dx, 6),
                             y_in=round(e.y_in + dy, 6),
                             geometry=_shift_geometry(e.geometry, dx, dy)))

    # 标题：左对齐贴内边距，盒高 = 带高，垂直居中由渲染器负责。
    title = by_id.get("title")
    title_text = (title.text if title is not None else spec.chart_title) or ""
    moved = [e for e in moved if e.role not in ("title", "subtitle", "scale_note")]

    chrome = [
        ElementSpec(id=FRAME_ID, type="rect", role="frame",
                    x_in=0.0, y_in=0.0, w_in=frame_w, h_in=frame_h,
                    fill=palette.color("surface"),
                    geometry={"border": palette.color(BORDER_ROLE)}),
        ElementSpec(id=BAND_ID, type="rect", role="title_band",
                    x_in=PAD_IN, y_in=band_y, w_in=inner_w, h_in=BAND_H_IN,
                    fill=palette.color(BAND_ROLE)),
        ElementSpec(id="title", type="text", role="title",
                    x_in=round(text_x, 6), y_in=band_y,
                    w_in=round(text_w, 6), h_in=BAND_H_IN,
                    text=title_text, geometry={"align": "left"}),
    ]
    if subtitle_text:
        # 副标题（数据来源 / 时间范围之类）：带内第二行，字号 subtitle 档。
        chrome.append(ElementSpec(
            id="subtitle", type="text", role="subtitle",
            x_in=round(text_x, 6), y_in=round(band_y + BAND_H_IN * 0.62, 6),
            w_in=round(text_w, 6), h_in=round(BAND_H_IN * 0.38, 6),
            text=subtitle_text, geometry={"align": "left"}))
    note = note_text
    if note is None:
        note_el = by_id.get("scale_note")
        note = note_el.text if note_el is not None else ""
    if note:
        chrome.append(ElementSpec(
            id="scale_note", type="text", role="scale_note",
            x_in=round(text_x, 6), y_in=note_y,
            w_in=round(text_w, 6), h_in=NOTE_H_IN,
            text=note, geometry={"align": "left"}))

    layout = dict(spec.layout or {})
    layout["frame"] = {
        "origin": [round(dx, 6), round(dy, 6)],
        "canvas": [canvas_w, canvas_h],
        "pad_in": PAD_IN,
        "band_h_in": BAND_H_IN,
        "canvas_in": [frame_w, frame_h],
    }

    return PageSpec(
        width_in=frame_w,
        height_in=frame_h,
        chart_key=spec.chart_key,
        chart_title=spec.chart_title,
        scale=spec.scale,
        elements=chrome + moved,
        semantic_tags=list(spec.semantic_tags),
        constraints=list(spec.constraints),
        layout=layout,
        content_bbox=[round(x0 + dx, 6), round(y0 + dy, 6),
                      round(content_w, 6), round(content_h, 6)],
        frame_bbox=[0.0, 0.0, frame_w, frame_h],
    )


def unwrap(spec: PageSpec) -> PageSpec:
    """把卡片规格还原成内容坐标（供 validate_spec 复用原有全部校验器）。

    不是卡片规格（``layout`` 里没有 ``frame``）时原样返回。还原是精确的：
    平移量取自 ``layout["frame"]["origin"]``，画布尺寸取自 ``canvas``，
    所以 C1/C6/C7 这些依赖画布与边距的约束看到的还是求解时那套数。
    """
    meta = (spec.layout or {}).get("frame")
    if not meta:
        return spec
    dx, dy = meta["origin"]
    canvas_w, canvas_h = meta["canvas"]
    # 标题/说明的卡片坐标无法反推回求解坐标（wrap 时它们被重新摆放了），
    # 所以整块 chrome 一并丢掉——它们是图框自己的事，由 validate_frame 校验，
    # 而 C1/C6/C7 这些内容约束从来不管标题放在哪。
    keep = [e for e in spec.elements if e.role not in CHROME_ROLES]
    restored = [replace(e, x_in=round(e.x_in - dx, 6),
                        y_in=round(e.y_in - dy, 6),
                        geometry=_shift_geometry(e.geometry, -dx, -dy))
                for e in keep]
    layout = {k: v for k, v in (spec.layout or {}).items() if k != "frame"}
    return PageSpec(
        width_in=canvas_w,
        height_in=canvas_h,
        chart_key=spec.chart_key,
        chart_title=spec.chart_title,
        scale=spec.scale,
        elements=restored,
        semantic_tags=list(spec.semantic_tags),
        constraints=list(spec.constraints),
        layout=layout,
    )


# ---------------------------------------------------------------------------
# 图框自己的校验（不归 solve.py 的 C1–C8 管）
# ---------------------------------------------------------------------------
def validate_frame(spec: PageSpec) -> PageSpec:
    """检查卡片规格的三件套是否齐、是否对齐、是否落在框里。

    与 ``validate_spec`` 分开：``validate_spec`` 校验**内容**，由 ``unwrap``
    还原成求解坐标后跑原有全部约束；这里校验**chrome**（框 / 标题带 / 标题 /
    说明），两者职责不混。
    """
    meta = (spec.layout or {}).get("frame")
    if not meta:
        raise ValueError("spec has no frame metadata (layout['frame'])")
    by_id = {e.id: e for e in spec.elements}
    for want in (FRAME_ID, BAND_ID, "title"):
        if want not in by_id:
            raise ValueError(f"framed spec is missing element {want!r}")

    def _close(a, b):
        return abs(a - b) <= 1e-6

    pad = float(meta["pad_in"])
    frame, band = by_id[FRAME_ID], by_id[BAND_ID]
    # 框 = 画布，且起点在原点
    if not (_close(frame.x_in, 0.0) and _close(frame.y_in, 0.0)
            and _close(frame.w_in, spec.width_in)
            and _close(frame.h_in, spec.height_in)):
        raise ValueError(
            f"frame box {[frame.x_in, frame.y_in, frame.w_in, frame.h_in]} "
            f"!= canvas {[spec.width_in, spec.height_in]}")
    # 标题带贴住框的内边距，横向铺满内宽
    if not (_close(band.x_in, pad) and _close(band.y_in, pad)
            and _close(band.w_in, spec.width_in - 2 * pad)
            and _close(band.h_in, BAND_H_IN)):
        raise ValueError(
            f"title band {[band.x_in, band.y_in, band.w_in, band.h_in]} "
            f"is not padded by {pad} or not {BAND_H_IN} high")
    # 标题必须与带同高、同在带内、左对齐（用户 m04818 要求统一左对齐）
    title = by_id["title"]
    if not (_close(title.y_in, band.y_in) and _close(title.h_in, band.h_in)):
        raise ValueError("title is not vertically centred in the title band")
    if not (title.x_in >= band.x_in - 1e-6
            and title.x_in + title.w_in <= band.x_in + band.w_in + 1e-6):
        raise ValueError("title overflows the title band")
    if ((title.geometry or {}).get("align") or "").lower() != "left":
        raise ValueError("title is not left aligned")
    # 内容必须在框内（留出内边距），且 content_bbox 与实算一致
    x0, y0, x1, y1 = content_bbox(spec.elements)
    if (x0 < pad - 1e-6 or y0 < pad - 1e-6
            or x1 > spec.width_in - pad + 1e-6
            or y1 > spec.height_in - pad + 1e-6):
        raise ValueError(
            f"content {[x0, y0, x1, y1]} does not sit inside the frame "
            f"with pad {pad}")
    if spec.content_bbox is not None:
        want = [round(x0, 6), round(y0, 6), round(x1 - x0, 6), round(y1 - y0, 6)]
        got = [round(float(v), 6) for v in spec.content_bbox]
        if got != want:
            raise ValueError(f"content_bbox {got} != measured {want}")
    if spec.frame_bbox is not None:
        want_f = [0.0, 0.0, round(spec.width_in, 6), round(spec.height_in, 6)]
        got_f = [round(float(v), 6) for v in spec.frame_bbox]
        if got_f != want_f:
            raise ValueError(f"frame_bbox {got_f} != canvas {want_f}")
    return spec
