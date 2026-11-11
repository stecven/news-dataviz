# -*- coding: utf-8 -*-
"""素材库语义层的 schema 定义与校验（第五层 S1/S2 落地）。

本模块**只定义** DDL 片段、词表种子与校验 SQL，不执行任何写操作；
真正的落库由 ``scripts/migrate_db.py`` 调用这里的常量完成。

设计约束（对应设计文档 2026-11-09-asset-semantic-schema.md）：

* **真源唯一**：``asset_tags`` 是标签的唯一真源；``assets.semantic_tags`` /
  ``assets.asset_tags`` 两列只是可空冗余缓存，必须与真源逐条一致
  （``SQL_CACHE_SEMANTIC_MISMATCH`` / ``SQL_CACHE_APPEARANCE_MISMATCH`` 返回 0 行）。
  教训来自图形侧的 L1（C2/DATA 双写语义漂移）。
* **P1 硬规则**：``kind='page_image'`` 的素材不参与检索。实现是**视图**
  ``v_searchable_assets`` + ``v_asset_search``（唯一检索入口），而不是 CHECK 约束——
  详见 ``docs`` 与 ``scripts/migrate_db.py`` 顶部注释。另加一条触发器禁止整版位图
  声明 ``chart_semantic``。
* **词表先行**：``asset_tags.tag`` 有外键指向 ``tag_vocabulary.tag``，
  不在词表里的标签写不进来。
"""
from __future__ import annotations

#: 六种标签维度。前两个是「讲什么」与「长什么样」，中间三个是风格与用途，
#: 最后一个是「图表语义桥」——选型器输出的那一侧。
TAG_TYPES = ("semantic", "appearance", "season", "style", "usage", "chart_semantic")

#: 素材状态四态。``placeholder`` 专供 no_applicable 分支的占位图，
#: 不参与正常检索（见 ``v_searchable_assets``）。
STATUSES = ("待登记", "待审核", "已标注", "placeholder")

#: 检索入口允许的 layout_slot。
LAYOUT_SLOTS = ("hero", "chart_illustration", "body", "legend_icon",
                "footer_decoration", "fallback_placeholder")

#: 未命中原因四值，与设计文档 §2.4 一一对应。
MISS_REASONS = ("no_table", "no_tag", "no_vocab", "no_asset")

TAG_TYPE_IN = "('semantic','appearance','season','style','usage','chart_semantic')"
STATUS_IN = "('待登记','待审核','已标注','placeholder')"
SLOT_IN = ("('hero','chart_illustration','body','legend_icon',"
           "'footer_decoration','fallback_placeholder')")

#: ``assets`` 表要新增的列：(列名, 完整列定义)。
#: 用 ALTER TABLE ADD COLUMN 逐列加，迁移脚本靠 PRAGMA 判重实现幂等。
ASSETS_NEW_COLUMNS = (
    ("semantic_tags", "TEXT"),
    ("asset_tags", "TEXT"),
    ("style_token", "TEXT NOT NULL DEFAULT 'flat'"),
    ("palette", "TEXT"),
    ("alpha", "REAL"),
    ("width", "INTEGER"),
    ("height", "INTEGER"),
    ("license", "TEXT"),
    ("status", "TEXT NOT NULL DEFAULT '待登记' CHECK(status IN " + STATUS_IN + ")"),
)

DDL_TAG_VOCABULARY = f"""
CREATE TABLE IF NOT EXISTS tag_vocabulary (
    tag        TEXT PRIMARY KEY,
    tag_type   TEXT NOT NULL CHECK (tag_type IN {TAG_TYPE_IN}),
    label_zh   TEXT NOT NULL,
    aliases    TEXT,
    parent_tag TEXT REFERENCES tag_vocabulary(tag) ON UPDATE CASCADE,
    deprecated INTEGER NOT NULL DEFAULT 0 CHECK (deprecated IN (0, 1)),
    note       TEXT
)
"""

DDL_ASSET_TAGS = f"""
CREATE TABLE IF NOT EXISTS asset_tags (
    asset_id   INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    tag        TEXT NOT NULL REFERENCES tag_vocabulary(tag) ON UPDATE CASCADE,
    tag_type   TEXT NOT NULL CHECK (tag_type IN {TAG_TYPE_IN}),
    weight     REAL NOT NULL DEFAULT 1.0 CHECK (weight >= 0.0 AND weight <= 1.0),
    source     TEXT NOT NULL DEFAULT 'manual'
               CHECK (source IN ('manual', 'model', 'crawl')),
    created_at TEXT NOT NULL,
    PRIMARY KEY (asset_id, tag)
)
"""

