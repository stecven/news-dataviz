# pagelayout.json 契约冻结（P1）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `pagelayout.json` 从「内部产物」升级成「有版本号、有 JSON Schema、Python 能读回、主题随图纸自包含」的正式契约，并把卡片内文本的折行结果写进图纸——让后续的 JS 渲染器、编辑器、CLI/MCP 插件都有一份冻结的、可对拍的目标格式。

**Architecture:** 契约的唯一机器可读定义是 `frontend/schema/pagelayout.schema.json`（JSON Schema draft 2020-12 的一个**受限子集**）。Python 侧新增 `loop/contract.py` 作为读写入口：`dump_layout()` 严格写出（校验失败抛 `ContractError`），`load_layout()` 宽松读入（老样本缺字段只给 warning，不抛）。四个已有的排版 dataclass（`PageLayoutSpec` / `PlacedCard` / `PlacedBlock` / `PlacedImage`）补齐 `from_dict` 以支持读回；`loop/models.py` 的三处新增字段一律**可空且放在 dataclass 末尾**，保证老 JSON 仍能读、老构造写法仍能用。卡片文本折行（D10）由新模块 `loop/card_text.py` 在 `flow_layout()` 里落章，折行口径复用现成的 `loop/text_flow.py::wrap()`——它是项目里唯一被两个渲染后端都认过的折行实现。**本计划不新增任何渲染能力、不改任何几何算法、不动 `loop/preview.py`。**

**Tech Stack:** Python 3.12.14（bundled `C:\Users\29642\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe`）、标准库 `json` / `unittest` / `dataclasses` / `hashlib` / `os` / `sys`。**无新依赖**（不装 `jsonschema`、不引 pytest、不需要 Node/npm）。运行环境：工作目录 `D:\appmy\news-dataviz`，shell 是 MSYS Bash（`cd /d/appmy/news-dataviz`）。

**Spec:** [docs/superpowers/specs/2026-11-12-pagespec-contract-and-js-renderer-design.md](<../specs/2026-11-12-pagespec-contract-and-js-renderer-design.md>)（用户 2026-11-12 已批准；执行者须先通读 §3 约束、§4 决定、§5 契约规格、§9 分期、§11 边界澄清）。

## Scope Check

Spec §9 定了七个阶段：P1 契约冻结 · P2 只读渲染 · P3 编辑 · P4 CLI+MCP · P5 素材导出 · P6(v2) chart+ECharts · P7(v2) draw.io。

**本计划只做 P1。** P2–P7 各自另写一份计划，原因有两条：

1. **P1 是接口，P2 之后都是它的消费者。** 契约定死之前写渲染器，等于用一份还会变的格式写代码；定死之后，每一份后续计划都能拿 `tests/fixtures/contract/` 里的真实夹具对拍，返工最少。
2. **P1 是唯一一处动 `loop/` 的阶段。** `CONTRIBUTING.md` 要求「一个 PR 只做一件事」，而 P1 之外的阶段只新增 `frontend/` 文件、不碰引擎，回报率更高——把它们和 P1 混在一个 PR 里会让评审看不出哪一处动了引擎。

**P1 结束时应该发生的事**：契约文件存在且被两侧校验；`pagelayout.json` 带 `version: "1.0"` 和自包含的 `theme`；卡片内每个文本元素带 `lines` / `font_pt`；Python 能把图纸读回成对象；11 份历史样本的几何数字**一个字节没变**；`python -m unittest discover -s tests -t . -q` 从 676 涨到 718 全绿。

## Global Constraints

- **既存 676 个 unittest 不许挂。** 基线实测：`cd /d/appmy/news-dataviz && python -m unittest discover -s tests -t . -q` → `Ran 676 tests in 33.194s` / `OK`。每个 Task 结束都要它全绿。
- **新增字段一律可空、且放在 dataclass 末尾。** 依据 `loop/models.py:35` 的注释「新增字段一律放在末尾，避免破坏既有按位置构造的 ElementSpec(...)」与 Spec §3 C4。老 `pagespec.json` / `pagelayout.json` 必须仍能 `from_dict` 读回。
- **不改变任何已存在样本的几何数字。** `x_in` / `y_in` / `w_in` / `h_in`，含卡片内相对坐标与 `geometry` 里的 `cx` / `cy` / `cap_top` / `tube_bottom`，以及 `arc` 的 `start_angle` / `end_angle`。Task 1 捕获的几何指纹是这条约束的判据；Task 7 用重新生成的产物复判。
- **单位一律英寸、契约里不引入 px**（Spec §3 C1）。卡片内元素坐标**相对卡片左上角**（Spec §3 C2），本计划不得改变这一点。
- **契约必须后端无关**（Spec §3 C3）：图纸里不许出现 ECharts option、draw.io XML、PPTX 形状 XML。
- **颜色与字号只有一个来源 `loop/palette.py`**（`frontend/README.md` 铁律 1、`CONTRIBUTING.md` §六）。本计划不许在 `loop/` 里新增十六进制色值或写死字号。
- **目录所有权**（Spec §3 C6）：本计划只许改 `loop/`、`tests/`，只许新建 `frontend/schema/` 与 `frontend/README.md` 的一节。**不许碰** `ingest/`、`assets/`、`db/`、`scripts/`（含新增文件）、`CONTRIBUTING.md`、`.gitignore`、`.gitattributes`、`.github/`。
- **产物只写 `out/`（已 gitignore）与 `tests/fixtures/`。** 不许提交 `out/`、`db/*.bak*`、`.dev-keys/`、`scratch/`。
- **git 纪律**：分支 `frontend/pagespec-contract`（已存在，含设计文档提交 `1797572`）。`main` 已加保护、只能经 Pull Request 合入；本机**没有 `gh` CLI**，PR 需用户自己在网页开：https://github.com/stecven/news-dataviz/pull/new/frontend/pagespec-contract 。本计划**继续用这个分支**（理由与风险见下方「已知偏差」）。
- **验收标准映射**：本计划覆盖 Spec §7 的 **V4**（676→718 全绿，每个 Task）、**V5**（Task 6）、**V6**（Task 6）。**V1 / V2 / V3 不在本计划**——它们要等 P2 有 JS 渲染器才能跑。

### 已知偏差（执行者须知，不要"顺手修正"）

1. **Spec §6 的文件结构表里没有 `frontend/schema/`。** 本计划把契约 schema 放在那儿，因为它是 JS 包的一部分（P2 起由 `frontend/package.json` 发布）、同时被 Python 按路径读取。这是 Spec 的细化而非违背；执行者在 PR 描述里点明这一处。
2. **Spec §4 D10 说"顺带修掉 PNG/PPTX 折行不一致的老问题"。** 本计划只做前半截（把 `lines` 写进契约），**不改 `loop/preview.py`**。理由：让预览层改吃 `lines` 会动到 PNG 像素输出，而像素对拍（V2）要等 P2 才有渲染器做对照；把它拆进 P1 等于在没有对照的日子里改动输出。P2 的 Task 里再切换。
3. **沿用未合的 `frontend/pagespec-contract` 分支。** `CONTRIBUTING.md` 说「一个 PR 只做一件事」，但设计文档（提交 `1797572`）尚未合并，而它就是本计划代码的 Spec——分叉开分支会让 PR 的 base 指向另一个未合并分支。因此本 PR 描述写成「冻结 pagelayout.json 契约：设计文档 + P1 实现」。若用户要求拆成两个 PR，执行者应停下询问，不要自行决定。

## File Structure

