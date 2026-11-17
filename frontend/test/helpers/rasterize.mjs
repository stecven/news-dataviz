/**
 * P2 Task 6 / V2 像素对拍：SVG → PNG 光栅化 + 逐像素比对。
 *
 * 本模块只做「机械活」，判据（阈值、掩膜、口径）全在 `v2-pixels.test.mjs` 里。
 * 四条实测口径写死在这里，改之前先读 `task-6-brief.md` 与计划 Task 6：
 *
 * 1. **光栅化前必须把外层 `<svg>` 的展示尺寸改写成 `viewBox` 尺寸**。
 *    `renderPage` 缺省 `scale=96`，10×15 英寸的一页出 `width="960" height="1440"`，
 *    而金样本 `preview.png` 是 `1000×1500`（`PX_PER_IN=100` 口径）。不改写就会
 *    光栅化出 960×1440 → 直接 SIZE MISMATCH。见 {@link rewriteDisplaySize}。
 *
 * 2. **两边都必须 `.removeAlpha()`**。Pillow 产出的 PNG 是 3 通道，SVG 光栅化
 *    出来的是 4 通道（带 alpha）；按同一索引取值会整体错位 —— 实测把相似度
 *    从 99% 砸到 **49%**。见 {@link decodePng}。
 *
 * 3. **不要手设 `xmlns`**。`XMLSerializer` 自己会补；手动 `setAttribute('xmlns', …)`
 *    会让 librsvg 报 `Input buffer has corrupt header: glib: XML parse error:
 *    … Attribute xmlns redefined`（实测踩过）。
 *
 * 4. **「1px 容差」的方向是「金样本的颜色在我的 3×3 邻域里」**，不是反过来，
 *    也不是双向取并。三种写法在真实样本上的差别是**可观测**的（实测卡1）：
 *    正向（我的颜色在金样本邻域里）97.68%、双向并 99.37% 但内部差归零、
 *    本文用的反向 99.37% 且留 10 个内部差 —— 任务书里的 98.8% 边缘占比只有
 *    反向写法能复现。见 {@link comparePixels}。
 *
 * 5. **边缘带用金样本的 4 邻域**（不是 8 邻域）。8 邻域会把全部差异都判成边缘，
 *    边缘占比恒等于 100%，「差值记账」这条判据就变成摆设。
 *
 * 本文件**不 import `src/units.js`**：期望值一律在测试里独立算，免得「用实现
 * 算期望」自证。
 */
import sharp from 'sharp';

/** 渲染器的内部像素密度：1 英寸 = 100 用户单位。与契约同值，**不是** 96。 */
export const PX_PER_IN = 100;

/**
 * 序列化一个 DOM 节点成 XML 串。
 *
 * 用节点自己所属窗口的 `XMLSerializer`（jsdom 环境里 `globalThis.XMLSerializer`
 * 也有，但拿 `ownerDocument` 的更稳）。**不补 `<?xml … ?>` 声明也不要紧**，
 * 但补上能让 librsvg 少猜一次编码。
 *
 * @param {Node} node
 * @returns {string}
 */
export function toSvgString(node) {
  if (node == null) throw new Error('toSvgString: 节点为空');
  const view = node.ownerDocument && node.ownerDocument.defaultView;
  const Serializer = (view && view.XMLSerializer) || globalThis.XMLSerializer;
  if (typeof Serializer !== 'function') {
    throw new Error('toSvgString: 找不到 XMLSerializer（测试需要 DOM 环境）');
  }
  const xml = new Serializer().serializeToString(node);
  return xml.startsWith('<?xml') ? xml : `<?xml version="1.0" encoding="UTF-8"?>\n${xml}`;
}

/**
 * 取根 `<svg>` 的 `viewBox` 尺寸。
 * @param {string} xml
 * @returns {{width: number, height: number}}
 */
