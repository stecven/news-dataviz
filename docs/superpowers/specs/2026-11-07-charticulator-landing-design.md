# 《Charticulator 借鉴方案》

> **范围声明**：只做设计，不写实现代码、不执行脚本；不引入 Charticulator 代码 / 依赖 / UI；不推翻现有 `PageSpec`，只在其上扩展「约束」字段与求解步骤；约束子集只覆盖**温度计 + 半圆图**；不改 `db/assets.db`、不爬虫、不做整版排版、不调 LLM。
> 参考：*Charticulator: Interactive Construction of Bespoke Chart Layouts* (CHI 2019)。可借鉴点仅三个：两层框架、约束求解代替写死坐标、模板与数据解耦。
> 现状核对依据（本轮只读文件，未运行任何脚本）：`loop/models.py`、`loop/scaffold.py`、`loop/render.py`、`loop/build_loop.py`、`out/loop1/pagespec.json`、`docs/superpowers/specs/2026-11-07-lida-landing-design.md` B 节。

---

## A. 现有 PageSpec 的差距诊断

### A.1 哪些字段是「写死坐标」

| 位置 | 字段 / 代码 | 写死内容 | 性质 |
|---|---|---|---|
| `loop/models.py:17-27` | `ElementSpec.x_in / y_in / w_in / h_in` | 本应是「求解结果」字段，当前没有求解过程，由生成端直接填满绝对坐标 | 规格里全是绝对坐标 |
| `loop/scaffold.py:72` | 标题 | `(0.5, 0.30, 9.0, 0.50)` | 绝对坐标 |
| `loop/scaffold.py:73-77` | 量程说明 | `(0.5, 0.85, 9.0, 0.30)` | 绝对坐标 |
| `loop/scaffold.py:83` | `x = 0.8 + i * 1.8`（`i = seq−1`） | 水平步长 `1.8` 写死，与数据条数 `n`、画布宽 `W` 无关 | 排布规则硬编码 |
| `loop/scaffold.py:87` | 管身 | `(x, 1.30, 0.5, 3.0)`，起点 y 与管高写死 | 绝对坐标 |
| `loop/scaffold.py:90` | 液柱 | `(x, 4.30 − h_i, 0.5, h_i)`，`4.30` 是「管底」常量（由 `1.30+3.0` 手算固化） | 绝对坐标 |
| `loop/scaffold.py:95` | 球泡 | `(x − 0.15, 4.15, 0.8, 0.8)`，`x−0.15` 居中偏移写死 | 绝对坐标 |
| `loop/scaffold.py:98 / :101` | 标签 / 真值 | `(x − 0.55, 5.05, 1.6, 0.35)` 与 `(x − 0.55, 5.40, 1.6, 0.35)` | 绝对坐标 |
| `loop/scaffold.py:106` | 画布 | `10.0 × 6.0` 英寸写死 | 绝对尺寸 |
| `loop/render.py:22, :36-37` | 渲染后端 | 直接 `Inches(el.x_in)` 逐个落形状；`spec.width_in/height_in` 只用于设画布尺寸，**不参与推导元素坐标** | 画布与元素无关联 |
| `loop/scaffold.py:92-93` | `binding` | `{chart_key, seq, value, computed_h_in}`，`computed_h_in` 把 `h_i` 烘焙进 binding，`binding.value` 仅作溯源 | 数据绑定未参与求值 |

### A.2 失效场景（用温度计闭环的实际数据举例）

