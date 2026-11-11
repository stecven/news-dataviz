"""预览产物：从同一份 PageSpec 用 Pillow 出 PNG（1000×600 @100px/in）。

预览不是可编辑源；它只用于目视确认「5 支长短不一的温度计」。
"""
import os

from PIL import Image, ImageDraw, ImageFont

from loop import palette
from loop.frame import BORDER_ROLE
from loop.models import PageSpec

PX_PER_IN = 100
_FONT_PATH = "C:/Windows/Fonts/msyh.ttc"

#: 元素描边色 / 文本色 / 兜底填充色，全部来自色板（m04549：颜色单一来源）。
#: PNG 预览需要轮廓才能看清色块边界；PPTX 端形状靠填充区分，不描边。
_EDGE = "#" + palette.color("neutral_mid")
#: 半圆扇区描边（用户 m05688）。0.5 pt 在 100 px/in 下约 0.69 px，Pillow 的
#: pieslice 只支持整数线宽，取整为 1 px——再细就画不出来。
_SECTOR_EDGE = "#" + palette.color(palette.SECTOR_STROKE_ROLE)
_TEXT = "#" + palette.color("text")
_SURFACE = "#" + palette.color("surface")


#: 1 pt = 1/72 in；预览画布按 100 px/in 出图，故 pt → px 要乘 100/72。
#: 色板字号表给的是 pt（与 PPTX 端 Pt(x) 同口径），预览层必须换算，
#: 否则 8 pt 的注释会被当成 8 像素画出来，小到看不见。
_PX_PER_PT = PX_PER_IN / 72.0


def _font(size=14):
    try:
        return ImageFont.truetype(_FONT_PATH, size)
    except (OSError, FileNotFoundError):
        return ImageFont.load_default()


def _render_order(spec: PageSpec) -> list:
    """z-order：先画形状（扇区/矩形/椭圆），文字一律留到最后画。

    半圆图的 sector 是整圆 PIE 的 180° 楔形，其 bbox 覆盖 (250..750, 50..350)
    一整块；若按规格顺序先画文字再画扇区，中心百分比与量程说明会被色块盖掉。
    文字后置与规格 / 求解器无关，纯粹是渲染层的绘制顺序（两个后端同口径）。
    """
    shapes = [e for e in spec.elements if e.type != "text"]
    texts = [e for e in spec.elements if e.type == "text"]
    return shapes + texts