| 文件 | 职责 |
|---|---|
| `frontend/schema/pagelayout.schema.json` | **新建**。契约的唯一机器可读定义（draft 2020-12 受限子集）。JS 侧 P2 直接 `import`，Python 侧按路径读。 |
| `loop/schema_check.py` | **新建**。受限子集校验器：`validate_doc()` 返回带 JSON Pointer 式路径的错误列表；`unsupported_keywords()` 防止 schema 用到校验器不认识的关键字。 |
| `loop/contract.py` | **新建**。读写入口：`CONTRACT_VERSION`、`ContractError`、`ReadResult`、`load_layout()` / `load_layout_json()` / `dump_layout()` / `write_layout_atomic()`。 |
| `loop/card_text.py` | **新建**。D10：把卡片内 `type == "text"` 元素的折行与字号写进契约；唯一的折行调用点。 |
| `loop/layout.py` | **改**。`PageLayoutSpec` 加 `version` / `theme`（末尾、可空）；`PageLayoutSpec` / `PlacedCard` / `PlacedBlock` / `PlacedImage` 补 `from_dict`；`to_dict()` 补两个新键；`flow_layout()` 构造 `PlacedCard` 时接一行 `card_text.annotate_card_text()`。 |
| `loop/models.py` | **改**。`ElementSpec` 末尾加 `lines` / `font_pt` / `editable`；`PageSpec` 末尾加 `chart`，并让 `from_dict` 接住它。 |
| `loop/palette.py` | **不动**。`summary()`（:283）已经是 D11 要的产物。 |
| `frontend/README.md` | **改**。加一节「契约在哪、谁校验」，指向 `frontend/schema/pagelayout.schema.json`。 |
| `tests/contract_fixtures.py` | **新建**。夹具定位、几何指纹、基线生成器（`python -m tests.contract_fixtures --write-baseline`）。非 `test*.py`，不被 discover 收集。 |
| `tests/fixtures/contract/legacy/*.json` | **新建**。2 份完整老样本（`auto_layout.pagelayout.json` 45899 B、`_plain.pagelayout.json` 2681 B）。 |
| `tests/fixtures/contract/legacy_fingerprints.json` | **新建**。11 份老样本的几何指纹基线。 |
| `tests/test_step31_contract_fixtures.py` | Task 1 测试 |
| `tests/test_step32_schema_check.py` | Task 2 测试 |
| `tests/test_step33_contract_read.py` | Task 3 测试 |
| `tests/test_step34_contract_write.py` | Task 4 测试 |
| `tests/test_step35_card_text.py` | Task 5 测试 |
| `tests/test_step36_contract_guards.py` | Task 6 测试 |
| `tests/test_step37_contract_delivery.py` | Task 7 测试 |

## Review Focus

> Spec 是愿景文档，没写到的输入不等于可以崩。以下 6 类最可能咬人，每一条都已经把测试钉进所属 Task——**执行者发现某条测试写不出来或写出来是红的，要停下报告，不许改测试去迁就实现**。

1. **老样本缺键，而且是各种缺法。** 11 份样本里 `version` **全都是 `None`**；`images` 键在 `auto_layout`、`auto_layout/_plain`、`multicol`、`multicol/_spread`、`page`、`paper` 六份里**根本不存在**（连 `[]` 都不是）。所以 `load_layout_json()` 与 `PageLayoutSpec.from_dict()` 必须用 `d.get("images", [])`，不能 `d["images"]`。钉在 Task 3 `test_legacy_plain_layout_reads_without_raising`、Task 1 `test_legacy_fixture_documents_are_readable_json_and_versionless`。
2. **`ElementSpec(**e)` 遇到未知键会抛 `TypeError`。** `loop/models.py:75` 的 `from_dict` 用的是 `ElementSpec(**e)`——一份带未来字段的图纸会直接炸。读入口必须**显式挑已知键**，未知键降级成 warning。钉在 Task 3 `test_unknown_element_key_becomes_warning_not_crash`。
3. **卡片文本折行口径漂移。** `loop/preview.py::_draw_text`（:132）自己写了一个逐字折行循环，`loop/fit.py::_wrap_lines`（:182）也写了一个（docstring 自称「与 `preview._draw_text` 同口径」）。契约里的 `lines` 走的是 `text_flow.wrap()` → `fit._wrap_lines`，**必须与 `preview._draw_text` 在真实样本上输出完全相同的行列表**。Task 5 用真实卡片元素逐个比对；有任何一条不等就停下报告，**不许"顺手统一"**。
4. **`lines` 是完整折行结果，不是截断后的 4 行。** `preview._draw_text` 只画 `lines[:4]`（:164，注释「盒高最多容 4 行，多余裁掉」），那是**绘制**时的裁剪，不该被写进契约。契约里的 `lines` 写全量，`font_pt` 必须等于 `palette.scaled_font_size(el.role, scale)`。钉在 Task 5 `test_lines_are_not_truncated_to_four`。
5. **schema 与 dataclass 漂移。** schema 是契约的第二份独立描述；它唯一的价值就是「和 `loop/models.py` 说的不一样时报警」。Task 2 的白名单测试防止 schema 用到校验器不支持的关键字；Task 4 的 `test_dump_layout_output_passes_strict_schema` 防止「dataclass 加了字段、schema 没加」。两条缺一不可。
6. **几何被"顺手"平移或取整。** `loop/layout.py:853 flatten()`（:865-879）会把卡片内相对坐标平移成页面绝对坐标并记 `_scale`——那是**渲染视图**，不是契约。`pagelayout.json` 里卡片内元素必须仍是相对坐标（实测卡片 `frame` 元素在 `(0.0, 0.0)`）。读回时**不要**反向平移、**不要**重新取整到别的位数。钉在 Task 3 `test_geometry_is_not_translated_on_read`、Task 1 `test_fingerprint_matches_baseline_for_every_document`。

---

### Task 1: 老样本几何指纹基线（**必须先于任何代码改动做**）

**为什么是第一个**：Task 3/4/5 都会碰 `loop/`。一旦代码改了，`out/demo/` 里现存的 11 份 `pagelayout.json` 就不再是「改动前」的证据了。先把它们的几何指纹钉进 git，后面才有判据。

**Files:**
- Create: `tests/contract_fixtures.py`
- Create: `tests/fixtures/contract/legacy/auto_layout.pagelayout.json`（从 `out/demo/auto_layout/pagelayout.json` 复制，45899 字节）
- Create: `tests/fixtures/contract/legacy/_plain.pagelayout.json`（从 `out/demo/auto_layout/_plain/pagelayout.json` 复制，2681 字节）
- Create: `tests/fixtures/contract/legacy_fingerprints.json`
- Test: `tests/test_step31_contract_fixtures.py`

**Interfaces:**
- Consumes: `out/demo/**/pagelayout.json`（11 份，实测路径见 Step 4 的清单）
- Produces:
  - `tests/contract_fixtures.py`:
    - `REPO_ROOT: str` — 仓库根绝对路径（由 `__file__` 上溯两级）
    - `LEGACY_DIR: str` — `<REPO_ROOT>/tests/fixtures/contract/legacy`
    - `BASELINE_PATH: str` — `<REPO_ROOT>/tests/fixtures/contract/legacy_fingerprints.json`
    - `DEMO_ROOT: str` — `<REPO_ROOT>/out/demo`
    - `demo_layout_paths() -> list[str]` — 排序后的、相对仓库根的 `out/demo/**/pagelayout.json` 路径；`out/demo` 不存在时返回 `[]`
    - `geometry_fingerprint(doc: dict) -> dict` — **只**看几何（算法见 Step 4）
    - `fingerprint_sha(doc: dict) -> str` — `geometry_fingerprint` 规范化序列化后的 sha256
    - `load_baseline() -> dict` — 读 `legacy_fingerprints.json`
    - `__main__` 入口：`python -m tests.contract_fixtures --write-baseline` 重算并写回基线

- [ ] **Step 1: 写 `tests/contract_fixtures.py` 的骨架与指纹函数**

指纹只收几何，**故意忽略** `version` / `theme` / `lines` / `font_pt` / `editable` / `chart` 这些"外观与元数据"，因为本计划正是要新增它们——它们的增减不该让指纹变化，而几何一动就必须变。