| # | 输入变化 | 当前行为 | 后果 / 根因 |
|---|---|---|---|
| 1 | 换数据条数：`heat_ratio_top5` 5 行 → 6 行 | `x = 0.8 + 5×1.8 = 9.8`，加 `0.5` 宽 = `10.3 > W=10.0` | 第 6 支溢出画布；底部 `5.40+0.35=5.75` 只余 0.25，第 7 行必溢出。根因：`d` 与 `n`、`W` 无约束关联 |
| 2 | 换画布尺寸：`height_in 6.0 → 4.0` | 27 个元素的 `x/y/w/h` 一个都不变（`render.py` 只把新尺寸给画布） | `label y=5.05`、`value y=5.40` 直接掉出画布；`track` 仍 3.0 高、`4.30` 基准不变 → 上半截断、下半大片空白。根因：没有任何约束把元素与 `W/H` 关联 |
| 3 | 改 PageSpec 数值 | 把 `pagespec.json` 的 `liquid_1.binding.value` 由 `10.0` 改 `5.0` 再渲染，液柱 EMU 仍 `2493818` 不变；改 `h_in` 才变 `1246909` | 「改规格数值 → 图形跟着变」不成立。根因：`build_pagespec()` 把 `h_i = 3.0×v/V_max`（`V_max = ceil(10×1.1) = 11.0`，`h_1 = 2.7272727`）算一次后烘焙进 `h_in`/`computed_h_in`，渲染不读 `binding.value`。Charticulator 的 `width = scale.factor × data_i` 正是把数据绑定作为约束参与求解，这是本次要补的根子 |
| 4 | 换图形类型（半圆图） | 半圆图需要圆心、半径 `R`、扇角 `θ`，现有 `scaffold.py` 只有温度计一套循环常量 | 得另写一套 `0.8 + i*1.8` 式硬编码；模板与数据、与画布耦合，无法导出复用 |
| 5 | 比例尺变更 | `Scale(v_max, h_in, unit)` 没有 `factor`（= `3.0/11.0`）、没有 domain 声明 | `V_max` 变了只能靠重跑 `build_pagespec()` 全量重算，没有「约束 → 重解」的增量路径 |

> **现状注**：现有闭环是 31 条 unittest 全绿（初版 23 条，审查修复轮补到 31），`build_loop` 每次从 DB 重跑 `build_pagespec`，所以「改 DB → 重跑 → 全组重算」**成立**；A.2 的缺口集中在「坐标写死、模板不可复用、改规格数值不重算」三条，正是本次借鉴要补的。

---

## B. 两层框架映射

| Charticulator 概念 | 含义 | 项目里的对应 | 现状 |
|---|---|---|---|
| Glyph-level · marks | 小图元的图元集合 | `ElementSpec`（`rect` / `ellipse` / `text`）；`loop/render.py` 一元素 = 一个 PPT 原生形状、`shape.name = el.id` | **已有** |
| Glyph-level · 布局约束 | 图元内部「谁挨着谁、间距多少」 | 管身 / 液柱 / 球泡 / 标签 / 真值的相对关系 | **需新增**：现散落在 `scaffold.py:90/95/98/101` 的 `4.30−h_i`、`x−0.15`、`x−0.55`、`5.40` 等硬编码 |
| Chart-level · plot segment | 字形在画布上怎么排 | 「5 管并排」的序列排布段 | **需新增**：现在是 `0.8 + i*1.8`，与 `n`、`W` 无关 |
| Chart-level · scaffold / 轴 | 排布骨架与刻度 | 部分对应 `Scale`（`v_max/h_in/unit`）；当前无刻度元素、无轴 | **部分已有，需补**：把刻度/轴列为可选元素，并用约束把 scale 与画布、元素尺寸连起来 |
| scale | linear/log、domain、factor | `Scale` + `compute_scale()`（`loop/scaffold.py:34-42`） | **部分已有，需补**：新增 `factor`、domain 声明；`h = factor·v` 写成约束而非烘焙 |
| link | 数据绑定作为约束参与求解（`width = scale.factor × data_i`） | `ElementSpec.binding` | **需新增**：现在只是溯源 dict（`chart_key/seq/value/computed_h_in`），渲染不读；升级为求解输入 |
| 约束求解器 | 声明 → 数学约束 → 最终坐标尺寸 | 无 | **需新增**（D 节选型） |
| chart template | 换数据、换画布自动适配、可导出复用 | `loop/scaffold.py:build_pagespec()` | **需新增**：函数不是可导出规格；升级为 `TemplateSpec`（参数 schema + 约束集 + 输出规格片段） |
| 渲染 | 把解出的规格画出来 | `loop/render.py` + `loop/preview.py` | **已有，不改** |

**新增清单（不推翻 PageSpec，只扩展）**：