export function viewBoxSize(xml) {
  const match = /viewBox="\s*(-?[\d.]+)[\s,]+(-?[\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)\s*"/.exec(xml);
  if (!match) throw new Error('viewBoxSize: 根 <svg> 上没有可解析的 viewBox');
  const width = Number(match[3]);
  const height = Number(match[4]);
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
    throw new Error(`viewBoxSize: viewBox 尺寸不合法（读到 ${match[3]} × ${match[4]}）`);
  }
  return { width, height };
}

/**
 * 把**根 `<svg>` 标签**的展示尺寸 `width`/`height` 改写成 `viewBox` 尺寸。
 *
 * 只动第一个 `<svg …>` 开标签里的两个属性：子节点里同名属性（比如背景 `<rect>`
 * 的 `width`）一个都不碰。
 *
 * @param {string} xml
 * @param {{width?: number, height?: number}} [opts] 显式指定目标尺寸（缺省取 viewBox）
 * @returns {{xml: string, width: number, height: number, display: {width: string, height: string}}}
 *   `display` 是改写**之前**读到的展示尺寸，失败时用来报「你忘了改写」。
 */
export function rewriteDisplaySize(xml, opts = {}) {
  const rootTag = /<svg\b[^>]*>/.exec(xml);
  if (!rootTag) throw new Error('rewriteDisplaySize: 找不到根 <svg> 标签');
  const raw = rootTag[0];
  const box = viewBoxSize(xml);
  const width = opts.width == null ? box.width : Number(opts.width);
  const height = opts.height == null ? box.height : Number(opts.height);
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
    throw new Error(`rewriteDisplaySize: 目标尺寸不合法（${width} × ${height}）`);
  }

  const before = {
    width: (/<svg\b[^>]*?\swidth="([^"]*)"/.exec(raw) || [])[1],
    height: (/<svg\b[^>]*?\sheight="([^"]*)"/.exec(raw) || [])[1],
  };

  let patched = raw;
  // 没有 width / height 属性时也要补上：librsvg 缺这两个属性会按 300×150 兜底。
  patched = /\swidth="[^"]*"/.test(patched)
    ? patched.replace(/\swidth="[^"]*"/, ` width="${width}"`)
    : patched.replace(/<svg\b/, `<svg width="${width}"`);
  patched = /\sheight="[^"]*"/.test(patched)
    ? patched.replace(/\sheight="[^"]*"/, ` height="${height}"`)
    : patched.replace(/<svg\b/, `<svg height="${height}"`);

  return {
    xml: xml.slice(0, rootTag.index) + patched + xml.slice(rootTag.index + raw.length),
    width,
    height,
    display: before,
  };
}

/**
 * 把 SVG 光栅化成 PNG。
 *
 * `svg` 可以是 DOM 节点，也可以是现成的 XML 串。展示尺寸缺省按 {@link rewriteDisplaySize}
 * 改写成 `viewBox` 尺寸 —— 也就是说，**调用方不需要自己先改**；想强制别的尺寸就
 * 传 `{width, height}`。
 *
 * @param {SVGSVGElement|string} svg
 * @param {{width?: number, height?: number}} [opts]
 * @returns {Promise<{buffer: Buffer, width: number, height: number, display: {width?: string, height?: string}}>}
 *   `width`/`height` 是**期望**的光栅化尺寸；实际尺寸用 {@link decodePng} 读。
 */
export async function svgToPng(svg, opts = {}) {
  const xml = typeof svg === 'string' ? svg : toSvgString(svg);
  const sized = rewriteDisplaySize(xml, opts);
  const buffer = await sharp(Buffer.from(sized.xml, 'utf8')).removeAlpha().png().toBuffer();
  return {
    buffer, width: sized.width, height: sized.height, display: sized.display,
  };
}

