# -*- coding: utf-8 -*-
"""把原图与成品预览统一到 1000x1417 并排/叠加，便于比对版式差距。"""
import os
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORIG = os.path.join(ROOT, "assets", "3d38891c-b26a-417c-9e9c-38744d388ee8.jpg.2")
MINE = os.path.join(ROOT, "out", "preview6", "p", "幻灯片1.PNG")
OUT = os.path.join(ROOT, "out")

o = Image.open(ORIG).convert("RGB").resize((1000, 1417), Image.LANCZOS)
m = Image.open(MINE).convert("RGB").resize((1000, 1417), Image.LANCZOS)
o.save(os.path.join(OUT, "cmp_orig.png"))
m.save(os.path.join(OUT, "cmp_mine.png"))

sbs = Image.new("RGB", (2010, 1417), "white")
sbs.paste(o, (0, 0))
sbs.paste(m, (1010, 0))
sbs.save(os.path.join(OUT, "cmp_sbs.png"))

ov = Image.blend(o, m, 0.5)
ov.save(os.path.join(OUT, "cmp_overlay.png"))
print("ok")