| 新增项 | 落点 | 说明 |
|---|---|---|
| `constraints`（约束集） | `PageSpec` 可选字段 | 存 C 节约束声明，缺省 `[]` |
| `layout`（plot segment 声明） | `PageSpec` 可选字段 | `orient / margin / gap / radius` 等，缺省 `{}` |
| `geometry_expr` | `ElementSpec` 可选字段 | 声明式表达式，如 `h = scale.factor * binding.value`；`x_in/y_in/w_in/h_in` 保留为**求解后的输出属性** |
| `TemplateSpec` + 注册表 | 新模块 | 参数 schema + 约束集 + 输出规格片段 + 渲染适配器标识 |
| `solve()` 步骤 | 流水线新增 | 见 D.2 |

`to_dict()/from_dict()` 对新增字段给缺省值，老的 `out/loop1/pagespec.json` 仍可读，不破坏已交付产物。

---

## C. 约束子集设计（只覆盖温度计 + 半圆图）

### C.1 约束原语表

| 编号 | 约束类型 | 数学表达 | 对应 PageSpec 字段 | 求解后产出属性 | 线性? |
|---|---|---|---|---|---|
| C1 | 画布边界 | `0 ≤ x_i`，`x_i + w_i ≤ W`，`0 ≤ y_i`，`y_i + h_i ≤ H` | `width_in / height_in` + 元素四个几何字段 | 全部几何属性 | 线性不等式 |
| C2 | 数据绑定(link) | 温度计 `h_liquid_i = k·v_i`，`k = H_track / V_max`；半圆 `θ_i = (180°/S)·v_i`，`S = Σv` | `binding.value` + `Scale.factor` | `h_in`（温度计）/ `start_angle, end_angle`（半圆） | 温度计线性；半圆先聚合 `S` 再线性（两阶段）。【补遗】本约束在实现上拆为：**预处理聚合 + 线性求解**两步；`S = Σv` 由预处理算出常量，禁止把 `Σv` 写进约束矩阵变成非线性 |
| C3 | 比例尺共享 / 闭合 | 温度计 `V_max = ceil(max(v)×1.1)` 且 `max(h_i) < H_track`；半圆 `Σθ_i = 180°` | `Scale` + 全组元素 | 全组尺寸 / 角度 | 线性等式（`ceil` 作预处理常量） |
| C4 | 垂直相邻 + 间距固定 | 【补遗·报纸原版】`y_bulb = y_track + H_track`（**球泡顶点即 0 点**）；`y_liq + h_liq = y_bulb`（液柱从 0 点向上长）；`y_value = y_bulb + bulb_d + g_v`；`y_label + h_label + g_l + H_track = y_bulb`（类别名在管口上方）。【补遗·皮肤 m02273】`cap_top = y_track`；`R = bulb_d/2 + bulb_ring_pad`；`cap_r = w_track/2 + outline_pad`；`CX = x_track + w_track/2`；`ticks.box = track.box`，刻度带 `pad_top = cap_r`、`pad_bottom = neck_h` | `constraints[].adjacent / gap` | 各 `y_in`、`ticks`/`outline` 的 bbox 与 geometry | 线性等式 |
| C5 | 居中 | `x_label + w_label/2 = x_track + w_track/2`；球泡同理；【补遗·细杆液柱】`x_liq + liquid_w/2 = x_track + w_track/2`（原版液柱是约管宽 36% 的细杆，居中悬在管身里，不塞满管身） | `constraints[].center` | 各 `x_in` | 线性等式 |
| C6 | 水平等距(plot segment) | `x_{i+1} − x_i = d`，【补遗】`d = max(gap_min, (W − 2m − w_track)/(n−1))`，【补遗·拍板】`gap_min` 默认 `0.5 in`（原 `0.3 in`）、可配，`n = 数据条数`；若 `max` 取到 `gap_min` 导致总宽超出 `W−2m`，则无解 | `layout{orient, margin, gap, gap_min}` | 各 `x_in` | 线性等式（`d` 由 `W/n` 与 `gap_min` 在预处理阶段算成常量） |
| C7 | 半圆半径随画布 | `R = min((W−2m)/2, (H−top_reserve−bottom_margin)/2)` | `layout.radius` | `cx, cy, R` | 【补遗·硬规则】`R` 在**预处理阶段算成常量**，再进线性求解；求解器不处理 `min/max` 分支，约束矩阵里不含 `min`。【审查修复】`R` 必须为标题 / 量程说明预留 `top_reserve`（由 `m+h_title+gap_title+h_note+gap_note` 派生）与 `bottom_margin`，否则扇区会压住已有文字；`top_reserve` / `bottom_margin` 同时写入 `layout`，供读回校验独立复算 |
| C8 | 扇角递推 | `α₀ = 180°`，`α_i = α_{i−1} + θ_i` | `constraints[].arc` | 各扇区 `start_angle / end_angle` | 线性递推 |
| C9 | 标签避让 | 任意两标签盒不重叠 | `constraints[].avoid_overlap` | 标签 `x/y` | **非线性 / 非凸** → 本子集不实现，降级为固定避让规则 + 重叠即 `SolveError` |

