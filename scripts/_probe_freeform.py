"""只读探针：验证 python-pptx 1.0.2 的 freeform 是否能画「多轮廓小矩形 + 描边」。"""
import os
import sys

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Inches, Pt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.scratch import mkdtemp  # noqa: E402

d = mkdtemp(prefix="freeform-")
out = os.path.join(d, "probe.pptx")

prs = Presentation()
prs.slide_width = Inches(4)
prs.slide_height = Inches(3)
slide = prs.slides.add_slide(prs.slide_layouts[6])

# 两个分离的闭合小矩形，用 move_to 开第二个轮廓
# 局部单位必须是整数（库内先 round 再乘 scale）→ 直接用 EMU，scale=1
EMU_IN = 914400
x0, y0 = int(0.5 * EMU_IN), int(0.5 * EMU_IN)
b = slide.shapes.build_freeform(x0, y0, scale=1.0)
rects = [
    [(0, 0), (0.09, 0), (0.09, 0.012), (0, 0.012)],
    [(0, 0.2), (0, 0.2), (0.09, 0.212), (0, 0.212)],
]
rects[1] = [(0, 0.2), (0.09, 0.2), (0.09, 0.212), (0, 0.212)]
for i, r in enumerate(rects):
    pts = [(x0 + int(px * EMU_IN), y0 + int(py * EMU_IN)) for px, py in r]
    if i:
        b.move_to(pts[0][0], pts[0][1])
    b.add_line_segments(pts[1:], close=True)
shp = b.convert_to_shape()
shp.name = "ticks_1"
shp.fill.solid()
shp.fill.fore_color.rgb = RGBColor.from_string("C9C9C9")
shp.line.fill.background()

prs.save(out)

prs2 = Presentation(out)
for s in prs2.slides[0].shapes:
    print("name=", s.name, "type=", s.shape_type,
          "l/t/w/h=", s.left, s.top, s.width, s.height)
print("OUT", out)
