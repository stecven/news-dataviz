# -*- coding: utf-8 -*-
"""素材库：把新闻页面的图、正文、图表数据统一收进 SQLite。
用法：
  python scripts/fetch_assets.py            # 抓当日默认版面并入库
  python scripts/fetch_assets.py <版面URL>  # 抓指定版面
"""
import hashlib
import json
import os
import re
import sqlite3
import sys
import urllib.request
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "db", "assets.db")
ASSETS = os.path.join(ROOT, "assets")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"}
DEFAULT_LAYOUT = "http://paper.ce.cn/pc/layout/202611/03/node_09.html"


def fetch(url, binary=False):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=40) as r:
        raw = r.read()
    if binary:
        return raw
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "ignore")


def strip_tags(html):
    html = re.sub(r"(?is)<(script|style).*?</\1>", "", html)
    html = re.sub(r"(?i)<br\s*/?>|</p>", "\n", html)
    txt = re.sub(r"(?s)<[^>]+>", "", html)
    txt = txt.replace("&nbsp;", " ").replace("&amp;", "&").replace("&quot;", '"')
    return [l.strip() for l in txt.splitlines() if l.strip()]


def init(con):
    con.executescript("""
    CREATE TABLE IF NOT EXISTS pages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        layout_url TEXT UNIQUE, date TEXT, page TEXT, title TEXT, author TEXT,
        fetched_at TEXT
    );
    CREATE TABLE IF NOT EXISTS assets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        page_id INTEGER, kind TEXT, url TEXT UNIQUE, local_path TEXT,
        sha256 TEXT, bytes INTEGER, note TEXT
    );
    CREATE TABLE IF NOT EXISTS paragraphs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        page_id INTEGER, seq INTEGER, text TEXT
    );
    CREATE TABLE IF NOT EXISTS chart_points (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        page_id INTEGER, chart_key TEXT, chart_title TEXT,
        seq INTEGER, label TEXT, value REAL, unit TEXT
    );
    """)


def main():
    layout = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_LAYOUT
    os.makedirs(ASSETS, exist_ok=True)
    con = sqlite3.connect(DB)
    init(con)

    idx = fetch(layout)
    m = re.search(r"(\d{6})/(\d{2})/node_(\d+)\.html", layout)
    date = f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(2)}" if m else ""
    page_no = int(m.group(3)) if m else 0

    art = re.search(r'href="(?:\.\./)*(?:https?://paper\.ce\.cn/pc/)?(content/[\d/]+/content_\d+\.html)"', idx)
    imgs = re.findall(r'(?:\.\./)*(?:https?://paper\.ce\.cn/pc/)?(pic/[\d/]+/[\w\-]+\.jpg\.\d)', idx)

    body_lines = []
    title = ""
    if art:
        art_url = "http://paper.ce.cn/pc/" + art.group(1)
        art_html = fetch(art_url)
        tm = re.search(r"<title>\s*(.*?)\s*</title>", art_html, re.S)
        title = tm.group(1).strip() if tm else ""
        lines = strip_tags(art_html)
        s = next((i for i, l in enumerate(lines) if "放大+" in l), 0) + 1
        e = next((i for i, l in enumerate(lines) if "关于经济日报社" in l), len(lines))
        chunk = lines[s:e]
        body_lines = [l for l in chunk if len(l) > 40 and l != title
                      and not re.match(r"^\d{4}-\d{2}-\d{2}", l)
                      and "http" not in l]

    con.execute("INSERT OR IGNORE INTO pages(layout_url,date,page,title,author,fetched_at) "
                "VALUES(?,?,?,?,?,?)",
                (layout, date, f"第{page_no:02d}版", title, "",
                 datetime.now().isoformat(timespec="seconds")))
    pid = con.execute("SELECT id FROM pages WHERE layout_url=?", (layout,)).fetchone()[0]
    con.execute("UPDATE pages SET title=?, date=?, page=? WHERE id=?",
                (title, date, f"第{page_no:02d}版", pid))
    con.execute("DELETE FROM paragraphs WHERE page_id=?", (pid,))
    con.execute("DELETE FROM assets WHERE page_id=?", (pid,))
    for i, p in enumerate(body_lines, 1):
        con.execute("INSERT INTO paragraphs(page_id,seq,text) VALUES(?,?,?)", (pid, i, p))

    for u in imgs:
        url = "http://paper.ce.cn/pc/" + u
        try:
            raw = fetch(url, binary=True)
        except Exception as ex:
            print("跳过", url, ex)
            continue
        name = re.sub(r"[^\w.\-]", "_", u.split("/")[-1])
        dst = os.path.join(ASSETS, name)
        with open(dst, "wb") as f:
            f.write(raw)
        con.execute("INSERT OR IGNORE INTO assets(page_id,kind,url,local_path,sha256,bytes,note) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (pid, "page_image", url, os.path.relpath(dst, ROOT),
                     hashlib.sha256(raw).hexdigest(), len(raw), ""))
        print("素材入库", dst, len(raw), "字节")

    con.commit()
    print(f"page_id={pid}  date={date}  title={title}  正文{len(body_lines)}段  图{len(imgs)}张")
    con.close()


if __name__ == "__main__":
    main()