```python
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
    payload = json.dumps(geometry_fingerprint(doc), sort_keys=True,
                         ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

> 注意 `blocks` 里带了 `lines`：整版文本块的折行**本来就是契约的一部分**（`loop/layout.py:887` 早就写进 `geometry["lines"]`），它的变化会让整版高度变化，属于几何。卡片内文本的 `lines` 则**不**进指纹（新字段）。

- [ ] **Step 2: 写失败测试 `tests/test_step31_contract_fixtures.py`**

测试用例与断言（按此顺序写，共 **5** 个 test method）：

| 测试名 | 断言 |
|---|---|
| `test_fingerprint_is_deterministic` | 同一 `doc` 调两次 `fingerprint_sha` 相等 |
| `test_fingerprint_ignores_presentation_fields` | 复制夹具 doc，塞入 `version="1.0"`、`theme={"palette":{}}`、并给每个元素加 `lines=["x"]`/`font_pt=9.0`/`editable=True` → 指纹 **不变**；再把某个 `x_in` 加 `1e-9` 并 `round(...,6)` 成不同的值 → 指纹 **改变** |
| `test_baseline_covers_every_demo_layout` | `set(load_baseline()) == set(demo_layout_paths())`；`out/demo` 缺失时 `self.skipTest("out/demo 未生成")` |
| `test_fingerprint_matches_baseline_for_every_document` | 逐个读盘上文档，`fingerprint_sha(doc) == baseline[path]["sha256"]`；`out/demo` 缺失时 skip。**这是「几何一个字节没变」的直接判据** |
| `test_legacy_fixture_documents_are_readable_json_and_versionless` | 两份夹具 `json.load` 成功；两份 `doc.get("version") is None`；`_plain` 那份 `"images" not in doc`；`auto_layout` 那份 `len(doc["cards"]) == 2`、`len(doc["blocks"]) == 4` |

- [ ] **Step 3: 跑它，确认是红的**

```bash
cd /d/appmy/news-dataviz && python -m unittest tests.test_step31_contract_fixtures -v
```

预期：`ModuleNotFoundError: No module named 'tests.contract_fixtures'`（或夹具缺失导致的 `FileNotFoundError`）。**必须是失败**——如果它过了，说明测试没有真的在检查东西。

- [ ] **Step 4: 生成夹具与基线**

先复制两份完整老样本（用 `cp`，不要手抄）：

```bash
cd /d/appmy/news-dataviz
mkdir -p tests/fixtures/contract/legacy
cp out/demo/auto_layout/pagelayout.json tests/fixtures/contract/legacy/auto_layout.pagelayout.json
cp out/demo/auto_layout/_plain/pagelayout.json tests/fixtures/contract/legacy/_plain.pagelayout.json
ls -l tests/fixtures/contract/legacy/
```

预期：`45899` 与 `2681` 两个字节数对上。

再跑基线生成器（它同时充当 `demo_layout_paths()` 的自检）：

```bash
cd /d/appmy/news-dataviz && python -m tests.contract_fixtures --write-baseline
```

预期 stdout 逐行打印 11 个路径，最后一行 `wrote 11 fingerprints`。基线里应该正好是这 11 个键（实测清单，按路径排序）：

```
out/demo/auto_layout/_plain/pagelayout.json         2681 B
out/demo/auto_layout/pagelayout.json               45899 B
out/demo/illustrated/_no_asset/pagelayout.json     45475 B
out/demo/illustrated/_spread/pagelayout.json       45666 B
out/demo/illustrated/pagelayout.json               47119 B
out/demo/multicol/_spread/pagelayout.json          49824 B
out/demo/multicol/pagelayout.json                  45353 B
out/demo/page/pagelayout.json                      45063 B
out/demo/paper/pagelayout.json                     49463 B
out/demo/theme_match/_no_theme/pagelayout.json     30832 B
out/demo/theme_match/pagelayout.json               46919 B
```

- [ ] **Step 5: 跑测试，确认是绿的**

```bash
cd /d/appmy/news-dataviz && python -m unittest tests.test_step31_contract_fixtures -v
```

预期：`Ran 5 tests` / `OK`。

- [ ] **Step 6: 跑全量，记录新基线**

```bash
cd /d/appmy/news-dataviz && python -m unittest discover -s tests -t . -q
```

预期：`Ran 681 tests` / `OK`（676 + 5）。

- [ ] **Step 7: 提交**

```bash
cd /d/appmy/news-dataviz
git add tests/contract_fixtures.py tests/fixtures/contract tests/test_step31_contract_fixtures.py
git commit -m "test: 冻结 11 份老 pagelayout 样本的几何指纹基线（P1 Task 1）"
```

---

### Task 2: 契约 schema + 受限子集校验器

**Files:**
- Create: `frontend/schema/pagelayout.schema.json`
- Create: `loop/schema_check.py`
- Test: `tests/test_step32_schema_check.py`

**Interfaces:**
- Produces:
  - `loop/schema_check.py`:
    - `SUPPORTED_KEYWORDS: frozenset[str]` = `{"$schema", "$id", "$defs", "$ref", "title", "description", "type", "properties", "required", "additionalProperties", "items", "enum", "minimum", "maximum", "default"}`
    - `SCHEMA_PATH: str` — `<repo>/frontend/schema/pagelayout.schema.json`（由 `__file__` 上溯两级；`loop/` 与 `frontend/` 是兄弟目录）
    - `load_schema() -> dict`
    - `unsupported_keywords(schema: dict) -> list[str]` — 返回 schema 里出现的、不在 `SUPPORTED_KEYWORDS` 里的**关键字**，元素形如 `"$.properties.cards.$ref"`；无则 `[]`
    - `validate_doc(doc: dict, schema: dict | None = None) -> list[dict]` — 每个错误 `{"path": "$.cards[0].spec.elements[3].x_in", "message": "expected number, got str"}`；无错返回 `[]`
  - `frontend/schema/pagelayout.schema.json`:
    - 顶层 `"$schema": "https://json-schema.org/draft/2020-12/schema"`
    - 顶层 `required`: `["version","theme","width_in","height_in","margin_in","gutter_in","column_count","column_gutter_in","rows","cards","blocks","images"]`
    - 顶层 `properties`: 除上述外还含 `"$defs"` 用不到的元信息键可省；`version` 类型 `["string","null"]`、`theme` 类型 `["object","null"]`
    - `$defs`: `page`（= PageSpec，供卡片内 `spec` 复用）、`element`、`card`、`block`、`image`、`row`
    - `$defs.element.properties.type` 用 `{"enum": ["rect","ellipse","arc","text","ticks","outline","image","chart"]}`（Spec §5.5 的 7+1 图元词汇表）
    - `$defs.element.required`: `["id","type","role","x_in","y_in","w_in","h_in"]`
    - `$defs.element.properties.geometry` 用 `{"type": ["object","null"]}`（**故意宽松**：各图元的 geometry 键由 Spec §5.5 与渲染器定义，不在这份 schema 里做 `oneOf` 分支——那会让 schema 与校验器都膨胀到没人维护）
    - 顶层**不设** `additionalProperties: false`；只在 `$defs.element` 与 `$defs.card` / `$defs.block` / `$defs.image` 上设 `additionalProperties: false`

- [ ] **Step 1: 写 `frontend/schema/pagelayout.schema.json`**

按上面的 Interfaces 逐条落。**关键取舍**：`element` 只硬卡 `id/type/role/x_in/y_in/w_in/h_in`，`geometry` 一律放行。理由写进文件的 `description`：图元几何的权威定义在 Spec §5.5 与 `loop/thermo_shape.py`、`loop/scaffold.py`，schema 的职责是卡"结构"而不是复述"几何语义"——复述就会漂移。

- [ ] **Step 2: 写失败测试 `tests/test_step32_schema_check.py`**

共 **7** 个 test method。测试自带一份最小合法文档构造函数 `_minimal_doc()`（约 30 行），不要从 `out/demo` 读——这份测试必须能在没有 `out/` 的克隆里跑。

| 测试名 | 断言 |
|---|---|
| `test_schema_uses_only_supported_keywords` | `unsupported_keywords(load_schema()) == []` |
| `test_minimal_valid_document_has_no_errors` | `validate_doc(_minimal_doc()) == []` |
| `test_element_level_path_is_reported` | 把 `$.cards[0].spec.elements[1].x_in` 改成字符串 `"0.4"` → `len(errors) == 1` 且 `errors[0]["path"] == "$.cards[0].spec.elements[1].x_in"` |
| `test_missing_required_top_level_key_is_reported` | 删掉 `images` → 恰好 1 条错误，`errors[0]["path"] == "$.images"` |
| `test_unknown_element_type_is_rejected` | `type = "donut"` → 错误路径含 `$.cards[0].spec.elements[0].type` |
| `test_unknown_key_rejected_only_where_additional_properties_is_false` | 元素里加 `"bogus": 1` → 报错；顶层加 `"bogus": 1` → **不**报错 |
| `test_legacy_document_fails_strict_schema` | 对夹具 `_plain.pagelayout.json` 跑 `validate_doc` → 错误非空，且**含** `"$.version"` 与 `"$.images"` 两条路径。这条把 Spec §7 V5「历史样本今天全红」编码成了可执行断言 |

- [ ] **Step 3: 跑它，确认是红的**

```bash
cd /d/appmy/news-dataviz && python -m unittest tests.test_step32_schema_check -v
```

预期：`ModuleNotFoundError: No module named 'loop.schema_check'`。

- [ ] **Step 4: 实现 `loop/schema_check.py`**

核心递归（这是本 Task 唯一的算法代码块，其余是 `os` / `json` / `frozenset` 的包装）：

```python
def _check(node, schema, root, path, errors):
    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/$defs/"):
            errors.append({"path": path, "message": f"unsupported $ref: {ref}"})
            return
        return _check(node, root["$defs"][ref[len("#/$defs/"):]], root, path, errors)

    if "type" in schema:
        allowed = schema["type"]
        allowed = allowed if isinstance(allowed, list) else [allowed]
        if not any(_is_type(node, t) for t in allowed):
            errors.append({"path": path,
                           "message": f"expected {' | '.join(allowed)}, got {_kind(node)}"})
            return                      # 类型不对就不再往下探，避免报一串无关错误

    if "enum" in schema and not any(node == v for v in schema["enum"]):
        errors.append({"path": path, "message": f"expected one of {schema['enum']!r}"})

    if isinstance(node, (int, float)) and not isinstance(node, bool):
        if "minimum" in schema and node < schema["minimum"]:
            errors.append({"path": path, "message": f"< minimum {schema['minimum']}"})
        if "maximum" in schema and node > schema["maximum"]:
            errors.append({"path": path, "message": f"> maximum {schema['maximum']}"})

    if isinstance(node, dict):
        for key in schema.get("required", []):
            if key not in node:
                errors.append({"path": f"{path}.{key}", "message": "required key is missing"})
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in node:
                if key not in props:
                    errors.append({"path": f"{path}.{key}", "message": "unknown key"})
        for key, sub in props.items():
            if key in node:
                _check(node[key], sub, root, f"{path}.{key}", errors)

    if isinstance(node, list) and "items" in schema:
        for i, item in enumerate(node):
            _check(item, schema["items"], root, f"{path}[{i}]", errors)


