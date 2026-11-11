# 《LIDA 参考落地方案》（设计文档 · 已验收补遗）

> 原始交付：对话 m00164（2026-11-07）。本文件是其落盘副本，附 2026-11-07 的四硬决策验收补遗（第 0 节）。
> 本文件是实施计划 `docs/superpowers/plans/2026-11-07-thermometer-minimal-loop.md` 的 Spec，执行者需同时阅读两者。

---

## 0. 验收补遗：四个硬决策定死（2026-11-07）

按「先验收四个硬问题、哪条含糊就退回补」的要求，逐条核查结果如下。**#1、#2 原本含糊，已补死；#3、#4 文档本身合格，但明确划为后续阶段、不计入本轮实现。**

| # | 硬问题 | 验收判定 | 补遗后的定稿 |
|---|---|---|---|
| 1 | 「可编辑」定死没有？ | **含糊**：原文 B 节同时写了「输出是规格而非位图或写死坐标」和「渲染时一元素 = 一个 PPT 原生对象」，没在 Vega-Lite JSON / 代码规格 / PowerPoint 原生图表中只选一种 | **只选「代码规格 `PageSpec` JSON」**。PPTX 是渲染产物，不是可编辑源；不引入 Vega-Lite。理由：温度计/半圆无法用 PPT 原生图表表达（只有 BAR/COLUMN/PIE），纯形状又不能绑定数据，只有声明式规格能同时满足「改数据→重绘」与「生活化形状」。副作用：`README.md:3`「PowerPoint 原生图表，能点开改数据」口径本轮**不改**、留待后续统一，此处明确记下以免又成模糊点 |
| 2 | 脚手架清单覆盖够不够？硬约束写在哪一行？ | **基本合格但没落到可执行行**：原文给了 `size = L_min + (L_max − L_min)·norm(v)` 和六类图形的文字约束，但没有函数签名与常量 | 最小闭环只实现**温度计**一类，硬约束钉死为两个纯函数：`compute_scale(values) -> Scale(v_max=ceil(max(v)*1.1))`、`liquid_height_in(v, scale, H) = H*v/V_max`，`H = 3.0`（来自 `GOAL_STUB.inner_h_in`）。其余 5 类（半圆图、带图标进度条、辐射节点图、点位连线地图、双色温度计）本轮**不实现**，文档保留为后续注册表条目 |
| 3 | 目标探索的选型约束有没有？ | **合格**：C 节有封闭枚举 + 显式 `fallback_default` 通道 + 确定性校验器 + few-shot 正反例 | 本轮**不含 LLM / GoalExplorer**，改为固定 `GOAL_STUB` 注入，只验证「脚手架 + 填充中间」的结构本身（stub 可替换、脚手架不变）。选型约束保留在 C 节，等第四步「自评估守门员」再上。**明确记为非目标**，避免被误认为已实现 |
| 4 | 素材库接口约定了吗？ | **合格且符合「只给 schema」**：E 节给了 `semantic_tags` 与 `assets.kind` / `asset_tags` / `tag_vocabulary` / `asset_usage` 的映射 | 本轮不碰 `db/assets.db`、不建表；`GOAL_STUB.semantic_tags` 用空数组占位，字段名与 E 节一致。语义标注列为第四步前置任务 |

### 0.1 最小闭环范围（第二步：砍出的一条最窄链路）

