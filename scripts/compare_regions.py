# -*- coding: utf-8 -*-
"""分区放大对比：每块区域「上=原图，下=复刻」，方便看细节差距。"""
import os
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORIG = os.path.join(ROOT, "assets", "3d38891c-b26a-417c-9e9c-38744d388ee8.jpg.2")
MINE = os.path.join(ROOT, "out", "preview6", "p", "幻灯片1.PNG")
OUT = os.path.join(ROOT, "out", "cmp")
os.makedirs(OUT, exist_ok=True)

# 原图按 1000 宽归一化；预览图也归一到 1000x1417
o = Image.open(ORIG).convert("RGB").resize((1000, 1417), Image.LANCZOS)
m = Image.open(MINE).convert("RGB").resize((1000, 1417), Image.LANCZOS)

REGIONS = {
    "r1_header_title": (0, 0, 1000, 175),
    "r2_body": (0, 160, 680, 520),
    "r3_sec1": (650, 150, 1000, 340),
    "r4_sec2_top": (0, 330, 1000, 560),
    "r5_sec2_mid": (0, 540, 1000, 800),
    "r6_sec3": (0, 900, 1000, 1260),
    "r7_footer": (0, 1250, 1000, 1417),
}

for name, box in REGIONS.items():
    a = o.crop(box)
    b = m.crop(box)
    w, h = a.size
    scale = 2 if w <= 700 else 1.6
    W, H = int(w * scale), int(h * scale)
    a = a.resize((W, H), Image.LANCZOS)
    b = b.resize((W, H), Image.LANCZOS)
    canvas = Image.new("RGB", (W, H * 2 + 26), "white")
    canvas.paste(a, (0, 0))
    canvas.paste(b, (0, H + 26))
    d = ImageDraw.Draw(canvas)
    d.rectangle([0, H + 2, W, H + 26], fill=(20, 20, 20))
    d.text((8, H + 7), "ORIGINAL  ^   /   MINE  v", fill="white")
    canvas.save(os.path.join(OUT, name + ".png"))
print("ok")