### C.2 两种图形各取哪些约束

| 图形 | 取用的约束 | 图元(marks) | 输出规格片段 |
|---|---|---|---|
| 温度计 | C1、C2(线性)、C3(温度计)、C4、C5、C6 | 管身 `rect`(圆角顶) / 液柱细杆 `rect` / 球泡 `ellipse` / 标签 `text` / 真值 `text`，外加皮肤图元 刻度 `ticks` / 外圈 `outline`，每支 7 个 | 37 个元素（2 文本 + 5×7），坐标全部由求解产出；`ticks`/`outline` 用原生 FREEFORM 形状（可编辑顶点，不是位图） |
| 半圆图 | C1、C2(两阶段)、C3(闭合)、C5、C7、C8 | 扇区形状组（每扇区独立原生形状）/ 中心数值 / 图例 | 扇区形状组 + 角度 `binding`，中心数值由 `Σv` 实时归一，禁止写死「80%」。【补遗·容量】模板参数 `max_slices = 5` 在预处理阶段硬生效：`n > max_slices` 抛 `SolveError(conflicts=["MAX_SLICES"])`，不静默画 6 个扇区。选型阶段换图 + `fallback_used` 标注仍属 GoalExplorer（本子集不实现），故此处只保证「不静默降级」 |

**线性可解**：C1、C2(温度计)、C3、C4、C5、C6、C8 → 一次线性方程组 / 不等式组求出全部坐标。
**需数据聚合预处理**：C2(半圆先算 `S` 再线性化)、C3(`ceil` 作预处理常量)、C6(`d` 含 `gap_min` 预处理)、C7(`R` 由 `min` 在预处理阶段算成常量)——【补遗·硬规则】四者都把聚合 / `min` / `ceil` 结果**当常量**喂进约束矩阵，求解器只解线性等式 / 不等式，**不处理 `min/max` 分支**；**C9 明确排除**在本子集外，不为其引入非线性求解器。
与「不一次性实现全部约束类型」一致：注册表只登记温度计、半圆图两个模板，其余 4 类（带图标进度条 / 辐射节点图 / 点位连线地图 / 双色温度计）按设计文档 B 节留条目、不实现。

---

## D. 求解器选型与集成方案

### D.1 候选对比

| 方案 | 依赖成本 | 可解释性 | 非线性支持 | 与本项目契合度 |
|---|---|---|---|---|
| ① **自写线性约束求解**（高斯消元 + 不等式可行性检查 / 最小二乘，标准库） | **零新依赖** | 最高：`a·x = b` / `≤ b` 直接可读，求解日志可写进 unittest 断言 | 不支持；但 C 节子集全可化成线性 / 两阶段线性 | 最契合 |
| ② 现成线性规划库（`scipy.optimize.linprog` / `PuLP`） | 中~重：需装包 | 中：目标函数 / 约束矩阵对业务是黑箱 | 仅线性，非线性仍不支持 | 新增依赖，收益为 0 |
| ③ Cassowary 类求解器（`kiwisolver` / `cassowary`） | 中：编译扩展，matplotlib 生态常见但仍是新增依赖 | 中：靠约束强度 / 优先级建模，不是「等式即业务规则」 | 仅线性等式 / 不等式 | 增量重解是优点，本子集不需要 |

