# 素材库语义 schema（第五层第一步）

> 状态：**只出设计，不建表、不迁移、不爬虫**
> 日期：2026-11-09
> 前置：`2026-11-07-lida-landing-design.md` E 节的「仅建议」版本（本文把它定稿到可落地的字段级）
> 相关：`2026-11-07-charticulator-landing-design.md`（图形侧）、`loop/selector.py` + `loop/pipeline.py`（选型侧）

## 0. 本轮边界

| 做 | 不做 |
|---|---|
| 定义 4 类语义字段的字段名/类型/可空/示例 | 建表、写迁移脚本、改 `db/assets.db` |
| 8 个在库素材按新 schema 手动打标 | 写入数据库（打标结果只在本文表格里） |
| 选型器输出 → 素材库查询的对照验证 | 爬虫、批量抓图、批量入库 |
| fallback 位置的设计 | 改 `selector.py` / `solve.py` / `render.py` / `pipeline.py` |

`db/assets.db` 全程以 `mode=ro` 打开，只读。本轮结束时 SHA-256 未变
（`BBB8B2DFFBE772B03B9F33749B8AD583BA64269F7A55F26D5EF5E666FE2990B0`）。

---

## 1. 现状（先量清楚，再定 schema）

`assets` 表现有 8 行、7 个字段，**没有任何语义字段**：

| id | kind | url | 说明 |
|---|---|---|---|
| 15 | `page_image` | 经济日报整版 jpg.2（1600×2267，510350 B） | 整版位图，sha256 `fd398fd3…` |
| 16 | `icon` | `local:leaf_soft` | 枫叶，alpha 0.22 |
| 17 | `icon` | `local:radiator_soft` | 暖气片，alpha 0.20 |
| 18 | `icon` | `local:sock_soft` | 袜子，alpha 0.22 |
| 19 | `icon` | `local:cup_soft` | 水杯，alpha 0.20 |
| 20 | `icon` | `local:thermometer_soft` | 温度计，alpha 0.18 |
| 21 | `icon` | `local:snowflake_soft` | 雪花，alpha 0.16 |
| 22 | `icon` | `local:flame_soft` | 火焰，alpha 0.18 |

```sql
-- 现有列（PRAGMA table_info(assets) 实测）
id INTEGER PK · page_id INTEGER · kind TEXT · url TEXT · local_path TEXT
sha256 TEXT · bytes INTEGER · note TEXT
```

对照 `assets/icons/` 实际 19 个 png，**12 个未登记**：

`cup` `droplet` `flame` `leaf` `people` `percent` `pin` `radiator`
`snowflake` `sock` `thermometer` `thermometer_flat`

> 未登记里包含 `percent.png`（百分比符号）与 `people.png`（人群）——
> 这两个恰好是「占比构成」类语义最需要的图标。**缺口首先是登记，不是素材本身。**

---

## 2. Schema 定义

四条原则：

1. **检索真源只有一份**。`asset_tags` 是唯一真源；`assets.semantic_tags` /
   `assets.asset_tags` 两个 JSON 列是**可选冗余缓存**，若启用必须满足
   「与 `asset_tags` 完全一致」这一不变量（附校验 SQL）。
   教训来自图形侧的 L1（C2/DATA 双写不统一），不重复同一个错误。
2. **词表先行**。任何 `tag` 落库前必须在 `tag_vocabulary` 里存在，否则拒绝写入
   （相当于 `tag` 有 FK）。同义词只通过 `aliases` 归一，不允许多个受控词表达同一概念。
3. **图表语义 ≠ 素材主题**。选型器说的「占比构成 / 比较大小」是**图表该怎么画**，
   不是**插图该画什么**。两者之间需要一层桥（见 §5 缺口 G2），不能直接当 tag 用。
4. **无命中要能说清缺什么**。`asset_usage` 记录每次查询结果，未命中时
   `miss_reason` 记 `no_tag` / `no_vocab` / `no_asset` / `no_table` 四类之一。

### 2.1 `assets`（扩列，不新建表）

| 字段 | 类型 | 可空 | 默认 | 示例值 | 用途 |
|---|---|---|---|---|---|
| `semantic_tags` | TEXT（JSON 数组） | 可空 | `NULL` | `["取暖电器","季节性家电"]` | **冗余缓存**；真源是 `asset_tags` |
| `asset_tags` | TEXT（JSON 数组） | 可空 | `NULL` | `["图标","线稿","淡化"]` | **冗余缓存**；真源是 `asset_tags` |
| `style_token` | TEXT | NOT NULL | `'flat'` | `flat` / `soft` / `line` / `realistic` | 风格一致性打分，防 `_soft` 与原色混用 |
| `palette` | TEXT | 可空 | `NULL` | `autumn` | 暖秋色板匹配 |
| `alpha` | REAL | 可空 | `NULL` | `0.22` | 淡化程度（从 `note` 里提升为列） |
| `width` | INTEGER | 可空 | `NULL` | `400` | 占位计算 |
| `height` | INTEGER | 可空 | `NULL` | `400` | 占位计算 |
| `license` | TEXT | 可空 | `NULL` | `自有绘制` | 合规 |
| `status` | TEXT | NOT NULL | `'待登记'` | `已标注` / `待审核` / `待登记` / `placeholder` | 标注进度；`placeholder` 供 fallback 用 |
| `semantic_note` | TEXT | 可空 | `NULL` | `淡化枫叶，作页脚季节装饰` | 一句话人读描述（不参与检索） |

`status` 四态取值与流转：

```
待登记 ──人工补 kind/尺寸/风格──► 待审核 ──复核──► 已标注
                                          └──► placeholder（占位图，见 §6）
```

### 2.2 `asset_tags`（新建，**检索真源**）

| 字段 | 类型 | 可空 | 示例值 | 约束 |
|---|---|---|---|---|
| `asset_id` | INTEGER | NOT NULL | `16` | FK → `assets.id`；与 `tag` 组成 PK |
| `tag` | TEXT | NOT NULL | `枫叶` | FK → `tag_vocabulary.tag`（不在词表里就写不进来） |
| `tag_type` | TEXT | NOT NULL | `semantic` | `semantic`/`appearance`/`season`/`style`/`usage`/`chart_semantic` |
| `weight` | REAL | NOT NULL | `0.9` | `DEFAULT 1.0`，`CHECK(0.0 <= weight <= 1.0)`，多标签排序 |
| `source` | TEXT | NOT NULL | `manual` | `manual`/`model`/`crawl` |
| `created_at` | TEXT | NOT NULL | `2026-11-09T00:20:00+08:00` | ISO 8601 |