def _is_type(v, t):
    if t == "object":  return isinstance(v, dict)
    if t == "array":   return isinstance(v, list)
    if t == "integer": return isinstance(v, int) and not isinstance(v, bool)
    if t == "number":  return isinstance(v, (int, float)) and not isinstance(v, bool)
    if t == "string":  return isinstance(v, str)
    if t == "boolean": return isinstance(v, bool)
    if t == "null":    return v is None
    return False
```

`unsupported_keywords()` 走另一条递归，**必须区分"关键字位"和"属性名位"**：在 `properties` / `$defs` 底下，键是名字不是关键字：

```python
_NAME_SLOTS = ("properties", "$defs")

def unsupported_keywords(schema, path="$"):
    bad = []
    if isinstance(schema, dict):
        for key, value in schema.items():
            if path.endswith(".properties") or path.endswith(".$defs"):
                child_path = f"{path}.{key}"          # key 是名字，跳过白名单检查
            else:
                child_path = f"{path}.{key}"
                if key not in SUPPORTED_KEYWORDS:
                    bad.append(child_path)
            bad.extend(unsupported_keywords(value, child_path))
    elif isinstance(schema, list):
        for i, item in enumerate(schema):
            bad.extend(unsupported_keywords(item, f"{path}[{i}]"))
    return bad
```

- [ ] **Step 5: 跑测试，确认是绿的**

```bash
cd /d/appmy/news-dataviz && python -m unittest tests.test_step32_schema_check -v
```

预期：`Ran 7 tests` / `OK`。

- [ ] **Step 6: 跑全量**

```bash
cd /d/appmy/news-dataviz && python -m unittest discover -s tests -t . -q
```

预期：`Ran 692 tests` / `OK`。

- [ ] **Step 7: 提交**

```bash
cd /d/appmy/news-dataviz
git add frontend/schema/pagelayout.schema.json loop/schema_check.py tests/test_step32_schema_check.py
git commit -m "feat(contract): pagelayout.json 的 JSON Schema 与受限子集校验器（P1 Task 2）"
```

---

### Task 3: 读回入口（宽松）+ 四个 `from_dict`

**Files:**
- Create: `loop/contract.py`
- Modify: `loop/layout.py`
- Test: `tests/test_step33_contract_read.py`

**Interfaces:**
- Consumes: `loop.layout.PageLayoutSpec`（:401）、`PlacedCard`（:304）、`PlacedBlock`（:242）、`PlacedImage`（:275）、`CardSpec`（:124）；`loop.models.PageSpec.from_dict`（`models.py:68`）、`ElementSpec`、`Scale`；`tests/contract_fixtures.py`
- Produces:
  - `loop/layout.py` 改动：
    - `PlacedCard.from_dict(d) -> PlacedCard`、`PlacedBlock.from_dict(d)`、`PlacedImage.from_dict(d)`、`PageLayoutSpec.from_dict(d)`
    - `PageLayoutSpec` 末尾加 `version: str | None = None`、`theme: dict | None = None`（**Task 4 才写进 `to_dict`**，本 Task 只加字段与 `from_dict` 的接住逻辑）
  - `loop/contract.py`:
    - `CONTRACT_VERSION = "1.0"`
    - `class ContractError(ValueError)` — 写出侧校验失败
    - `@dataclass class ReadResult: layout: PageLayoutSpec; warnings: list[str]; version: str | None`
    - `load_layout_json(doc: dict) -> ReadResult`
    - `load_layout(path: str) -> ReadResult`
    - `_element_from_dict(d: dict, where: str, warnings: list[str]) -> ElementSpec` — **显式挑已知键**（`id type role x_in y_in w_in h_in fill text binding geometry_expr geometry image_path`），未知键追加 `f"{where}: 忽略未知键 {key!r}"` 到 warnings
    - `_spec_from_dict(d: dict, where: str, warnings: list[str]) -> PageSpec` — 用 `_element_from_dict` 处理 `elements`，其余键交给 `PageSpec.from_dict` 的等价逻辑（**不要**直接 `PageSpec.from_dict`，因为它的 `ElementSpec(**e)` 会抛）

`load_layout_json` 的宽松口径（照 Spec §5.6「version 可选、缺省按 0.x 宽松读」）：

```python
def load_layout_json(doc: dict) -> ReadResult:
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
    layout = PageLayoutSpec.from_dict(doc)      # 缺键靠 dataclass 默认值兜底
    return ReadResult(layout=layout, warnings=warnings, version=version)
