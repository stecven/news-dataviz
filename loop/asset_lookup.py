# -*- coding: utf-8 -*-
"""素材检索的只读入口（第五层 S5 / S6）。

做四件事：

* :func:`find_fallback_assets` —— 选型器返回 ``no_applicable`` 时找兜底占位图。
* :func:`find_assets_by_semantic` —— 按 ``chart_semantic`` 找真素材。
* :func:`find_assets_by_theme` —— 按 ``semantic``（主题）标签找真素材。
* :func:`semantic_theme_terms` —— 导出主题词表（S6 桥接用的反向匹配）。

为什么分成几个函数：这两类检索的**可见性规则相反**。占位图必须能查到，但绝不能
出现在正常配图检索里（否则「比较大小」会返回一张灰色方块）。所以它们查两个不同
的视图，而不是给同一个视图加参数——参数忘传就会让占位图漏进正文。

主题检索与图表语义检索查的是**同一个视图、同一套排序**（标签全局唯一，不会撞），
分开命名只是为了让调用点读起来是「按主题找图」这件事。
"""
import json
import os
import sqlite3

from loop.data_source import DB_PATH

FALLBACK_TAG = "fallback_placeholder"


def _connect(db_path=DB_PATH):
    con = sqlite3.connect("file:%s?mode=ro" % str(db_path).replace("\\", "/"),
                          uri=True)
    con.row_factory = sqlite3.Row
    return con


def find_fallback_assets(db_path=DB_PATH):
    """返回兜底占位图列表（无占位图时为空列表，绝不抛错）。

    走 ``v_fallback_assets``：该视图绕开 ``v_searchable_assets`` 对
    ``status='placeholder'`` 的排除，只收打了 ``fallback_placeholder`` 的素材。
    """
    con = _connect(db_path)
    try:
        rows = con.execute(
            "SELECT asset_id, url, local_path, kind, status, style_token, palette,"
            " tag, label_zh FROM v_fallback_assets ORDER BY asset_id").fetchall()
    finally:
        con.close()
    return [dict(r) for r in rows]


def find_assets_by_semantic(semantic, db_path=DB_PATH):
    """按图表语义找真素材。占位图永远不会出现在结果里（P1 对 placeholder 生效）。

    结果按 ``weight`` 降序、同权重按 id 升序：S4 用权重表达「同一档里谁更适合
    当配图」（例如「比较大小」档里 radiator 1.0 优先于 thermometer 0.6，因为
    后者是原版信息图里的图表本体，当插图会和数据撞车）。**调用方必须尊重这个
    顺序**，不能自己再排一遍。
    """
    con = _connect(db_path)
    try:
        rows = con.execute(
            "SELECT asset_id, url, local_path, kind, style_token, palette, tag,"
            " label_zh, weight FROM v_asset_search WHERE tag = ?"
            " ORDER BY weight DESC, asset_id", (semantic,)).fetchall()
    finally:
        con.close()
    return [dict(r) for r in rows]


def resolve_theme_tag(theme, db_path=DB_PATH):
    """把主题**词面**解析成词表里的**规范标签**（S6 桥接 0.1）。

    ``asset_tags.tag`` 存的是规范标签，别名只活在 ``tag_vocabulary.aliases``
    里；所以拿「年龄段」直接去 ``WHERE tag = ?`` 会查空。词面本来就是人手写的
    简称，别名解析是这一层的责任，不该推给调用方。认不出的词面原样返回。
    """
    con = _connect(db_path)
    try:
        row = con.execute(
            "SELECT v.tag FROM tag_vocabulary v"
            " WHERE v.tag = ? OR EXISTS (SELECT 1 FROM json_each(v.aliases)"
            "                            WHERE json_each.value = ?)"
            " ORDER BY (v.tag = ?) DESC LIMIT 1",
            (theme, theme, theme)).fetchone()
    finally:
        con.close()
    return row["tag"] if row else theme


def find_assets_by_theme(theme, db_path=DB_PATH):
    """按**主题**（``semantic`` 标签或它的别名）找插图（S6 桥接 0.1）。

    与 :func:`find_assets_by_semantic` 查同一个视图、同一套排序（weight 降序、
    同权重按 id）：标签是全局唯一的，所以 ``WHERE tag = ?`` 对两类标签都成立。
    差别只在于这里先把词面解析成规范标签（见 :func:`resolve_theme_tag`），
    分开一个函数名也让调用点读起来是「按文本主题找图」。
    """
    return find_assets_by_semantic(resolve_theme_tag(theme, db_path), db_path)


def _aliases(raw):
    """``tag_vocabulary.aliases`` 是 JSON 数组字符串；坏数据当没有别名。"""
    try:
        values = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return [v for v in values if isinstance(v, str) and v]


def semantic_theme_terms(db_path=DB_PATH):
    """主题词表：``{词面: 规范标签}``，**反着从素材出发**（S6 桥接 0.1）。

    只收真正挂在 ``v_searchable_assets`` 上的 ``semantic`` 标签 —— 库里没素材
    的主题不进词表，免得抽出一个查不到图的主题、白白把降级路径走一遍。
    词面包含规范标签本身与它的 ``aliases``：稿子里写「年龄段」比写「人群」多。
    规范标签先全部登记，别名再补，所以别名永远不会覆盖掉另一个正式标签。
    """
    con = _connect(db_path)
    try:
        rows = con.execute(
            "SELECT v.tag, v.aliases FROM tag_vocabulary v"
            " WHERE v.tag_type = 'semantic' AND v.deprecated = 0"
            "   AND EXISTS (SELECT 1 FROM asset_tags t"
            "               JOIN v_searchable_assets s ON s.id = t.asset_id"
            "               WHERE t.tag = v.tag)"
            " ORDER BY v.tag").fetchall()
    finally:
        con.close()
    terms = {r["tag"]: r["tag"] for r in rows}
    for row in rows:
        for alias in _aliases(row["aliases"]):
            terms.setdefault(alias, row["tag"])
    return terms


def resolve_local_path(row, root=None):
    """把 ``local_path`` 解成绝对路径；文件不存在返回 None（调用方决定怎么兜）。"""
    root = root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p = os.path.join(root, row["local_path"].replace("/", os.sep))
    return p if os.path.exists(p) else None