/**
 * 解码一张 PNG（Buffer / 路径 / 任何 sharp 吃得下的输入）成 3 通道裸像素。
 *
 * `.removeAlpha()` 是**必做**的那一步：不做的话金样本（Pillow 出的 3 通道）与
 * 我方（SVG 光栅化的 4 通道）通道数不同，逐像素索引整体错位 —— 实测相似度
 * 49%。这里顺手把「通道数不是 3」变成**抛错**，免得下次又静默错位。
 *
 * @param {Buffer|string} input
 * @returns {Promise<{data: Uint8Array, width: number, height: number, channels: 3}>}
 */
export async function decodePng(input) {
  const { data, info } = await sharp(input).removeAlpha().raw().toBuffer({ resolveWithObject: true });
  if (info.channels !== 3) {
    throw new Error(
      `decodePng: 期望 3 通道（removeAlpha 之后），实际 ${info.channels} 通道`
      + `（${info.width}×${info.height}）`,
    );
  }
  return {
    data, width: info.width, height: info.height, channels: 3,
  };
}

/**
 * 一列文字元素的**契约盒**掩膜（px 四元组，外扩 `pad`）。
 *
 * 为什么不能用 `<text>` 的 `x`/`y`/`font-size` 粗估：粗估（宽 = 字数 × 字号）
 * 会多掩 **30.55%** 画面、把整页相似度压到 `94.97% ~ 95.60%`（假红）。契约盒
 * 是排版阶段冻结的真值，`x_in/y_in/w_in/h_in` × `PX_PER_IN` 就是像素盒。
 *
 * 取整口径：**截断**（`Math.trunc`），与 `loop/preview.py` 的 `int(x*100)` 一致。
 * 实测截断口径的整页非文字像素 `356810`、四舍五入口径 `356582`，任务书里的
 * 数字是截断那一套。
 *
 * @param {object[]} elements 契约元素数组
 * @param {{ox?: number, oy?: number, pad?: number, width?: number, height?: number}} [opts]
 *   `ox`/`oy` 把卡片局部坐标平移到页坐标；`width`/`height` 给了就把盒子裁进画面。
 * @returns {number[][]} `[[x0, y0, x1, y1], …]`（半开区间）
 */
export function textMaskBoxes(elements, opts = {}) {
  const pad = opts.pad == null ? 2 : Number(opts.pad);
  const ox = Number(opts.ox) || 0;
  const oy = Number(opts.oy) || 0;
  const boxes = [];
  for (const el of Array.isArray(elements) ? elements : []) {
    if (!el || el.type !== 'text') continue;
    const x0 = Math.trunc((Number(el.x_in) || 0) * PX_PER_IN) + ox - pad;
    const y0 = Math.trunc((Number(el.y_in) || 0) * PX_PER_IN) + oy - pad;
    const x1 = Math.trunc(((Number(el.x_in) || 0) + (Number(el.w_in) || 0)) * PX_PER_IN) + ox + pad;
    const y1 = Math.trunc(((Number(el.y_in) || 0) + (Number(el.h_in) || 0)) * PX_PER_IN) + oy + pad;
    if (opts.width != null) {
      if (x1 <= 0 || x0 >= opts.width) continue;
    }
    if (opts.height != null) {
      if (y1 <= 0 || y0 >= opts.height) continue;
    }
    boxes.push([x0, y0, x1, y1]);
  }
  return boxes;
}

/**
 * 把盒列表烧成位图掩膜（1 = 掩掉）。
 * @param {number} width
 * @param {number} height
 * @param {number[][]} boxes
 * @returns {Uint8Array}
 */
export function maskOf(width, height, boxes) {
  const mask = new Uint8Array(width * height);
  for (const [bx0, by0, bx1, by1] of boxes) {
    const x0 = Math.max(0, Math.trunc(bx0));
    const y0 = Math.max(0, Math.trunc(by0));
    const x1 = Math.min(width, Math.trunc(bx1));
    const y1 = Math.min(height, Math.trunc(by1));
    for (let y = y0; y < y1; y += 1) {
      const row = y * width;
      for (let x = x0; x < x1; x += 1) mask[row + x] = 1;
    }
  }
  return mask;
}