| 项 | 定稿 |
|---|---|
| 一个数据集 | `chart_points.chart_key = 'heat_ratio_top5'`，只读，5 行，`value = 10.0, 3.0, 3.0, 3.0, 3.0`，`unit = '倍(超)'`。**特意选它**：这正是上一轮 `scripts/build_onepage.py:330` 的 `ratio = 1.0 if v >= 10 else v / 3.0` 削顶现场，极端值测试自带 |
| 一个目标 | 固定 `GOAL_STUB`（`chart_type="thermometer"`，5 支温度计，共用比例尺），无 LLM |
| 一种生活化图形 | 温度计：5 管并排，每管含管身(track) + 液柱(liquid) + 球泡(bulb) + 标签 + 真值，均为 PPT 原生形状 |
| 数值→尺寸硬约束 | `V_max = ceil(max(v)*1.1) = 11.0`；`h_i = 3.0 * v_i / 11.0`；**禁止 `min(v, 上限)`、禁止「超阈值画满」、禁止固定尺寸**；超量程时扩展 `V_max` 并重算全组 |
| 输出可编辑规格 | `out/loop1/pagespec.json`（`PageSpec` JSON，UTF-8 `ensure_ascii=False`，支持 `to_dict`/`from_dict` 往返） |
| 一张预览图 | `out/loop1/preview.png`，由 `out/loop1/loop1.pptx` 经 PowerPoint COM 导出，保证与可编辑产物同源 |

### 0.2 第三步：验收标准与不许做（写进实施指令）

**验收标准（三条，逐条可测）**

1. **图形形状是温度计**：PPTX 中有 5 组「管身 + 液柱 + 球泡」，液柱是 `MSO_SHAPE_TYPE.AUTO_SHAPE` 而非图片。
2. **长度严格等于数值、极端值不削顶**：`v=10.0` 的液柱高度 = `3.0*10/11 ≈ 2.727 in`，**不等于** `3.0 in`（旧逻辑会画满）；`h(10)/h(3) == 10/3`；把 `seq=1` 改成 `12.0` 后 `V_max` 扩到 `14.0` 且**全组**液柱按新比例尺重算。
3. **规格可改数据后重绘**：`pagespec.json` 往返等价；`build_loop(overrides={1: 12.0})` → 重新渲染 → 第二份 PPTX 的液柱 EMU 高度与第一次不同且比例正确。

**不许做**

- 不改 `db/assets.db`（只读 URI + 前后 SHA-256 一致）、不爬虫、不做整版排版。
- 不修改 `scripts/` 下任何现有脚本；新代码全部放独立 `loop/` 包。
- 不调用 LLM、不建 `asset_tags` 等新表、不实现温度计以外的生活化图形。
- 不引入 pytest / 新依赖、不初始化 git 仓库（本目录无 `.git`）。

### 0.3 第四步（跑通后再上，非本计划任务）

1. 素材库语义标注（项目真正的创新点，LIDA 帮不上的地方）：先定 `assets` 语义字段 schema，再决定爬什么、怎么打标。
2. 自评估守门员（SEVQ + 「图形贴近生活」「数值忠实度」两项）：批量筛掉退化成默认图表的结果。

---

## A. 模块映射表

> 本次仅做设计，不改代码、不爬虫、不动 `db/assets.db`。以下基线取自已核查的现状：画布 10×14.17 in（`scripts/build_onepage.py` 按「原图像素/100」写死坐标）、`db/assets.db` 的 `chart_points`（12 组×5 点）/`paragraphs`（5 段）/`assets`（8 行：1 张整版大图 + 7 个 `_soft` 淡化图标），以及三处已知的削顶逻辑 `ratio = 1.0 if v >= 10 else v / 3.0`、`min(v, 2.85)`、`min(v, 3.1)`。