`tag_type` 六个取值的分工（这是本 schema 最关键的一列）：

| `tag_type` | 回答什么问题 | 例 |
|---|---|---|
| `semantic` | 这张图**讲的是什么主题** | 取暖电器 / 除湿机 / 温度计图标 |
| `appearance` | 这张图**长什么样** | 实物照片 / 线稿 / 图标 / 平涂 |
| `season` | 季节/氛围 | 秋季 / 冬季 |
| `style` | 风格一致性用的细粒度 token | `soft` / `flat` / `hand_drawn` |
| `usage` | 适合放哪 | 图表插图 / 正文配图 / 页脚装饰 |
| `chart_semantic` | **图表语义桥**（选型器输出的那一侧，见 §5） | 占比构成 / 比较大小 |

> `usage` 与 `asset_usage.layout_slot` 是两个方向：`asset_tags.usage` 是
> 「这张图**适合**用在哪」（素材固有属性，可多值），`asset_usage.layout_slot`
> 是「这次**实际**用在哪」（一次使用记录）。不要合并。

不变量校验（若启用冗余列）：

```sql
-- 必须返回 0 行
SELECT a.id FROM assets a
WHERE COALESCE(a.semantic_tags, '[]') <> COALESCE((
        SELECT json_group_array(t) FROM (
            SELECT tag AS t FROM asset_tags
            WHERE asset_id = a.id AND tag_type = 'semantic'
            ORDER BY tag)), '[]');
```

### 2.3 `tag_vocabulary`（新建，受控词表）

| 字段 | 类型 | 可空 | 示例值 | 约束 |
|---|---|---|---|---|
| `tag` | TEXT | NOT NULL | `取暖电器` | PK |
| `tag_type` | TEXT | NOT NULL | `semantic` | 同 §2.2 的六值 |
| `label_zh` | TEXT | NOT NULL | `取暖电器` | 展示名（可与 `tag` 相同） |
| `aliases` | TEXT（JSON 数组） | 可空 | `["电暖器","取暖器","采暖设备"]` | 同义词归一，检索前先过这层 |
| `parent_tag` | TEXT | 可空 | `小家电` | 自引用 FK，支持层级检索（`parent_tag` 不算命中，除非显式 `include_ancestors`） |
| `deprecated` | INTEGER | NOT NULL | `0` | 1 = 废弃词，保留历史标签但拒绝新增 |
| `note` | TEXT | 可空 | `含电油汀、踢脚线取暖器、快热炉等子品类` | 人读说明 |

三条约束：

1. 写入 `asset_tags` 前 `tag` 必须已存在且 `deprecated = 0`（否则 `no_vocab` 拒绝）。
2. 同一 `aliases` 里的字符串**不得**同时作为别的 `tag` 存在（防同义词乱飞）。
3. `parent_tag` 不得成环。

### 2.4 `asset_usage`（新建，使用与反馈）

| 字段 | 类型 | 可空 | 示例值 | 约束 |
|---|---|---|---|---|
| `id` | INTEGER | NOT NULL | `1` | PK AUTOINCREMENT |
| `asset_id` | INTEGER | 可空 | `16` | FK → `assets.id`；**可空**——`no_asset` 时也要留一条记录 |
| `goal_key` | TEXT | NOT NULL | `heat_age\|占比构成` | 建议用 `chart_key + 语义` 拼，避免引入新的 goal 表 |
| `layout_slot` | TEXT | NOT NULL | `footer_decoration` | `hero`/`chart_illustration`/`body`/`legend_icon`/`footer_decoration`/`fallback_placeholder` |
| `score` | REAL | 可空 | `0.83` | 检索打分；无候选时为 `NULL` |
| `chosen` | INTEGER | NOT NULL | `0` | 1 = 最终采用 |
| `miss_reason` | TEXT | 可空 | `no_asset` | `no_table`/`no_tag`/`no_vocab`/`no_asset`；命中时为 `NULL` |
| `note` | TEXT | 可空 | `选型器建议配构成类插图，库中无对应素材` | |
| `created_at` | TEXT | NOT NULL | ISO 8601 | |

`miss_reason` 四值与 §6「缺口」一一对应，这是本文最重要的一列：

| `miss_reason` | 含义 | 该补什么 |
|---|---|---|
| `no_table` | 表/字段还不存在（本轮现状） | 建表（§2.2–2.4） |
| `no_tag` | 表在，但素材没打这个标签 | 补标注（§3） |
| `no_vocab` | 标签不在词表里 / 被废弃 | 补词表 + `aliases` |
| `no_asset` | 词表和标签都对，但库里没有这种素材 | 补素材（爬/画） |

---

## 3. 8 个在库素材的手动打标结果

**不写库**，只在此表格中人工判定。`weight` 全为 `1.0` 时省略。

### 3.1 `assets` 扩列取值

| id | 名称 | style_token | palette | alpha | w×h | license | status | semantic_note |
|---|---|---|---|---|---|---|---|---|
| 15 | 经济日报整版 | `realistic` | `autumn` | — | 1600×2267 | 原刊引用 | `已标注` | 整版报纸版面，含三大区块与枫叶主视觉；**不进检索**，仅作参考母版 |
| 16 | leaf_soft | `soft` | `autumn` | 0.22 | 400×400 | 自有绘制 | `已标注` | 淡化枫叶，季节装饰 |
| 17 | radiator_soft | `soft` | `autumn` | 0.20 | 400×400 | 自有绘制 | `已标注` | 淡化暖气片正视图 |
| 18 | sock_soft | `soft` | `neutral` | 0.22 | 400×400 | 自有绘制 | `已标注` | 淡化袜子/暖脚套 |
| 19 | cup_soft | `soft` | `cool` | 0.20 | 400×400 | 自有绘制 | `已标注` | 淡化带热气水杯 |
| 20 | thermometer_soft | `soft` | `autumn` | 0.18 | 400×400 | 自有绘制 | `已标注` | 淡化温度计，带刻度与球泡 |
| 21 | snowflake_soft | `soft` | `cool` | 0.16 | 400×400 | 自有绘制 | `已标注` | 淡化雪花 |
| 22 | flame_soft | `soft` | `autumn` | 0.18 | 400×400 | 自有绘制 | `已标注` | 淡化火焰 |