**推荐：方案 ①**，理由：

| # | 理由 |
|---|---|
| 1 | 借鉴边界明确「不引入 Charticulator 的代码、不装它的依赖」，最小闭环也一贯「不引入新依赖」；方案 ②③ 都要新装包，与本轮克制取向冲突 |
| 2 | C 节约束子集全是线性等式 / 不等式；半圆归一化用「先聚合 `S`」、【补遗·硬规则】`min` 半径在**预处理阶段算成常量**再进线性求解（求解器不处理 `min/max` 分支），通用非线性求解器没有用武之地 |
| 3 | 可解释性直接服务项目风格：现有 31 条 unittest 靠确定性断言守「不削顶」，约束写成可读等式后，「`h_i/v_i` 恒定」「`Σθ = 180°`」「`y+h ≤ H`」都能原样变成断言 |
| 4 | 代价可接受：不处理 C9 标签避让等非凸约束，降级为固定避让 + 重叠即报错，不做静默妥协 |

### D.2 集成位置（PageSpec 生成之后、渲染之前）

| 步 | 环节 | 变化 |
|---|---|---|
| 1 | `load_points()` | 不变：只读 `chart_points`，`overrides` 仅在内存 |
| 2 | `build_pagespec()` | **改造**：选模板 → 产出带 `constraints` / `layout` / `geometry_expr` 的 `TemplateSpec`（**不含绝对坐标**） |
| 3 | **`solve(spec, data) → spec`（新增）** | 【补遗】进入线性求解前，先做一次**数据聚合预处理**（求 `V_max`、`Σv`、`n`，并按 C7 算 `R`、按 C6 算 `d`），把这些聚合结果**当常量**喂给约束矩阵；禁止把 `Σv` 写进约束矩阵变成非线性。之后建线性约束组 → 高斯消元 + 可行性检查 → 回填每个 `ElementSpec` 的 `x_in/y_in/w_in/h_in`（半圆另填角度与 `cx, cy, R`） |
| 4 | 写 `pagespec.json` | 【补遗】**原子写**：字段分工固定为 `constraints` 存约束声明、`geometry_expr` 存求解表达式、`x_in/y_in/w_in/h_in` 存求解结果（三者同时留痕，可复算、可审计） |
| 5 | `PageSpec.from_dict()` → `render_from_spec()` | 不变：保持「磁盘规格是唯一渲染源」；读回时可再跑一次约束校验（幂等，不改坐标） |

关键：求解在**写 JSON 之前**完成，`pagespec.json` 既是渲染源也是求解结果留痕；`render_from_spec()` 的既有语义不动。

### D.3 失败与回退

| 失败类型 | 处理 | 禁止行为 |
|---|---|---|
| 约束矛盾 / 无解（`n` 过大导致 `d_free < gap_min`：【补遗·拍板】`gap_min=0.5` 时 `n=20`，`d_free=(10−1−0.5)/19≈0.447 < 0.5`；`Σv = 0`、`V_max ≤ 0`、C1 不可行） | 抛 `SolveError` 并列出冲突约束编号；`pagespec.json` 不落盘（先解完再写） | 不静默降级、不改数据、不削顶、不「超阈值画满」 |
| 【补遗】`n` 过大导致总宽超界（`d` 取 `gap_min` 后 `n·d + w_track > W − 2m`）：【补遗·拍板】`n=20` 时 `d_free≈0.447 < gap_min=0.5`，`max` 取到 `gap_min` 后总宽超出 `W−2m=9.0` | 抛 `SolveError`，报冲突编号 **C1+C6** | 不静默压缩间距、不溢出画布 |
| 半圆图分项 > 5 | 按设计文档 B 节「不适用」在**选型阶段**显式换图并标 `fallback_used` | 不静默改饼图、不写死「80%」。【补充·已实现】选型逻辑不在本子集，但容量哨兵已落地：`preprocess()` 在 `n > max_slices(=5)` 时抛 `SolveError(["MAX_SLICES"])`，不落盘；`param_overrides={"max_slices": N}` 可放宽以便测其他路径 |
| 非正值 `v ≤ 0` | 沿用 `liquid_height_in()` 的物理下界守 0（不是天花板截断） | 不删数据点 |
| C9 标签避让等非凸约束 | 本子集明确不实现；固定避让规则 + 重叠检测失败即 `SolveError` | 不为它引入非线性求解器 |