| LIDA 模块 | 本项目模块（命名） | 输入 | 输出 | 依赖的现有脚本/表 | 复用判定 | 改造/新建要点 |
|---|---|---|---|---|---|---|
| SUMMARIZER | `DataBrief`（数据概要器） | `db/assets.db`: `chart_points`(12 组×5 点)、`paragraphs`(5 段)；`scripts/seed_chart_data.py` 的 DATA 列表作为输入样例 | 紧凑自然语言摘要 + `data_profile`（每组 `chart_key`/`chart_title`/`unit`/n/min/max/异常值/数据形态） | `scripts/seed_chart_data.py`、`scripts/dump_db.py`（只读读取逻辑）、表 `chart_points`/`paragraphs` | **部分复用**：表结构可直接用，摘要层需新建 | `chart_points` 已有 `seq/label/value/unit`，可直接作摘要输入；现状没有摘要层，数值直接喂给 `build_onepage.py` 写死坐标。LIDA 消融结论：摘要不可省 |
| GOAL EXPLORER | `GoalExplorer`（目标探索器） | `DataBrief` + `data_profile` + 生活化图形注册表 + 受控语义词表（未来） | `goal[]` JSON：`question`/`chart_type`/`rationale`/`required_fields`/`chart_key`/`semantic_tags`/`fallback_used`+`fallback_reason` | 无直接可复用；`scripts/build_onepage.py` 的 `hbar/vbar/pie/thermometer_col` 仅作「现有能力盘点」 | **需新建（全部）** | `chart_type` 必须限定为注册表 id 白名单；现有图表函数不可直接复用（写死坐标 + 削顶） |
| VISGENERATOR | `SpecRenderer`（脚手架编译器：脚手架 + 填充中间） | `goal[]` + `chart_points` 数值 + 脚手架模板 | `PageSpec`（页/区块/元素三层声明式规格）+ 编译日志（编译失败/过滤记录） | `scripts/build_onepage.py` 的 `tb/shape/pic/pic_alpha/head/sub/hbar/vbar/pie` 可作渲染后端 | **部分复用**：仅底层绘制函数与画布定义可留，坐标层必须重写 | README「全部 PowerPoint 原生图表可改数据」不成立：仅 `hbar/vbar/pie` 是原生图表，进度条/气泡/温度计柱是 `ROUNDED_RECTANGLE`/`OVAL` 纯形状且数值写死在循环里；三处削顶必须废弃。LLM 只填受限 stub，数值→尺寸由确定性模板计算 |
| INFOGRAPHER | `StyleComposer` + `LayoutComposer`（风格化 + 自动排版） | `PageSpec` + 报纸风格 token + 素材库检索结果 | 带版面坐标与 z-order 的最终 `PageSpec` → python-pptx 可编辑文档 | `build_onepage.py` 画布尺寸与 `head/sub` 标题层、`assets/icons/` 19 个 png、表 `assets`(8 行) | **部分复用**：画布/标题层可留；配色、排版、选图需新建 | 统一暖秋色板（现状红蓝灰绿橙蓝紫混用）、书法体标题/三栏正文/署名「林 蔚」/二维码位；`assets` 表仅 1 张整版大图 + 7 个 `_soft`，19 个图标只登记 7 个且无语义字段 |
| SEVQ 自评估（横切） | `Evaluator` + `RepairLoop`（评估与回退修复） | `PageSpec` + `goal[]` + 渲染结果 + 确定性校验器输出 | 8 维评分 + 不通过项定位 + 重跑指令 | 无 | **需新建** | 确定性校验优先（削顶/白名单/字段存在性用代码查），LLM 只评语义与美观；见 D |

**复用判定汇总**

- 可直接复用：`chart_points`/`paragraphs` 表结构、`seed_chart_data.py` 的 DATA、`build_onepage.py` 底层绘制函数与画布定义、`dump_db.py` 的只读读取逻辑。
- 需改造：`build_onepage.py` 的坐标层与削顶逻辑、README 的「全部可编辑」说法、`assets` 表登记不全（19 个图标只入库 7 个）。
- 需新建：`DataBrief`、`GoalExplorer`、`SpecRenderer` + 脚手架注册表、`StyleComposer`/`LayoutComposer`、`Evaluator`、素材语义层。

## B. 脚手架模板清单

**统一骨架（每个脚手架 = 5 件套，LLM 只填 stub）**

| 件套 | 内容 | 是否经过 LLM |
|---|---|---|
| ① 参数 schema | 必填/可选、类型、默认值、单位（unit） | 模型填取值 |
| ② 适用数据形态 | 比较/占比/构成/趋势/地理/层级/双序列对比 + 反例 | 模型判定，模板校验 |
| ③ 确定性硬约束 | `size = L_min + (L_max − L_min) · norm(v)`；domain 取该组真实 min/max 且上限 ≥ `max(v)`；超量程时**扩展 domain 并重算全组**，禁止 `min(v, 上限)`、禁止「超阈值画满」、禁止固定尺寸 | **否**，纯函数 |
| ④ 输出规格片段 | `PageSpec` 元素：`id`/`type`/`binding`/`geometry`(表达式)/`style`/`asset_ref`/`text`/`z-order` | 否 |
| ⑤ 渲染适配器 | 把该元素编译成 python-pptx 原生形状/图表/文本框/图片 | 否 |

