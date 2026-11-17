# CI 与可复现构建

> 用户 m07216（PR-D）建立，m07603 两项收尾决策（老样本入库、字体预检）后更新。
> 这份文档说明**为什么**流水线长这样，以及**怎么在没有 CI 的机器上手工跑一遍**。

## 1. 它保护什么

发布前审查（m07120）发现两件事：

1. **仓库没有任何 CI**（`.github/` 下只有 `CODEOWNERS`）。
2. 干净检出上跑测试，Python 会跳过 9 条、JS 会跳过 101 条（其中
   `primitives.test.mjs` / `stage.test.mjs` **整文件跳过**），而测试进程**仍然退出 0**。

被跳过的那几条恰好是最关键的判据：

| 判据 | 位置 | 干净检出上的行为 |
| --- | --- | --- |
| 几何指纹基线（11 份产物） | `tests/test_step31_contract_fixtures.py` | 5 条里跳 2 条（含全部指纹断言） |
| P1 交付判据（盘上字节带 `version`/`theme`） | `tests/test_step37_contract_delivery.py` | 3 条**全跳** |
| 产物契约版本判据 | `tests/test_step38_contract_version_gate.py` | 16 条里跳 1 条 |
| V1 结构对拍 / V2 像素对拍 | `frontend/test/v1-structure.test.mjs`、`v2-pixels.test.mjs` | 金样本组整组跳过 |
| 图元 / 整版渲染字面量 | `frontend/test/primitives.test.mjs`、`stage.test.mjs` | **整文件跳过** |

根因是 `out/` 被 `.gitignore` 忽略（`.gitignore:2`），而上述判据全部读
`out/demo/**` 的盘上字节。跳过本身是**给 fresh clone 的合理降级**，但把它原样搬进
CI，就变成「关键判据没跑，流水线还是绿的」。

所以 CI 要做的事有三件：**先核对字体**、**把产物造出来**、**让缺产物变成红**。

## 2. 严格模式：`REQUIRE_ARTIFACTS=1`

CI 全程设 `REQUIRE_ARTIFACTS=1`。它把"缺产物"从 `skip` 改成 `fail`：

- **Python**：`tests/contract_fixtures.py::skip_or_fail(case, reason)` —— 严格模式
  `case.fail(...)`，普通模式 `case.skipTest(...)`。三个读 `out/demo` 的用例走它：
  `test_step31`（几何指纹基线）、`test_step37`（P1 交付判据）、`test_step38`
  （产物契约版本）。
- **JavaScript**：`frontend/test/helpers/golden.mjs`
  - `requireArtifacts(paths)` —— 在**测试文件模块作用域**调用，缺产物直接抛，
    于是那个文件**收集失败**（整文件红），而不是被 `describe.skipIf` 整组跳过；
  - `demoLayoutPaths()` / `demoLayouts()` / `goldenDoc()` 在严格模式下也会抛；
  - `requirePagePreviews()` —— V2 还要每份图纸同目录的 `preview.png`；
  - `requireFontProbe(ok, detail)` —— sharp 画不出中文时，像素对拍会静默跳过，
    严格模式下改成红。

普通的 `describe.skipIf` / `it.skipIf` 守卫**保留不动**：本地不设环境变量时，
fresh clone 依然能"全绿但跳过依赖产物的组"，这是有意的开发体验。严格模式让 CI
不可能在这种状态下报绿。

CI 还会在跑完测试后**复查日志**：**Python 与 JS 都必须零跳过**。

> 用户 m07603 决策一之后，这里不再有白名单。原先的三个「老样本回读」用例
> （`tests/test_step10` / `test_step17` / `test_step22`）读的是
> `out/loop1/pagespec.json` —— 那是一个**旧版引擎**留下的 27 元素温度计规格，
> 当前代码产不出来（`python -m loop.build_loop` 给的是 39 个元素），文件又在
> `.gitignore` 的 `out/` 下，干净检出上必然跳过。
>
> 现在的做法是把那份老样本**收进仓库当夹具**：`tests/fixtures/legacy/loop1_pagespec.json`
> （同族真实遗留产物，27 元素 / `thermometer` / 10×6，JSON 内容与字段结构一字未改，
> 只按 `.gitattributes` 的 `eol=lf` 归一了行尾）。三个用例改成读它，于是它们在
> **没有 `out/` 的干净检出上也真跑**，跳过白名单随之删除。
>
> 注意区分两件事：
>
> * `out/demo/**` —— 由当前代码造得出来，严格模式下缺了就红；
> * `tests/fixtures/**` —— 入库夹具，与 `out/` 无关，clean checkout 上一定在。