---

## E. 模板解耦与可复用性验证

### E.1 TemplateSpec 结构（呼应设计文档 B 节「统一骨架 5 件套」）

| 件套 | 内容 | 是否含绝对坐标 |
|---|---|---|
| ① 参数 schema | 必填 / 可选、类型、默认值、单位（`H_track`、`R`、`m`、`g₁/g₂`、色标） | 否 |
| ② 适用数据形态 | 温度计 = 比较；半圆 = 占比 / 构成 + 反例（分项 > 5 不适用） | 否 |
| ③ 确定性硬约束 | C 节约束集 + `Scale.factor` 表达式（`h = factor·v`、`θ = 180°·v/Σv`）；禁 `min(v, 上限)` | 否 |
| ④ 输出规格片段 | 元素 `id/type/role/binding/geometry_expr/style/z-order`。【补遗】`pagespec.json` 里三者分工：`constraints` 存约束声明、`geometry_expr` 存求解表达式、`x_in/y_in/w_in/h_in` 存求解结果 | 否 |
| ⑤ 渲染适配器 | `thermometer` → 现 `render.py` 的 `rect/ellipse/text`；`semicircle` → 新增 arc 扇区适配器 | 否 |

### E.2 三条解耦能力

| 能力 | 机制 |
|---|---|
| 换数据自动重排 | `n = 数据条数` 参与 C6，【补遗】`d = max(gap_min, (W − 2m − w_track)/(n−1))` 自动收窄、触及 `gap_min` 即无解（见 D.3）；`V_max = ceil(max(v)×1.1)` 重算 `k = H_track/V_max`（半圆为 `S = Σv` 重算 `180°/S`），全组液柱 / 扇角重算。5 管变 6 管不溢出；`10.0→12.0` 时 `V_max 11→14`、液柱 `2.727→2.143 in` 由求解产出而非烘焙 |
| 换画布尺寸自动适配 | `W/H` 是求解输入，C1 / C6 / C7 让 `d`、`R`、各 `y` 全部重解；不再有 `0.8 + i*1.8`、`4.30 − h_i`、`5.40` 这类常量，`render.py` 无需改动 |
| 导出成可复用模板 | 模板 JSON 只含参数名与约束标识符；温度计与半圆图共用同一个 `solve()` 与同一套约束原语（C1 边界 / C4 相邻 / C5 居中 / C2 数据绑定），差异仅在约束集组合与渲染适配器（半圆多 C7/C8 + arc 适配器）→ 即「同一套求解逻辑供两类图形复用」 |

### E.3 可执行验收断言