### 3.2 `asset_tags` 打标

| id | `semantic` | `appearance` | `season` | `style` | `usage` | `chart_semantic` |
|---|---|---|---|---|---|---|
| 15 | 小家电、取暖电器、除湿机、秋季消费 | 整版版面、位图、含文字 | 秋季 | `realistic` | —（不进检索） | — |
| 16 | 枫叶、秋季、季节装饰 | 图标、线稿、淡化 | 秋季 | `soft` | 页脚装饰、正文配图 | — |
| 17 | 取暖电器、暖气片 | 图标、线稿、淡化、正视图 | 冬季 | `soft` | 图表插图、页脚装饰 | 比较大小 |
| 18 | 保暖用品、袜子、暖脚套 | 图标、线稿、淡化 | 冬季 | `soft` | 正文配图 | — |
| 19 | 热水、饮水、保温 | 图标、线稿、淡化 | — | `soft` | 正文配图 | — |
| 20 | 温度计图标、温度、测量 | 图标、线稿、淡化、带刻度 | — | `soft` | 图表插图、正文配图 | 比较大小 |
| 21 | 雪花、寒冷、冬季 | 图标、线稿、淡化 | 冬季 | `soft` | 页脚装饰、图表插图 | — |
| 22 | 火焰、加热、热量 | 图标、线稿、淡化 | 冬季 | `soft` | 图表插图、正文配图 | — |

### 3.3 打标过程中暴露的问题（不是打标失误，是 schema 还没覆盖）

| # | 现象 | 说明 |
|---|---|---|
| P1 | id 15 的 `usage` **必须留空** | 整版位图若进了检索，会以最高分命中所有「取暖/除湿」查询，把整张报纸当插图贴进去。schema 需要一个硬规则：`kind = 'page_image'` 的行不参与 `asset_tags` 检索 |
| P2 | 只有 id 17 / 20 能打上 `chart_semantic = 比较大小` | 其余 6 个素材与图表语义无关。这说明 `chart_semantic` **不是每张图都需要**的标签，是「图表插图专用」的桥 |
| P3 | 没有任何素材能打上 `chart_semantic = 占比构成` | 库里有 `percent.png` 但**未登记**；`people.png` 也未登记。这是「缺登记 + 缺标签」，不是「缺素材」 |
| P4 | id 18/19/21/22 的 `season` 我判成了「冬季」而 `palette` 是 cool/neutral | 季节与色板是**两个维度**，不能互相推导。检索时若要求暖秋色板，这几个会因 `palette` 不一致被降权——这正是 `palette` 独立成列的理由 |

---

## 4. 12 个未登记图标（只列不打标，待登记）

| 文件 | 大致内容 | 建议 `semantic` | 建议 `chart_semantic` | 备注 |
|---|---|---|---|---|
| `percent.png` | 百分比符号 | 百分比、占比 | **占比构成** | 本轮最关键的缺失素材 |
| `people.png` | 人群剪影 | 人群、消费者 | 占比构成 | 年龄段占比配图首选 |
| `pin.png` | 地图定位针 | 地理位置、产地 | — | 点位连线地图用 |
| `droplet.png` | 水滴 | 除湿、湿度 | — | 除湿机区块配图 |
| `cup.png` `flame.png` `leaf.png` `radiator.png` `snowflake.png` `sock.png` `thermometer.png` | 对应原色版 | 同 id 16–22 | 比较大小（thermometer） | 与 `_soft` 是同一素材的两种风格，需 `style_token` 区分 |
| `thermometer_flat.png` | 温度计平涂版 | 温度计图标 | 比较大小 | 与 `thermometer.png` 风格不同，注意别混用 |

登记这 12 个 + 打标，是「素材库可用」的最小前置工作量：19 行素材、每行约 6 个标签、约 114 条 `asset_tags` 记录。

---

## 5. 选型器 → 素材库对照验证

选型器（`loop/pipeline.py`）产出 `selection.json`，三个字段：
`selected_template` / `rationale` / `rejected`。
素材库侧按 `semantic_tags` 检索。**两边维度不同**，逐行对照如下。

查询口径统一为：给定 `goal_key` 与一个目标 tag，在 `asset_tags` 里查
`tag_type IN ('semantic','chart_semantic')` 且 `weight >= 0.5`，再按
`style_token` / `palette` 与目标页面做一致性过滤。

| # | 选型器输出（实测） | 素材库查询 | 现状（无新 schema） | 新 schema 落地后 | 命中/未命中原因 |
|---|---|---|---|---|---|
| 1 | `heat_ratio_top5` → `thermometer`；rationale：「比较大小」语义，温度计以液柱高度直接编码数值 | `chart_semantic = 比较大小` + `usage = 图表插图` | **未命中**（无 `semantic_tags` 列：`no such column`） | **命中 2 条**：id 17 radiator_soft、id 20 thermometer_soft | 命中。但注意：图表本体已由 `thermometer` 模板画出，这里只需**装饰性**插图；`radiator_soft` 比 `thermometer_soft` 更合适（后者会和图里的温度计撞车） |
| 2 | `heat_age` → `semicircle`；rationale：「占比构成」语义…最贴合「构成」表达 | `chart_semantic = 占比构成` + `usage = 图表插图` | **未命中** | **未命中**：0 条 | **缺标签 + 缺登记**，不是缺素材：`percent.png`、`people.png` 都适合，但未登记（`no_tag`）。补登记 + 打 `chart_semantic=占比构成` 后即可命中 |
| 3 | `heat_age` 换查主题侧：rationale 提到「各年龄段消费者」 | `semantic = 人群` 或 `消费者` | **未命中** | **未命中**：0 条 | **缺词表 + 缺登记**：`people.png` 未登记；词表里也没有「消费者」这个词，需要 `aliases` 把「年龄/人群/消费者」归一到 `人群`（`no_vocab`） |
| 4 | `six_share_no_applicable`（6 项占比）→ `selected_template = None`；rationale：「无适用图形…按 D.3 需在选型阶段换图并标 fallback_used」 | `status = placeholder` 或 `layout_slot = fallback_placeholder` | **未命中** | **未命中**：0 条 | **缺素材本体**：库里没有占位图（`no_asset`）。这是 §6 要预留的位置 |
| 5 | 数据主题侧：`dehum_share_prov`（除湿机省份占比）→ 选型器会选 `semicircle`；rationale 提「除湿机」 | `semantic = 除湿机` + `usage = 图表插图` | **未命中** | **命中 1 条**：id 21 snowflake_soft（`semantic = 雪花、寒冷、冬季` 需先扩到「除湿」） | **缺标签**：`snowflake_soft` 是除湿机最贴切的现成图标（原版区块②就用雪花），但当前打的标签里没有「除湿机」；补一条 `semantic = 除湿机`（weight 0.7）即可命中（`no_tag`） |