**六种生活化图形**

| 图形 | 参数 | 数值→尺寸硬约束 | 输出规格片段 | 可编辑要点 |
|---|---|---|---|---|
| 温度计 | v 序列(label/value/unit)、管高 H/管宽/球泡半径/位置、刻度数、色标、标题、真值标签 | `h_i = H · v_i / V_max`，`V_max = 向上取整到刻度(max(v) × 1.1)`；刻度上限 ≥ `max(v)`；任一值超量程 → 扩展 `V_max` 并重算全组液柱（同一比例尺），禁止 `min(v, 上限)`；球泡与 v 无关 | 管身+球泡(装饰形状) · 液柱(形状，`binding = h_i`) · 刻度组 · 真值文本(`binding = v_i`) | 现状 `thermometer_col` 是纯形状 + 写死数值，须改为绑定式液柱；单点改值重算 |
| 半圆图 | 分项(label/value/占比)、半径 R、起始角 180°、中心留白比例、扇区色阶、标签 | `θ_i = 180° · v_i / Σv`，加 `Σθ = 180°` 闭合校验；占比文本由 v 实时归一，禁止写死「80%」；分项 > 5 触发「不适用」并显式换图，**不静默改饼图** | 扇区形状组(角度 `binding`) · 中心数值 · 图例 | 对应原版「贵州取暖…占比 TOP5」处的紫色环形/扇形；每扇区是独立原生形状，改值重算全部扇角 |
| 带图标进度条 | 序列、`L_track`/行高、图标 `asset_ref` 与位置、底色/填充色、标签、`scale` 声明 | `L_i = L_track · v_i / V_max`，`V_max = 向上取整(max(v))`（真实最大值）；禁止 `ratio = 1.0 if v >= 10 else v / 3.0` 这类超阈值画满；真值标签恒为 `v_i`；跨数量级可显式声明 `scale = log` 并画出刻度，不许静默削顶 | 底条 · 填充条(长度 `binding`) · 图标图片(`asset_ref`) · 文本标签 · 真值文本(`binding`) | 现状区块①进度条是 `ROUNDED_RECTANGLE` 且数值写死；改为逐行填充条绑定 `chart_points`，图标为可替换图片元素 |
| 辐射节点图 | 中心主题、节点序列、环半径 R、半径域 `[r_min, r_max]`、连线、标签避让、配色 | `r_i = r_min + (r_max − r_min) · (v_i − v_min)/(v_max − v_min)`；角度均分、半径严格随值；连线若按第二度量绑定须显式声明；禁固定半径 | 中心节点 · 节点圆(半径 `binding`) · 连线 · 文本标签 | 每节点独立原生形状，半径表达式可反查数据源 |
| 点位连线地图 | 底图 `asset_ref`、点位(经纬度)、连线绑定值、点半径绑定值、图例 | `w_i = w_min + (w_max − w_min) · norm(v_i)`，点半径同理；经纬度→画布投影参数必须写入 `transform`（可复算），禁止手填像素坐标后固化；无坐标数据时降级为「地区×数值」清单并在 `goal` 注明，**不伪造点位** | 底图图片(可替换) · 点位形状 · 连线形状组(线宽/色 `binding`) · 文本标签 | 底图为图片元素，点位/连线为原生形状；投影记录为 `transform` |
| 双色温度计 | A/B 两组序列、共享 `scale` 对象、双色、图例、差值标注 | 两组共用 `V_max = 向上取整(max(max A, max B) × 1.1)`，`h = H · v / V_max`；**禁止两组分别缩放**（会夸大差异）；差值文本 = 真实差值；一组超量程 → 两柱同时按新 `V_max` 重算 | 管身+球泡 · 两条液柱(各 `binding`，引用同一 `scale` 对象) · 双色图例 · 差值标签 | 两柱共享一个 scale 规格，改任一值重算两柱，保证可比 |

