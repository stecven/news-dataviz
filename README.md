# news-dataviz · 新闻数据可视化流水线

把一段新闻稿 + 一个数据集，自动排成一张**可编辑的报纸风格信息图**（PowerPoint 原生图形，能点开改）。

起点是复刻《经济日报》2026-11-03 第 9 版「时令小家电换季热销」，现在长成了一条完整流水线：
**数据 → 选型 → 约束求解 → 单卡渲染 → 整版排版 → 自动编排 → 主题配图**。

## 现在能做什么

- **约束求解出图形**：温度计（细管 + 刻度 + 球泡，0 点在球泡顶点）、半圆图（扇角按数值分配、Σθ 恒为 180°），每条几何都由声明式约束推导，改一个数值整张图跟着重解。
- **单卡自适应**：给一张卡片 `target_width_in × target_height_in`，内部自动缩放重排装进格子；物理装不下时抛 `BoundaryError` 并给出**每轴最小可行尺寸**，不静默撑破。
- **整版排版**：多栏流式（最多 3 栏）、同行等高拉伸、文本块分栏与跨栏、卡片跨栏与并排。
- **自动编排**：只给一段文字和数据库，自动拆标题/导语/正文、按「品类 + 指标 + 维度/地区」匹配数据集、调用选型器组流。
- **主题配图**：从正文提取语义主题去素材库挑插图（主题优先 → 被本页占用就降级到图表语义 → 都查不到就跳过），如「取暖电器」配暖气片。
- **兜底不崩**：选型器判「不适用」时不静默兜底成别的图，而是画一张占位图并把理由写进说明。

## 目录

| 路径 | 内容 |
|---|---|
| `loop/` | 核心：`solve`/`scaffold`/`fit`/`frame` 约束求解；`palette`/`text_style`/`thermo_shape` 视觉单一来源；`render*`/`preview` 单卡渲染；`layout`/`text_flow`/`render_page` 整版排版；`selector`/`pipeline`/`compose` 选型与编排；`asset_schema`/`asset_lookup` 素材库语义层 |
| `frontend/` | **前端出图线**：前端界面与调用层（调绘图引擎出图） |
| `ingest/` | **素材采集线**：爬取数据图、清洗、登记进素材库、打语义标签 |
| `scripts/` | 数据入库、素材生成与打标、各阶段演示脚本、数据库迁移 |
| `tests/` | 676 个 unittest（`python -m unittest discover -s tests`） |
| `docs/superpowers/specs/` | 设计文档、素材库语义 schema、端到端复盘 |
| `.superpowers/sdd/` | 实施台账（第 1–30 步的决策与验证记录） |
| `db/assets.db` | 素材库真源（含语义标签、词表、检索视图）——**二进制，只由素材线提交** |
| `assets/` | 原版参考图与图标 |
| `out/` | **生成物，不入库**，由 `scripts/` 重建 |

两条线怎么分工、数据库为什么只有一个写者、500 张图怎么不撑爆仓库：[CONTRIBUTING.md](CONTRIBUTING.md)。

## 快速开始

```bash
# 环境：任何 Python 3.11+，只依赖 pillow 与 python-pptx
python -m unittest discover -s tests -q          # 跑全量测试

# 重建一则报道（自动编排 + 主题配图）
python scripts/build_theme_match_demo.py         # → out/demo/theme_match/
python scripts/build_multicol_demo.py            # → out/demo/multicol/
python scripts/build_auto_layout_demo.py         # → out/demo/auto_layout/
```

历史脚本（最初的整版复刻，用绝对路径调用 Python）：

```bash
python scripts/fetch_assets.py       # 抓版面 + 正文 + 原图，写库
python scripts/seed_chart_data.py    # 把图上的数据点写进 chart_points
python scripts/make_icons.py && python scripts/make_soft_icons.py
python scripts/build_onepage.py      # 出 pptx
```

> 当初的版式规则是「原图像素 / 100 = 英寸」，所以复刻画布是 10 × 14.17 英寸，比例与原图 1000×1417 一致。

## 几条设计约定（改代码前请先读）

1. **色板与字号只有一个来源**：`loop/palette.py`。渲染层任何地方都不许出现十六进制色值或写死的 `Pt(10)`，有测试在守。
2. **折行在排版层算**：`loop/text_flow.py` 折好行写进规格，PPTX 与 PNG 两个后端照抄同一份；代价是 PPTX 里关掉了 `word_wrap`，在 PowerPoint 里改字号不会重排。
3. **图形不含数据驱动的几何字面量**：模板里的坐标一律是 `@参数名` 或约束表达式，数值走参数；测试 `tests/test_step2_templates.py` 会拒绝裸数字。
4. **校验器从几何重推，不信自报值**：`validate_spec` 逐条约束重新推导，所以「自洽地错」也会被抓到。
5. **数据库只读**：素材与数据查询一律 `mode=ro`，改库走 `scripts/migrate_db.py`（幂等 + 迁移后自动体检）。

## 文档

- [设计文档：Charticulator 约束求解落地](docs/superpowers/specs/2026-11-07-charticulator-landing-design.md)
- [素材库语义 schema（含 S1–S6 落地记录）](docs/superpowers/specs/2026-11-09-asset-semantic-schema.md)
- [端到端复盘（色板/图框/字号/排版/编排/插图逐轮实测）](docs/superpowers/specs/2026-11-09-end-to-end-review.md)
- [实施台账](.superpowers/sdd/2026-11-07-charticulator-implementation/progress.md)

## 协作

1. 克隆：`git clone git@github.com:stecven/news-dataviz.git`
2. 加协作者：仓库 **Settings → Collaborators → Add people**（对方接受邀请后即可推分支）
3. 改动走分支 + PR：`git switch -c feat/xxx` → 提交 → `git push -u origin feat/xxx` → 在 GitHub 开 Pull Request
4. 提交前请保证 `python -m unittest discover -s tests -q` 全绿。**不要提交 `out/`**（已在 `.gitignore`）。

## 已知限制

- 半圆图分项超过 5 时按设计判「不适用」，走占位图兜底；「全相等」档目前缺专门素材。
- 图文混排只做上下型 + 栏内均分，没有两侧文字环绕；段落不回填上一行空栏。
- 球泡与管身的接合用折线近似（400% 放大可见轻微折角）。
- 排版层自己折行，因此 PPTX 中手动改字号不会触发重排。