| # | 断言 |
|---|---|
| 1 | **换画布**：固定 `heat_ratio_top5` 五点，把 `height_in` 由 `6.0` 改 `4.0` 后重新求解——所有元素满足 `0 ≤ y_in` 且 `y_in + h_in ≤ 4.0`；相邻组间距等于声明的 `d`；`label`/`value` 两两不重叠且不出界；渲染出的 PPTX 经 `read_shapes()` 回读，27 个形状坐标全部落在 `10.0×4.0` 画布内。【补遗】**反例**：`n=20` 时求解必须抛 `SolveError`（冲突编号 C1+C6），不能静默压缩间距或溢出画布；【补遗·拍板】`gap_min=0.5` 时 `n=5` 场景 `d=2.18`（报纸原版细管 `w_track=0.28`；原粗管 `0.5` 时为 `2.125`），不影响已交付的 `heat_ratio_top5` 产物 |
| 2 | **换数据**：`--override 1=12.0`（或换成 6 条数据）后重新求解——`scale.factor` 自动由 `3.0/11.0` 变 `3.0/14.0`（半圆由 `180°/Σv` 重算），所有液柱高度（扇角）按新 factor 重算且 `h_i/v_i` 恒定；温度计 `max(h_i) < H_track`、半圆 `Σθ_i = 180°` 仍闭合；不出现任何 `min` / `>= 10` 式削顶 |
| 3 | **模板无坐标**：导出的 `thermometer.template.json` 与 `semicircle.template.json` 中不出现任何绝对坐标字面量（`0.8`、`1.30`、`4.30`、`5.05`、`5.40`、`1.8` 等），只含约束标识符与参数名；同一个 `solve()` 分别喂两份模板都能产出合法 `PageSpec`，且半圆模板成功复用温度计的 C1/C4/C5 原语。【补遗】同一模板生成的两份 spec，`constraints` 必须相同、`x_in` 可以不同 |
| 4 | 【补遗】**半圆中心数值随数据变**：改某一个扇区数值后，中心数值必须跟着变，且恒等于 `v_center / Σv × 100%`（实时归一），禁止写死「80%」。【补遗·拍板】`v_center` 指中心数值所对应的扇区值，实现时由模板参数 `center_slice_id` 指定，不在断言里写死具体扇区 |

### E.4 已知限制（本子集不处理，明确记录以防误解）

| # | 限制 | 说明 |
|---|---|---|
| L1 | **数据链接 C2 / DATA 双写、未统一** | 设计文档称该原语为 C2，模板 `constraints` 里登记的 id 是 `DATA`，而 `SolveError.conflicts` 仍同时报 `C2`（兼容已交付测试）。三者指同一件事，但命名尚未收敛；声明一行字面量 `C2` 会被判为未知 id。 |
| L2 | **老格式路径仅做 C1 校验** | 无 `constraints` 字段的历史 `pagespec.json` 读回时只跑 C1 越界检查（向后兼容，`test_step1_models` 依赖该行为）。老规格的读回校验强度弱于新规格，不能据此认为其数值→尺寸链接已被验证。 |
| L3 | **窄画布 W<8 下图例可能重叠** | 半圆图例占据扇区左侧留白带 `w_legend = max(0.5, x_pie − m)`；画布过窄时图例与扇区在 x 上可能重叠。真正的标签避让属 C9（非线性、非凸），本子集按 C.2 / D.3 明确排除，不处理。 |
| L4 | ~~管内刻度线未渲染~~ **已在 m02273 修复** | 原限制：报纸原版细管内有等距刻度短线，本子集只声明 `color_tick`、不产出刻度图元。修复方式：新增 `ticks` / `outline` 两种图元，`_check_element_integrity` 增加 role 白名单让非数据图元不参与 seq 集合比对，元素数 27 → 37 的断言已同步；刻度与轮廓都用 PPT 原生 FREEFORM（可编辑顶点），未改 `loop/render.py`。 |
| L5 | **球泡与管身的接合靠折线近似** | 原版的锥形收口是一条光滑曲线；`ticks`/`outline` 用多段直线逼近（球环 50 段、收口 7 段二次贝塞尔采样）。放大到 400% 以上能看出轻微折角，正常阅读尺寸不可辨。真要换成真曲线需引入 `cubicBezTo` 写入 OOXML，超出本轮范围。 |
| L6 | **改版前的历史产物不保证通过最新校验** | `out/loop1/pagespec.json` 是「球心对齐管底」旧 C4 口径（27 元素、满管宽液柱、无 ticks/outline）。当前 `validate_spec` 会以 `bulb_1 top != track_1 bottom (0 point)` 拒绝它，这是**预期行为**：校验器按最新 C4 复算，不为迁就老数据放宽。该产物仍可 `PageSpec.from_dict` 读回并用 `render_pptx` 正常渲染（27 形状），但不要把它当成「符合当前约束」的样本。 |

## F. 图片图元（第五层接线，用户 m04220）

前面所有章节的图元都只有一个前提：**几何由数据驱动**（`rect` / `ellipse` / `text` / `arc` / `ticks` / `outline`）。占位图打破了这个前提——它不是数据图形，是「此处缺一个图形」的显式产物。所以这里要解释为什么允许它，以及它的边界在哪。

