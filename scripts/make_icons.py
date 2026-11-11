# -*- coding: utf-8 -*-
"""生成信息图用的小图标（温度计、雪花、水滴、暖气片、袜子、杯子、火焰等），
输出到 assets/icons/*.png，并登记进 assets.db 的 assets 表（kind='icon'）。
全部用 PIL 矢量式绘制，4 倍超采样后缩小，边缘不毛。
"""

import math
import os
import sqlite3
from datetime import datetime

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICONS = os.path.join(ROOT, "assets", "icons")
DB = os.path.join(ROOT, "db", "assets.db")
S = 4  # 超采样倍数
W = 400  # 逻辑尺寸


def canvas(size=W):
    return Image.new("RGBA", (size * S, size * S), (0, 0, 0, 0))


def finish(im, name):
    out = im.resize((W, W), Image.LANCZOS)
    path = os.path.join(ICONS, name + ".png")
    out.save(path)
    return path


def thermometer(color=(226, 58, 44), tube=(70, 70, 78), face=(255, 255, 255)):
    """温度计：竖管 + 圆球 + 液柱 + 刻度。"""
    im = canvas()
    d = ImageDraw.Draw(im)
    cx, top, bulb_r = W // 2, 34, 46
    tube_w = 34
    # 管身外壳
    d.rounded_rectangle([(cx - tube_w // 2) * S, top * S, (cx + tube_w // 2) * S, (W - bulb_r * 2 + 6) * S],
                        radius=tube_w // 2 * S, fill=tube, outline=None)
    # 球
    d.ellipse([(cx - bulb_r) * S, (W - bulb_r * 2) * S, (cx + bulb_r) * S, W * S], fill=color)
    # 内部白腔
    d.rounded_rectangle([(cx - 11) * S, (top + 8) * S, (cx + 11) * S, (W - bulb_r * 2 + 2) * S],
                        radius=11 * S, fill=face)
    # 液柱
    d.rounded_rectangle([(cx - 11) * S, (120) * S, (cx + 11) * S, (W - bulb_r * 2 + 4) * S],
                        radius=11 * S, fill=color)
    # 刻度
    for i in range(9):
        y = (70 + i * 26) * S
        if y > (W - bulb_r * 2 - 10) * S:
            break
        long = i % 2 == 0
        d.line([(cx + 15) * S, y, (cx + (38 if long else 28)) * S, y],
               fill=tube, width=3 * S)
    return finish(im, "thermometer")


def thermometer_flat(color=(226, 58, 44)):
    """扁平温度计，只有轮廓，用于小尺寸。"""
    im = canvas()
    d = ImageDraw.Draw(im)
    cx = W // 2
    d.rounded_rectangle([(cx - 26) * S, 40 * S, (cx + 26) * S, (W - 96) * S],
                        radius=26 * S, fill=color)
    d.ellipse([(cx - 56) * S, (W - 112) * S, (cx + 56) * S, W * S], fill=color)
    d.rounded_rectangle([(cx - 10) * S, 80 * S, (cx + 10) * S, (W - 100) * S],
                        radius=10 * S, fill=(255, 255, 255))
    return finish(im, "thermometer_flat")


def snowflake(color=(58, 132, 200)):
    im = canvas()
    d = ImageDraw.Draw(im)
    cx = cy = W // 2
    for k in range(6):
        a = math.radians(k * 60)
        x2, y2 = cx + 150 * math.cos(a), cy + 150 * math.sin(a)
        d.line([cx * S, cy * S, x2 * S, y2 * S], fill=color, width=16 * S)
        # 分枝
        for t, bl in ((0.55, 46), (0.75, 34)):
            bx, by = cx + 150 * t * math.cos(a), cy + 150 * t * math.sin(a)
            for da in (35, -35):
                aa = a + math.radians(da)
                d.line([bx * S, by * S, (bx + bl * math.cos(aa)) * S, (by + bl * math.sin(aa)) * S],
                       fill=color, width=12 * S)
    d.ellipse([(cx - 26) * S, (cy - 26) * S, (cx + 26) * S, (cy + 26) * S], fill=color)
    return finish(im, "snowflake")


def droplet(color=(72, 160, 214)):
    im = canvas()
    d = ImageDraw.Draw(im)
    pts = []
    for i in range(181):
        t = math.radians(i * 2)
        r = 120 * (1 - math.cos(t)) / 2 + 60
        pts.append((W // 2 + 110 * math.sin(t), 250 - 130 * math.cos(t) * 0 + 0))
    # 用两段：上半尖，下半圆
    d.ellipse([(W // 2 - 110) * S, (W // 2 - 40) * S, (W // 2 + 110) * S, (W // 2 + 180) * S], fill=color)
    d.polygon([(W // 2 * S, 30 * S), (W // 2 - 108) * S, (W // 2 + 20) * S,
               (W // 2 + 108) * S, (W // 2 + 20) * S], fill=color)
    return finish(im, "droplet")


def radiator(color=(232, 96, 60)):
    im = canvas()
    d = ImageDraw.Draw(im)
    for i in range(5):
        x = 52 + i * 66
        d.rounded_rectangle([(x - 22) * S, 96 * S, (x + 22) * S, 330 * S], radius=20 * S, fill=color)
    d.rounded_rectangle([38 * S, 84 * S, 362 * S, 118 * S], radius=17 * S, fill=color)
    d.rounded_rectangle([38 * S, 308 * S, 362 * S, 342 * S], radius=17 * S, fill=color)
    return finish(im, "radiator")


def flame(color=(240, 128, 48)):
    im = canvas()
    d = ImageDraw.Draw(im)
    d.polygon([(W // 2) * S, 30 * S,
               (W // 2 + 96) * S, 180 * S,
               (W // 2 + 110) * S, 268 * S,
               (W // 2) * S, 372 * S,
               (W // 2 - 110) * S, 268 * S,
               (W // 2 - 96) * S, 180 * S], fill=color)
    d.polygon([(W // 2) * S, 150 * S,
               (W // 2 + 52) * S, 250 * S,
               (W // 2) * S, 330 * S,
               (W // 2 - 52) * S, 250 * S], fill=(255, 226, 140))
    return finish(im, "flame")


def sock(color=(150, 108, 200)):
    im = canvas()
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([110 * S, 40 * S, 250 * S, 250 * S], radius=30 * S, fill=color)
    d.pieslice([110 * S, 180 * S, 330 * S, 360 * S], start=180, end=360, fill=color)
    d.rectangle([110 * S, 200 * S, 250 * S, 270 * S], fill=color)
    d.rounded_rectangle([100 * S, 40 * S, 260 * S, 96 * S], radius=24 * S, fill=(255, 255, 255))
    d.rounded_rectangle([110 * S, 52 * S, 250 * S, 84 * S], radius=16 * S, fill=color)
    return finish(im, "sock")


def cup(color=(64, 150, 170)):
    im = canvas()
    d = ImageDraw.Draw(im)
    d.polygon([110 * S, 140 * S, 290 * S, 140 * S, 258 * S, 340 * S, 142 * S, 340 * S], fill=color)
    d.rounded_rectangle([96 * S, 120 * S, 304 * S, 152 * S], radius=16 * S, fill=color)
    for i, x in enumerate((170, 230)):
        d.arc([(x - 40) * S, 30 * S, (x + 40) * S, 140 * S], start=200, end=340, fill=color, width=12 * S)
    return finish(im, "cup")


def pin(color=(196, 46, 46)):
    im = canvas()
    d = ImageDraw.Draw(im)
    d.ellipse([110 * S, 40 * S, 290 * S, 220 * S], fill=color)
    d.polygon([(W // 2) * S, 372 * S, 132 * S, 190 * S, 268 * S, 190 * S], fill=color)
    d.ellipse([158 * S, 88 * S, 242 * S, 172 * S], fill=(255, 255, 255))
    return finish(im, "pin")


def people(color=(96, 120, 190)):
    im = canvas()
    d = ImageDraw.Draw(im)
    for cx, r, base in ((150, 46, 250), (250, 38, 260)):
        d.ellipse([(cx - r) * S, (110 - r) * S, (cx + r) * S, (110 + r) * S], fill=color)
        d.pieslice([(cx - r - 26) * S, base * S, (cx + r + 26) * S, (base + 150) * S],
                   start=180, end=360, fill=color)
    return finish(im, "people")


def percent(color=(180, 60, 60)):
    im = canvas()
    d = ImageDraw.Draw(im)
    d.ellipse([110 * S, 90 * S, 190 * S, 170 * S], outline=color, width=16 * S)
    d.ellipse([210 * S, 230 * S, 290 * S, 310 * S], outline=color, width=16 * S)
    d.line([286 * S, 96 * S, 114 * S, 304 * S], fill=color, width=16 * S)
    return finish(im, "percent")


def leaf(color=(206, 132, 44)):
    im = canvas()
    d = ImageDraw.Draw(im)
    d.polygon([(W // 2) * S, 20 * S, (W // 2 + 130) * S, 150 * S,
               (W // 2 + 90) * S, 320 * S, (W // 2) * S, 380 * S,
               (W // 2 - 90) * S, 320 * S, (W // 2 - 130) * S, 150 * S], fill=color)
    d.line([(W // 2) * S, 60 * S, (W // 2) * S, 360 * S], fill=(255, 255, 255), width=8 * S)
    return finish(im, "leaf")


BUILDERS = [thermometer, thermometer_flat, snowflake, droplet, radiator,
            flame, sock, cup, pin, people, percent, leaf]


def main():
    os.makedirs(ICONS, exist_ok=True)
    con = sqlite3.connect(DB)
    pid = con.execute("SELECT id FROM pages ORDER BY id DESC LIMIT 1").fetchone()[0]
    for fn in BUILDERS:
        path = fn()
        rel = os.path.relpath(path, ROOT)
        con.execute("INSERT OR REPLACE INTO assets(page_id,kind,url,local_path,sha256,bytes,note) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (pid, "icon", "local:" + fn.__name__, rel, "",
                     os.path.getsize(path), "PIL 绘制"))
        print("图标", rel, os.path.getsize(path), "字节")
    con.commit()
    con.close()


if __name__ == "__main__":
    main()