/** 从 `[x0, y0, x1, y1]` 盒列表里统计「被掩掉的像素数」（重叠只算一次）。 */
export function maskedCount(width, height, boxes) {
  const mask = maskOf(width, height, boxes);
  let count = 0;
  for (let i = 0; i < mask.length; i += 1) count += mask[i];
  return count;
}

/**
 * 金样本的**4 邻域**边缘带（1 = 该像素与外向邻居颜色不同）。
 *
 * 为什么是 4 邻域不是 8：8 邻域会把全部差异都判成边缘（实测三处占比都是
 * 100%），「描边差占全部差异 ≥60%」这条判据随之失去意义。4 邻域实测
 * 卡1 98.8% / 卡2 96.5% / 整页 97.9%，正是任务书里的数字。
 *
 * @param {{data: Uint8Array, width: number, height: number, channels: number}} raw
 * @returns {Uint8Array}
 */
export function edgeBand(raw) {
  const {
    data, width, height, channels,
  } = raw;
  const edge = new Uint8Array(width * height);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const i = (y * width + x) * channels;
      const r = data[i];
      const g = data[i + 1];
      const b = data[i + 2];
      let hit = 0;
      for (let k = 0; k < 4; k += 1) {
        const nx = x + (k === 0 ? -1 : k === 1 ? 1 : 0);
        const ny = y + (k === 2 ? -1 : k === 3 ? 1 : 0);
        if (nx < 0 || nx >= width || ny < 0 || ny >= height) continue;
        const j = (ny * width + nx) * channels;
        if (data[j] !== r || data[j + 1] !== g || data[j + 2] !== b) {
          hit = 1;
          break;
        }
      }
      if (hit) edge[y * width + x] = 1;
    }
  }
  return edge;
}

/** 像素是否完全相同。 */
function sameAt(a, ai, b, bi) {
  return a[ai] === b[bi] && a[ai + 1] === b[bi + 1] && a[ai + 2] === b[bi + 2];
}

/**
 * 「1px 容差」判据：金样本在该像素的颜色，**出现在我的 3×3 邻域里**。
 *
 * 语义是「我的这格内容最多被挪了 1px」，而不是「我的颜色在金样本附近」——
 * 方向写反会松到卡1 97.68%、双向取并会把内部差吃干（实测内部差 10 → 0），
 * 两者都复现不出任务书里的边缘占比。见文件头第 4 条。
 */
function withinOnePixel(golden, mine, width, height, x, y) {
  const gi = (y * width + x) * golden.channels;
  for (let dy = -1; dy <= 1; dy += 1) {
    const ny = y + dy;
    if (ny < 0 || ny >= height) continue;
    for (let dx = -1; dx <= 1; dx += 1) {
      const nx = x + dx;
      if (nx < 0 || nx >= width) continue;
      if (sameAt(golden.data, gi, mine.data, (ny * width + nx) * mine.channels)) return true;
    }
  }
  return false;
}

/**
 * 逐像素比对：非文字像素的 exact / 1px 容差 / 差值分类。
 *
 * 只统计**掩膜之外**的像素（掩膜 = 文字契约盒，见 {@link textMaskBoxes}）。
 *
 * @param {Buffer|object} golden 金样本（PNG Buffer 或 {@link decodePng} 的产物）
 * @param {Buffer|object} mine 我方渲染（同上）
 * @param {{width: number, height: number, boxes: number[][]}} mask
 *   尺寸 + 要掩掉的盒列表；`boxes` 可省略（= 不掩）
 * @param {{innerSampleLimit?: number}} [opts]
 * @returns {Promise<object>} 见下方 return
 */
