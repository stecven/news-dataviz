"""字体解析：全仓**唯一**的字体来源（用户 m07216 任务 3）。

为什么字体不能"找不到就退回默认"
--------------------------------

字体不参与排版决策，但**参与几何**：

* 折行在 :func:`loop.fit._wrap_lines` 里用 ``font.getlength(...)`` 量宽度逐字断行；
* 预览在 :func:`loop.preview._draw_text` 里用同一个字体画字；
* 温度计 / 半圆的标签宽度、行高下限、``FitRequirement`` 的触发点，全都从这两处
  推出来。

所以换一个字体（或者让 Pillow 用 ``ImageFont.load_default()`` 的位图字体顶上）
不会"只是字难看一点"，而是会**算出另一套几何**：``out/demo/**/pagelayout.json``
的卡片框、折行结果、``tests/fixtures/contract/legacy_fingerprints.json`` 里 11 份
基线指纹、以及 V2 像素对拍的口径数字都会一起变。那会表现成"CI 红了但代码没动"，
最坏的情况是有人把基线重冻一遍把问题盖掉。

因此这里的原则是：**要么给出确定的字体文件，要么明确报错**，绝不静默兜底。

字体从哪来
----------

1. 环境变量 ``NEWSDATAVIZ_FONT_PATH``（优先级最高）：CI 与自定义环境用它指向
   本机字体文件；文件不存在即报错。
2. 否则回落到 :data:`DEFAULT_FONT_PATH` —— 生成现有几何基线的那个字体
   （Windows 自带的微软雅黑 ``msyh.ttc``）。

``msyh.ttc`` 是随 Windows 分发的商业字体，**不随本仓库分发**：不复制进仓库，也不
通过 base64 secret 之类的方式"搬运"它（用户 m07603 决策二明确禁止）。CI 因此把
``runs-on`` 定在自带该字体的 Windows runner 上，并在构建前用
:func:`check_baseline_font` 逐字节核对字体身份 —— 核对不过就**明确失败，绝不继续
生成新的 golden**。真要用可再分发的开源字体，必须先确认几何与基线一致并重冻基线
—— 那是独立的一次契约变更，不在本阶段范围内。
"""
import os

#: 环境变量：显式指定字体文件路径（CI 与自定义环境用）。
FONT_PATH_ENV = "NEWSDATAVIZ_FONT_PATH"

#: 缺省字体：生成现有几何基线的微软雅黑（Windows 自带）。
DEFAULT_FONT_PATH = "C:/Windows/Fonts/msyh.ttc"

#: 允许的字体文件后缀 —— 用来把"指向一个目录 / 一个 .txt"这类误配置尽早挡掉。
_FONT_SUFFIXES = (".ttc", ".ttf", ".otf", ".ttc#", ".ttf#")


class FontUnavailable(RuntimeError):
    """找不到可用字体文件（不是"用默认字体凑合"，是明确失败）。"""


#: 生成 ``tests/fixtures/contract/legacy_fingerprints.json`` 那 11 份几何指纹时所用
#: 字体文件的 SHA-256 —— 即 ``C:/Windows/Fonts/msyh.ttc``（19,704,352 字节）。
#:
#: 钉住它是为了防止最危险的一种"修复"：字体换了 → 几何变了 → 有人顺手把基线重冻
#: 一遍把问题盖掉。CI 在**跑任何 demo 之前**就用 :func:`check_baseline_font` 核对
#: 这份摘要，不一致直接失败（用户 m07603 决策二）。
BASELINE_FONT_SHA256 = (
    "d79c55e68b1131eea0cc1c47be4f572d964f28c682e143db2ad09c1e4cb07a3f")