```

- [ ] **Step 1: 写失败测试 `tests/test_step33_contract_read.py`**

共 **6** 个 test method：

| 测试名 | 断言 |
|---|---|
| `test_legacy_plain_layout_reads_without_raising` | `load_layout(LEGACY_DIR + "/_plain.pagelayout.json")` 不抛；`result.version is None`；`any("images" in w for w in result.warnings)` 且 `any("version" in w for w in result.warnings)` |
| `test_legacy_auto_layout_reads_all_cards_and_blocks` | cards `2`、blocks `4`；每张卡片的 `spec.elements` 非空；卡片 `heat_ratio_top5` 的 `kind == "thermometer"` 且 `w_in == 8.937504` |
| `test_roundtrip_superset_and_idempotent` | 两份夹具各一次：`d1 = PageLayoutSpec.from_dict(d).to_dict()`；对 `d` 中出现的**每个**键，`d1` 递归等值（写个 `_assert_superset(sub, sup, path)` helper）；再 `PageLayoutSpec.from_dict(d1).to_dict() == d1` 严格成立 |
| `test_new_nullable_keys_present_with_none` | `d1["version"] is None`；`d1` 的每张卡片的每个元素都有 `lines` / `font_pt` / `editable` 三键且值为 `None` |
| `test_unknown_element_key_becomes_warning_not_crash` | 往 `cards[0].spec.elements[0]` 塞 `{"beep": 1}` → 读成功，且 `any("beep" in w for w in result.warnings)` |
| `test_geometry_is_not_translated_on_read` | 读回 `auto_layout` 后：卡片 `heat_ratio_top5` 的 `x_in == 0.4`、`y_in == 2.3875`；该卡片内 `role == "frame"` 的元素仍是 `x_in == 0.0`、`y_in == 0.0`；全库最小 `x_in` **不是** 0.4（证明没有做页面级平移） |

- [ ] **Step 2: 跑它，确认是红的**

```bash
cd /d/appmy/news-dataviz && python -m unittest tests.test_step33_contract_read -v
```

预期：`ModuleNotFoundError: No module named 'loop.contract'`。

- [ ] **Step 3: 给 `loop/layout.py` 的四个 dataclass 补 `from_dict`**

先读现状：`PlacedBlock.to_dict()`（:262）、`PlacedImage.to_dict()`（:295，末尾 `"rect": list(self.rect)`，:300）、`PlacedCard.to_dict()`（:319，`"spec": self.spec.to_dict()`，:324）、`PageLayoutSpec.to_dict()`（:415）。`from_dict` 必须是各自 `to_dict` 的**左逆**——`PlacedBlock` 要从扁平 dict 重建 `TextBlock`，`PlacedImage` 要从扁平 dict 重建 `ImageBlock`，**先读这两个 block 类的构造签名再动手**，不要猜。

`PageLayoutSpec.from_dict` 里卡片用 `PlacedCard.from_dict`（它会调 `_spec_from_dict`），**不能**直接把 dict 丢给 `PageSpec.from_dict`。为避免 `loop/contract.py` 与 `loop/layout.py` 循环导入，`_element_from_dict` / `_spec_from_dict` 放在 `loop/layout.py` 里作为模块级函数，`loop/contract.py` 只 import 它们。

- [ ] **Step 4: 实现 `loop/contract.py` 的读入口**

按上面的 Interfaces 落。`load_layout(path)` 就是 `json.load` + `load_layout_json`。

- [ ] **Step 5: 跑测试，确认是绿的**

```bash
cd /d/appmy/news-dataviz && python -m unittest tests.test_step33_contract_read -v
```

预期：`Ran 6 tests` / `OK`。

- [ ] **Step 6: 跑全量**

```bash
cd /d/appmy/news-dataviz && python -m unittest discover -s tests -t . -q
```

预期：`Ran 698 tests` / `OK`。**这一关是"没动几何"的第一道自动判据**——Task 1 的指纹测试如果变红，说明 `PlacedBlock` / `PageSpec` 的 `to_dict` 被动过了，立刻回退。

- [ ] **Step 7: 提交**

```bash
cd /d/appmy/news-dataviz
git add loop/contract.py loop/layout.py tests/test_step33_contract_read.py
git commit -m "feat(contract): pagelayout.json 读回入口 + 四个 from_dict（P1 Task 3）"
```

---

### Task 4: 主题与图表字段 + 严格写出

**Files:**
- Modify: `loop/models.py`
- Modify: `loop/layout.py`
- Modify: `loop/contract.py`
- Test: `tests/test_step34_contract_write.py`

**Interfaces:**
- Consumes: `loop.palette.summary()`（`palette.py:283`）、`loop.schema_check.validate_doc`
- Produces:
  - `loop/models.py`：
    - `ElementSpec` **末尾**加 `lines: list | None = None`、`font_pt: float | None = None`、`editable: bool | None = None`
    - `PageSpec` **末尾**加 `chart: dict | None = None`，并在 `PageSpec.from_dict` 里加 `chart=d.get("chart")`
  - `loop/layout.py`：`PageLayoutSpec.to_dict()` 补 `"version": self.version`、`"theme": self.theme`；`PageLayoutSpec` 字段顺序变为 `..., images, version, theme`（**两个新键必须在末尾**，老 plan 里 `cards` / `rows` 等按位置的构造不受影响）
  - `loop/contract.py`：
    - `dump_layout(layout: PageLayoutSpec) -> dict` — 缺 `version` 填 `CONTRACT_VERSION`、缺 `theme` 填 `palette.summary()`；先 `validate_doc`，有错抛 `ContractError`，消息里带**前 5 条**错误路径
    - `write_layout_atomic(path: str, doc: dict) -> None` — 与 `loop/build_loop.py::write_pagespec_atomic`（:21）同语义：写 `<path>.tmp` → `os.replace`；任何失败清 `.tmp` 并原样抛

  > **为什么不去 import `write_pagespec_atomic`**：`loop/build_loop.py` 顶部 import 了 `loop.render*`（python-pptx）与 `loop.preview`（Pillow）。契约层是纯数据模块，不该为了 8 行原子写把渲染依赖拖进来。复制这 8 行，并在 docstring 里注明原版位置与"两处必须同步"。

- [ ] **Step 1: 写失败测试 `tests/test_step34_contract_write.py`**

共 **6** 个 test method：

| 测试名 | 断言 |
|---|---|
| `test_dump_layout_fills_version_and_theme` | 读夹具 → `dump_layout` → `doc["version"] == "1.0"`；`doc["theme"]["role_to_font"]["value"] == "body"`；`doc["theme"]["font_sizes"]["title"] == 20`；`doc["theme"]["font_pt_clamp"] == [6.0, 24.0]`；`doc["theme"]["base_canvas_in"] == [10.0, 6.0]` |
| `test_dump_layout_output_passes_strict_schema` | 两份夹具各读→`dump_layout`→`validate_doc(doc) == []`。**这是 schema ↔ dataclass 不漂移的判据**（Review Focus #5） |
| `test_dump_layout_raises_contract_error_with_element_path` | 手工构造一份 `PageLayoutSpec`，把某卡片元素 `x_in` 设成 `"x"` → `dump_layout` 抛 `ContractError`，消息含 `$.cards[0].spec.elements[0].x_in` |
| `test_write_layout_atomic_leaves_no_tmp_on_failure` | 传一份含不可序列化对象（`object()`）的 doc → 抛错；断言 `<path>.tmp` 不存在；断言已存在的目标文件字节 **不变** |
| `test_new_fields_default_to_none_and_models_construction_is_backward_compatible` | `ElementSpec("a","rect","liquid",0,0,1,1)` 仍可构造；`ElementSpec` 三个新字段默认 `None`；`PageSpec.from_dict` 能接住 `chart={"kind":"thermometer"}` 并读回 |
| `test_new_fields_are_last_in_dataclass` | `[f.name for f in fields(ElementSpec)][-3:] == ["lines","font_pt","editable"]`；`[f.name for f in fields(PageSpec)][-1] == "chart"`；`[f.name for f in fields(PageLayoutSpec)][-2:] == ["version","theme"]`。这条把 `loop/models.py:35` 的注释变成可执行约束 |

- [ ] **Step 2: 跑它，确认是红的**

```bash
cd /d/appmy/news-dataviz && python -m unittest tests.test_step34_contract_write -v
```

预期：`ImportError: cannot import name 'dump_layout' from 'loop.contract'`。

- [ ] **Step 3: 改 `loop/models.py`**

三个新字段放 `ElementSpec` 末尾、`chart` 放 `PageSpec` 末尾，各带一行注释说明用途与"缺省 None 保证改版前的 JSON 仍能读回"（照 `image_path`（:38-42）与 `content_bbox`（:57-62）的既有写法）。`PageSpec.from_dict` 加 `chart=d.get("chart")`。

- [ ] **Step 4: 改 `loop/layout.py` 的 `PageLayoutSpec.to_dict()`**

补两个键，**放在末尾**：

```python
    def to_dict(self) -> dict:
        return {"width_in": self.width_in, "height_in": self.height_in,
                "margin_in": self.margin_in, "gutter_in": self.gutter_in,
                "column_count": self.column_count,
                "column_gutter_in": self.column_gutter_in,
                "rows": list(self.rows), "cards": [c.to_dict() for c in self.cards],
                "blocks": [b.to_dict() for b in self.blocks],
                "images": [i.to_dict() for i in self.images],
                "version": self.version, "theme": self.theme}