**规格格式与「可编辑」的统一保证**

| 项 | 约定 |
|---|---|
| 规格格式 | 一份声明式 `PageSpec` JSON，三层：页(width/height/风格 token) → 区块(栅格位/标题/`chart_key`) → 元素(id/type/binding/geometry/style/asset_ref/text/z-order) |
| 可编辑 ① | 输出是规格而非位图或写死坐标；每元素带 `binding`（指向 `chart_points` 的 `chart_key`+`seq`）与可逆 `transform` |
| 可编辑 ② | 渲染时一元素 = 一个 PPT 原生对象；改数据只重算 transform、重跑渲染，元素仍可单独选中/改值/改样式 |
| 可编辑 ③ | 禁止把数值写进循环常量或「用文字补真值」假装显示；现状三类纯形状的做法废弃 |
| 可编辑 ④ | 形状类（进度条/温度计/气泡/扇区）必须输出为原生形状，不得烘焙成图片 |
| 可编辑 ⑤ | `scale` 对象（linear/log、domain、`V_max`）在 spec 里留痕，比例尺变更可追溯 |

> **补遗注**：以上「可编辑 ①/②」的措辞在验收中判为含糊，以第 0 节 #1 的定稿为准（唯一可编辑源 = `PageSpec` JSON，PPTX 为渲染产物）。

## C. 目标探索的提示词设计

**输出 JSON 字段表**

| 字段 | 类型/取值 | 约束 | 校验方式（确定性，非 LLM） |
|---|---|---|---|
| `goals` | array | 每条对应一个区块 | 非空、去重 `chart_key` |
| `id` | string | 稳定编号 | 唯一 |
| `question` | string | 该图要回答的问题，须与 `chart_title` 对应 | 与 `data_profile.chart_title` 匹配 |
| `chart_key` | string | 必须 ∈ `db/assets.db` 的 12 个 `chart_key` | 查表，防止模型编数据 |
| `data_shape` | enum | 比较/占比/构成/趋势/地理/层级/双序列对比 | 与 `chart_type` 的适用形态一致 |
| `chart_type` | **封闭枚举** | 只能是脚手架注册表 id（`thermometer`/`semicircle`/`icon_progress`/`radial_node`/`point_line_map`/`dual_thermometer`…）或显式 `fallback_default` | 不在白名单 → 丢弃重试 |
| `rationale` | string | 必须引用 `data_profile` 中的具体数值/形态；用 `fallback_default` 时须逐条说明所有生活化图形为何不适用 | 含数值引用；「默认/通用/简单」作为唯一理由 → 拒 |
| `required_fields` | array of `{name, source, unit, aggregation}` | `source` ∈ `chart_points`/`paragraphs`/`derived`；必须声明 unit 与 domain | 字段可被 `data_profile` 满足 |
| `semantic_tags` | array of `{tag, role, weight}` | 受控词；`role` ∈ hero/icon/product/map_base/texture | 见 E |
| `fallback_used` / `fallback_reason` | bool / string\|null | 二者一致 | 一致性校验 |

**提示词分层与草稿**