DDL_ASSET_USAGE = f"""
CREATE TABLE IF NOT EXISTS asset_usage (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id    INTEGER REFERENCES assets(id) ON DELETE SET NULL,
    goal_key    TEXT NOT NULL,
    layout_slot TEXT NOT NULL CHECK (layout_slot IN {SLOT_IN}),
    score       REAL,
    chosen      INTEGER NOT NULL DEFAULT 0 CHECK (chosen IN (0, 1)),
    miss_reason TEXT CHECK (miss_reason IS NULL
                            OR miss_reason IN ('no_table','no_tag','no_vocab','no_asset')),
    note        TEXT,
    created_at  TEXT NOT NULL
)
"""

# --- P1 硬规则：唯一检索入口是视图，而不是直接查 asset_tags -----------------
#
# 为什么用视图：
#   1. SQLite 的 CHECK 约束不能跨表（拿不到 assets.kind），所以「素材是谁」这件事
#      在 asset_tags 的 CHECK 里根本表达不了。
#   2. 触发器能禁止「给 page_image 打标签」，但那太宽——整版位图**可以**有主题标签
#      （用于溯源与人工查看），只是不能出现在检索结果里。
#   3. 视图把「可检索素材」定义成一份可被 SQL 直接复用的谓词，任何查询器（Python、
#      命令行、未来 LLM 工具调用）只要查 v_asset_search 就自动受约束，不依赖调用方
#      记得加 WHERE。测试可断言「即使 page_image 被打满标签，也查不出来」。
DDL_VIEW_SEARCHABLE = """
CREATE VIEW IF NOT EXISTS v_searchable_assets AS
SELECT id, page_id, kind, url, local_path, sha256, bytes,
       style_token, palette, alpha, width, height, license, status
FROM assets
WHERE kind <> 'page_image'
  AND status <> 'placeholder'
"""

DDL_VIEW_SEARCH = """
CREATE VIEW IF NOT EXISTS v_asset_search AS
SELECT s.id   AS asset_id,
       s.url,
       s.local_path,
       s.kind,
       s.style_token,
       s.palette,
       t.tag,
       t.tag_type,
       t.weight,
       v.label_zh
FROM v_searchable_assets s
JOIN asset_tags t      ON t.asset_id = s.id
JOIN tag_vocabulary v  ON v.tag = t.tag
WHERE v.deprecated = 0
"""

#: 兜底素材的检索入口。**为什么单独开一个视图**：
#: ``v_searchable_assets`` 刻意排除 ``status='placeholder'``（占位图不该出现在
#: 正常配图检索里），所以占位图走 ``v_asset_search`` 永远查不到。而「无适用图形」
#: 这条分支恰恰需要找到占位图。两条检索目标互斥，只能分两个视图，不能放宽
#: ``v_searchable_assets``（那会让占位图污染「比较大小」这类正常检索）。
DDL_VIEW_FALLBACK = """
CREATE VIEW IF NOT EXISTS v_fallback_assets AS
SELECT s.id     AS asset_id,
       s.url,
       s.local_path,
       s.kind,
       s.status,
       s.style_token,
       s.palette,
       t.tag,
       t.tag_type,
       t.weight,
       v.label_zh
FROM assets s
JOIN asset_tags t      ON t.asset_id = s.id
JOIN tag_vocabulary v  ON v.tag = t.tag
WHERE s.status = 'placeholder'
  AND t.tag = 'fallback_placeholder'
  AND v.deprecated = 0
"""

#: 兜底不变量：整版位图不得声明图表语义（chart_semantic 是「这张图适合配什么图」的桥，
#: 整版报纸本身不是可复用插图）。用触发器而不是视图，因为这是**写入时**就该拒绝的错误。
DDL_TRIGGER_PAGE_IMAGE_NO_CHART_SEMANTIC = """
CREATE TRIGGER IF NOT EXISTS trg_page_image_no_chart_semantic
BEFORE INSERT ON asset_tags
WHEN NEW.tag_type = 'chart_semantic'
     AND (SELECT kind FROM assets WHERE id = NEW.asset_id) = 'page_image'
BEGIN
    SELECT RAISE(ABORT, 'page_image assets cannot carry chart_semantic tags (P1)');
END
"""

