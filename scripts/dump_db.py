# -*- coding: utf-8 -*-
"""只读：把 db/assets.db 的全部内容打印出来，方便查看素材库有哪些元素。"""
import os
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "db", "assets.db")
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

tables = [r[0] for r in con.execute(
    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
print("=== 表 ===", tables)

for t in tables:
    rows = con.execute(f"SELECT * FROM {t}").fetchall()
    print(f"\n=== {t}  ({len(rows)} 行) ===")
    for r in rows:
        print(dict(r))

# 汇总：每个 chart_key 有多少点
print("\n=== chart_points 汇总 ===")
for r in con.execute(
        "SELECT chart_key, chart_title, COUNT(*) n FROM chart_points "
        "GROUP BY chart_key ORDER BY chart_key"):
    print(f"  {r['chart_key']:<24} {r['n']:>2} 点  {r['chart_title']}")

con.close()
