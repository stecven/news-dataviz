/**
 * 整版渲染：把一份 `pagelayout.json` 画成一页 SVG。
 *
 * 绘制顺序对齐 `loop/render_page.py::compose_preview`：
 *
 *   1. 画布底色（主题的 `surface` 角色），尺寸 = 图纸的宽高（单位英寸）→ 像素
 *   2. 卡片：每张卡片是**嵌套 `<svg>`**，位置用 `roundPx`、尺寸用 `truncPx`
 *   3. 整版块：逐栏、逐行画 `<text>`，从块顶 + `BLOCK_PAD_IN` 起排
 *   4. 插图：按 `rect` 给出的**真实绘制矩形**落位
 *
 * 两套取整口径是 Python 侧的真实行为，不是笔误：卡片**贴图位置**在
 * `render_page.py` 里走 `int(round(x_in*100))`，而卡片 **PNG 尺寸**来自
 * `render_preview` 的 `int(w_in*100)`（截断）。实测卡1 `w=6.072` → 607×337、
 * 贴在 `y=239`（`2.3875*100 = 238.75`）。所以这里绝不"统一"成一种。
 */
import {
  PX_PER_IN, boxPxTrunc, pageScale as pageScaleOf, pyRound, roundPx, truncPx,
} from '../units.js';
import { createTheme } from '../theme.js';
import { normalizeDoc } from '../doc.js';
import { renderElement } from './primitives.js';
import { renderText } from './text.js';

const SVG_NS = 'http://www.w3.org/2000/svg';

/**
 * 整版块从块顶往下留的白（英寸）。
 *
 * 与 `loop/text_flow.py::BLOCK_PAD_IN` 同值：Pillow 侧不把文字贴到块的最上沿，
 * 因为字形上升部（ascent）已经吃掉一段，再贴边会显得顶格。
 */
export const BLOCK_PAD_IN = 0.05;

/** 虚线占位的线型，与 `primitives.js` 的同名字面量一致。 */
const PLACEHOLDER_DASH = '6 4';

/** 缺省 `scale`：每英寸展示像素数（只影响外层 `width`/`height`，见 `renderPage`）。 */
const DEFAULT_SCALE = 96;

/** 缺省资源前缀：图纸里的 `image_path` 多为 `assets/icons/x.png`，原样拼在后面。 */
const DEFAULT_ASSETS_BASE = 'assets';

/**
 * 解析容器参数：选择器字符串 / DOM 节点 / `null`（只建不挂）。
 *
 * `null` 是合法输入 —— 任务书允许"只拿到一棵 SVG 树、不挂进文档"，这也是
 * `exportSVG` 之类后续能力的基础。
 */
function resolveContainer(container) {
  if (container == null) return null;
  if (typeof container === 'string') {
    const found = document.querySelector(container);
    if (!found) {
      throw new Error(`renderPage: 找不到容器 ${JSON.stringify(container)}`);
    }
    return found;
  }
  if (typeof container.appendChild === 'function') return container;
  throw new Error(
    `renderPage: 容器既不是选择器也不是 DOM 节点（读到 ${typeof container}）`,
  );
}

/** 一个裸 `<svg>` 节点；**不**手设 `xmlns`（序列化器自己会补）。 */
function svgNode(attrs) {
  const node = document.createElementNS(SVG_NS, 'svg');
  for (const [key, value] of Object.entries(attrs)) {
    if (value == null) continue;
    node.setAttribute(key, String(value));
  }
  return node;
}

/**
 * 画一张卡片：嵌套 `<svg>`，用 `viewBox` 自带裁切（不用 `<g transform>`）。
 *
 * 位置 `roundPx`、尺寸 `truncPx`，见文件头注释。
 */
function renderCard(parent, card, ctx) {
  const w = truncPx(card.w_in);
  const h = truncPx(card.h_in);
  const node = svgNode({
    x: roundPx(card.x_in),
    y: roundPx(card.y_in),
    width: w,
    height: h,
    viewBox: `0 0 ${w} ${h}`,
    // 卡片里的图形是按卡片自己的坐标系画的，溢出**必须**裁掉，否则液柱/半圆
    // 会画到隔壁卡片上。`viewBox` 只负责缩放，裁剪要靠 `overflow`。
    overflow: 'hidden',
  });
  // 卡片容器不是契约元素，不打 `data-el-id`：T5 的节点口径只数带这个属性的节点。
  node.setAttribute('data-card-name', card.name);
  parent.appendChild(node);

  const elements = card.spec && Array.isArray(card.spec.elements) ? card.spec.elements : null;
  if (!elements) {
    if (Array.isArray(ctx.warnings)) {
      ctx.warnings.push(
        `卡片 ${JSON.stringify(card.name)} 缺 spec.elements，只画空卡片（不抛）`,
      );
    }
    return node;
  }

  // Review Focus #5：所有文字晚于所有形状。卡片元素在数组里是**交错**的
  // （frame, title_band, title, scope_note, track, outline, ...），按数组序画会让
  // 后画的形状盖住先画的字。Python 侧同样先形状后文字（`preview.py::_render_order`）。
  const texts = elements.filter((el) => el && el.type === 'text');
  const shapes = elements.filter((el) => el && el.type !== 'text');
  for (const el of shapes) renderElement(node, el, ctx);
  for (const el of texts) renderElement(node, el, ctx);
  return node;
}

