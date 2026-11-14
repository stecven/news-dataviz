/**
 * P2 Task 5 / V1 结构对拍：金样本（`out/demo/**`）的定位与加载。
 *
 * `out/` 被 `.gitignore` 忽略，fresh clone / CI 上这些文件**不存在**。所以本模块
 * 只做「有就读，没有就 `null`」，绝不抛；调用方据此 `describe.skipIf(...)`。
 *
 * **但整组 skip 会让 V1 结构对拍在 CI 上静默全绿**，所以测试文件里另有一条
 * 完全手写合成 doc 的判据（不依赖任何金样本），见 `v1-structure.test.mjs` 的
 * 「合成 doc」组。
 */
import { existsSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
/** `frontend/test/helpers` → 仓库根。 */
export const REPO_ROOT = resolve(HERE, '..', '..', '..');

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
 * @param {string} relPath 相对仓库根，例如 `out/demo/auto_layout/pagelayout.json`
 * @returns {object|null} 文件不存在时返回 `null`（不抛）
 */
export function goldenDoc(relPath) {
  const full = goldenPath(relPath);
  if (!existsSync(full)) return null;
  return JSON.parse(readFileSync(full, 'utf8'));
}

/**
 * 当前工作区里真实存在的 demo 图纸路径（相对仓库根），按字典序排序。
 * 一份都不存在时返回 `[]`。
 * @returns {string[]}
 */
export function demoLayoutPaths() {
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
