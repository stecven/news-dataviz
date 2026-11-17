/**
 * 只读渲染 demo：把 `out/demo/auto_layout/pagelayout.json` 画成一页 SVG。
 *
 * 跑法（从**仓库根**起服务，页面里的相对路径是按这个前提写的）：
 *
 *   python -m http.server 8765
 *   浏览器打开 http://127.0.0.1:8765/frontend/demo/
 *
 * 这是临时验证用的静态页，不要把它变成产品入口；它存在的意义是让人用眼睛看
 * 一眼"整版渲染骨架"画出来的东西对不对（结构对拍在 vitest 里，像素对拍在 T6）。
 */
import { mountPage } from '../src/index.js';

const SPEC_URL = '../../out/demo/auto_layout/pagelayout.json';

/** 展示用的每英寸像素数：10×15in 的一页缩到 500×750，普通屏幕放得下。 */
const DEMO_SCALE = 50;

const stage = document.querySelector('#stage');
const warningBox = document.querySelector('#warnings');

function showWarnings(warnings) {
  if (!warnings.length) return;
  warningBox.textContent = warnings.map((message) => `⚠ ${message}`).join('\n');
}

async function main() {
  const response = await fetch(SPEC_URL);
  if (!response.ok) {
    throw new Error(`取 ${SPEC_URL} 失败：HTTP ${response.status}`);
  }
  const doc = await response.json();

  const page = mountPage(stage, doc, {
    scale: DEMO_SCALE,
    // 图纸里的 `image_path` 形如 `assets/icons/x.png`，相对**仓库根**。
    // 本页在 `/frontend/demo/` 下，所以往上退两级。R47：这个回调收到的是原文。
    resolveAsset: (path) => `../../${path}`,
  });

  // v1 只有 warning 一个事件；`on` 会补发挂载阶段就已产生的那些。
  const warnings = [];
  page.on('warning', (message) => {
    warnings.push(message);
    showWarnings(warnings);
  });

  // 便于在控制台里手动把玩
  globalThis.page = page;
}

main().catch((error) => {
  warningBox.textContent = `渲染失败：${error.message}`;
  console.error(error);
});