export async function comparePixels(golden, mine, mask, opts = {}) {
  const g = Buffer.isBuffer(golden) || typeof golden === 'string'
    ? await decodePng(golden) : golden;
  const m = Buffer.isBuffer(mine) || typeof mine === 'string'
    ? await decodePng(mine) : mine;
  const width = mask && mask.width != null ? mask.width : g.width;
  const height = mask && mask.height != null ? mask.height : g.height;

  // SIZE MISMATCH 必须是**第一条**断言：尺寸不同时逐像素比较毫无意义，
  // 而「忘了改写展示尺寸」正是最容易犯的错（960×1440 vs 1000×1500）。
  if (g.width !== m.width || g.height !== m.height) {
    throw new Error(
      `SIZE MISMATCH: 金样本 ${g.width}×${g.height}，我方 ${m.width}×${m.height}`
      + '（多半是光栅化前没把外层 <svg> 的展示尺寸改写成 viewBox 尺寸）',
    );
  }
  if (width !== g.width || height !== g.height) {
    throw new Error(
      `SIZE MISMATCH: 掩膜/区域 ${width}×${height} 与图像 ${g.width}×${g.height} 不一致`,
    );
  }

  const boxes = (mask && mask.boxes) || [];
  const skipped = maskOf(width, height, boxes);
  const edge = edgeBand(g);
  const innerSampleLimit = opts.innerSampleLimit == null ? 40 : opts.innerSampleLimit;

  let considered = 0;
  let exact = 0;
  let within1px = 0;
  let within1 = 0; // 逐通道差 ≤1（诊断口径，不进判据）
  let diffCount = 0;
  let edgeDiff = 0;
  let innerDiff = 0;
  /** @type {object[]} */
  const innerSamples = [];

  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const p = y * width + x;
      if (skipped[p]) continue;
      considered += 1;
      const gi = p * g.channels;
      const mi = p * m.channels;
      if (sameAt(g.data, gi, m.data, mi)) {
        exact += 1;
        within1px += 1;
        within1 += 1;
        continue;
      }
      const dr = Math.abs(g.data[gi] - m.data[mi]);
      const dg = Math.abs(g.data[gi + 1] - m.data[mi + 1]);
      const db = Math.abs(g.data[gi + 2] - m.data[mi + 2]);
      if (dr <= 1 && dg <= 1 && db <= 1) within1 += 1;
      const displaced = withinOnePixel(g, m, width, height, x, y);
      if (displaced) {
        within1px += 1;
        continue;
      }
      diffCount += 1;
      if (edge[p]) {
        edgeDiff += 1;
      } else {
        innerDiff += 1;
        if (innerSamples.length < innerSampleLimit) {
          innerSamples.push({
            x,
            y,
            golden: [g.data[gi], g.data[gi + 1], g.data[gi + 2]],
            mine: [m.data[mi], m.data[mi + 1], m.data[mi + 2]],
          });
        }
      }
    }
  }

  const pct = (n) => (considered === 0 ? 0 : (n / considered) * 100);
  return {
    width,
    height,
    /** 参与统计的像素数（非文字）。 */
    considered,
    /** 被文字掩膜掩掉的像素数。 */
    masked: width * height - considered,
    exact,
    within1px,
    /** 仅逐通道差 ≤1 的像素数（诊断用，比 exact 松、比 1px 容差严）。 */
    within1,
    /** 未被 1px 容差吸收的差异像素总数。 */
    diffCount,
    /** 差异里落在金样本 4 邻域边缘带内的像素数。 */
    edgeDiff,
    /** 差异里落在平色块内部的像素数。 */
    innerDiff,
    /** 各百分比（0..100，未取整）。 */
    exactPct: pct(exact),
    within1Pct: pct(within1px),
    within1DeltaPct: pct(within1),
    edgeShareOfDiffPct: diffCount === 0 ? 100 : (edgeDiff / diffCount) * 100,
    /** 内部差异样本（最多 `innerSampleLimit` 个），供测试打印。 */
    innerSamples,
    /** 边缘带位图（调试用）。 */
    edgeBand: edge,
  };
}