任何跳过都会被判失败 —— 这是"没有静默跳过"的可执行含义。

## 3. 字体：为什么它算构建依赖

折行在 `loop/fit.py::_wrap_lines` 里用 `font.getlength(...)` 逐字量宽，预览在
`loop/preview.py::_draw_text` 里用同一个字体画字。**换字体就是换几何**：卡片框、
行高下限、`FitRequirement` 的触发点、`out/demo/**/pagelayout.json` 的全部数字，
以及 `tests/fixtures/contract/legacy_fingerprints.json` 里 11 份基线指纹，都会跟着变。

原实现有两处隐患：

1. 字体路径在三个地方各写死一次（`loop/preview.py`、`scripts/build_illustrated_demo.py`、
   `scripts/build_theme_match_demo.py`）；
2. 找不到字体时 `ImageFont.load_default()` **静默兜底** —— 不报错，但算出来的是
   另一套折行。最坏的结果是有人看到 CI 红了就去把基线重冻一遍，把问题盖掉。

现在的做法：

- 字体路径的唯一来源是 `loop/fonts.py`：环境变量 `NEWSDATAVIZ_FONT_PATH` 优先，
  否则回落到 `C:/Windows/Fonts/msyh.ttc`（生成现有基线的微软雅黑）。
- **找不到就抛 `FontUnavailable`**，不兜底。三处写死的路径全部改为
  `fonts.load_font(size)`。
- CI 在跑任何构建之前调用 `fonts.check_baseline_font()`：**用钉住版本的 Pillow
  真的打开一次**，并把文件的 SHA-256 与基线摘要比对。这一步不过是红。

### 几何基线用的是哪个字体

`C:/Windows/Fonts/msyh.ttc`（微软雅黑），SHA-256：

```
d79c55e68b1131eea0cc1c47be4f572d964f28c682e143db2ad09c1e4cb07a3f
```

这个摘要钉在 `loop/fonts.py::BASELINE_FONT_SHA256` 里；`fonts.check_baseline_font()`
拿它当判据。

**用户 m07603 决策二：不搬运这个字体。** 它随 Windows 分发、**不可再分发**，所以：

- 不复制进仓库；
- 不通过 `NEWSDATAVIZ_FONT_B64` 之类的 base64 secret 送到 GitHub Runner；
- `check_baseline_font()` 失败时**不静默回退**到 `ImageFont.load_default()`。

CI 因此把 `runs-on` 定在 **`windows-2025`**，并**实测**该 runner 上的
`C:\Windows\Fonts\msyh.ttc` 是否就是基线那一份：

1. 文件不存在 → 红（错误信息说明两条出路）；
2. Pillow 载不动 → 红；
3. SHA-256 与 `BASELINE_FONT_SHA256` 不一致 → 红，**并且不继续跑六个 demo**。

> ⚠️ 已实际验证的是：本机（Windows 11，Python 3.14.5 + Pillow 13.0.0）上
> `check_baseline_font()` 通过。**「GitHub 的 `windows-2025` 镜像里那份 msyh.ttc
> 是否与基线逐字节一致」尚未得到实际运行验证** —— 官方 runner 镜像的字体清单不能
> 当作实测结果。所以第一次真正跑 CI 时，这一步就是判据本身：
> 过不过以日志里的 sha256 为准。
>
> 若它不过：**不要**换字体、**不要**重冻 `legacy_fingerprints.json`、**不要**用
> secret 绕过授权，而是配置一台具备微软雅黑合法使用权的**自托管 Windows runner**。

**换成可再分发的开源字体是另一回事**：那会改变折行与几何，必须作为一次独立的契约
变更去做（重新生成 11 份产物 + 重冻指纹基线 + 重测 V2 像素口径）。本阶段不做，
也不允许"只让 CI 变绿、字体与基线不一致"。

## 4. 依赖固定

`requirements.txt` 钉死 `Pillow` / `python-pptx` / `lxml` / `XlsxWriter` /
`typing_extensions`（后两个是 python-pptx 的传递依赖）。理由同字体：Pillow 的
FreeType 影响字形宽度，python-pptx + lxml 影响 PPTX 字节。

前端用 `frontend/package-lock.json` + `npm ci`，锁定 `vitest` / `jsdom` / `sharp`。

## 5. CI 跑什么（`.github/workflows/ci.yml`）