```

> 键序变化会让 Task 1 的指纹**不**变（指纹只抽几何），但会让 Task 3 的 `to_dict()` 输出多两个键——Task 3 的 superset 断言已经预留了这种情况。

- [ ] **Step 5: 在 `loop/contract.py` 实现 `dump_layout` / `write_layout_atomic`**

```python
def dump_layout(layout: PageLayoutSpec) -> dict:
    """严格写出：补 version/theme → 过 schema → 原样返回（不落盘）。"""
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
```

- [ ] **Step 6: 跑测试与全量**

```bash
cd /d/appmy/news-dataviz
python -m unittest tests.test_step34_contract_write -v
python -m unittest discover -s tests -t . -q
```

预期：`Ran 6 tests` / `OK`；全量 `Ran 704 tests` / `OK`。

- [ ] **Step 7: 提交**

```bash
cd /d/appmy/news-dataviz
git add loop/models.py loop/layout.py loop/contract.py tests/test_step34_contract_write.py
git commit -m "feat(contract): version/theme/chart/lines 字段与严格写出（P1 Task 4）"
```

---

### Task 5: 卡片文本折行进契约（Spec §4 D10）

**Files:**
- Create: `loop/card_text.py`
- Modify: `loop/layout.py`（`flow_layout()` 构造 `PlacedCard` 处，:814-816）
- Test: `tests/test_step35_card_text.py`

**Interfaces:**
- Consumes: `loop.text_flow.wrap(text, style, width_in, scale=1.0)`（`text_flow.py:30`）、`loop.palette.scaled_font_size(role, scale=1.0)`（`palette.py:192`）、`loop.palette.spec_scale(spec)`（`palette.py:178`，`flatten()` 用的就是它，见 `layout.py:865`）、`loop.models.PageSpec` / `ElementSpec`
- Produces:
  - `loop/card_text.py`:
    - `wrap_element(el: ElementSpec, scale: float) -> list[str]` — `= text_flow.wrap(el.text, el.role, el.w_in, scale)`。**唯一**调用 `text_flow.wrap` 的地方。
    - `annotate_card_text(spec: PageSpec, scale: float) -> PageSpec` — 返回**新的** `PageSpec`（`dataclasses.replace`），对每个 `type == "text"` 且 `text` 为真、`w_in > 0`、`lines` 为空的元素：`lines = wrap_element(el, scale)`、`font_pt = palette.scaled_font_size(el.role, scale)`。其它元素原样带过。**幂等**：已经带 `lines` 的元素不再重算。
    - `annotate_layout(layout: PageLayoutSpec) -> PageLayoutSpec` — 对 `layout.cards` 逐张用 `palette.spec_scale(card.spec)` 调 `annotate_card_text`。**只动卡片，不动整版 blocks**（整版块的 `lines` 早就写进 `geometry["lines"]` 了，见 `layout.py:887`）。
  - `loop/layout.py`：`flow_layout()` 里 `PlacedCard(...)`（:814）构造前，把 `spec` 换成 `card_text.annotate_card_text(spec, palette.spec_scale(spec))`。**只加这一处调用**，不改流式排版的任何高度/位置计算。

```python
def annotate_card_text(spec: PageSpec, scale: float) -> PageSpec:
    """把卡片内文本的折行结果与字号写进元素（Spec §4 D10）。

    跳过三种情况并保持 lines=None：非 text 元素、text 为空、盒宽 <= 0。
    最后一种不是"防御性编程"——卡片几何由求解器产出，求解失败的卡片可能带
    过期尺寸，读图纸的人宁可看到 None 也不该看到异常。
    """
    out = []
    changed = False
    for el in spec.elements:
        if (el.type == "text" and el.text and el.lines is None and el.w_in > 0):
            out.append(replace(el, lines=wrap_element(el, scale),
                               font_pt=palette.scaled_font_size(el.role, scale)))
            changed = True
        else:
            out.append(el)
    return replace(spec, elements=out) if changed else spec
```

- [ ] **Step 1: 写失败测试 `tests/test_step35_card_text.py`**

共 **6** 个 test method。前两个是本 Task 的**核心判据**，用的是"记录式 draw 替身"——不去改 `loop/preview.py`，而是给 `_draw_text` 喂一个只实现 `textlength` / `text` 两个方法的假 draw，把它**实际画出的行**记下来：

```python
class _Recorder:
    """假 draw：_draw_text 只用 textlength 量宽、用 text 画行。"""
    def __init__(self, font):
        self.font, self.drawn = font, []
    def textlength(self, text, font=None):
        return (font or self.font).getlength(text)
    def text(self, xy, text, fill=None, font=None):
        self.drawn.append(text)


def _preview_lines(el, scale):
    from PIL import Image, ImageDraw
    from loop import preview, palette
    px = int(round(palette.scaled_font_size(el.role, scale) * preview._PX_PER_PT))
    rec = _Recorder(preview._font(px))
    box = (0, 0, el.w_in * preview.PX_PER_IN, el.h_in * preview.PX_PER_IN)
    preview._draw_text(rec, box, el.text, el.role, "center", scale)
    return rec.drawn          # _draw_text 内部已截到 4 行