| 指令块 | 草稿要点 | 作用 |
|---|---|---|
| ① 角色与任务 | 「你是信息图目标规划器。只依据给定的数据摘要与字段清单，为每条数据规划一个可视化目标。**不得编造数据、不得生成数值、不得输出 JSON 以外的文字**」 | 限定职责与输出纯净度 |
| ② 输入块 | 依次注入：`DataBrief` 全文、`data_profile`（逐组列出 unit/n/min/max/异常值）、**生活化图形清单**（每个 id + 适用数据形态 + 所需字段 + 反例）、受控词语表、输出 schema | 消融结论：摘要不可省；清单是选型的唯一依据 |
| ③ 硬规则 | 「`chart_type` 只能从清单 id 中取值；仅当清单中**所有**图形都不适用时，才允许 `fallback_default`，并必须在 `rationale` 中逐一排除；`chart_key` 必须来自给定列表；`required_fields` 必须声明 unit 与 domain；禁止建议『把超过 10 倍的值画满』『把数值截断到上限』」 | 把「优先生活化」和「不削顶」写进约束 |
| ④ 输出格式 | 「只输出一个 JSON 数组，字段严格按 schema，不要 markdown 代码块、不要解释」 | 便于确定性解析 |
| ⑤ 自检清单 | 输出前逐条自检：问题是否可答？`chart_type` 是否在白名单？`rationale` 是否引用了具体数值？`required_fields` 是否都能取到？是否不小心用了默认柱图/饼图？任一为否，重新生成 | 模型侧第一道闸 |
| ⑥ 示例（few-shot） | 2 正例：倍数数据 → `icon_progress`（且不削顶、量程随真值扩展）、占比 TOP5 → `semicircle`；1 反例：把「超 10 倍一律画满」的柱图判为不合格并给出改正 | 校准选型与削顶边界 |

**强制优先生活化图形的机制**

- 白名单封闭枚举 + 显式 `fallback_default` 通道：默认柱图/饼图不再是「自然选择」，而是需要举证的特殊路径。
- 数据形态判定前置：先输出 `data_shape`，再按「形态 → 推荐图形」映射表选型，跳过模型自由发挥；可参考 Draco 的约束规则做基线候选，LLM 只做排序与文案。
- 确定性校验器：解析 JSON 后校验 `chart_type ∈ 白名单`、`chart_key` 存在、`required_fields` 可满足、unit/domain 齐全；不合格丢弃并重试（LIDA 的过滤 / 自一致性多采样投票）。
- 硬否决评分：D 节「图形贴近生活程度」设「是否优于默认柱图/饼图」为一票否决项，形成提示词之外的第二层防御。
- 回归指标：记录 `fallback_used` 比例；比例上升即说明清单覆盖不足或提示词失效，触发 B 节注册表扩充。

## D. 自评估维度设计

**8 维评分表（1–5 分）**

| 维度 | 来源 | 评什么 | 评分提示词草稿 | 门槛 / 回退 |
|---|---|---|---|---|
| 代码准确性 | LIDA 六维 | 改为「脚手架编译/渲染可执行」 | 「检查 `PageSpec` 能否被模板与渲染后端无异常编译、元素 id 无冲突、`binding` 指向的 `chart_points` 行存在；任一编译失败或悬空引用判 1 分」 | ≤2 → 回 `SpecRenderer` |
| 数据转换 | LIDA 六维 | `chart_points` → spec 的映射、unit、聚合 | 「核对字段映射、单位(unit)、聚合(求和/占比/倍数)与 `data_profile` 是否一致，label 与 value 是否一一对应；出现错列、错单位或凭空数值判 1 分」 | ≤2 → 回 `DataBrief` |
| 目标符合度 | LIDA 六维 | 是否回答了 `goal.question` | 「逐条比对 `question` 与 `chart_title`/图内标签，判断图形是否回答了该问题、是否漏掉 `required_fields`；答非所问或缺字段判 ≤2 分」 | ≤2 → 回 `GoalExplorer` |
| 图表类型 | LIDA 六维 | 选型与数据形态匹配 | 「`chart_type` 是否在生活化注册表白名单内、是否与 `data_shape` 匹配；若为 `fallback_default` 且 `fallback_reason` 不充分，判 1 分」 | 1 分 → 强制重选 |
| 数据编码 | LIDA 六维 | 数值→尺寸/角度/线宽的编码有效性 | 「数值是否通过声明式 `transform` 绑定、同组是否共用比例尺、刻度/图例/单位/真值标签是否齐全；编码不可读或比例尺不一致判 ≤2 分」 | ≤2 → 回脚手架 |
| 美观性 | LIDA 六维 | 报纸风格与色板 | 「整体是否统一暖秋色板(红橙黄褐)、是否保持报纸版式(书法体标题、三栏、署名、二维码位)、有无重叠/越界/过密；风格割裂或压字判 ≤2 分」 | ≤2 → 回 `StyleComposer` |
| 图形贴近生活程度 | **新增** | 生活化 + 语义相关 + 优于默认 | 「所选图形是否来自生活化清单、是否与数据语义相关(如取暖设备配暖气/温度计/枫叶)、是否**明显优于同数据的默认柱图/饼图**；若只是柱图换皮或与主题无关，判 1 分」 | **<3 分不合格**（含「优于默认」硬门槛）→ 回 `GoalExplorer` 重选 |
| 数值忠实度（无削顶） | **新增** | 无截断、无画满、无比例尺作弊 | 「逐元素核查：① 未出现 `min(v, 上限)`、超阈值画满、固定长度；② 量程上限 ≥ 该组 `max(v)`；③ 图上标签 = `chart_points.value`；④ 双序列/多组共用比例尺；⑤ 异常值通过扩展量程处理而非截断。任一元素削顶即判 1 分，整体不通过」 | **一票否决**（判 1 即整体不通过）→ 回脚手架/渲染器 |