/**
 * 画一个整版块：按 `line_groups` 逐栏、逐行画。
 *
 * 多栏是**真会出现的**（`out/demo/multicol/_spread/pagelayout.json` 第 4 块
 * `columns=2`），所以这里逐栏渲染、不降级也不告警。
 */
function renderBlock(parent, block, ctx) {
  const groups = Array.isArray(block.line_groups) && block.line_groups.length > 0
    ? block.line_groups
    : [Array.isArray(block.lines) ? block.lines : []];
  const count = groups.length;
  const gutter = Number(block.column_gutter_in) || 0;
  const inner = count > 0
    ? (Number(block.w_in) - (count - 1) * gutter) / count
    : Number(block.w_in);
  const y0 = roundPx(Number(block.y_in) + BLOCK_PAD_IN);

  for (let k = 0; k < count; k += 1) {
    const x0 = roundPx(Number(block.x_in) + k * (inner + gutter));
    const x1 = roundPx(Number(block.x_in) + k * (inner + gutter) + inner);
    // `mode: 'block'` 取字号走 `theme.fontPt(block.style)`（设计角色直查），再按
    // `ctx.pageScale` 缩放并钳进 `theme.fontPtClamp()`（对齐
    // `loop/palette.py::scaled_font_size`）——字号必须跟着画布走，否则整版放大
    // 一倍时块文字还是原尺寸。`box` 直接给页口径的取整像素，`noDy` 关掉卡片那套
    // 竖直居中 —— 整版块从块顶 + 0.05in 起排，没有 dy（对齐
    // `loop/render_page.py::_draw_block`）。
    renderText(parent, {
      id: block.name,
      role: block.style,
      geometry: { lines: groups[k], align: block.align },
    }, {
      theme: ctx.theme,
      mode: 'block',
      box: [x0, y0, x1, y0 + Number(block.h_in) * PX_PER_IN],
      noDy: true,
      pageScale: ctx.pageScale,
    });
  }
}

/**
 * 画一张插图。
 *
 * 位置与尺寸来自 `image.rect`（**盒内真实绘制矩形**），不是外盒 `w_in`/`h_in`：
 * `illustrated` 那套样本的外盒是 4.5in（450 像素），而 `rect` 只占 2.84in。
 * 尺寸用 `roundPx`（283），不用 `truncPx`（282）—— 与 Python 的
 * `int(round(dw*100))` 一致。
 */
function renderIllustration(parent, image, ctx) {
  const theme = ctx.theme;
  const rect = Array.isArray(image.rect) ? image.rect : [0, 0, image.w_in, image.h_in];
  const box = {
    x: roundPx(Number(image.x_in) + Number(rect[0] || 0)),
    y: roundPx(Number(image.y_in) + Number(rect[1] || 0)),
    width: Math.max(1, roundPx(Number(rect[2] || 0))),
    height: Math.max(1, roundPx(Number(rect[3] || 0))),
  };
  const path = image.path;
  const href = path == null || String(path) === ''
    ? null
    : (typeof ctx.resolveAsset === 'function'
      ? ctx.resolveAsset(path)
      : `${ctx.assetsBase}/${path}`);

  if (href == null || String(href) === '') {
    const node = document.createElementNS(SVG_NS, 'rect');
    node.setAttribute('data-el-id', image.name);
    node.setAttribute('x', String(box.x));
    node.setAttribute('y', String(box.y));
    node.setAttribute('width', String(box.width));
    node.setAttribute('height', String(box.height));
    node.setAttribute('fill', 'none');
    node.setAttribute('stroke', theme.color('placeholder_stroke'));
    node.setAttribute('stroke-dasharray', PLACEHOLDER_DASH);
    const message = `插图 ${JSON.stringify(image.name)} 的图片资源 `
      + `${JSON.stringify(path)} 取不到，画虚线占位框`;
    const note = document.createElementNS(SVG_NS, 'title');
    note.textContent = message;
    node.appendChild(note);
    parent.appendChild(node);
    if (Array.isArray(ctx.warnings)) ctx.warnings.push(message);
    return node;
  }

  const node = document.createElementNS(SVG_NS, 'image');
  node.setAttribute('data-el-id', image.name);
  node.setAttribute('x', String(box.x));
  node.setAttribute('y', String(box.y));
  node.setAttribute('width', String(box.width));
  node.setAttribute('height', String(box.height));
  node.setAttribute('href', String(href));
  parent.appendChild(node);
  return node;
}