```

| 测试名 | 断言 |
|---|---|
| `test_wrap_matches_preview_for_every_card_text_element` | 对**两份夹具**的每张卡片的每个 `type == "text"` 且 `text` 非空的元素：`card_text.wrap_element(el, scale)[:4] == _preview_lines(el, scale)`，`scale = palette.spec_scale(card.spec)`。一条不等就 `self.fail` 并把 `el.id`、两边行列表打出来。**这就是 Review Focus #3 的判据——不等就停下报告，不许改 `preview.py` 去"统一"** |
| `test_lines_are_not_truncated_to_four` | `annotate_layout` 后的每个卡片文本元素：`lines == card_text.wrap_element(el, scale)`（**全量**，不截断）；且存在至少一个元素的 `len(lines) > 4` 或断言"两份夹具里最长折行 N 行"——先跑一次把真实 N 记进断言，N ≤ 4 时改成断言 `len(lines) == len(wrap_element(...))` 并注释说明样本没有超 4 行的元素 |
| `test_font_pt_equals_palette_scaled_font_size` | 每个被标注的元素 `font_pt == palette.scaled_font_size(el.role, scale)`；`role` 为 `title` / `scale_note` / `label` / `value` / `legend` / `center` 时分别等于 20 / 8 / 9 / 11 / 9 / 14 乘 `scale` 再 `round(...,2)` |
| `test_annotation_is_idempotent` | `annotate_layout(annotate_layout(x))` 与 `annotate_layout(x)` 的 `to_dict()` 完全相等；且第二次不重算（用 `unittest.mock.patch.object(card_text, "wrap_element", side_effect=AssertionError)` 包住第二次调用） |
| `test_non_text_and_empty_text_keep_lines_none` | `rect` / `ellipse` / `arc` / `ticks` / `outline` 元素的 `lines is None`；`text` 为空串或 `None` 的元素 `lines is None`；`w_in <= 0` 的 text 元素 `lines is None` 且**不抛** |
| `test_flow_layout_annotates_every_card` | 跑一次真实整版（用 `loop.compose` 的公开入口或夹具的 `PageLayoutSpec` 重建路径）→ `layout.cards` 里每张卡片的每个 text 元素都有非空 `lines` 与 `font_pt`。**这条把"接线真的接上了"钉住**——`card_text` 单测全绿但忘了改 `flow_layout` 是这一步最可能的失误 |

- [ ] **Step 2: 跑它，确认是红的**

```bash
cd /d/appmy/news-dataviz && python -m unittest tests.test_step35_card_text -v
```

预期：`ModuleNotFoundError: No module named 'loop.card_text'`。

> 若 `test_wrap_matches_preview_for_every_card_text_element` 在实现完成后仍然红，**停下报告**，把不等的元素 id 与两边行列表贴进 PR 描述。这代表 Spec §4 D10 的前提（两个折行实现同口径）不成立，需要用户拍板"以谁为准"，不是执行者能决定的。

- [ ] **Step 3: 实现 `loop/card_text.py`**（按上面的 Interfaces 与代码块）

- [ ] **Step 4: 在 `loop/layout.py::flow_layout` 接线**

找到 :814 的 `PlacedCard(card=item, spec=spec, ...)`，把 `spec` 参数改成 `card_text.annotate_card_text(spec, palette.spec_scale(spec))`。`loop/layout.py` 顶部已有 `from loop import palette`（`flatten()` 在用），只需再加 `from loop import card_text`。**确认没有循环导入**：`card_text` 只 import `text_flow` / `palette` / `models`，三者都不 import `layout`。

- [ ] **Step 5: 跑测试与全量**

```bash
cd /d/appmy/news-dataviz
python -m unittest tests.test_step35_card_text -v
python -m unittest discover -s tests -t . -q
```

预期：`Ran 6 tests` / `OK`；全量 `Ran 710 tests` / `OK`。**注意**：`flow_layout` 现在会返回带 `lines` 的卡片，`to_dict()` 的产物会变大——Task 1 的指纹测试必须**仍然绿**（卡片内 `lines` 不进指纹）。

- [ ] **Step 6: 提交**

```bash
cd /d/appmy/news-dataviz
git add loop/card_text.py loop/layout.py tests/test_step35_card_text.py
git commit -m "feat(contract): 卡片内文本折行与字号写进契约（P1 Task 5，Spec D10）"
```

---

### Task 6: V5 / V6 验收守卫

**Files:**
- Create: `tests/test_step36_contract_guards.py`
- Modify: `frontend/README.md`
- Test: `tests/test_step36_contract_guards.py`

**Interfaces:**
- Consumes: `loop.contract.load_layout` / `dump_layout`、`loop.schema_check.validate_doc`、`tests/contract_fixtures.py`
- Produces:
  - `tests/contract_fixtures.py` 增补：
    - `iter_js_sources() -> list[str]` — `frontend/src/**/*.js` 的排序列表；目录不存在返回 `[]`
    - `find_hardcoded_theme_tokens(source: str) -> list[tuple[int, str]]` — 返回 `(行号, 匹配文本)`：十六进制色值 `#rgb` / `#rrggbb` / `#rrggbbaa`（大小写都算），以及写死字号 `font-size` 后跟数字、`"12px"` / `"12pt"` 这类字面量
  - `frontend/README.md` 新增一节：契约定义在 `frontend/schema/pagelayout.schema.json`，颜色与字号只能从图纸的 `theme` 取，禁止在 `frontend/src/` 里出现十六进制色值与写死字号（`theme.js` 是唯一例外，因为它就是读取层）

- [ ] **Step 1: 写失败测试 `tests/test_step36_contract_guards.py`**

共 **5** 个 test method：

| 测试名 | 断言 |
|---|---|
| `test_legacy_samples_read_loosely_with_warnings`（V5 前半） | 对 Task 1 的**全部 11 份**样本（`out/demo` 缺失时退化为 2 份夹具）：`load_layout(path)` 不抛；每份都至少产出 1 条 warning；每份都含一条关于 `version` 的 warning |
| `test_new_documents_pass_strict_schema`（V5 后半） | 每份样本 `load_layout` → `dump_layout` → `validate_doc(doc) == []`；`doc["version"] == "1.0"` |
| `test_theme_comes_from_palette_not_from_disk`（V6 的 Python 侧） | `dump_layout(x)["theme"] == palette.summary()`（深比较）；改 `palette.summary()` 的返回（`patch` 掉）后 `dump_layout` 跟着变。这条证明主题**不是**从旧图纸抄来的，而是**当前** `palette.py` 的产物 |
| `test_theme_token_scanner_catches_hex_and_font_size`（V6 的自检） | `find_hardcoded_theme_tokens` 对样本代码片段能抓到 `fill = "#C01F2A"`、`stroke = "#abc"`、`ctx.font = "12px sans"`、`style.fontSize = 14`；对 `const c = theme.palette.title;` 返回 `[]`。**守卫必须先证明自己抓得住东西**，否则它只是个永远绿的摆设 |
| `test_frontend_sources_have_no_hardcoded_theme_tokens`（V6 本体） | `iter_js_sources()` 为空时 `self.skipTest("frontend/src 尚未创建（P2 才建）")`；非空时逐个扫，**放过 `frontend/src/theme.js`**，其余有命中就 `self.fail` 并打印文件与行号 |

- [ ] **Step 2: 跑它，确认是红的**

```bash
cd /d/appmy/news-dataviz && python -m unittest tests.test_step36_contract_guards -v
```

预期：`ImportError` / `AttributeError`（`find_hardcoded_theme_tokens` 还不存在）。**`test_frontend_sources_have_no_hardcoded_theme_tokens` 会 skip**，这是预期的——P1 还没有 JS 代码，但守卫要先落地。

- [ ] **Step 3: 在 `tests/contract_fixtures.py` 实现两个 helper，在 `frontend/README.md` 加一节**

V6 的正则不要用 `\b#\w{3}\b`（会误伤注释与 URL 锚点）——用 `#[0-9a-fA-F]{3,8}\b` 并排除紧跟字母的 `#`（如 `#section`）。字号匹配 `(font-size|fontSize)\s*[:=]\s*["']?\d` 与 `["']\d+(px|pt)["']`。

- [ ] **Step 4: 跑测试与全量**

```bash
cd /d/appmy/news-dataviz
python -m unittest tests.test_step36_contract_guards -v
python -m unittest discover -s tests -t . -q
```

预期：`Ran 5 tests` / `OK`（其中 1 个 skip）；全量 `Ran 715 tests` / `OK (skipped=1)`。

- [ ] **Step 5: 提交**

```bash
cd /d/appmy/news-dataviz
git add tests/contract_fixtures.py tests/test_step36_contract_guards.py frontend/README.md
git commit -m "test(contract): V5 宽松读/严格写与 V6 主题单一来源守卫（P1 Task 6）"
```

---

### Task 7: 回归复判与交付

**Files:**
- Create: `tests/test_step37_contract_delivery.py`
- Test: `tests/test_step37_contract_delivery.py`

**Interfaces:**
- Consumes: `tests/contract_fixtures.py`、`loop.contract`、`scripts/build_*_demo.py`（**只运行，不修改**）
- Produces:
  - `tests/test_step37_contract_delivery.py` 内定义验收常量：`EXPECTED_MIN_TESTS = 718`、`EXPECTED_CONTRACT_VERSION = "1.0"`