**评估执行原则**

- 确定性优先：削顶、白名单、字段存在性、单位一致性、编译成功与否用校验器直接判定，不必交给 LLM；LLM 只评语义相关性与美观。
- 修复路由：选型/贴近生活 → `GoalExplorer`；削顶/编码/编译 → `SpecRenderer` 或脚手架；美观 → `StyleComposer`；数据转换/目标符合 → `DataBrief`/`GoalExplorer`。
- 最多 3 轮重跑，仍不过标人工复核；每轮保留评分与失败项，作为 B/C 节清单与提示词的回归依据。
- 新增两维的判定权高于其余六维：即使美观性 5 分，出现削顶或柱图换皮也不放行。

## E. 与素材库的衔接（仅 schema 建议，不建表）

**现状缺口**

- `db/assets.db` 的 `assets` 表 8 行 = 1 张整版大图（`page_image`，510350 字节，sha256 `fd398fd3…`）+ 7 个 `url=local:xxx` 的 `_soft` 淡化图标（leaf/radiator/sock/cup/thermometer/snowflake/flame_soft，alpha 0.16~0.22）。
- `assets/icons/` 实际 19 个 png（12 原色 + 7 淡化），**12 个未登记入库**；无「内容→插图」语义字段。
- 表结构留有扩展位 `assets.kind`、`chart_points.unit`，可直接承载本次建议的部分字段。

**`GoalExplorer` 输出的 `semantic_tags`**

| 字段 | 说明 | 例 |
|---|---|---|
| `tag` | 受控词（非自由文本） | 枫叶 / 电油汀 / 干衣机 / 水龙头 / 暖秋 / 雪花 |
| `role` | `hero`(中部主视觉) / `icon`(栏头、图例旁) / `product` / `map_base` / `texture` | `hero` |
| `weight` | 0–1，用于多标签排序 | 0.9 |
| 可选约束 | `season` / `style_token` / `palette`（与页面色板一致性） | `autumn`、`flat` |

**建议 schema（仅建议，本次不建表、不动 `db/assets.db`）**

| 表/字段 | 类型或取值 | 用途 |
|---|---|---|
| `assets.kind`（启用现有扩展位） | `page_image`/`hero`/`icon`/`product`/`map_base`/`texture` | 区分整版位图与可复用元素 |
| `assets.file_path` 或 `url`、`sha256`、`width`/`height` | 文本/整数 | 去重、占位计算、来源追溯 |
| `assets.style_token` | `flat`/`realistic`/`line`/`soft` | 风格一致性打分（防止 `_soft` 淡化图与原色图混用） |
| `assets.palette`、`alpha`、`is_soft`、`source_url`/`license`、`status` | 色板 id / 数值 / bool / 文本 / `已标注`/`待审核` | 暖秋色板匹配、合规 |
| 新增 `asset_tags`（建议） | `asset_id`, `tag`, `tag_type`(topic/entity/style/season/role), `weight`, `source`(人工/模型/爬虫) | 多对多语义标注，支撑检索 |
| 新增 `tag_vocabulary`（建议） | `tag`, `tag_type`, `aliases`(中文同义词), `parent_tag` | 把「电暖器/取暖器/电油汀」归一到同一受控词 |
| 新增 `asset_usage`（建议） | `goal_id`, `asset_id`, `score`, `layout_slot`, 反馈 | 选型闭环与回归 |