/**
 * 把一份图纸画成一页 SVG。
 *
 * @param {Element|string|null} container 挂载点（选择器 / DOM 节点 / `null` 只建不挂）
 * @param {object} doc 解析好的 `pagelayout.json`
 * @param {{scale?: number, assetsBase?: string, resolveAsset?: Function}} [opts]
 * @returns {{svg: SVGSVGElement, warnings: string[]}}
 *
 * `opts.scale` 是**展示**用的每英寸像素数（缺省 96），只写进外层 `width`/`height`。
 * 内部一律 100 像素每英寸：`viewBox` 与所有子节点坐标都不受 `scale` 影响。
 * 换句话说，`scale` 是"这页在屏幕上多大"，不是"这页怎么画"——把它混进任何
 * 取整换算，都会与 Pillow 的像素结果错开。
 */
export function renderPage(container, doc, opts = {}) {
  const host = resolveContainer(container);
  const normalized = normalizeDoc(doc);
  const page = normalized.doc;
  const warnings = normalized.warnings.slice();
  // theme 缺失时 `createTheme` 会抛 —— 这是有意的：没有色板就画不出任何东西，
  // 静默画一页空白比崩难查得多。
  const theme = createTheme(page.theme);

  const widthPx = roundPx(Number(page.width_in));
  const heightPx = roundPx(Number(page.height_in));
  const scale = opts.scale == null ? DEFAULT_SCALE : Number(opts.scale);
  if (!Number.isFinite(scale) || scale <= 0) {
    throw new Error(`renderPage: opts.scale 必须是正数，实际是 ${JSON.stringify(opts.scale)}`);
  }

  const svg = svgNode({
    // 展示尺寸：由 scale 决定（缺省 96 → 10in 宽的一页是 960 像素）。
    // 注意这里**不能**用 `roundPx`：那个函数自带 `×100`（英寸 → 内部像素），
    // 而展示尺寸的单位已经是像素，乘进去会得到 96000。
    width: pyRound(scale * Number(page.width_in)),
    height: pyRound(scale * Number(page.height_in)),
    // 内部坐标：固定 100 像素每英寸，与所有子节点的取整口径同一个坐标系
    viewBox: `0 0 ${widthPx} ${heightPx}`,
  });

  // 1. 画布底色
  const background = document.createElementNS(SVG_NS, 'rect');
  background.setAttribute('data-role', 'page-background');
  background.setAttribute('x', '0');
  background.setAttribute('y', '0');
  background.setAttribute('width', String(widthPx));
  background.setAttribute('height', String(heightPx));
  background.setAttribute('fill', theme.color('surface'));
  svg.appendChild(background);

  const assetsBase = opts.assetsBase == null ? DEFAULT_ASSETS_BASE : String(opts.assetsBase);
  // 整版块的字体缩放比：画布相对**基准画布**的比例（`loop/palette.py::canvas_scale`），
  // 基准取自图纸的 `theme.base_canvas_in`（缺省 10×6）。只影响 block 模式的字号，
  // 与卡片元素冻结的 `font_pt` 无关 —— 也**不许**混进任何坐标取整。
  const pageScale = pageScaleOf(
    Number(page.width_in), Number(page.height_in), theme.baseCanvasIn(),
  );
  const ctx = {
    theme,
    mode: 'card',
    pageScale,
    // R47：没给 `resolveAsset` 就按 `assetsBase + '/' + path` 拼，`path` 用原文。
    // 给了就**原样转发原文**（不预先拼接），调用方自己决定怎么落成 URL。
    resolveAsset: typeof opts.resolveAsset === 'function'
      ? opts.resolveAsset
      : (path) => `${assetsBase}/${path}`,
    assetsBase,
    warnings,
  };

  // 2. 卡片
  const cards = Array.isArray(page.cards) ? page.cards : [];
  for (const card of cards) renderCard(svg, card, ctx);

  // 3. 整版块
  const blocks = Array.isArray(page.blocks) ? page.blocks : [];
  for (const block of blocks) renderBlock(svg, block, ctx);

  // 4. 插图（最后贴，压在所有文字之上 —— 与 `compose_preview` 的调用顺序一致）
  const images = Array.isArray(page.images) ? page.images : [];
  for (const image of images) renderIllustration(svg, image, ctx);

  if (host) host.appendChild(svg);
  return { svg, warnings };
}

/**
 * 内部用，给测试/调试留一个口：卡片盒的截断像素（尺寸口径）。
 *
 * T5 的卡片结构对拍会用到它（卡片尺寸走 `truncPx`、位置走 `roundPx`，两套口径
 * 不能混）。
 */
export function cardBoxPx(card) {
  return {
    x: roundPx(card.x_in),
    y: roundPx(card.y_in),
    width: truncPx(card.w_in),
    height: truncPx(card.h_in),
  };
}

/**
 * 内部用：元素盒（截断口径），主要是为了让调试脚本能复用同一套取整。
 *
 * T5 的元素结构对拍会用到它。
 */
export function elementBoxPx(el) {
  return boxPxTrunc(el);
}