### 5.1 缺口归纳（回答「缺的是标签、词表，还是素材」）

| 编号 | 缺口 | 层次 | 影响面 | 补法 |
|---|---|---|---|---|
| **G1** | `assets` 无语义字段，`asset_tags` / `tag_vocabulary` / `asset_usage` 三表都不存在 | **表结构** | **100% 未命中**（任何查询都 `no_table`） | 按 §2 建表；这是阻断性缺口，其余缺口在它之上 |
| **G2** | 「图表语义」（占比构成/比较大小）与「素材主题」（取暖电器/枫叶）不是同一维度，中间没有映射 | **桥接层** | 选型器的 rationale 无法直接当 tag 查 | 用 `tag_type = 'chart_semantic'` 承载桥的一端（本轮已设计）；另一端（`chart_semantic → 建议主题`）属 GoalExplorer 职责，本轮**不实现**，只留位置 |
| **G3** | 19 个图标只登记 7 个，缺的 12 个里恰好有 `percent.png` / `people.png` / `pin.png` / `droplet.png` | **登记** | 占比类、地理类、除湿类查询全部落空 | 补 12 行 `assets` + 约 72 条 `asset_tags` |
| **G4** | 现有 7 个 `_soft` 图标全无 `chart_semantic` 标签，且多数主题与图表语义无关 | **标签** | 「图表插图」类查询只命中 2 条，选择面太窄 | 按 §3.2 补 `chart_semantic`；同时承认「不是每张图都需要它」 |
| **G5** | 库里 0 个占位图 / fallback 素材 | **素材本体** | `no_applicable` 分支无图可用 | §6 设计位置；素材本身可先用手绘 1 张通用「待定图形」占位 |
| **G6** | 季节与色板被混为一谈的风险（P4） | **字段分离** | 检索会把「冬季但配色冷」的素材错误降权或错误加权 | `season` 与 `palette` 已是独立列，检索时必须各自加权、不得互相推导 |

**一句话结论**：缺口是**表结构（G1，阻断性）→ 登记（G3）→ 标签（G4/G5）→ 桥接（G2）**这个顺序，
其中 **G2 不是「缺东西」，而是「两个维度本来就不同」**，必须承认而不能用一张 tag 表硬凑。

---

## 6. fallback 预留位置的设计

`no_applicable` 分支（6 项占比）现在只产出 `selection.json`，一图未画。要给它留位：

### 6.1 三处预留

| 位置 | 预留什么 | 取值 |
|---|---|---|
| `asset_usage.layout_slot` | 新增枚举值 | `fallback_placeholder` |
| `assets.status` | 新增状态 | `placeholder`（占位图专用；不参与正常检索，只在 fallback 时按此状态查） |
| `tag_vocabulary` | 新增受控词 | `tag = fallback_placeholder`，`tag_type = 'usage'`，`aliases = []`，`note = '选型器返回 no_applicable 时的占位素材'` |

### 6.2 为什么用 `status = placeholder` 而不是新建一张 `fallback_assets` 表

- 占位图与普通素材的**存储、尺寸、风格**字段完全一样，只有「能不能被正常检索命中」不同；
  用 `status` 一个字段就能表达，不必多一张表。
- 检索规则：正常查询加 `WHERE status <> 'placeholder'`；fallback 查询只查 `status = 'placeholder'`。
  两条查询互斥，不会互相污染。

### 6.3 未来第三种图形怎么接

`chart_semantic` 已经能做桥的一端。第三种图形上线时只需两步，**不动本 schema**：

1. 旧图形模板的 `not_applicable_when` 改为触发选型器的 `rejected`；
2. 新图形在 `tag_vocabulary` 里注册自己的 `chart_semantic` 词，并在 `asset_tags` 里给适合的素材打上该词。

即：**新图形 = 新词条 + 新标签**，不是新表。

---

## 7. `rationale` / `rejected` 不进 `PageSpec` 本体（明确记录）

本轮**不改** `loop/models.py` 的 `PageSpec` / `ElementSpec`。

理由：

1. `PageSpec` 描述的是「画什么、画在哪」，是**渲染源**；选型理由描述的是
   「为什么这么画、为什么排除了另一个」，是**决策日志**。两者生命周期不同：
   前者会被 `render_from_spec` 反复读取，后者只在选型那一刻有意义。
2. 一旦进 `PageSpec`，`validate_spec` 的 8 条约束校验器就要为它增加分支，
   而它不受任何几何约束——会让「规格里的每个字段都可被约束校验」这条不变量失效。
3. 已有的落点是 `loop/pipeline.py` 的 `INTERFACE_MAP`：`rationale` / `rejected`
   状态标为「缺失」，落到产物目录旁的 `selection.json`。本轮维持不变。

若将来确需进库，**进 `asset_usage` / 单独的 `goal_log` 表，不进 `PageSpec`**。

---

## 8. 落地顺序（供下一轮排期，本轮不做）

| 步骤 | 内容 | 阻断性 |
|---|---|---|
| S1 | 建 `asset_tags` / `tag_vocabulary` / `asset_usage` 三表 + `assets` 扩列（空表，不迁移） | 阻断 |
| S2 | 词表初始化约 40 条（semantic 25 / appearance 6 / season 4 / style 4 / usage 6 / chart_semantic 2） | 阻断 |
| S3 | 登记 12 个未登记图标（`assets` 12 行） | 高 |
| S4 | 19 个素材按 §3.2 打标（约 114 条 `asset_tags`） | 高 |
| S5 | 1 张 fallback 占位图 + `status='placeholder'`（G5） | 中 |
| S6 | `chart_semantic → 建议主题` 的桥（G2），属 GoalExplorer | 中，可后置 |

---

## 9. S1/S2 落地记录（2026-11-09）

本节记录 §8 中 **S1 + S2** 的实际落地结果。**S3/S4/S5/S6 未做**。

### 9.1 产物