### F.1 为什么允许一个位图图元

`loop/render.py` 的原始约束是「禁止用图片替代任何形状」：液柱必须是 `AUTO_SHAPE` 才能被 `read_shapes()` 回读校验。判据不是「位图 vs 形状」，而是**这个元素是否本该由数据驱动几何**：

| 元素 | 有 binding | 参与约束校验 | 能否回读校验 | 判定 |
|---|---|---|---|---|
| 液柱 `liquid` | 是 | 是（C2/DATA） | 是 | 必须 `AUTO_SHAPE` |
| 占位图 `image` | 否 | 否 | 是（`shape.name`） | 允许 `PICTURE` |

占位图没有 binding、不参与任何约束校验，画成 PICTURE 不损失可编辑性以外的任何东西——而它本来就不该被编辑成几何。

### F.2 三处改动与两个「刻意不做」

| 文件 | 改动 |
|---|---|
| `loop/models.py` | `ElementSpec` 末尾新增 `image_path: str \| None = None`。**不复用 `binding`**：`binding` 载数据点 `{value,label}`，图片载文件位置，混用会让「数据链接」校验器误判图片有数据绑定。缺省 `None` 保证改版前 JSON 可读。 |
| `loop/render.py` | `_add_shape()` 新增 `image` 分支：`add_picture(path, Inches(x), Inches(y), Inches(w), Inches(h))`；缺 `image_path` 抛 `ValueError`、文件不存在抛 `FileNotFoundError`（带元素 id 与实际解析路径）；`resolve_image_path()` 把「相对项目根」解析成绝对路径；`render_pptx` 的填充段加 `el.type != "image"` 守卫（PICTURE 设 fill 会 AttributeError）。 |
| `loop/preview.py` | 同源新增 `image` 分支（`Image.open` → 缩放 → `paste`），路径解析复用 `render.resolve_image_path`，保证 PNG 与 PPTX 看到的是同一张图、同一个失败口径。 |
| `loop/pipeline.py` | `no_applicable` 分支：查 `v_fallback_assets` → `_build_fallback_spec()` 造单元素 PageSpec → `write_pagespec_atomic` → 读回 → `render_from_spec`。位置写死 `PLACEHOLDER_W_IN/H_IN = 2.2`、`PLACEHOLDER_TOP_IN = 3.0`（6 in 画布中部偏下）。 |

**刻意不做之一**：`_build_fallback_spec` 不写 `constraints`，该分支也**不走 `validate_spec`**。占位图没有模板，`validate_spec` 要基于模板跑；强行走就得给 `solve.py` 加模板豁免分支 = 改动求解逻辑，超出本轮范围。

**刻意不做之二**：`status` 仍是 `no_applicable`、`selected_template` 仍是 `None`。画占位图 ≠ 选了一个图形，状态必须如实反映「没有适用的图形模板」，否则调用方会以为选型成功。

### F.3 边界

| # | 边界 | 说明 |
|---|---|---|
| F1 | 只有一种图片图元 | `type == "image"`，不做多图轮换、不做样式变体。 |
| F2 | 位置写死 | 占位图放在版面中部偏下，不是排版决策。等版面引擎（layout_slot）做出来再替换。 |
| F3 | 占位图不进 `v_asset_search` | 正常检索（如「比较大小」）永远查不到占位图；只有 `v_fallback_assets` 能查到。 |
| F4 | 失败即报错 | `image_path` 缺失、文件不存在都抛异常，绝不静默跳过——静默跳过会让「占位图没画出来」只在预览里被发现，而调用方拿到的是「渲染成功」。 |

---

---

**一句话总结**：Charticulator 对本项目最值得借鉴的是「把数据绑定作为约束参与求解、用约束描述代替写死坐标」，让模板与数据 / 画布解耦、换数据换画布自动重排；最不该照搬的是它的交互式 UI 与通用非线性约束求解器全套——本子集约束全可线性化、项目禁新依赖，且输入只有数据 + 文本、根本没有人工拖拽布局这一环。