- [ ] **Step 1: 写失败测试 `tests/test_step37_contract_delivery.py`**

共 **3** 个 test method：

| 测试名 | 断言 |
|---|---|
| `test_every_demo_layout_regenerates_geometrically_identical` | 对 `demo_layout_paths()` 逐份：`fingerprint_sha(json.load(open(p))) == load_baseline()[p]["sha256"]`。**这是本计划唯一的"几何一个字节没变"判据**，在 Step 3 重新生成产物之后跑才有意义 |
| `test_regenerated_documents_are_contract_conformant` | 逐份 `load_layout(p)` → `dump_layout(...)` → `validate_doc(...) == []`；`doc["version"] == "1.0"`；`doc["theme"]` 非空 |
| `test_card_text_elements_carry_lines_and_font_pt_after_regeneration` | 逐份：每张卡片的每个 text 元素 `lines` 是非空 list、`font_pt` 是正数 |

- [ ] **Step 2: 跑它**（此时代码已全部就位，产物还是旧的，前两条应该已经绿）

```bash
cd /d/appmy/news-dataviz && python -m unittest tests.test_step37_contract_delivery -v
```

- [ ] **Step 3: 用现有 demo 构建脚本重新生成 11 份产物**

这些脚本**不改动**，只是运行；产物落 `out/demo/`（已 gitignore）。逐个跑，逐个确认退出码为 0：

```bash
cd /d/appmy/news-dataviz
for s in build_auto_layout_demo build_illustrated_demo build_multicol_demo \
         build_page_demo build_newspaper_demo build_theme_match_demo; do
  echo "=== $s ==="
  python -m scripts.$s || echo "FAILED: $s"
done
find out/demo -name pagelayout.json | wc -l
```

预期：最后一行仍是 **11**。若脚本的产物路径与 Task 1 的清单不一致（多出或少了文件），**停下报告**——不要在没弄清为什么的情况下重写基线。

- [ ] **Step 4: 复判（本计划最关键的一步）**

```bash
cd /d/appmy/news-dataviz
python -m unittest tests.test_step37_contract_delivery -v
python -m unittest tests.test_step31_contract_fixtures -v
```

预期：两条都全绿。**若 `test_every_demo_layout_regenerates_geometrically_identical` 红**，说明本计划的改动碰到了几何——立刻用 `git diff` 逐个 Task 回查 `loop/layout.py` 与 `loop/models.py`，**不许重写基线**。

- [ ] **Step 5: 跑全量并核对计数**

```bash
cd /d/appmy/news-dataviz && python -m unittest discover -s tests -t . -q
```

预期：`Ran 718 tests` / `OK (skipped=1)`。

- [ ] **Step 6: 确认工作区干净、Nothing 越界**

```bash
cd /d/appmy/news-dataviz
git status --short
git diff --stat main...HEAD
```

逐条确认：
- `git status --short` 只有 `out/`（被 ignore，不该出现）之外的空输出；
- `git diff --stat` 里**没有** `ingest/`、`assets/`、`db/`、`scripts/`、`CONTRIBUTING.md`、`.gitignore`、`.gitattributes`、`.github/`；
- 改动只落在 `loop/`、`tests/`、`frontend/`、`docs/`。

- [ ] **Step 7: 提交并推送**

```bash
cd /d/appmy/news-dataviz
git add tests/test_step37_contract_delivery.py
git commit -m "test(contract): P1 交付复判——几何指纹、契约合规、折行落章（P1 Task 7）"
git push -u origin frontend/pagespec-contract
```

- [ ] **Step 8: 把 PR 描述写进交付消息**（本机无 `gh`，不能自动开 PR）

交付消息里必须包含：PR 链接 https://github.com/stecven/news-dataviz/pull/new/frontend/pagespec-contract 、本次提交范围（设计文档 `1797572` + P1 七个 Task 的提交）、`Ran 718 tests` 的实测输出、`git diff --stat main...HEAD` 的实际改动清单、以及「已知偏差」三条（`frontend/schema/` 的位置、**不改 `preview.py`**、沿用未合分支）、Review Focus 第 3 条（折行等价）的实测结论。

---

## Self-Review

**Spec 覆盖检查**
- Spec §3 C1（英寸）→ Global Constraints + 指纹只比英寸值。
- Spec §3 C2（卡片内相对坐标）→ Task 3 `test_geometry_is_not_translated_on_read`、Review Focus #6。
- Spec §3 C3（后端无关）→ schema 里没有 ECharts / draw.io / PPTX 键；Task 2 的白名单会挡住意外引入。
- Spec §3 C4（676 不挂、新字段可空放末尾）→ Global Constraints、Task 4 `test_new_fields_are_last_in_dataclass`。
- Spec §3 C5（浏览器打不开 SQLite）→ 本计划不涉及；P5 才处理。
- Spec §3 C6（目录所有权）→ Global Constraints + Task 7 Step 6 的 `git diff --stat` 核对。
- Spec §4 D9（版本化）→ Task 4 `CONTRACT_VERSION` + `version` 字段。
- Spec §4 D10（卡片文本折行进契约）→ Task 5 全篇；**验收需说明"PNG 侧换吃 lines"留给 P2**（已知偏差 2）。
- Spec §4 D11（theme = palette.summary()）→ Task 4 `dump_layout`、Task 6 `test_theme_comes_from_palette_not_from_disk`。
- Spec §4 D12（老样本宽松读 / 新样本严格写 / 夹具放 tests/fixtures/contract/、不接 CI）→ Task 1、Task 3、Task 6；本计划**没有**新增 `.github/workflows/`。
- Spec §4 D14（`loop/contract.py` + 四个 `from_dict`）→ Task 3。
- Spec §5.2/5.3/5.4/5.6/5.7（字段清单与 schema）→ Task 2 的 schema、Task 4 的字段。
- Spec §7 V4/V5/V6 → 每个 Task 的全量跑 / Task 6。
- Spec §7 V1/V2/V3 → **明确不在本计划**（需要 P2 的 JS 渲染器）。
- Spec §9 P1 的六项交付（schema + version + theme + 卡片 lines/font_pt + contract.py + 夹具 + V4/V5/V6）→ Task 1–7 全覆盖。
- Spec §11 边界澄清 → Global Constraints 的「不改变任何已存在样本的几何数字」+ Task 7 Step 4。

**未覆盖且**必须在 P2/P3/P4/P5 计划里补**的**：JS 库骨架与构建（Vite/ESM）、7 个图元 + ticks/outline 的 JS 复刻、`mountPage` API、编辑与撤销、`exportSVG`、CLI + MCP server、`scripts/export_web_assets.py` 与插图渲染、V1/V2/V3、`chart` 图元的填充（P6）。

**类型一致性**：`PageLayoutSpec.version` 在 Task 3 是 `str | None`、Task 4 写出时一定非空 `"1.0"`；`ElementSpec.lines` 全程 `list | None`；`font_pt` 全程 `float | None`（`palette.scaled_font_size` 返回 `round(...,2)` 的 `float`）；`annotate_card_text` 与 `annotate_layout` 都返回新对象、不原地改。

**篇幅比例**：Task 1（基线）与 Task 7（复判）各占一个完整 Task，因为它们承担"几何不变"这一条唯一的硬判据；Task 2 的校验器是唯一有算法代码块的地方。JS 侧一行不写，因为它不在 P1。

## Execution Handoff

**Subagent-Driven（推荐）** — 每个 Task 交给一个新的 subagent，Task 之间做一次 review。理由：本计划有七个 Task，其中 Task 3/4/5 都会边改 `loop/`，而 Task 1 的指纹是全计划的判据；subagent 之间插一道 review 能在几何被碰坏的当次就发现，而不是等到 Task 7 才发现三处改动都有份。

**Inline Execution** — 在当前会话按 Task 顺序执行，在 Task 3/5/7 之后停下让我复核。

选哪种？