| 文件 | 作用 |
|---|---|
| `loop/asset_schema.py` | 唯一的 schema 真源：DDL 片段、词表种子、9 条校验 SQL、`audit()` |
| `scripts/migrate_db.py` | 幂等迁移脚本；`--dry-run` 预览、`--audit` 只体检 |
| `scripts/asset_coverage.py` | G4 覆盖率体检（只读） |
| `tests/test_step13_asset_schema.py` | 52 个验收用例 |

迁移前备份：`db/assets.db.bak-preS1`。

### 9.2 新表结构

- `tag_vocabulary(tag PK, tag_type, label_zh, aliases, parent_tag→自引用, deprecated, note)`
- `asset_tags(asset_id→assets, tag→tag_vocabulary, tag_type, weight 0..1, source, created_at)`，
  **PK(asset_id, tag)**，`ON DELETE CASCADE` / `ON UPDATE CASCADE`
- `asset_usage(id PK, asset_id 可空→assets ON DELETE SET NULL, goal_key, layout_slot,
  score, chosen, miss_reason, note, created_at)`
- `assets` 扩 9 列：`semantic_tags, asset_tags, style_token(默认 'flat'), palette,
  alpha, width, height, license, status(默认 '待登记')`

### 9.3 词表：52 条（原计划约 40 条）

semantic 27 / appearance 9 / chart_semantic 6 / style 4 / usage 4 / season 2。

`chart_semantic` 从设计初稿的 2 值扩到 **6 值**，覆盖选型器 `select()` 的**全部**
可达分支：`比较大小`、`占比构成`、`全相等`（规则 5a）、`含负值`（规则 4）、
`无适用`（规则 1 非比较 / 规则 6）、`其他`（`SEMANTIC_OTHER`）。

> 词是全局唯一的（`tag` 是主键），所以「秋季/冬季」只登记为 `season`，
> 主题侧用「秋季消费」表达，避免同一个词跨 `tag_type` 重复。

### 9.4 P1 硬规则的实现方式与理由

用 **视图 + 触发器**，不用 CHECK：

1. `CHECK` 约束不能跨表——`asset_tags` 的 CHECK 拿不到 `assets.kind`，表达不了。
2. 触发器可以禁止「给整版图打 chart_semantic」（`trg_page_image_no_chart_semantic`），
   但**不能**禁止给整版图打主题标签——那是合法的溯源信息，只是不该被检索出来。
3. 所以「可检索」被定义为两个视图：
   - `v_searchable_assets`：`kind <> 'page_image' AND status <> 'placeholder'`
   - `v_asset_search`：在它之上 join `asset_tags` + `tag_vocabulary`（且 `deprecated=0`）

   任何查询器（Python / 命令行 / 未来 LLM 工具调用）只要查 `v_asset_search`
   就自动受约束，不依赖调用方记得写 `WHERE`。
   测试 `test_page_image_tags_never_surface_in_search_view_even_if_tagged`
   给整版图打满主题标签后断言检索结果为空，即这条规则的核心证明。

### 9.5 一致性校验：9 项，全部返回 0 行

`cache_semantic_mismatch`、`cache_appearance_mismatch`、`orphan_tags`、
`tag_type_drift`、`alias_conflict`、`deprecated_used`、`parent_cycle`、
`bad_status`、`page_image_chart_semantic`。

跑法：`python scripts/migrate_db.py --audit` → `[OK] 9 项体检全部返回 0 行`。

### 9.6 G4 结论：词表已扩，仍缺两类特殊素材

`python scripts/asset_coverage.py`：

| chart_semantic | 7 个已登记 _soft | 含 4 个未登记文件 |
|---|---|---|
| 比较大小 | thermometer, flame | + people |
| 占比构成 | — | **people, percent** |
| 含负值 | thermometer | thermometer |
| 其他 | 6 个 | + droplet, pin |
| 全相等 | — | — |
| 无适用 | — | — |

**覆盖率：已登记 3/6，含未登记文件 4/6。**

结论（回答 §5.1 的 G4 问题）：

1. **「占比构成」是缺登记 + 缺标签，不是缺素材**。`percent.png`（百分比符号）与
   `people.png`（人群）本来就能表达占比，只是没登记进 `assets`。S3 + S4 即可补上。
2. **「全相等」「无适用」是真缺素材**，且普通物品图标表达不了：前者要「等号 / 两个
   一样高」这类对比符号，后者要专门占位图（S5）。扩词表**不足以**覆盖这两档。
3. 所以 G4 的答案是**两者兼有**，但要分清：扩词表解决了「选型器说得出的话，
   素材库也有对应的词」；缺的是两张专门素材 + 4 个未登记图标的登记与打标。

### 9.7 幂等性

- 迁移前后：`assets` 8 行、`pages` 1 行、`paragraphs` 5 行、`chart_points` 60 行，
  `id/kind/url/bytes` 逐行不变；`db/assets.db` 从 40960 B 变为 65536 B，
  **SHA-256 从 `BBB8B2DF…990B0` 变为 `B0FC78BD…C339E`**（只新增结构与词表）。
- 第二次、第三次执行 `scripts/migrate_db.py` 均输出「无变更」，且文件字节 SHA 不变。
  `tests/test_models.py::test_db_sha256_matches_known_constant` 已更新为新常量。
- 迁移脚本在**单个事务**内执行，迁移后立刻跑 9 项体检，任一项不为 0 行就整体回滚。

### 9.8 本轮明确未做

- 批量打标（`asset_tags` 仍是 0 行）——S4
- 登记 12 个（实为 4 个基名）未登记图标——S3
- fallback 占位图——S5
- `chart_semantic → 主题` 的桥——S6
- 未改 `loop/selector.py` / `loop/solve.py` / `loop/render.py` / `loop/pipeline.py`
  / `loop/models.py`（`grep` 命中数为 0）

## 10. S5 落地记录：fallback 占位图（2026-11-09）

S5 的目标只有一个：让选型器返回 `no_applicable` 时，版面上有一张「这里本该有图但
没有」的中性图可查，而不是留白或崩溃。

### 10.1 一个必须先解决的冲突

S1/S2 把 P1 写成了两道闸：`v_searchable_assets` 排除 `kind='page_image'` **和**
`status='placeholder'`。也就是说占位图**按设计**就查不到——这正是我们要的
（灰色方块不该出现在「比较大小」的配图结果里），但 S5 又要求「用
`fallback_placeholder` 能命中它」。两条检索目标互斥，不能用同一个视图。

