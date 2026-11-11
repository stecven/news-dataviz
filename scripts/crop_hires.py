# -*- coding: utf-8 -*-
"""从全分辨率原图 / 预览图裁出各区块，便于逐块核对细节。"""
import os
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORIG = os.path.join(ROOT, "assets", "3d38891c-b26a-417c-9e9c-38744d388ee8.jpg.2")
MINE = os.path.join(ROOT, "out", "preview6", "p", "幻灯片1.PNG")
OUT = os.path.join(ROOT, "out", "hi")
os.makedirs(OUT, exist_ok=True)

o = Image.open(ORIG).convert("RGB")   # 1600 x 2267
m = Image.open(MINE).convert("RGB")   # 960 x 1360

def norm(im, W=1000, H=1417):
    return im.resize((W, H), Image.LANCZOS)

# 用归一化坐标(1000x1417)定义区域
REGIONS = {
    "header":   (0, 0, 1000, 170),
    "body":     (0, 150, 620, 500),
    "sec1":     (580, 155, 1000, 340),
    "sec2a":    (0, 320, 1000, 560),
    "sec2b":    (0, 530, 1000, 810),
    "sec3":     (0, 900, 1000, 1270),
    "footer":   (0, 1280, 1000, 1417),
}

for name, box in REGIONS.items():
    # 原图：归一化坐标 -> 全分辨率坐标
    ob = tuple(int(v * 1.6) for v in box)
    oc = o.crop(ob)
    # 预览图：归一化坐标 -> 960x1360 坐标
    mb = (int(box[0] * 0.96), int(box[1] * 0.96), int(box[2] * 0.96), int(box[3] * 0.96))
    mc = m.crop(mb)
    # 统一放大到相同宽度
    W = 1400
    oc = oc.resize((W, int(oc.height * W / oc.width)), Image.LANCZOS)
    mc = mc.resize((W, int(mc.height * W / mc.width)), Image.LANCZOS)
    oc.save(os.path.join(OUT, name + "_orig.png"))
    mc.save(os.path.join(OUT, name + "_mine.png"))
print("ok")
