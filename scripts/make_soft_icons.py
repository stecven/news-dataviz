# -*- coding: utf-8 -*-
"""给图标生成半透明淡色版本（PIL 直接改 alpha），用于版面背景装饰。
输出 assets/icons/<name>_soft.png，并登记进 assets.db。"""

import os
import sqlite3

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICONS = os.path.join(ROOT, "assets", "icons")
DB = os.path.join(ROOT, "db", "assets.db")

SOFT = {
    "leaf": (0.22, None),
    "radiator": (0.20, None),
    "sock": (0.22, None),
    "cup": (0.20, None),
    "thermometer": (0.18, None),
    "snowflake": (0.16, None),
    "flame": (0.18, None),
}


def main():
    con = sqlite3.connect(DB)
    pid = con.execute("SELECT id FROM pages ORDER BY id DESC LIMIT 1").fetchone()[0]
    for name, (alpha, _) in SOFT.items():
        src = os.path.join(ICONS, name + ".png")
        if not os.path.exists(src):
            continue
        im = Image.open(src).convert("RGBA")
        a = im.getchannel("A").point(lambda v: int(v * alpha))
        im.putalpha(a)
        dst = os.path.join(ICONS, name + "_soft.png")
        im.save(dst)
        rel = os.path.relpath(dst, ROOT)
        con.execute("INSERT OR REPLACE INTO assets(page_id,kind,url,local_path,sha256,bytes,note) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (pid, "icon", "local:" + name + "_soft", rel, "",
                     os.path.getsize(dst), f"PIL 淡化 alpha={alpha}"))
        print("淡化图标", rel, os.path.getsize(dst), "字节")
    con.commit()
    con.close()


if __name__ == "__main__":
    main()