**裁定**（2026-11-09，用户确认）：新开一个 `v_fallback_assets` 视图，而不是放宽
`v_searchable_assets`。理由：放宽等于让占位图污染正常检索，而 P1 对 placeholder
的排除恰恰是 S1/S2 刻意做的；单独开视图能把「两条检索路径」的分歧固定在 schema 层，
而不是靠调用方记得传参数。

### 10.2 视图

```sql
CREATE VIEW v_fallback_assets AS
SELECT s.id AS asset_id, s.url, s.local_path, s.kind, s.status,
       s.style_token, s.palette, t.tag, t.tag_type, t.weight, v.label_zh
FROM assets s
JOIN asset_tags t     ON t.asset_id = s.id
JOIN tag_vocabulary v ON v.tag = t.tag
WHERE s.status = 'placeholder'
  AND t.tag = 'fallback_placeholder'
  AND v.deprecated = 0
```

与 `v_asset_search` 的差别只有 `FROM` 那一句：正常检索从 `v_searchable_assets`
出发（已排除占位图与整版图），兜底检索从 `assets` 出发但自己加 `status` 条件。

### 10.3 两张占位图

| 文件 | 内容 | 用途 |
|---|---|---|
| `assets/placeholders/placeholder_todo.png` | 虚线方框 + 三个点 | 「待补充」通用占位 |
| `assets/placeholders/placeholder_chart.png` | 坐标轴 + 三根柱 | 「此处缺一张图」 |

都 400×400 RGBA、中性灰（三通道最大差 ≤ 40，有测试钉住）、由
`scripts/make_placeholder.py` 用 PIL 绘制，无外部素材。

**为什么放在 `assets/placeholders/` 而不是 `assets/icons/`**：
`scripts/asset_coverage.py` 扫 `assets/icons/` 统计图标覆盖率，占位图混进去会把
「未登记图标」从 4 个变成 6 个，污染 G4 的口径。

### 10.4 登记结果

| id | kind | status | style_token | palette | license |
|---|---|---|---|---|---|
| 23 | `placeholder` | `placeholder` | `flat` | `neutral_grey` | `self-drawn (PIL)` |
| 24 | `placeholder` | `placeholder` | `flat` | `neutral_grey` | `self-drawn (PIL)` |

`kind` 用 `placeholder` 而不是复用 `icon`：这样 `asset_coverage.py`（只查
`kind='icon'`）与 `v_searchable_assets`（排除 `status='placeholder'`）都不会捎带它们。
`width` / `height` = 400，`alpha` = 1.0，`local_path` 指向 `assets/placeholders/*.png`。

**标签**：每张只打一条 `(asset_id, 'fallback_placeholder', tag_type='usage', weight=1.0, source='manual')`。

**不挂 `chart_semantic`**（用户裁定）：占位图不是「适合配某类图」，它本身就是
「没有图」的标记；`chart_semantic` 那一侧留给真素材。写入侧也不会被
`trg_page_image_no_chart_semantic` 拦（那条触发器只针对 `kind='page_image'`），
是**按设计选择不打**，不是被拦。

### 10.5 检索入口

`loop/asset_lookup.py`（新增，只读）：

* `find_fallback_assets(db_path=DB_PATH)` → 走 `v_fallback_assets`
* `find_assets_by_semantic(semantic, db_path=DB_PATH)` → 走 `v_asset_search`
* `resolve_local_path(row, root=None)` → `local_path` 解绝对路径，文件不存在返回 `None`

拆成两个函数而不是一个带 flag 的函数：这两条路径的可见性规则**相反**，
一个 flag 忘了传就会让占位图漏进正文。

### 10.6 验收

| 闸口 | 结果 |
|---|---|
| 占位图文件存在、能读 | 2 张 400×400 RGBA，中性灰（最大通道差 ≤ 40） |
| `assets` 里 `status='placeholder'` 且 `kind≠page_image` | id 23/24，`kind='placeholder'` |
| 用 `fallback_placeholder` 查询能命中 | `v_fallback_assets` 返回 2 行；`find_fallback_assets()` 同样 2 行 |
| 正常检索不误命中占位图 | `v_asset_search` 里 `kind='placeholder'` 命中 **0** 行；`WHERE tag='比较大小'` 结果里无占位图 |
| 端到端：6 项占比分支能查到占位图 | `run_selected(values=[10,3,2,2,2,1], semantic='占比构成')` → `status='no_applicable'`、`preview=None`；兜底查询命中 2 行 |
| 全量测试 | **348 tests OK**（S1/S2 时 333） |
| 既有文件零改动 | `loop/selector.py` / `solve.py` / `render.py` / `pipeline.py` / `models.py` `grep placeholder` 命中 0 |

### 10.7 幂等性与迁移

- `scripts/make_placeholder.py` 重复执行：`新增 assets 0 行 / asset_tags 0 行`，
  并把 `local_path` 自愈到 `assets/placeholders/`（图片挪过目录时）。
- `scripts/migrate_db.py` 现在会在**视图定义变化时重建**视图（`DROP VIEW` +
  `CREATE VIEW`）——`CREATE VIEW IF NOT EXISTS` 不会更新已存在视图的定义，这一版
  加 `_view_matches()` 用归一化 SQL 比对，不一致就重建。否则改了 DDL 却静默不生效。
- 数据库 SHA（S1/S2 → S5）：
  `B0FC78BD…C339E` → `44A6C024EADB9F9DD0C687710CA08AE472BA1ADCB1C184F9823F4950A902EA56`，
  `tests/test_models.py` 常量已同步。

### 10.8 对 G4 覆盖率的修正

占位图**不**计入图标覆盖率（`kind='placeholder'`，且不在 `assets/icons/`），所以
S1/S2 的结论不变：已登记 3/6、含未登记 4/6。但「无适用」这一档从「真缺素材」
变成「有兜底素材但未接入选型链路」——`v_fallback_assets` 提供了检索入口，
**接线（选型器/渲染器真的去用它）不在 S5 范围**，留给 S6 或后续。

### 10.9 本轮明确未做

- 批量打标（`asset_tags` 除占位图 2 条仍为 0 行）——S4
- 登记 4 个未登记图标基名（droplet / people / percent / pin）——S3
- 把占位图真正画进版面（`solver` / `render` 仍不认识占位图）——需扩 PageSpec 或新增图元类型
- `chart_semantic → 主题` 的桥——S6

