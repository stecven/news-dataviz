# CI 与可复现构建

> 用户 m07216（PR-D）。这份文档说明**为什么**流水线长这样，以及**怎么在没有 CI 的
> 机器上手工跑一遍**。

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

所以 CI 要做的事只有两件：**先把产物造出来**，**再让缺产物变成红**。

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

CI 还会在跑完测试后**复查日志**，而且不是"零跳过"这种口号式检查 —— 是**白名单**：

> 有两个名字很像的东西，必须分清：
>
> * `out/demo/**` —— **可以由当前代码造出来**，所以严格模式下缺了就是红。
> * `out/loop1/pagespec.json` —— **当前代码造不出同形状的文件**。它被三个用例当作
>   "旧版本遗留样本"读（断言 27 个元素），而现在 `python -m loop.build_loop` 跑出来
>   是 39 个元素。它在 `.gitignore` 里，干净机上根本不存在，CI 也**无法**提供一个。
>
> 所以这三个用例保留原来的 `skipTest`，**不让**它们走 `skip_or_fail` ——
> 强行严格化只会得到一个和本任务无关的假红。

CI 的做法是把允许的跳过**钉死并点名**：

| 用例 | 文件 | 为什么允许跳过 |
| --- | --- | --- |
| `test_legacy_loop1_pagespec_still_readable_and_renderable` | `tests/test_step10_semicircle_acceptance.py` | 需要老样本 |
| `test_old_loop1_pagespec_still_renders` | `tests/test_step17_image_element.py` | 需要老样本 |
| `test_legacy_pagespec_still_reads_and_renders` | `tests/test_step22_target_box.py` | 需要老样本 |

流水线要求跳过集合**恰好等于**这 3 个（数量 + 名字都对）。任何**新增**跳过都会被
判失败 —— 这才是"没有静默跳过"的可执行含义：不是不许跳，而是**跳了必须是被点名过
的**。JS 侧没有这种历史包袱，所以仍然是零跳过。

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
- CI 的第一步打印字体路径与它的 sha256，日志里能查"这次用的是什么字体"。

### 几何基线用的是哪个字体

`C:/Windows/Fonts/msyh.ttc`（微软雅黑）— **随 Windows 分发，不可再分发**，因此
不能入库、也不能塞进 `requirements.txt`。CI 里按下面的顺序拿：

1. runner 自带 `C:\Windows\Fonts\msyh.ttc`（Windows runner 直接用）；
2. 否则读仓库 secret `NEWSDATAVIZ_FONT_B64`（该字体文件的 base64），写到
   `$RUNNER_TEMP` 再设 `NEWSDATAVIZ_FONT_PATH` 指过去；
3. 两者都没有 → **CI 明确失败**，错误信息指向这份文档。

> 想让 CI 更省事，仓库管理员可以把 `msyh.ttc` 做成 base64 存进
> Settings → Secrets → Actions，名字叫 `NEWSDATAVIZ_FONT_B64`。
> 这是"把私有环境里的字体喂给私有 runner"，不是把字体内库。

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
  → 准备字体（见 §3；打印路径 + sha256）
  → 六个 demo 脚本                      # out/demo/**/pagelayout.json + preview.png + _cards/
  → 检查 11 份 pagelayout.json 真的落盘
  → python -m unittest discover -s tests -t . -v
  → npm test（工作目录 frontend）
  → 复查两份日志：Python 跳过集合 == 3 个白名单用例；JS 零跳过
```

**这里故意不跑 `python -m loop.build_loop`** —— 见 §2 的说明：它产出的不是那三个
用例想要的老样本，跑了只会把"老样本回读"变成假红。

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

- **三个"老样本回读"用例在 CI 上仍然是跳过**（白名单见 §2）。它们要的
  `out/loop1/pagespec.json`（27 个元素）是旧版本引擎留下的产物，当前代码产不出来
  （现在是 39 个元素），也没有入库。**这是个真缺口，不是"已经解决"**：
  两个可选出路，需要人工决定 ——
  ① 把那个老样本作为夹具入库（`tests/fixtures/legacy/…`），让用例改成读夹具，
  于是它变成可复现的判据；② 认定这两个格式的回读已无价值，正式退役这三个用例
  （退役要写进计划，不是悄悄删）。**本轮不擅自选**：库里的老样本已经不可复现，
  而"补一个我手工造的同形状文件"会把判据变成自说自话。
- **runner 必须是能提供该字体的平台**（自带 `msyh.ttc` 的 Windows，或配了
  `NEWSDATAVIZ_FONT_B64` 的任意平台）。JIT runner 上没字体就是红，不会静默降级。
- `git ls-remote` 在本机因 `core.sshCommand` 的 Windows 反斜杠路径被 Git-Bash
  吃掉而不可用；推送要用 `git -c core.sshCommand=<正斜杠路径> push`。这与 CI 无关
  （Actions 自己管凭据），但会把"本地看远端"搞坏，容易误判。
- 本阶段**不**承诺跨机器字节级可复现（zlib/FreeType 版本差异），只承诺"同环境内
  可复现 + 环境不一致时红"。
