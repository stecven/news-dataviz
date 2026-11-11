# ingest/ · 素材采集与入库线

这条线只干一件事：**把外面的数据图弄进来，变成素材库里可检索的条目**。
出图、排版、界面都不在这里做——那些在 `frontend/` 与 `loop/`。

## 归属与边界

| 你负责 | 不要碰 |
|---|---|
| `ingest/`（爬虫与清洗脚本） | `loop/`（求解与渲染） |
| `assets/`（入库的图片） | `frontend/`（前端界面） |
| `db/assets.db`（**唯一写者**） | `tests/`（要改先在 PR 里说） |

## 已有的家当

| 文件 | 作用 |
|---|---|
| `scripts/fetch_assets.py` | 最早那版：抓版面 + 正文 + 原图，建 `pages`/`assets`/`paragraphs` 表 |
| `scripts/make_icons.py` | 用 PIL 画图标，4 倍超采样后缩到 400×400 RGBA |
| `scripts/make_soft_icons.py` | 生成 `_soft` 淡化版 |
| `scripts/register_icons.py` | 扫描 `assets/icons/`，把没登记的图片补进 `assets` 表（幂等） |
| `scripts/migrate_db.py` | 建/改表结构与词表（幂等 + 迁移后自动体检） |
| `loop/asset_schema.py` | 表结构、视图、触发器的唯一真源 |
| `loop/asset_lookup.py` | 只读检索入口（`v_asset_search` / `v_fallback_assets`） |

## 新增一批图的标准流程

```bash
# 1. 清洗 + 落盘（自己写脚本，统一成 400×400 RGBA PNG，带 sha256）
python ingest/<你的脚本>.py

# 2. 登记进 assets 表（幂等，重复跑不会插两次）
python scripts/register_icons.py --list      # 先看扫描结果
python scripts/register_icons.py

# 3. 打语义标签（词表里没有的标签先加词条，别在代码里硬编码）
python scripts/tag_assets.py --dry-run
python scripts/tag_assets.py

# 4. 体检：必须 9 项全 0 行
python scripts/migrate_db.py --audit
```

## 铁律

1. **`db/assets.db` 只有你能提交。** 前端线只读；他们要素材就开 issue。
2. **提交前必须 `ls` 一遍体积**：单张 ≤ 200KB，总量 ≤ 50MB。超了走 Git LFS 或只提交清单 + 下载脚本。
3. **不要发明词表外的标签**：`tag_vocabulary` 是唯一来源，缺词就先加词条（`loop/asset_schema.py` 的 `VOCABULARY_SEED` + 迁移）。
4. **整版图（`kind='page_image'`）不参与检索**：这是 P1 硬规则，视图层面已挡；别绕过 `v_asset_search` 直接查 `assets`。
5. **命名别撞车**：文件名带语义或来源前缀（如 `heat_pump_01.png`），避免和别人的图同名却被 git 当成同一个文件的两个版本。

## 提交信息怎么写

```
ingest: 爬取 120 张取暖电器图片并入库

- 新增 assets 120 行（id 29-148），kind=icon，均 400×400 RGBA
- 新增 asset_tags 340 条（semantic/appearance/season）
- 新增词条 3 个：热泵 / 油汀 / 踢脚线取暖器
- migrate_db.py --audit 9 项全 0 行
```