## 11. S3 落地记录：补登记 4 个未登记基名（2026-11-09）

S3 的范围只有一条：把 `assets/icons/` 下**已有文件、但 `assets` 表里没有**的基名登记进表。
**不打标**（`asset_tags` 除 S5 占位图那 2 条仍为 0 行）。

### 11.1 扫描结果（assets/icons/ 共 19 个文件 / 11 个基名）

| 基名 | 文件 | 登记前状态 |
|---|---|---|
| cup / flame / leaf / radiator / snowflake / sock | `x.png` + `x_soft.png` | 已登记（只登了 `_soft` 变体，id 16–22） |
| thermometer | `thermometer.png` + `thermometer_flat.png` + `thermometer_soft.png` | 已登记（`_soft`，id 20） |
| **droplet / people / percent / pin** | 各只 `x.png`，无 `_soft` | **未登记** ← S3 补齐 |

4 个待登记文件全部 400×400 RGBA、alpha 峰值 255（原图，不是淡化版）。

### 11.2 登记结果

| id | url | kind | status | style_token | palette | width×height | alpha |
|---|---|---|---|---|---|---|---|
| 25 | `local:droplet` | `icon` | 待登记 | flat | NULL | 400×400 | 1.0 |
| 26 | `local:people` | `icon` | 待登记 | flat | NULL | 400×400 | 1.0 |
| 27 | `local:percent` | `icon` | 待登记 | flat | NULL | 400×400 | 1.0 |
| 28 | `local:pin` | `icon` | 待登记 | flat | NULL | 400×400 | 1.0 |

字段取的与既有 icon 行一致的口径：`kind='icon'`、`status='待登记'`、`style_token='flat'`、
`palette=NULL`、`license=NULL`。**`palette` 填 NULL** 的理由：现有 7 个 icon 全是 NULL，
且词表里没有色板维度；S5 占位图的 `neutral_grey` 是专为占位图定义的，不能推广。

`width`/`height`/`alpha` 按文件实际值填（既有 7 个 icon 行这三列是 NULL，属 S1/S2
只加列未回填；新行直接填对，不算破坏约定）。

### 11.3 幂等

`scripts/register_icons.py` 三层判断：

1. `url` 已存在 → 跳过整行，**不覆盖任何非空字段**；
2. 行存在但某字段为空 → 只补该字段（`_fill_blanks`）；
3. 文件在磁盘、库里没有 → 插入。

实测：第一次 `新增 4 / 跳过 0`；第二次 `新增 0 / 跳过 4`（列出 id 25–28）；
`register_icons.py` + `make_placeholder.py` + `migrate_db.py` 连跑两遍，
DB SHA 前后一致（`79E7F1A6…`）。行 25–28 与 S1/S2 的 8 行互不影响。

### 11.4 覆盖率口径修正（顺带）

`scripts/asset_coverage.py` 原来的「已登记」只统计**文件名以 `_soft` 结尾**的图标。
S3 补登记的 4 个基名磁盘上只有原图、没有 `_soft`，旧口径下登记了也不算数，
覆盖率数字纹丝不动——**口径比事实窄，把已登记的报成未登记**。

**裁定**（2026-11-09，用户确认）：口径改为「`assets` 表里 `kind='icon'` 的基名集合」，
基名归并 `_soft` / `_flat` 变体。报告键同步改名：

| 旧键 | 新键 |
|---|---|
| `registered_soft_icons` | `registered_icons` |
| `covered_soft` | `covered_registered` |
| `missing_with_soft` | `missing_with_registered` |

S3 之后：已登记 11 个基名 = 磁盘上 11 个基名（未登记 0 个），
覆盖率 **3/6 → 4/6**（「占比构成」由 people + percent 补上），
仍空缺：**全相等**（需等号/持平类对比符号）、**无适用**（需占位图，S5 已备素材但未接线）。

### 11.5 验收

| 闸口 | 结果 |
|---|---|
| 4 个基名全部登记、能查到 | id 25–28，`assets` 各 1 行，无重复 url |
| 重复执行不产生重复行、不覆盖非空字段 | 二次跑 `新增 0 / 跳过 4`；测试用库副本验证 `palette='keep_me'`、`alpha=0.5` 未被覆盖 |
| asset_tags 除占位图外仍 0 行 | 全表仍只有 2 条 `fallback_placeholder` |
| `v_asset_search` 能按 kind 查到新素材、不误命中 | `v_searchable_assets` 11 行全为 `icon`；`v_asset_search` 里 `placeholder` / `page_image` 命中均 0 |
| 全量测试 | **370 tests OK**（S5 时 348） |
| 既有文件零改动 | `loop/selector.py` / `solve.py` / `render.py` / `pipeline.py` / `models.py` 的 sha256 前缀与 S5 时相同，`grep` 命中 0 |

DB SHA：`44A6C024…EA56` → `79E7F1A6FB3A9B095E95B0D10890DC386A260DE13FE46CC03DF23BE451217F41`。

### 11.6 本轮明确未做

- 批量打标（S4）——`asset_tags` 仍只有占位图 2 条
- 给 4 个新图标补 `_soft` 变体（只登记现有文件，不新生成）
- `style_token` 细分（全部 `flat`，与既有 7 行一致）
- 占位图接入选型/渲染链路（S5 遗留）
- `chart_semantic → 主题` 的桥（S6）

## 12. S4 落地记录：11 个 icon 批量打标（2026-11-09）

S4 只做一件事：给库里**真正需要被检索**的 11 个 icon 打 `asset_tags`，让选型器
按 `chart_semantic` / `semantic` 能查到东西。不打 page_image（P1 挡着）、不动占位图、
不扩素材、不爬虫、不改表结构、不发明词表外的标签。

### 12.1 打标对象与量级

打标对象写死在 `scripts/tag_assets.py::EXPECTED_IDS`（16–22、25–28），**不靠扫描推断**
——扫描会把 `page_image` 和 `placeholder` 混进来。脚本开头先核 `id` 与 `url` 一一对应，
不符就 `SystemExit` 而不是硬写。

预计 85 条，实际 85 条（一致）。分布：