**对接流程**

- `semantic_tags` → 词表归一（`aliases`）→ 在 `asset_tags` 上检索（tag 命中 × `weight` × `role` 匹配 × `style_token`/`palette` 一致性）→ top-k 候选 → `LayoutComposer` 放入版面位（中部主视觉/栏头/图例旁）→ 写 `asset_usage`。
- 无命中：降级为通用装饰图标，并在 `goal` 标记 `asset_missing`，把缺失 tag 写回词表待补，**不伪造插图**。
- 边界：整版大图是位图，不做可复用 `hero`（除非后续走 ReVision / Mystique / Chart2SVG 逆向切片）；在补齐 19 个图标登记与语义标注前，检索必然大量为空——标注与词表是项目前置任务，不能假设自动完成。

## F. 风险与边界

| # | 风险 | 结合现状的具体表现 | 缓解措施 |
|---|---|---|---|
| 1 | 脚手架覆盖不全 | 清单只有 6 类，遇到时间序列/桑基/地理热力等新形态无对应模板，模型被迫回退默认柱图/饼图，或强套温度计导致失真（如「倍数」和「占比」共用一把尺） | 注册表做成可扩展插件（新增图形 = 参数 schema + 确定性硬约束函数 + 渲染适配器）；每个脚手架声明适用/不适用形态与反例；`data_shape` 判定前置并按映射表选型；监控 `fallback_used` 比例，超阈值即扩充清单 |
| 2 | LLM 仍倾向默认柱图/饼图 | 长上下文或弱模型会忽略白名单，或输出「柱图换皮」看似生活化；现状 `build_onepage.py` 本来就只有 BAR/COLUMN/PIE 能力，回退成本极低 | 双层防御：提示词层（封闭枚举 + few-shot 正反例 + 自检清单）与确定性校验层（解析后 `chart_type ∈ 白名单`，否则丢弃重试/多采样投票）；D 节「优于默认柱图/饼图」设为一票否决；可用 Draco 式规则基线先给候选，LLM 只排序与写文案；记录 fallback 率作回归指标 |
| 3 | 素材库语义标注缺失 | `assets` 表 8 行、19 个图标只登记 7 个、无语义字段；检索为空或选错风格（淡化 `_soft` 与原色混用、暖秋色板对不上），「按内容选插图」形同虚设 | 标注先行：补齐 19 个图标登记 + 受控词表 + `style_token`/`palette`；检索加风格一致性硬约束；无命中降级通用装饰并标 `asset_missing` 反馈补库；整版大图不进检索；把「内容→插图」标注工作量列为前置任务，不假设自动完成 |

**边界声明**

- 本次只产出设计文档，不改代码、不爬虫、不动 `db/assets.db`，E 节全部为 schema 建议。
- 不解决位图矢量逆向（那是 ReVision / Mystique 另一条线）、不承诺插图语义检索准确率、不覆盖多页/跨版联动。
- 不假设 100% 免人工复核；`Evaluator` 3 轮不过即转人工，削顶与选型错误宁可拦截也不静默放行。

---

**一句话总结**：LIDA 对本项目最大的可借鉴点是「脚手架 + 填充中间」——用可执行规格模板把数值→尺寸写成确定性硬约束、只让模型填受限 stub，从而同时保证「可编辑」与「不削顶」；最大的不适用点是 INFOGRAPHER 用图像生成模型产出风格化位图，既不可编辑、也不绑定数据、更无法接入按内容检索的自建素材库，与本项目「各元素可编辑 + 从素材库选插图」的根本要求相冲突。
