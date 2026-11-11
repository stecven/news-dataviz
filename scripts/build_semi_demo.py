"""半圆图补完（用户 m03184 步骤 4）：四组数据 + 一组 6 项 fallback 演示。

每组输出 pagespec.json + preview.png 到 out/demo/semicircle/<组名>/。
6 项那组按 D.3 应被 max_slices=5 拒绝 —— 这里**真的去调**，捕获 SolveError
并把结论写进 fallback.txt（不落盘 pagespec，证明「无解不落盘」）。

运行：
    PYTHONIOENCODING=utf-8 PYTHONPATH=. python -m scripts.build_semi_demo
"""
import json
import os

from loop.data_source import DB_PATH, load_points
from loop.preview import render_preview
from loop.scaffold import build_pagespec
from loop.solve import SolveError

OUT = os.path.join("out", "demo", "semicircle")

GROUPS = [
    ("g1_original", None, "① 原数据（DB heat_age 占比 5 项）"),
    ("g2_equal", [5, 5, 5, 5, 5], "② 全相等 5/5/5/5/5（退化 / 除零边界）"),
    ("g3_peak", [100, 1, 1, 1, 1], "③ 单点极值 100/1/1/1/1（最小扇区不被抬高）"),
    ("g4_zero", [10, 0, 3, 2, 1], "④ 含零值 10/0/3/2/1（零扇区 + Σθ 闭合）"),
]

SIX = ([10, 3, 2, 2, 2, 1], "⑤ 6 项 → max_slices=5 必须 fallback")


def _pts(values, unit="占比"):
    return [{"seq": i + 1, "label": f"项{i + 1}", "value": float(v), "unit": unit}
            for i, v in enumerate(values)]


def _emit(name: str, spec, note: str) -> dict:
    d = os.path.join(OUT, name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "pagespec.json"), "w", encoding="utf-8") as f:
        json.dump(spec.to_dict(), f, ensure_ascii=False, indent=2)
    render_preview(spec, os.path.join(d, "preview.png"))
    sectors = sorted((e for e in spec.elements if e.role == "sector"),
                    key=lambda e: e.binding["seq"])
    center = next(e for e in spec.elements if e.role == "center")
    thetas = [s.geometry["theta"] for s in sectors]
    vals = [s.binding["value"] for s in sectors]
    k = [t / v if v else None for t, v in zip(thetas, vals)]
    row = {
        "组": name, "说明": note, "n": len(sectors),
        "Σθ": sum(thetas),
        "θ_i": [round(t, 6) for t in thetas],
        "中心": center.text,
        "θ/v": [None if x is None else round(x, 6) for x in k],
        "θ/v 恒定": all(x is not None for x in k) and
                  max(k) - min(k) < 1e-9,
    }
    print(json.dumps(row, ensure_ascii=False))
    return row


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    rows = []
    for name, values, note in GROUPS:
        if values is None:
            _title, pts = load_points(DB_PATH, chart_key="heat_age")
            spec = build_pagespec(pts, "半圆占比（原数据）",
                                  template_name="semicircle")
        else:
            spec = build_pagespec(_pts(values), "半圆占比",
                                  template_name="semicircle")
        rows.append(_emit(name, spec, note))

    # ⑤ 6 项：应当被 max_slices 拒绝，不静默画 6 个扇区、也不落盘。
    values, note = SIX
    d = os.path.join(OUT, "g5_six_fallback")
    os.makedirs(d, exist_ok=True)
    try:
        build_pagespec(_pts(values), "半圆占比", template_name="semicircle")
        verdict = "FAIL：6 项未被拒绝，fallback 未触发"
    except SolveError as exc:
        verdict = f"OK：被拒绝 conflicts={exc.conflicts}｜{exc}"
        if os.path.exists(os.path.join(d, "pagespec.json")):
            verdict += "｜但残留了旧文件"
    with open(os.path.join(d, "fallback.txt"), "w", encoding="utf-8") as f:
        f.write(f"{note}\n数据：{values}\n{verdict}\n")
    print(json.dumps({"组": "g5_six_fallback", "说明": note,
                      "结论": verdict}, ensure_ascii=False))

    with open(os.path.join(OUT, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