| id | 文件名 | 条数 | chart_semantic |
|---|---|---|---|
| 16 | leaf_soft | 6 | — |
| 17 | radiator_soft | 9 | 比较大小 1.0 |
| 18 | sock_soft | 9 | — |
| 19 | cup_soft | 6 | — |
| 20 | thermometer_soft | 11 | 比较大小 0.6、含负值 1.0 |
| 21 | snowflake_soft | 9 | 其他 1.0 |
| 22 | flame_soft | 9 | 比较大小 1.0、其他 1.0 |
| 25 | droplet | 6 | 其他 1.0 |
| 26 | people | 7 | 占比构成 1.0、比较大小 1.0 |
| 27 | percent | 6 | 占比构成 1.0 |
| 28 | pin | 7 | 其他 1.0 |

### 12.2 「比较大小」为什么 radiator 优先

两张图都能用，但原版信息图里**温度计本身就是区块③的图表本体**，再拿温度计图标
当配图会和图表撞车（读者分不清哪个是数据、哪个是插图）。暖气片是取暖电器本体，
做「大小比较」栏目的配图更中性。所以：

- radiator 的 `比较大小` 权重 **1.0**（首选）
- thermometer 的 `比较大小` 权重 **0.6**（次选，仍可用）
- people / percent 的 `占比构成` 均 1.0（两张各有所长，不设优先级）

权重只影响**检索排序**（`v_asset_search` → `ORDER BY weight DESC, asset_id`），
**不参与选型决策**——选型看数据形态（`loop/selector.py`），不看素材。

### 12.3 两个语义歧义（用户裁定）

| 图标 | 候选 | 裁定 |
|---|---|---|
| cup_soft | 热水 / 饮水 / 两个都打 | **热水**（图上冒热气，与取暖主题更贴） |
| flame_soft | 火焰 / 热量 / 加热 | **火焰 + 热量**（不打「加热」——那是动作，图标不表达动作） |

### 12.4 status 迁移

打标成功且该 icon 至少有一条 tag 的，`assets.status`：`待登记` → `已标注`（用户裁定）。
`triggers` 与 `CHECK` 不受影响；page_image（id 15）与占位图（23/24）状态不动。

### 12.5 三个踩坑

**① `asset_tags.created_at` 是 NOT NULL 且无默认值。** 第一次跑直接
`sqlite3.IntegrityError: NOT NULL constraint failed: asset_tags.created_at`。
S4 不改表结构，所以插入时显式给时间戳（`datetime.now().isoformat(timespec="seconds")`），
格式与 `scripts/make_placeholder.py` 一致。

**② `asset_tags.source` 有 CHECK 约束**，只允许 `'manual' / 'model' / 'crawl'`。
我最初写了批次号 `'manual-s4'`，直接 `CHECK constraint failed`。批次区分交给
`created_at` 与文档，不塞进 `source`。

**③ 缓存列必须同步回填，且 JSON 分隔符要对齐。** `assets.semantic_tags` /
`assets.asset_tags` 是冗余缓存，`audit()` 有 `cache_semantic_mismatch` 专门抓
「只写真源不更缓存」。第一版打标没回填 → 体检立刻报脏。
回填后仍报脏，原因是 `json.dumps` 默认写成 `["a", "b"]`（带空格），
而 sqlite 的 `json_group_array` 输出 `["a","b"]`（无空格）——**字面不等**。
必须 `separators=(",", ":")`。这条很容易漏，因为肉眼看两个 JSON 是"一样"的。

### 12.6 检索验证

| chart_semantic | 命中 | 顺序 |
|---|---|---|
| 比较大小 | 4 | radiator(1.0) → flame(1.0) → people(1.0) → **thermometer(0.6)** |
| 占比构成 | 2 | people(1.0) → percent(1.0) |
| 含负值 | 1 | thermometer(1.0) |
| 其他 | 4 | snowflake / flame / droplet / pin |
| 全相等 | **0** | 见 12.8 |
| 无适用 | **0** | 见 12.8 |

`v_asset_search` 里 `kind='placeholder'` 与 `kind='page_image'` 命中均为 **0**；
可检索池 `v_searchable_assets` 仍是 11 行、全为 `icon`。

### 12.7 验收

| 闸口 | 结果 |
|---|---|
| 11 个 icon 全部有 asset_tags | 是，最少 6 条（16/19/25/27）、最多 11 条（20） |
| 所有 tag 在词表内、tag_type 对齐、无裸写 | `missing_vocabulary()` = `[]`、`tag_type_drift()` = `[]`、库内 orphan tag = 0 |
| 比较大小 ≥ 2 命中、占比构成 ≥ 2 命中 | 4 命中 / 2 命中 |
| 不误命中 placeholder / page_image | 均 0 |
| 全量测试 | **394 tests OK**（S3 时 370） |
| 既有模块零改动 | `selector.py` / `solve.py` / `render.py` / `pipeline.py` / `models.py` sha256 与 S3 时相同，`grep placeholder` 命中 0 |

`loop/asset_lookup.py` 有一处必要改动：`find_assets_by_semantic` 增加 `weight` 列并
改为 `ORDER BY weight DESC, asset_id`。否则权重写了也没人读，radiator 优先无从体现。

### 12.8 两档如实未解决

**「全相等」档缺素材。** 词表里有 `全相等` 这个 chart_semantic（规则 5a 会用到），
但库里没有任何图标能表达「一样大 / 持平」。现有 11 个图标全是具体物件（暖气片、袜子、
温度计……），拿任何一个凑都是自欺。**需要一个等号类或「持平」类对比符号**，
本轮不造。

**「无适用」档占位图查得到但画不出来。** S5 的两张占位图（id 23/24）走的是
`v_fallback_assets`，不是 `v_asset_search`——所以按 `chart_semantic='无适用'` 查是
**0 命中**，这是设计使然而非缺陷（占位图不该污染正常检索）。真正的问题是：
即便把占位图交给下游，`loop/solve.py` 与 `loop/render.py` 也**不认识 `placeholder`
这种图元**——它们只认 `rect/ellipse/text/arc/ticks/outline`。所以占位图目前
"查得到、取得到 `local_path`、文件也在磁盘上"，但**没有一条代码路径会把它画进版面**。
接线需要扩 PageSpec 图元类型或加一层素材贴图渲染，超出本轮范围，故不做。

### 12.9 本轮明确未做

- 不解决「全相等」缺素材、「无适用」占位图接线（见 12.8）
- 不造新素材、不生成 `_soft` 变体、不爬虫
- 不改 `selector.py` / `solve.py` / `render.py` / `pipeline.py` / `models.py`
- 不改表结构、不新增 tag_type、不加词表外的标签
- `style_token` 仍全为 `flat`（未按图标实际风格细分）
