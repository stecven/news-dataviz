"""编排器：把「数据 → 规格 → 可编辑 PPTX → 预览图」串成一条命令。

对应 Spec A 节流水线的最小闭环（DataBrief → GoalExplorer(GOAL_STUB) →
SpecRenderer → StyleComposer/LayoutComposer(几何脚手架) → 产物）。
本轮不含 LLM、不含素材库、不做整版排版。
"""
import argparse
import json
import os

from loop.data_source import DB_PATH, load_points
from loop.models import PageSpec
from loop.preview import render_preview
from loop.render import render_pptx
from loop.render_arc import needs_arc_renderer, render_pptx_arc
from loop.render_thermo import needs_thermo_renderer, render_pptx_thermo
from loop.scaffold import build_pagespec
from loop.solve import validate_spec


def write_pagespec_atomic(path: str, doc: dict) -> None:
    """D.2 步骤 4：先写同目录 .tmp，再 os.replace 原子替换目标。

    任何失败（含 json.dump 序列化失败）都清掉 .tmp 并原样抛出，目标文件
    保持原字节不变——这正是失败路径 3「无解 / 出错不落盘、不覆盖」的落点。
    """
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def render_from_spec(spec: "PageSpec", out_dir: str) -> dict:
    """把一份 PageSpec（可来自磁盘上被人工改过的 pagespec.json）渲染成 PPTX+PNG。

    这是「规格是可编辑源」的真正入口：改 pagespec.json → from_dict → 本函数重绘。
    半圆图规格（含 arc 扇区）走 render_arc 适配器，温度计仍走 render_pptx；
    两者都不改 render.py 本体。
    """
    os.makedirs(out_dir, exist_ok=True)
    pptx_path = os.path.join(out_dir, "loop1.pptx")
    png_path = os.path.join(out_dir, "preview.png")
    renderer = render_pptx_arc if needs_arc_renderer(spec) else render_pptx
    if needs_thermo_renderer(spec):
        renderer = render_pptx_thermo
    renderer(spec, pptx_path)
    render_preview(spec, png_path)
    return {"pptx": pptx_path, "png": png_path}


def build_loop(out_dir: str, overrides: dict[int, float] | None = None,
               db_path: str = DB_PATH, template_name: str | None = None,
               param_overrides: dict | None = None) -> dict:
    """串起最小闭环，返回 {pagespec, pptx, png, spec} 路径字典 + 规格对象。

    D.2 步骤 4「先解完再原子写」：build_pagespec 内部若约束无解会抛
    SolveError，此时一个文件都还没写（无解不落盘、也不覆盖已有规格）。
    """
    os.makedirs(out_dir, exist_ok=True)

    title, pts = load_points(db_path, overrides=overrides)
    # 先求解：无解在这里抛 SolveError，绝不进入下面的落盘步骤。
    spec = build_pagespec(pts, title, template_name=template_name,
                          param_overrides=param_overrides, frame=True)

    pagespec_path = os.path.join(out_dir, "pagespec.json")
    write_pagespec_atomic(pagespec_path, spec.to_dict())

    # 写出 JSON 后，从写出的文件读回、再跑一次约束校验、再渲染，确保
    # 「磁盘规格」是唯一渲染源且读回的规格与求解结果一致（D.2 步骤 5）。
    with open(pagespec_path, encoding="utf-8") as f:
        disk_spec = PageSpec.from_dict(json.load(f))
    validate_spec(disk_spec)   # 包框规格由 validate_spec 自己拆框后校验
    artifacts = render_from_spec(disk_spec, out_dir)

    return {
        "pagespec": pagespec_path,
        "pptx": artifacts["pptx"],
        "png": artifacts["png"],
        "spec": spec,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="温度计最小闭环：数据 → PageSpec → 可编辑 PPTX + 预览图")
    parser.add_argument("--out", default=os.path.join("out", "loop1"),
                        help="产物目录（默认 out/loop1）")
    parser.add_argument("--override", action="append", default=[],
                        metavar="SEQ=VALUE",
                        help="覆写某 seq 的数值，可重复，如 --override 1=12.0")
    parser.add_argument("--template", default=None,
                        choices=["thermometer", "semicircle"],
                        help="图形模板（默认 thermometer；本子集只实现两种）")
    args = parser.parse_args()

    overrides: dict[int, float] = {}
    for item in args.override:
        seq_s, value_s = item.split("=", 1)
        overrides[int(seq_s)] = float(value_s)

    r = build_loop(args.out, overrides=overrides or None,
                   template_name=args.template)
    for key in ("pagespec", "pptx", "png"):
        print(r[key])


if __name__ == "__main__":
    main()
