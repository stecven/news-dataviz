/**
 * P2 Task 5 / V1 结构对拍：金样本（`out/demo/**`）的定位与加载。
 *
 * `out/` 被 `.gitignore` 忽略，fresh clone / CI 上这些文件**不存在**。所以本模块
 * 默认只做「有就读，没有就 `null`」（不抛），调用方据此 `describe.skipIf(...)`。
 *
 * **但整组 skip 会让 V1 结构对拍在 CI 上静默全绿**，所以测试文件里另有一条
 * 完全手写合成 doc 的判据（不依赖任何金样本），见 `v1-structure.test.mjs` 的
 * 「合成 doc」组。
 *
 * `REQUIRE_ARTIFACTS=1`（CI）时本模块改为**缺产物即抛**，见 `requireArtifacts`：
 * 那样缺产物是红，不是绿。
 *
 * ---------------------------------------------------------------------------
 * 【维护必读】测试里那些写死的数字，是**针对某一代排版引擎产物**实测出来的字面量
 *
 * 本目录只负责「找到并读出」金样本；真正把期望值写死的是这几个测试文件：
 * - `v1-structure.test.mjs` 的 `GOLDEN_STRUCTURE` 基线表（total / page / cards /
 *   elements / checked / skipped / skipHist）；
 * - `v2-pixels.test.mjs` 文件头那张三口径表格，以及各卡片的 `considered` 等账本数字；
 * - `primitives.test.mjs`、`stage.test.mjs` 里从夹具盒算出来的像素字面量
 *   （元素盒走 `truncPx`，卡片落位走 `roundPx`/`pyRound`）。
 *
 * **这些期望值不是「推导出来的」，而是「测出来写死的」。** 一旦 `loop/` 里的 Python
 * 排版几何发生变化（改变 `w_in`/`h_in` 的语义、缩放与居中留白规则、自动升栏、
 * 折行宽度等），重新生成 `out/demo/**` 之后，上面那些字面量就会集体失真：
 * 表现是 `npm test` 一片红，但**渲染器本身可能没有任何缺陷**。
 *
 * 届时正确的做法**不是**把断言改松、加 skip、或删掉用例，而是：
 * 1. 找出几何变化的可验算原因（例如「卡片外框由格子宽 6.072in 变成等比缩放后的
 *    4.8656in，于是水平居中后 `x = 0.4 + (6.072 − 4.8656)/2 = 1.0032`」）；
 * 2. 逐条给出 `旧期望值 → 新实际值 + 几何原因`，再更新字面量，**保持原有的判据强度**
 *    （精确断言仍精确、阈值不动、该钉死的量级继续钉死）；
 * 3. 若某条断言的**意图**在新几何下已不成立，就把它重新设计成能确定性检验同一性质的
 *    判据（`v2-pixels.test.mjs` 的「0.5 平局」组就是这么从真实样本改成合成 doc 的），
 *    而不是删掉。
 *
 * 【本次对齐的产物代次】PR-B 时代的产物 —— 分支 `fix/staggered-layout`，HEAD `f6c3508`
 * （契约：卡片 `w_in`/`h_in` 记录等比缩放后的真实外框尺寸、窄于格子时水平居中留白、
 * 1 栏放不下的卡片自动升到整栏；对应四个提交 `08f0ca8`/`8aebaa6`/`7366cf5`/`f6c3508`）。
 * 上一代（PR-A，父提交 `204db45`）的数字已全部作废。
 */
import { existsSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
/** `frontend/test/helpers` → 仓库根。 */
export const REPO_ROOT = resolve(HERE, '..', '..', '..');

/**
 * 严格模式开关（用户 m07216 任务 2）。
 *
 * 本地/fresh clone 上 `out/` 不存在，条件跳过是合理的（不然新克隆一跑就红）。
 * 但同一套跳过搬到 CI 上会变成「**关键判据没跑，流水线还是绿的**」：整文件跳的
 * `primitives`/`stage`，以及 `v1-structure`/`v2-pixels` 的金样本组，正好是 V1 结构
 * 对拍与 V2 像素对拍本身。所以 CI 设 `REQUIRE_ARTIFACTS=1`，让缺产物变成红。
 */
export const REQUIRE_ARTIFACTS = process.env.REQUIRE_ARTIFACTS === '1';

/** `DEMO_LAYOUTS` 里当前工作区缺失的那些（相对仓库根）。 */
export function missingArtifacts(relPaths = DEMO_LAYOUTS) {
  return relPaths.filter((relPath) => !existsSync(goldenPath(relPath)));
}

/**
 * 严格模式下要求这些产物**都存在**，缺一个就抛（带缺哪些文件的清单）。
 *
 * 普通模式是**空操作**。在测试文件模块作用域调用它（而不是放在 `it` 里）是有意
 * 的：产物缺失时该文件直接收集失败、整个文件红，而不是被 `describe.skipIf` 整组
 * 跳过；产物齐全时它什么也不做，`skipIf` 守卫照常为真。
 *
 * @param {string[]} relPaths 相对仓库根的产物路径
 */
export function requireArtifacts(relPaths) {
  if (!REQUIRE_ARTIFACTS) return;
  const missing = missingArtifacts(relPaths);
  if (missing.length) {
    throw new Error(
      `REQUIRE_ARTIFACTS=1（严格模式）：必需产物缺失 ${missing.length} 个 —— `
      + `${missing.join('、')}（先跑 scripts/build_*_demo.py）`,
    );
  }
}

/**
 * V2 像素对拍除了图纸，还要每份图纸同目录下的 `preview.png`（Pillow 出的参考图）。
 * 返回缺失的那些（相对仓库根）。
 */
export function missingPagePreviews() {
  return DEMO_LAYOUTS
    .map((relPath) => relPath.replace(/\/pagelayout\.json$/, '/preview.png'))
    .filter((relPath) => !existsSync(goldenPath(relPath)));
}

/** 严格模式下要求 `preview.png` 齐；普通模式空操作。 */
export function requirePagePreviews() {
  if (!REQUIRE_ARTIFACTS) return;
  const missing = missingPagePreviews();
  if (missing.length) {
    throw new Error(
      `REQUIRE_ARTIFACTS=1（严格模式）：V2 像素对拍需要的参考图缺失 ${missing.length} 个 —— `
      + `${missing.join('、')}（先跑 scripts/build_*_demo.py）`,
    );
  }
}

/**
 * 严格模式下要求「中文能被光栅化」这条探针成立，否则抛。
 *
 * `v2-pixels.test.mjs` 的像素对拍依赖 sharp 能画出中文；画不出来时整组会 skip，
 * 而"字都没画出来"正好会让对拍失去意义——所以严格模式必须红，不能跳。
 *
 * @param {boolean} ok 探针结果
 * @param {string} detail 探针细节（写进错误信息）
 */
export function requireFontProbe(ok, detail) {
  if (!REQUIRE_ARTIFACTS || ok) return;
  throw new Error(
    'REQUIRE_ARTIFACTS=1（严格模式）：sharp 渲染中文探针失败 —— '
    + `${detail}。运行环境没有可用的中文字体，像素对拍会静默跳过；`
    + '请先按 docs/ci.md 准备好与几何基线一致的字体。',
  );
}


/**
 * 计划里点名的 11 份 demo 图纸（相对仓库根）。
 * 顺序即测试报告里的展示顺序；`demoLayoutPaths()` 会再排一次序。
 */
export const DEMO_LAYOUTS = [
  'out/demo/auto_layout/pagelayout.json',
  'out/demo/auto_layout/_plain/pagelayout.json',
  'out/demo/illustrated/pagelayout.json',
  'out/demo/illustrated/_no_asset/pagelayout.json',
  'out/demo/illustrated/_spread/pagelayout.json',
  'out/demo/multicol/pagelayout.json',
  'out/demo/multicol/_spread/pagelayout.json',
  'out/demo/page/pagelayout.json',
  'out/demo/paper/pagelayout.json',
  'out/demo/theme_match/pagelayout.json',
  'out/demo/theme_match/_no_theme/pagelayout.json',
];

/** 把相对路径解析成绝对路径。 */
export function goldenPath(relPath) {
  return resolve(REPO_ROOT, relPath);
}

/**
 * 读一份金样本。
 *
 * 文件不存在时返回 `null` —— 这是**不变的低层契约**（`v1-structure.test.mjs`
 * 里有一条用例把它钉死：传一个绝对不存在的路径必须返回 null 而不是抛）。
 * 严格模式（`REQUIRE_ARTIFACTS=1`）的"缺产物就红"不在这里实现，而是放在
 * **模块作用域**的 `requireArtifacts([...])` 与 `demoLayoutPaths()` 里：
 * 产物缺了，测试文件在收集阶段就失败，比让每个 `goldenDoc` 调用点各自抛更早、
 * 也更不容易漏（漏掉一个调用点 = 一个静默 skip）。
 *
 * @param {string} relPath 相对仓库根，例如 `out/demo/auto_layout/pagelayout.json`
 * @returns {object|null} 文件不存在时返回 `null`
 */
export function goldenDoc(relPath) {
  const full = goldenPath(relPath);
  if (!existsSync(full)) return null;
  return JSON.parse(readFileSync(full, 'utf8'));
}

/**
 * 当前工作区里真实存在的 demo 图纸路径（相对仓库根），按字典序排序。
 * 一份都不存在时返回 `[]`（严格模式下改成抛，见 `requireArtifacts`）。
 * @returns {string[]}
 */
export function demoLayoutPaths() {
  requireArtifacts(DEMO_LAYOUTS);
  return DEMO_LAYOUTS.filter((relPath) => existsSync(goldenPath(relPath))).sort();
}

/**
 * 一次性读出所有存在的 demo 图纸，便于逐份跑子用例。
 * @returns {Array<{name: string, relPath: string, doc: object}>} `name` 是
 *   相对 `out/demo/` 的短名（如 `multicol/_spread`），用来说明失败是哪一份。
 */
export function demoLayouts() {
  return demoLayoutPaths().map((relPath) => ({
    name: relPath.replace(/^out\/demo\//, '').replace(/\/pagelayout\.json$/, ''),
    relPath,
    doc: goldenDoc(relPath),
  }));
}