```
checkout
  → setup-python 3.14
  → setup-node 24（cache: npm，路径指向 frontend/package-lock.json）
  → pip install -r requirements.txt
  → npm ci（工作目录 frontend）
  → 核对字体与几何基线一致（见 §3：存在 + Pillow 实载 + SHA-256 比对）
  → 打印生效的字体路径
  → 六个 demo 脚本                      # out/demo/**/pagelayout.json + preview.png + _cards/
  → 检查 11 份 pagelayout.json 真的落盘
  → python -m unittest discover -s tests -t . -v
  → npm test（工作目录 frontend）
  → 复查两份日志：Python 零跳过；JS 零跳过
```

`runs-on: windows-2025`。

**这里故意不跑 `python -m loop.build_loop`** —— 它产出的不是那三个用例要的老样本
（那三个用例现在读入库夹具），跑了没有意义。

六个写 `out/demo/**/pagelayout.json` 的脚本（顺序无关，证明产出关系的是「都在测试
之前」）:

| 脚本 | 产物目录 |
| --- | --- |
| `python -m scripts.build_auto_layout_demo` | `out/demo/auto_layout/`（含 `_plain/`） |
| `python -m scripts.build_illustrated_demo` | `out/demo/illustrated/`（含 `_no_asset/`、`_spread/`） |
| `python -m scripts.build_multicol_demo` | `out/demo/multicol/`（含 `_spread/`） |
| `python -m scripts.build_newspaper_demo` | `out/demo/paper/` |
| `python -m scripts.build_page_demo` | `out/demo/page/` |
| `python -m scripts.build_theme_match_demo` | `out/demo/theme_match/`（含 `_no_theme/`） |

另外 `scripts/build_palette_demo.py` / `build_semi_demo.py` 只写 pagespec 与 preview，
不写 `pagelayout.json`，CI 不需要它们。

任一步失败即整个 job 失败；没有 `continue-on-error`。

## 6. 本地等价跑法

```powershell
# 干净检出（或先删掉 out/）
$env:REQUIRE_ARTIFACTS = "1"          # 严格模式
$env:NEWSDATAVIZ_FONT_PATH = "C:/Windows/Fonts/msyh.ttc"   # 或让默认值生效

python -m pip install -r requirements.txt
cd frontend; npm ci; cd ..

# 字体身份先过 —— 不过就别往下跑（否则会造出另一套几何）
python -c "from loop import fonts; print(fonts.check_baseline_font())"

python -m scripts.build_auto_layout_demo
python -m scripts.build_illustrated_demo
python -m scripts.build_multicol_demo
python -m scripts.build_newspaper_demo
python -m scripts.build_page_demo
python -m scripts.build_theme_match_demo

python -m unittest discover -s tests -t . -v
cd frontend; npm test
```

红态（应当失败）: 干净检出 + `REQUIRE_ARTIFACTS=1` + **不跑**上面的构建命令，
直接跑测试 —— 期望缺产物指名报错，而不是全绿。

## 7. 已知边界

- **老样本回读已解决**（用户 m07603 决策一）：27 元素样本入库为
  `tests/fixtures/legacy/loop1_pagespec.json`，三个用例读它、不再依赖 `out/`，
  于是干净检出上它们也真跑。CI 因此要求**零跳过**。
  > 口径说明：入库的那份是**同族真实遗留产物**（2026-11-08 的 `out/demo/g1`，
  > 同样 27 元素 / `thermometer` / 10×6），因为原始的 `out/loop1/pagespec.json`
  > 从未入库、已不可恢复。JSON 内容与字段结构一字未改，只按 `.gitattributes`
  > 的 `eol=lf` 归一了行尾。判据（27 元素 + 可反序列化 + 可真渲染）与原来完全一致。
- **runner 必须能提供与基线一致的字体**：`runs-on: windows-2025` +
  `fonts.check_baseline_font()`。**该 runner 镜像里的雅黑是否与基线一致，本阶段
  未得到实际运行验证**（本地 Windows 上已验证通过）；不一致就是红，不会静默降级。
  真不一致时的出路是自托管 Windows runner，不是换字体或重冻基线。
- `git ls-remote` 在本机因 `core.sshCommand` 的 Windows 反斜杠路径被 Git-Bash
  吃掉而不可用；推送要用 `git -c core.sshCommand=<正斜杠路径> push`。这与 CI 无关
  （Actions 自己管凭据），但会把"本地看远端"搞坏，容易误判。
- 本阶段**不**承诺跨机器字节级可复现（zlib/FreeType 版本差异），只承诺"同环境内
  可复现 + 环境不一致时红"。