def render_preview(spec: PageSpec, out_path: str) -> None:
    # 画布变大/变小后字号跟着走（用户 m05688），比例取自图框尺寸。
    scale = palette.spec_scale(spec)

    img = Image.new(
        "RGB",
        (int(spec.width_in * PX_PER_IN), int(spec.height_in * PX_PER_IN)),
        _SURFACE,
    )
    draw = ImageDraw.Draw(img)

    for el in _render_order(spec):
        box = (int(el.x_in * PX_PER_IN), int(el.y_in * PX_PER_IN),
               int((el.x_in + el.w_in) * PX_PER_IN),
               int((el.y_in + el.h_in) * PX_PER_IN))
        if el.type == "text":
            _draw_text(draw, box, el.text or "", el.role,
                       align=((el.geometry or {}).get("align") or "center"),
                       scale=scale)
        elif el.role == "frame":
            # 图框（用户 m04818）：白底 + 一圈可见边框。边框色写在 geometry 里，
            # 不画在 fill 里——fill 是框内的底。
            border = (el.geometry or {}).get("border") or palette.color(BORDER_ROLE)
            draw.rectangle(box, fill=_hex(el.fill), outline="#" + border, width=2)
        elif el.role == "title_band":
            # 标题带：一条中性浅灰底，正好衬在左对齐标题下面。
            draw.rectangle(box, fill=_hex(el.fill))
        elif el.type == "ticks":
            # 报纸原版皮肤：管身右侧短刻度条（几何与 PPTX freeform 同源）。
            from loop.thermo_shape import tick_rects
            for x, y, w, h in tick_rects(el):
                draw.rectangle((int(x * PX_PER_IN), int(y * PX_PER_IN),
                                int((x + w) * PX_PER_IN), int((y + h) * PX_PER_IN)),
                               fill=_hex(el.fill))
        elif el.type == "outline":
            # 外圈轮廓：管口半圆顶 + 管身 + 锥形收口 + 球泡外环，一条闭合折线。
            # PIL 没有「只描边」的 polyline 填充口径，这里用 pd 的多边形描边。
            from loop.thermo_shape import outline_polyline
            pts = [(px * PX_PER_IN, py * PX_PER_IN) for px, py in outline_polyline(el)]
            draw.line(pts, fill=_hex(el.fill), width=3, joint="curve")
        elif el.type == "ellipse":
            draw.ellipse(box, fill=_hex(el.fill), outline=_EDGE)
        elif el.type == "arc":
            # 半圆扇区：Pillow pieslice 用 start/end angle（度），0°在 3 点方向，
            # 与 python-pptx PIE 的 α₀=180° 口径一致（下半平面）。
            g = el.geometry or {}
            draw.pieslice(box, start=g.get("start_angle", 180.0),
                          end=g.get("end_angle", 360.0),
                          fill=_hex(el.fill), outline=_SECTOR_EDGE)
        elif el.type == "image":
            # 图片图元（第五层接线，用户 m04220）：把磁盘上的位图按元素盒缩放贴进去。
            # 这里**必须**和 render.resolve_image_path 用同一套路径解析，否则
            # preview.png 与 pptx 会对不上（一个画出来、一个没有）。
            from loop.render import resolve_image_path
            if not el.image_path:
                raise ValueError(
                    f"{el.id}: image element has no image_path "
                    f"(type='image' requires the path of a file on disk)")
            path = resolve_image_path(el.image_path)
            if not os.path.exists(path):
                raise FileNotFoundError(
                    f"{el.id}: image file not found: {el.image_path} "
                    f"(resolved to {path})")
            pic = Image.open(path).convert("RGBA")
            pic = pic.resize((max(1, box[2] - box[0]), max(1, box[3] - box[1])))
            img.paste(pic, (box[0], box[1]), pic)
        elif el.role == "track":
            # 管身：白色竖直矩形 + 顶部半圆顶（原版 U 形管口）。
            # 不能画矩形描边——那会在管口横一道直角灰线，把半圆顶切成方形。
            draw.rectangle(box, fill=_hex(el.fill))
            cap_r = el.w_in * PX_PER_IN / 2
            cap_cx, cap_cy = (box[0] + box[2]) / 2, box[1] + cap_r
            draw.pieslice((cap_cx - cap_r, cap_cy - cap_r,
                           cap_cx + cap_r, cap_cy + cap_r),
                          start=180, end=360, fill=_hex(el.fill))
        else:
            draw.rectangle(box, fill=_hex(el.fill), outline=_EDGE)

    img.save(out_path, "PNG")


def _draw_text(draw, box, text, role: str, align: str = "center",
               scale: float = 1.0) -> None:
    """按元素盒宽换行并居中绘制，避免超长中文标签溢出到相邻元素。

    字号与行高按 ``role`` 从色板字号表取（m04549）：以前全局固定 14px，
    版面标题和「118%」一样大。现在 title/subtitle/body/label/note 逐档递减。

    PPTX 端靠 word_wrap=True；PNG 端 Pillow 不自动换行，这里手动做等价处理。
    以字符为最小单位逐字累加宽度，CJK 与西文都能正确折行。
    """
    font = _font(int(round(palette.scaled_font_size(role, scale) * _PX_PER_PT)))
    x0, y0, x1, _y1 = box
    max_w = max(1, x1 - x0)
    lines: list[str] = []
    cur = ""
    for ch in text:
        if ch == "\n":
            lines.append(cur)
            cur = ""
            continue
        trial = cur + ch
        if cur and draw.textlength(trial, font=font) > max_w:
            lines.append(cur)
            cur = ch
        else:
            cur = trial
    if cur:
        lines.append(cur)

    line_h = palette.line_height_px(role, scale=scale)
    # 图框的标题带显式要求左对齐（用户 m04818）；其余元素沿用居中。
    left = (align or "center").lower() == "left"
    for i, line in enumerate(lines[:4]):          # 盒高最多容 4 行，多余裁掉
        w = draw.textlength(line, font=font)
        x = x0 if left else x0 + (max_w - w) / 2
        # 左对齐时文字垂直居中在带里：带高 50 px、字号 20 pt 时约偏下 6 px。
        dy = max(0.0, (box[3] - box[1] - line_h * len(lines[:4])) / 2) if left else 0.0
        draw.text((x, y0 + dy + i * line_h), line, fill=_TEXT, font=font)


def _hex(fill: str | None) -> str:
    return "#" + (fill or palette.color("surface"))
