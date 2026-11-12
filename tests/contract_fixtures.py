"""P1 契约冻结：老样本的几何指纹。

Task 3/4/5 都要碰 ``loop/``，一旦代码改了 ``out/demo/**/pagelayout.json``
就不再是「改动前」的证据。所以这里先把 11 份老样本的**几何**指纹钉进 git：
只要 ``loop/`` 的改动动了画布、卡片框、卡片内元素、整版块或插图的位置尺寸，
``fingerprint_sha`` 就会变，测试立刻指出来。

指纹**故意不看** ``version`` / ``theme`` / 卡片内元素的 ``lines`` / ``font_pt`` /
``editable`` / ``chart*`` 这些外观与元数据 —— 本计划正是要新增它们，
它们的增减不该让指纹变化，而几何一动就必须变。

两份完整老样本另存于 ``tests/fixtures/contract/legacy/``：``out/`` 在
``.gitignore`` 里，fresh clone 上没有它，夹具才是可长期复现的证据。

重算并写回基线::

    python -m tests.contract_fixtures --write-baseline
"""
import hashlib
import json
import os

#: 仓库根绝对路径（本文件在 ``<root>/tests/`` 下，上溯两级）。
REPO_ROOT: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 两份完整老样本的存放目录。
LEGACY_DIR: str = os.path.join(REPO_ROOT, "tests", "fixtures", "contract", "legacy")

#: 几何指纹基线文件。
BASELINE_PATH: str = os.path.join(REPO_ROOT, "tests", "fixtures", "contract",
                                 "legacy_fingerprints.json")

#: 演示稿产物根目录（``out/`` 不入库，fresh clone 上不存在）。
DEMO_ROOT: str = os.path.join(REPO_ROOT, "out", "demo")


def demo_layout_paths() -> list[str]:
    """``out/demo/**/pagelayout.json`` 的仓库根相对路径，排序后返回。

    ``out/demo`` 不存在（fresh clone）时返回 ``[]``，不抛异常。
    路径统一用 ``/`` 分隔，这样基线文件跨平台可读。
    """
    if not os.path.isdir(DEMO_ROOT):
        return []
    found = []
    for dirpath, _dirnames, filenames in os.walk(DEMO_ROOT):
        if "pagelayout.json" in filenames:
            full = os.path.join(dirpath, "pagelayout.json")
            found.append(os.path.relpath(full, REPO_ROOT).replace(os.sep, "/"))
    return sorted(found)


def geometry_fingerprint(doc: dict) -> dict:
    """只抽几何：画布、卡片框、卡片内元素、整版块、插图。"""
    def _el(e):
        return [e.get("id"), e.get("type"), e.get("role"),
                e.get("x_in"), e.get("y_in"), e.get("w_in"), e.get("h_in")]

    def _geo(e):
        g = e.get("geometry") or {}
        keys = ("cx", "cy", "cap_top", "tube_bottom",
                "start_angle", "end_angle", "border")
        return {k: g[k] for k in keys if k in g}

    cards = []
    for c in doc.get("cards") or []:
        spec = c.get("spec") or {}
        cards.append({
            "name": c.get("name"), "kind": c.get("kind"),
            "x_in": c.get("x_in"), "y_in": c.get("y_in"),
            "w_in": c.get("w_in"), "h_in": c.get("h_in"),
            "spec_w": spec.get("width_in"), "spec_h": spec.get("height_in"),
            "elements": [[_el(e), _geo(e)] for e in (spec.get("elements") or [])],
        })

    blocks = [[b.get("name"), b.get("x_in"), b.get("y_in"),
               b.get("w_in"), b.get("h_in"), list(b.get("lines") or [])]
              for b in (doc.get("blocks") or [])]

    images = [[i.get("name"), i.get("x_in"), i.get("y_in"),
               i.get("w_in"), i.get("h_in"), list(i.get("rect") or [])]
              for i in (doc.get("images") or [])]

    return {"width_in": doc.get("width_in"), "height_in": doc.get("height_in"),
            "margin_in": doc.get("margin_in"), "gutter_in": doc.get("gutter_in"),
            "column_count": doc.get("column_count"),
            "column_gutter_in": doc.get("column_gutter_in"),
            "rows": doc.get("rows"), "cards": cards,
            "blocks": blocks, "images": images}


def fingerprint_sha(doc: dict) -> str:
    """``geometry_fingerprint`` 规范化序列化后的 sha256。"""
    payload = json.dumps(geometry_fingerprint(doc), sort_keys=True,
                         ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_baseline() -> dict:
    """读 ``legacy_fingerprints.json``：``{相对路径: {"sha256": ...}}``。"""
    with open(BASELINE_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def _write_baseline() -> int:
    """重算全部演示稿的指纹并写回基线；同时自检 ``demo_layout_paths()``。"""
    baseline = {}
    for rel in demo_layout_paths():
        with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as fh:
            doc = json.load(fh)
        baseline[rel] = {"sha256": fingerprint_sha(doc)}
        print(rel)
    os.makedirs(os.path.dirname(BASELINE_PATH), exist_ok=True)
    with open(BASELINE_PATH, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(baseline, fh, sort_keys=True, ensure_ascii=False, indent=2)
        fh.write("\n")
    print(f"wrote {len(baseline)} fingerprints")
    return 0


if __name__ == "__main__":
    import sys

    if "--write-baseline" in sys.argv[1:]:
        raise SystemExit(_write_baseline())
    raise SystemExit("usage: python -m tests.contract_fixtures --write-baseline")