DDL_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_asset_tags_tag ON asset_tags(tag, tag_type)",
    "CREATE INDEX IF NOT EXISTS ix_asset_usage_goal ON asset_usage(goal_key, chosen)",
)

# --- 校验 SQL（每条都应返回 0 行）------------------------------------------

#: 缓存列 semantic_tags 必须等于真源里 tag_type='semantic' 的集合（按 tag 排序的 JSON）。
_CACHE_TRUTH_SEMANTIC = """
COALESCE((SELECT json_group_array(tag) FROM (
    SELECT tag FROM asset_tags
    WHERE asset_id = a.id AND tag_type = 'semantic' ORDER BY tag)), '[]')"""

_CACHE_TRUTH_APPEARANCE = """
COALESCE((SELECT json_group_array(tag) FROM (
    SELECT tag FROM asset_tags
    WHERE asset_id = a.id AND tag_type = 'appearance' ORDER BY tag)), '[]')"""

SQL_CACHE_SEMANTIC_MISMATCH = (
    "SELECT a.id, a.semantic_tags AS cache, " + _CACHE_TRUTH_SEMANTIC + " AS truth\n"
    "FROM assets a\n"
    "WHERE COALESCE(a.semantic_tags, '[]') <> " + _CACHE_TRUTH_SEMANTIC + "\n"
    "ORDER BY a.id")

SQL_CACHE_APPEARANCE_MISMATCH = (
    "SELECT a.id, a.asset_tags AS cache, " + _CACHE_TRUTH_APPEARANCE + " AS truth\n"
    "FROM assets a\n"
    "WHERE COALESCE(a.asset_tags, '[]') <> " + _CACHE_TRUTH_APPEARANCE + "\n"
    "ORDER BY a.id")

#: asset_tags.tag 必须存在于词表（外键已保证，这里再以 SQL 形式兜底，防 FK 被关掉）。
SQL_ORPHAN_TAGS = """
SELECT t.asset_id, t.tag
FROM asset_tags t
LEFT JOIN tag_vocabulary v ON v.tag = t.tag
WHERE v.tag IS NULL
ORDER BY t.asset_id, t.tag
"""

#: asset_tags.tag_type 必须与词表登记的 tag_type 一致（防同一个词被当成两个维度用）。
SQL_TAG_TYPE_DRIFT = """
SELECT t.asset_id, t.tag, t.tag_type AS row_type, v.tag_type AS vocab_type
FROM asset_tags t
JOIN tag_vocabulary v ON v.tag = t.tag
WHERE t.tag_type <> v.tag_type
ORDER BY t.asset_id, t.tag
"""

#: 词表内部：aliases 里的字符串不得同时是另一个受控 tag（防同义词乱飞）。
SQL_ALIAS_CONFLICT = """
SELECT v.tag AS owner, j.value AS clashing_alias
FROM tag_vocabulary v, json_each(COALESCE(v.aliases, '[]')) j
JOIN tag_vocabulary w ON w.tag = j.value
WHERE w.tag <> v.tag
ORDER BY v.tag, j.value
"""

#: 废弃词不得再被新增引用（已存在的历史标签允许保留）。
SQL_DEPRECATED_USED = """
SELECT t.asset_id, t.tag
FROM asset_tags t JOIN tag_vocabulary v ON v.tag = t.tag
WHERE v.deprecated = 1 AND t.source <> 'crawl'
ORDER BY t.asset_id, t.tag
"""

#: parent_tag 成环检测：沿父链最多走 32 步，若回到自己即为环。
SQL_PARENT_CYCLE = """
WITH RECURSIVE walk(start, node, depth) AS (
    SELECT tag, parent_tag, 1 FROM tag_vocabulary WHERE parent_tag IS NOT NULL
    UNION ALL
    SELECT w.start, v.parent_tag, w.depth + 1
    FROM walk w JOIN tag_vocabulary v ON v.tag = w.node
    WHERE v.parent_tag IS NOT NULL AND w.depth < 32
)
SELECT DISTINCT start FROM walk WHERE node = start ORDER BY start
"""

#: assets 新增列的取值域自检。
SQL_BAD_STATUS = """
SELECT id, status FROM assets
WHERE status NOT IN ('待登记','待审核','已标注','placeholder') ORDER BY id
"""

