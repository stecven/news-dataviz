# -*- coding: utf-8 -*-
"""放大原图左下角，确认是否有二维码 / 更多内容扫码观看。"""
import os
from PIL import Image
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
o = Image.open(os.path.join(ROOT, "assets", "3d38891c-b26a-417c-9e9c-38744d388ee8.jpg.2")).convert("RGB")
# 全分辨率 1600x2267；取左下角
c = o.crop((0, 1900, 620, 2267))
c = c.resize((1240, 734), Image.LANCZOS)
c.save(os.path.join(ROOT, "out", "hi", "orig_bottomleft.png"))
print("ok")
