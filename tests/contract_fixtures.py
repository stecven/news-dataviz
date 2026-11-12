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
import re

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


#: 前端 JS 源码根目录（P2 才建；现在不存在，所以扫描器返回空列表）。
FRONTEND_SRC: str = os.path.join(REPO_ROOT, "frontend", "src")

#: 十六进制色值：``#rgb`` / ``#rrggbb`` / ``#rrggbbaa``，大小写都算。
#:
#: **必须**长前短后（8 → 6 → 3）：短的先匹配会把 ``#00ff0080`` 截成 ``#00f``。
#: ``(?![0-9a-zA-Z_-])`` 排除紧跟字母数字下划线连字符的 ``#``，否则
#: ``url(#faded)`` / ``href="#fragment-1"`` 这类 SVG 片段引用会被当成色值
#: （假阳性逼着守卫加白名单，很快形同虚设）。
#: 注释里的 ``#fff`` 仍算命中 —— **有意保守**，注释里写色值一样是写死。
HEX_COLOR_RE = re.compile(
    r"#(?:(?:[0-9a-fA-F]{8})|(?:[0-9a-fA-F]{6})|(?:[0-9a-fA-F]{3}))"
    r"(?![0-9a-zA-Z_-])")

#: 函数式颜色：``rgb()`` / ``rgba()`` / ``hsl()`` / ``hsla()``（``#`` 之外的常见写法）。
#:
#: 前面用 ``(?<![\w$.])`` 排除 ``myrgb(`` 这类自定义函数名。
#: **``0x`` 十六进制字面量不在覆盖范围内**（见 :func:`find_hardcoded_theme_tokens`
#: 的说明）：``0xFFFFFF`` 与位运算掩码 ``& 0xFFFFFF`` 无法区分。
FUNC_COLOR_RE = re.compile(r"(?<![\w$.])(?:rgba?|hsla?)\s*\(\s*[-+\d.]")

#: 字号关键字 + 紧邻数字，必中（``style.fontSize = 14`` / ``font: 12px`` /
#: ``font-size: 1.2rem``）。``font`` 单列一支是为了覆盖 ``ctx.font = "12px"``。
FONT_SIZE_KEYWORD_RE = re.compile(
    r"""(?:font-size|fontSize|font)\s*[:=]\s*["']?\d""")

#: ``px`` / ``pt`` 字面量。**单独用会误报**：``style.width = "100px"`` /
#: ``border = "1px solid"`` / ``translate("12px", 0)`` 都不是字号，所以只有
#: 同一语句（``;`` 之后）的前缀里出现 ``font`` 才算命中 —— 位置判断在
#: :func:`find_hardcoded_theme_tokens` 里做，不硬凑成一条更长更难懂的正则。
FONT_SIZE_LITERAL_RE = re.compile(r"\d+(?:px|pt)\b")


def iter_js_sources() -> list[str]:
    """``frontend/src/**/*.js`` 的仓库根相对路径，``/`` 分隔，排序后返回。

    ``frontend/src`` 不存在（P1 阶段就是这样）时返回 ``[]``，不抛。
    """
    if not os.path.isdir(FRONTEND_SRC):
        return []
    found = []
    for dirpath, _dirnames, filenames in os.walk(FRONTEND_SRC):
        for name in filenames:
            if name.endswith(".js"):
                full = os.path.join(dirpath, name)
                found.append(os.path.relpath(full, REPO_ROOT).replace(os.sep, "/"))
    return sorted(found)


def find_hardcoded_theme_tokens(source: str) -> list[tuple[int, str]]:
    """扫一段 JS 源码里的写死色值 / 字号：``[(行号, 匹配文本), ...]``。

    行号从 1 开始，同一行内的命中按列序排列。命中的是「从 ``#``（或
    ``rgb(`` / 数字）开始的文本」，用来在失败信息里指给出处。

    **当前识别的形态**（README 里的清单与此处一致）::

        #rgb  #rrggbb  #rrggbbaa        十六进制色值，大小写都算
        rgb(  rgba(  hsl(  hsla(        函数式颜色，参数以数字开头才算
        font-size:/fontSize=/font= + 数字
        含 font 的语句里的 12px / 9pt

    **不识别**：``0xRRGGBB`` 十六进制字面量 —— ``0xFFFFFF`` 与位运算掩码
    ``& 0xFFFFFF`` 在文本上无法区分，认了会误伤位运算。写死颜色的正路是
    ``#`` 或 ``rgb()``，``0x`` 不在契约鼓励的写法里。

    ``px`` / ``pt`` 字面量必须**有字号上下文**才算命中，否则
    ``style.width = "100px"`` / ``border: "1px solid"`` 会被误判成字号。
    """
    hits: list[tuple[int, str]] = []
    for lineno, line in enumerate(source.splitlines(), start=1):
        found: list[tuple[int, int, str]] = []
        for pattern in (HEX_COLOR_RE, FUNC_COLOR_RE, FONT_SIZE_KEYWORD_RE):
            found += [(m.start(), m.end(), m.group(0))
                      for m in pattern.finditer(line)]

        # ``12px`` / ``9pt``：只有当同一语句（``;`` / ``{`` 之后）的前缀里出现
        # ``font`` 才算字号，才不像 width / border / padding / translate。
        for m in FONT_SIZE_LITERAL_RE.finditer(line):
            statement = line[:m.start()]
            for sep in (";", "{", "}"):
                statement = statement.rsplit(sep, 1)[-1]
            if "font" not in statement.lower():
                continue
            # 已被 keyword 分支覆盖的（``fontSize = 12px``）不重复报。
            if any(start <= m.start() < end for start, end, _t in found):
                continue
            found.append((m.start(), m.end(), m.group(0)))

        for _start, _end, text in sorted(found, key=lambda item: item[0]):
            hits.append((lineno, text))
    return hits


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