#: 整版位图不得带 chart_semantic（触发器之外的第二道校验，用于历史数据体检）。
SQL_PAGE_IMAGE_CHART_SEMANTIC = """
SELECT t.asset_id, t.tag FROM asset_tags t JOIN assets a ON a.id = t.asset_id
WHERE a.kind = 'page_image' AND t.tag_type = 'chart_semantic' ORDER BY t.asset_id
"""

#: 全部体检项，(名称, SQL)。返回 0 行 = 通过。
ALL_CHECKS = (
    ("cache_semantic_mismatch", SQL_CACHE_SEMANTIC_MISMATCH),
    ("cache_appearance_mismatch", SQL_CACHE_APPEARANCE_MISMATCH),
    ("orphan_tags", SQL_ORPHAN_TAGS),
    ("tag_type_drift", SQL_TAG_TYPE_DRIFT),
    ("alias_conflict", SQL_ALIAS_CONFLICT),
    ("deprecated_used", SQL_DEPRECATED_USED),
    ("parent_cycle", SQL_PARENT_CYCLE),
    ("bad_status", SQL_BAD_STATUS),
    ("page_image_chart_semantic", SQL_PAGE_IMAGE_CHART_SEMANTIC),
)


def audit(conn) -> dict[str, list[tuple]]:
    """跑全部体检项，返回 ``{检查名: 违规行列表}``（空 dict 表示全通过）。"""
    problems = {}
    for name, sql in ALL_CHECKS:
        rows = conn.execute(sql).fetchall()
        if rows:
            problems[name] = rows
    return problems