def font_path() -> str:
    """解析并返回字体文件路径；解析不了就抛 :class:`FontUnavailable`。

    结果按环境变量与文件存在性缓存 —— 一次进程内只解析一次，测试里改了环境变量
    可以调 :func:`reset_cache` 清掉。
    """
    cached = _CACHE.get("path")
    if cached is not None:
        return cached

    explicit = os.environ.get(FONT_PATH_ENV)
    if explicit:
        if not os.path.isfile(explicit):
            raise FontUnavailable(
                f"{FONT_PATH_ENV}={explicit!r} 指向的文件不存在；"
                f"请修正或清掉这个环境变量")
        path = explicit
    elif os.path.isfile(DEFAULT_FONT_PATH):
        path = DEFAULT_FONT_PATH
    else:
        raise FontUnavailable(
            "找不到排版字体。几何基线是用微软雅黑（"
            f"{DEFAULT_FONT_PATH}）生成的，换成别的字体会算出另一套折行与卡片框，"
            "所以这里不退回 Pillow 默认字体。\n"
            f"解决方式二选一：\n"
            f"  1. 把字体文件放到某个路径，并设 {FONT_PATH_ENV}=<该路径>；\n"
            f"  2. 在自带该字体的机器上运行（详见 docs/ci.md）。")

    if not path.lower().endswith(_FONT_SUFFIXES):
        raise FontUnavailable(
            f"字体路径 {path!r} 的后缀不像字体文件（期望 "
            f"{'、'.join(_FONT_SUFFIXES[:3])} 之一）")
    _CACHE["path"] = path
    return path


def loaded_from_env() -> bool:
    """当前字体是不是由环境变量显式指定（供测试与 CI 日志说明用）。"""
    return bool(os.environ.get(FONT_PATH_ENV))


def load_font(size: int):
    """按字号取一个 Pillow 字体对象 —— **全仓唯一的 truetype 入口**。

    字体不可用时抛 :class:`FontUnavailable`（本函数**不**吞异常、**不**退回
    ``ImageFont.load_default()``）。
    """
    from PIL import ImageFont

    return ImageFont.truetype(font_path(), size)


def reset_cache() -> None:
    """清掉 :func:`font_path` 的缓存（测试用）。"""
    _CACHE.clear()


def sha256(path: str | None = None) -> str:
    """算字体文件的 SHA-256（``path`` 省略时用 :func:`font_path` 解析出来的）。"""
    import hashlib

    target = path if path is not None else font_path()
    digest = hashlib.sha256()
    with open(target, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_baseline_font() -> tuple[str, str]:
    """核对当前字体**就是**生成几何基线的那一份；返回 ``(路径, 摘要)``。

    任一环节不过就抛 :class:`FontUnavailable`（调用方不许吞掉它继续跑构建）：

    * 字体文件找不到 / 不可读（:func:`font_path` 抛的那一支）；
    * **Pillow 实际加载不了**它（``msyh.ttc`` 是 TTC，坏文件/换文件都可能载不动）；
    * SHA-256 与 :data:`BASELINE_FONT_SHA256` 不一致。

    最后一条是重点：字体换了，折行宽度就换，11 份几何指纹与 V2 像素判据都会跟着
    变。这时候**必须失败**，不许"继续跑 demo 顺手把基线重冻一遍"。
    """
    path = font_path()
    load_font(12)          # 让 Pillow 真的打开一次，挡住"文件在但载不动"
    actual = sha256(path)
    if actual != BASELINE_FONT_SHA256:
        raise FontUnavailable(
            f"字体文件与几何基线不一致：\n"
            f"  路径   = {path}\n"
            f"  实际   = {actual}\n"
            f"  基线   = {BASELINE_FONT_SHA256}\n"
            f"折行宽度由字体决定，换字体等于换几何 —— 所以这里不继续，也不会替你"
            f"重冻 tests/fixtures/contract/legacy_fingerprints.json。\n"
            f"如果是 runner 缺少匹配版本的微软雅黑，请改用具备该字体合法使用权的"
            f"自托管 Windows runner（详见 docs/ci.md）。")
    return path, actual


_CACHE: dict = {}
