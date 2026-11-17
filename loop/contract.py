"""``pagelayout.json`` 契约的读入口（宽松）。

这是**读**的一侧：老样本（0.x）缺 ``version`` / ``theme`` / ``images``、带未来
未知键，都要能读出来，缺什么降级成 ``ReadResult.warnings`` 里的一条，**不抛**。
严格校验是另一条路（``loop/schema_check.py::validate_doc``），只用在写出侧
（``dump_layout``，P1 Task 4）—— 读旧图纸不该被当成写错图纸。

``_element_from_dict`` / ``_spec_from_dict`` 定义在 ``loop/layout.py``：它们要
构造 ``ElementSpec`` / ``PageSpec``，而 ``PlacedCard.from_dict``（``layout.py``）
就要用；定义在这里会让 ``layout.py`` 反过来 import ``contract.py``，成环。
这里只 re-export，方便调用方从契约模块拿到全部读口径。
"""
import json
import os
from dataclasses import dataclass

from loop import palette
from loop.layout import (  # noqa: F401  （re-export：定义在 layout.py，避免循环 import）
    PageLayoutSpec, _element_from_dict, _spec_from_dict)
from loop.schema_check import validate_doc

#: 契约版本（``frontend/schema/pagelayout.schema.json`` 的 title 里那个 1.0）。
CONTRACT_VERSION = "1.0"


class ContractError(ValueError):
    """写出侧不符合契约（``dump_layout`` 校验失败时抛）。"""


@dataclass
class ReadResult:
    """一次宽松读回的结果：布局 + 警告 + 文档里读到的版本号。"""

    layout: PageLayoutSpec
    warnings: list[str]
    version: str | None


def load_layout_json(doc: dict) -> ReadResult:
    """宽松读回一份内存里的 ``pagelayout.json`` 文档（不缺键就报一声，不抛）。"""
    warnings: list[str] = []
    version = doc.get("version")
    if version is None:
        warnings.append("$.version: 缺失，按 0.x 宽松读")
    elif version != CONTRACT_VERSION:
        warnings.append(f"$.version: 读到 {version!r}，本代码是 {CONTRACT_VERSION!r}")
    if "images" not in doc:
        warnings.append("$.images: 缺失，按空列表读")
    if "theme" not in doc:
        warnings.append("$.theme: 缺失（0.x 样本没有主题，渲染器需自备色板）")
    # warnings 外置传入，好让卡片内元素的「未知键」告警也进同一个列表。
    layout = PageLayoutSpec.from_dict(doc, warnings=warnings)
    return ReadResult(layout=layout, warnings=warnings, version=version)


def load_layout(path: str) -> ReadResult:
    """读盘上的 ``pagelayout.json``：``json.load`` + ``load_layout_json``。"""
    with open(path, encoding="utf-8") as fh:
        return load_layout_json(json.load(fh))


def dump_layout(layout: PageLayoutSpec) -> dict:
    """严格写出：补 ``version`` / ``theme`` → 过 schema → 原样返回（不落盘）。

    读的一侧宽松（老文档、未来文档都读得进来），**写的一侧严格**：写出的
    文档必须过 ``validate_doc``，否则消费端（JS 渲染器）会在运行时炸。缺
    ``version`` 填 ``CONTRACT_VERSION``，缺 ``theme`` 填 ``palette.summary()``
    （渲染层的色板 / 字号单一来源）。
    """
    doc = layout.to_dict()
    if not doc.get("version"):
        doc["version"] = CONTRACT_VERSION
    if not doc.get("theme"):
        doc["theme"] = palette.summary()
    errors = validate_doc(doc)
    if errors:
        head = "; ".join(f"{e['path']}: {e['message']}" for e in errors[:5])
        raise ContractError(f"{len(errors)} 处不符合契约（前 5 条）：{head}")
    return doc


def write_layout_atomic(path: str, doc: dict) -> None:
    """先写同目录 ``.tmp``，再 ``os.replace`` 原子替换目标。

    与 ``loop/build_loop.py::write_pagespec_atomic``（:21）同语义，**刻意复制**
    而不 import 那一个：``loop/build_loop.py`` 顶部拖着 ``loop.render*``
    （python-pptx）与 ``loop.preview``（Pillow），契约层是纯数据模块，不该为
    这 8 行把渲染依赖拖进来。代价是两处必须同步 —— 改这里请同时改那里。

    任何失败（含 ``json.dump`` 序列化失败）都清掉 ``.tmp`` 并原样抛出，目标
    文件保持原字节不变。
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