# --- 词表种子（S2）---------------------------------------------------------
#
# chart_semantic 六个值覆盖选型器 select() 全部分支：
#   规则 3 / 规则 1+比较 → 比较大小
#   规则 2                → 占比构成
#   规则 5a               → 全相等（等角退化，需要「一样大」这类插图）
#   规则 4                → 含负值（需要「负/下探」类插图）
#   规则 1 非比较 / 规则 6 → 无适用（占位图走这一档）
#   其余                   → 其他
#
# 每条 (tag, tag_type, label_zh, aliases, parent_tag, note)
VOCABULARY_SEED = (
    # --- semantic：主题侧 -------------------------------------------------
    ("小家电", "semantic", "小家电", '["家电","小家电品类"]', None, "原版信息图的主题域"),
    ("取暖电器", "semantic", "取暖电器",
     '["电暖器","取暖器","采暖设备","电采暖"]', "小家电", "含快热炉、电油汀、踢脚线取暖器等"),
    # 注：词的归属唯一（tag 是主键），所以「秋季/冬季」只登记为 season，
    # 「讲什么主题」这一侧用「秋季消费」表达，避免同一个词跨类型重复。

    ("除湿机", "semantic", "除湿机", '["抽湿机","除湿器","抽湿器"]', "小家电", "区块②主题"),
    ("秋季消费", "semantic", "秋季消费", '["秋季热销","换季消费"]', None, ""),
    ("暖气片", "semantic", "暖气片", '["散热器","暖气"]', "取暖电器", "形近 radiator"),
    ("保暖用品", "semantic", "保暖用品", '["御寒用品","保暖"]', None, ""),
    ("袜子", "semantic", "袜子", '["袜","暖袜"]', "保暖用品", ""),
    ("暖脚套", "semantic", "暖脚套", '["脚套","暖脚"]', "保暖用品", ""),
    ("热水", "semantic", "热水", '["开水","温水"]', None, ""),
    ("饮水", "semantic", "饮水", '["喝水","饮水机"]', None, ""),
    ("保温", "semantic", "保温", '["保暖保热"]', None, ""),
    ("温度计图标", "semantic", "温度计图标", '["温度计","温度表"]', None, "形近 thermometer"),
    ("温度", "semantic", "温度", '["气温","室温"]', None, ""),
    ("测量", "semantic", "测量", '["度量","测算"]', None, ""),
    ("雪花", "semantic", "雪花", '["雪","降雪","冰晶"]', None, "除湿机区块的现成配图"),
    ("寒冷", "semantic", "寒冷", '["冷","低温"]', None, ""),
    ("火焰", "semantic", "火焰", '["火","火苗","焰"]', None, ""),
    ("加热", "semantic", "加热", '["加热功能","升温"]', None, ""),
    ("热量", "semantic", "热量", '["热能"]', None, ""),
    ("枫叶", "semantic", "枫叶", '["红叶","枫树"]', None, "页脚季节装饰"),
    ("季节装饰", "semantic", "季节装饰", '["节气装饰"]', None, ""),
    ("百分比", "semantic", "百分比", '["百分号","占比符号","％"]', None, "未登记的 percent.png"),
    ("占比", "semantic", "占比", '["构成","比例"]', None, ""),
    ("人群", "semantic", "人群", '["消费者","年龄段","用户画像"]', None, "未登记的 people.png"),
    ("地理位置", "semantic", "地理位置", '["地点","地区"]', None, "未登记的 pin.png"),
    ("产地", "semantic", "产地", '["原产地"]', "地理位置", ""),
    ("湿度", "semantic", "湿度", '["水汽","湿气"]', None, "未登记的 droplet.png"),
    # --- appearance：外观侧 ----------------------------------------------
    ("整版版面", "appearance", "整版版面", '["报纸版面","整版"]', None, "page_image 专用"),
    ("位图", "appearance", "位图", '["照片","raster"]', None, ""),
    ("含文字", "appearance", "含文字", '["带字","有正文"]', None, ""),
    ("图标", "appearance", "图标", '["icon","小图标"]', None, ""),
    ("线稿", "appearance", "线稿", '["描边","轮廓"]', None, ""),
    ("平涂", "appearance", "平涂", '["色块","flat fill"]', None, ""),
    ("淡化", "appearance", "淡化", '["半透明","浅色"]', None, "_soft 系列的共同特征"),
    ("正视图", "appearance", "正视图", '["正面","front"]', None, ""),
    ("带刻度", "appearance", "带刻度", '["有刻度","刻度线"]', None, ""),
    # --- season ----------------------------------------------------------
    ("秋季", "season", "秋季", '["秋天"]', None, None),
    ("冬季", "season", "冬季", '["冬天"]', None, None),
    # --- style：与 assets.style_token 同词 ---------------------------------
    ("soft", "style", "淡化风", '["浅色风"]', None, ""),
    ("flat", "style", "平涂风", '["扁平","纯色"]', None, ""),
    ("line", "style", "线描风", '["线条","outline"]', None, ""),
    ("realistic", "style", "写实风", '["照片感"]', None, ""),
    # --- usage：素材固有属性（与 asset_usage.layout_slot 不同）-------------
    ("页脚装饰", "usage", "页脚装饰", '["底纹装饰"]', None, ""),
    ("正文配图", "usage", "正文配图", '["文中配图"]', None, ""),
    ("图表插图", "usage", "图表插图", '["配图表"]', None, ""),
    ("fallback_placeholder", "usage", "占位素材", '[]', None,
     "选型器返回 no_applicable 时的占位，status='placeholder'"),
    # --- chart_semantic：选型器输出那一侧 --------------------------------
    ("比较大小", "chart_semantic", "比较大小", '["大小比较","对比"]', None,
     "对应选型器 SEMANTIC_COMPARE"),
    ("占比构成", "chart_semantic", "占比构成", '["构成占比","部分与整体"]', None,
     "对应选型器 SEMANTIC_SHARE"),
    ("全相等", "chart_semantic", "全相等", '["等值","无差异"]', None,
     "规则 5a：全相等一律温度计，需「一样大」类插图"),
    ("含负值", "chart_semantic", "含负值", '["负值","下探"]', None,
     "规则 4：含负值只能温度计，需「负数/下探」类插图"),
    ("无适用", "chart_semantic", "无适用", '["不适用","无匹配图形"]', None,
     "规则 1 非比较 / 规则 6：只能给占位素材"),
    ("其他", "chart_semantic", "其他", '["未分类"]', None,
     "对应选型器 SEMANTIC_OTHER"),
)


def _dedupe(rows):
    """按 tag 去重（保留首次出现的定义），防种子表里手滑写重复。"""
    seen, out = set(), []
    for row in rows:
        if row[0] in seen:
            continue
        seen.add(row[0])
        out.append(row)
    return out


def vocabulary_rows():
    """返回去重后的词表种子。"""
    return _dedupe(VOCABULARY_SEED)


def chart_semantic_values():
    """当前词表里 tag_type='chart_semantic' 的全部受控词。"""
    return [r[0] for r in vocabulary_rows() if r[1] == "chart_semantic"]
