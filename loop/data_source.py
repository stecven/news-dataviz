"""只读数据层：从 chart_points 加载数据，覆写只发生在内存里。

对应 Spec A 节 DataBrief 的最小只读替身。数据库一律以 mode=ro 打开，
任何 override 都不写回文件（Task 1/4 用 SHA-256 前后比对来守住这条）。
"""
import math
import os
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "db", "assets.db")


def load_points(db_path: str, chart_key: str = "heat_ratio_top5",
                overrides: dict[int, float] | None = None) -> tuple[str, list[dict]]:
    """返回 (chart_title, rows)，rows 按 seq 升序。

    overrides: {seq: value}；未知 seq、非数值、bool 或非有限数（nan/inf）
    一律抛 ValueError，绝不静默忽略、绝不写库。
    """
    uri = "file:" + db_path.replace("?", "%3f").replace("#", "%23") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        cur = conn.execute(
            "SELECT chart_title, seq, label, value, unit "
            "FROM chart_points WHERE chart_key=? ORDER BY seq",
            (chart_key,),
        )
        fetched = cur.fetchall()
    finally:
        conn.close()

    if not fetched:
        raise ValueError(f"no rows for chart_key: {chart_key}")

    title = fetched[0][0]
    rows = []
    for (_title, seq, label, value, unit) in fetched:
        v = float(value)
        if not math.isfinite(v):
            raise ValueError(f"non-finite db value for seq {seq}: {value!r}")
        rows.append({"seq": int(seq), "label": label, "value": v, "unit": unit})

    if overrides:
        known = {r["seq"] for r in rows}
        for seq, value in overrides.items():
            if seq not in known:
                raise ValueError(f"unknown seq: {seq}")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"non-numeric override for seq {seq}: {value!r}")
            if not math.isfinite(float(value)):
                raise ValueError(f"non-finite override for seq {seq}: {value!r}")
            for r in rows:
                if r["seq"] == seq:
                    r["value"] = float(value)
                    break
    return title, rows
