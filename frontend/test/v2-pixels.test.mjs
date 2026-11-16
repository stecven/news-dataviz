// @vitest-environment jsdom
/**
 * P2 Task 6 / V2 像素对拍。
 *
 * 把 JS 渲染出来的 SVG 光栅化成 PNG，与 Python（Pillow）产出的金样本 PNG 逐像素比，
 * 证明**形状对得上**。三个口径（数字全部来自实测，不要改阈值）：
 *
 * | 口径 | 非文字像素 | exact | 1px 容差 |
 * |---|---|---|---|
 * | 卡1 `card_00_heat_ratio_top5.png` (607×337) | 129551 | 96.79% | 99.37% |
 * | 卡2 `card_01_heat_age.png` (607×496) | 226652 | 99.04% | 99.76% |
 * | 整页卡片区域（`preview.png` 1000×1500） | 356810 | 98.22% | 99.62% |
 *
 * **主判据是卡片级**（每张卡 1px 容差 ≥98%）；整页用「卡片区域内」那个口径。
 * 整页全画面口径只当诊断打印、不设判据 —— 那里面大头是插图位图重采样，差异无意义。
 *
 * 五条会让人假红/假绿的坑（都踩过，见 `helpers/rasterize.mjs` 文件头）：
 * 1. 光栅化前必须把外层 `<svg>` 的展示尺寸改写成 `viewBox` 尺寸（960×1440 vs 1000×1500）。
 * 2. 两边都必须 `.removeAlpha()`（通道错位能把相似度砸到 49%）。
 * 3. 文字掩膜必须用**契约盒**，不能拿 `<text>` 的 `x`/`y`/`font-size` 粗估
 *    （粗估多掩 30.55% 画面，整页掉到 94.97%~95.60%，是假红）。
 * 4. 「1px 容差」的方向是「金样本的颜色在我的 3×3 邻域里」。
 * 5. 边缘带用金样本的 **4 邻域**（8 邻域会让「描边差 ≥60%」这条判据变成恒真）。
 *
 * 另外两条不依赖金样本的判据（`out/` 被 gitignore，fresh clone 上金样本不存在）：
 * - 「合成 doc」组：光栅化合成图纸，断言尺寸与背景色 —— 这条永远跑，防止整组静默全绿。
 * - `0.5` 平局用例：`pyRound` 的 half-to-even 与 `Math.round` 的分歧。
 */
import { existsSync, readFileSync } from 'node:fs';
import { extname, resolve } from 'node:path';

import sharp from 'sharp';
import { describe, expect, it } from 'vitest';

import { renderPage } from '../src/render/stage.js';
import { pyRound } from '../src/units.js';
import {
  PX_PER_IN,
  comparePixels,
  decodePng,
  maskedCount,
  maskOf,
  rewriteDisplaySize,
  svgToPng,
  textMaskBoxes,
  toSvgString,
} from './helpers/rasterize.mjs';
import { REPO_ROOT, demoLayouts, goldenPath } from './helpers/golden.mjs';

/** 主判据阈值：卡片级 / 整页卡片区域，1px 容差内 ≥ 98%。 */
const MIN_WITHIN_1PX_PCT = 98;
/** 差值记账：描边差（金样本 4 邻域边缘带内的像素）占全部差异 ≥ 60%。 */
const MIN_EDGE_SHARE_PCT = 60;

// ---------------------------------------------------------------------------
// 合成 doc：不依赖任何金样本（fresh clone / CI 上只有这一组会跑）
// ---------------------------------------------------------------------------

const SYNTH_THEME = {
  palette: {
    primary: '1F4E79',
    secondary: 'C0504D',
    accent_1: '9BBB59',
    accent_2: '8064A2',
    accent_3: '4BACC6',
    neutral_dark: '000000',
    neutral_strong: '404040',
    neutral_mid: '808080',
    neutral_light: 'D9D9D9',
    neutral_hairline: 'BFBFBF',
    // 刻意不用 FFFFFF：背景色断言要在「不是白纸」的前提下才有鉴别力。
    surface: 'FDF6E3',
  },
  font_sizes: {
    title: 20, subtitle: 14, body: 11, label: 9, note: 8,
  },
  base_canvas_in: [10, 6],
  font_pt_clamp: [6, 24],
  role_to_font: {
    title: 'title',
    scale_note: 'note',
    legend: 'label',
    label: 'label',
    value: 'body',
    center: 'subtitle',
  },
};

/** 10×15 英寸页 + 一张 4×3 英寸卡（rect 边框 + 一行字 + 一个实心圆）。 */
const SYNTH_DOC = {
  version: '1.0',
  width_in: 10,
  height_in: 15,
  margin_in: 0.4,
  gutter_in: 0.3,
  column_count: 1,
  column_gutter_in: 0.2,
  theme: SYNTH_THEME,
  rows: [],
  cards: [
    {
      name: 'synth_card',
      kind: 'chart',
      x_in: 0.4,
      y_in: 1,
      w_in: 4,
      h_in: 3,
      row: 0,
      column_span: 1,
      spec: {
        width_in: 4,
        height_in: 3,
        chart_key: 'synth',
        chart_title: '合成卡',
        scale: { v_max: 1, h_in: 3, unit: '' },
        elements: [
          {
            id: 'frame',
            type: 'rect',
            role: 'frame',
            x_in: 0,
            y_in: 0,
            w_in: 4,
            h_in: 3,
            fill: 'FFFFFF',
            geometry: { border: 'A8AEB6' },
          },
          {
            id: 'headline',
            type: 'text',
            role: 'title',
            x_in: 0.1,
            y_in: 0.1,
            w_in: 3.8,
            h_in: 0.6,
            font_pt: 12,
            lines: ['合成标题'],
          },
          {
            id: 'dot',
            type: 'ellipse',
            role: 'value',
            x_in: 0.2,
            y_in: 2,
            w_in: 1,
            h_in: 1,
            fill: '1F4E79',
          },
        ],
      },
    },
  ],
  blocks: [
    {
      name: 'synth_block',
      style: 'body',
      align: 'left',
      text: '合成正文',
      lines: ['合成正文'],
      line_groups: [['合成正文']],
      x_in: 0.4,
      y_in: 5,
      w_in: 9.2,
      h_in: 0.5,
      row: 0,
      column_span: 1,
      columns: 1,
      column_gutter_in: 0,
    },
  ],
  images: [],
};

/** 合成页的期望像素尺寸：10×15 英寸 × `PX_PER_IN`。 */
const SYNTH_PAGE = { width: 10 * PX_PER_IN, height: 15 * PX_PER_IN };
/** 合成卡的期望像素尺寸：4×3 英寸。 */
const SYNTH_CARD = { width: 4 * PX_PER_IN, height: 3 * PX_PER_IN };

/** RGB 三元组。 */
function rgbOf(hex) {
  const value = String(hex).replace('#', '');
  return [
    parseInt(value.slice(0, 2), 16),
    parseInt(value.slice(2, 4), 16),
    parseInt(value.slice(4, 6), 16),
  ];
}

/** 读某个像素（3 通道裸像素）。 */
function pixelAt(image, x, y) {
  const i = (y * image.width + x) * 3;
  return [image.data[i], image.data[i + 1], image.data[i + 2]];
}

/** 把 DOM 里的卡片 `<svg>` 重新包一层同尺寸根节点（金样本是**单卡** PNG）。 */
function wrapCard(cardNode) {
  const box = cardNode.getAttribute('viewBox').split(/[\s,]+/).map(Number);
  const width = box[2];
  const height = box[3];
  const wrapper = cardNode.ownerDocument.createElementNS(
    'http://www.w3.org/2000/svg',
    'svg',
  );
  wrapper.setAttribute('width', String(width));
  wrapper.setAttribute('height', String(height));
  wrapper.setAttribute('viewBox', `0 0 ${width} ${height}`);
  for (const child of Array.from(cardNode.childNodes)) {
    wrapper.appendChild(child.cloneNode(true));
  }
  return wrapper;
}

// ---------------------------------------------------------------------------
// 金样本的定位（`out/` 被 gitignore，缺失时必须 skip 而不是静默变绿）
// ---------------------------------------------------------------------------

const MIME_BY_EXT = {
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.webp': 'image/webp',
  '.svg': 'image/svg+xml',
  '.gif': 'image/gif',
};

/** 解析插图的读取记录，测试结束时打印（既证明真的读了，也能发现「全都没命中」）。 */
const assetHits = { hits: 0, misses: [] };

/**
 * 插图解析器：把 `assets/icons/xxx.png` 读成 `data:` URI。
 *
 * `renderPage` 缺省把路径拼成 `assets/assets/icons/xxx.png`（`assetsBase` + 原文），
 * 光栅化时 librsvg 解析不到，于是插图位置画成空白 —— 实测把 `page/ph` 卡的
 * 1px 容差从 98.98% 拖到 98.28%、内部差从 0 涨到 447。`resolveAsset` 是文档化的
 * 注入点（`stage.js` R47），这里用它把资源真的读进来；**这不是产品代码的缺陷**，
 * 是浏览器环境下 URL 由调用方决定。
 */
function resolveAssetFromRepo(path) {
  const full = resolve(REPO_ROOT, String(path));
  if (!existsSync(full)) {
    assetHits.misses.push(String(path));
    return String(path);
  }
  assetHits.hits += 1;
  const mime = MIME_BY_EXT[extname(full).toLowerCase()] || 'application/octet-stream';
  return `data:${mime};base64,${readFileSync(full).toString('base64')}`;
}

/** 每份图纸的目录（相对仓库根）。 */
function sampleDir(sample) {
  return sample.relPath.replace(/\/pagelayout\.json$/, '');
}

/** 卡片金样本文件名与 Python 命名一致：`card_{i:02d}_{card.name}.png`。 */
function cardGoldenPath(sample, card, index) {
  const file = `card_${String(index).padStart(2, '0')}_${card.name}.png`;
  return `${sampleDir(sample)}/_cards/${file}`;
}

/** 一份图纸的页面金样本。 */
function pageGoldenPath(sample) {
  return `${sampleDir(sample)}/preview.png`;
}

/** 一张图对应的卡片金样本是否存在（三件套齐了才算有）。 */
function hasCardGoldens(sample) {
  const cards = (sample.doc && sample.doc.cards) || [];
  return cards.some((card, index) => existsSync(goldenPath(cardGoldenPath(sample, card, index))));
}

const SAMPLES = demoLayouts();
const HAS_GOLDEN = SAMPLES.length > 0
  && SAMPLES.every((sample) => existsSync(goldenPath(pageGoldenPath(sample))))
  && SAMPLES.some(hasCardGoldens);

/**
 * 字形可用性探针：渲染一段中文，数深色像素。
 *
 * 字不可用时整组像素对拍没有意义（我方全是空白），必须 `skipTest` —— 但**不能**
 * 让它顺带把「合成 doc」那条非样本判据也跳过。
 */
const FONT_PROBE = await (async () => {
  const svg = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<svg xmlns="http://www.w3.org/2000/svg" width="240" height="80" viewBox="0 0 240 80">',
    '<rect width="240" height="80" fill="#ffffff"/>',
    '<text x="10" y="50" font-size="32" fill="#000000">中文测试</text>',
    '</svg>',
  ].join('');
  const buffer = await sharp(Buffer.from(svg, 'utf8')).removeAlpha().png().toBuffer();
  const image = await decodePng(buffer);
  let dark = 0;
  for (let i = 0; i < image.data.length; i += 3) {
    if (image.data[i] < 128) dark += 1;
  }
  return { dark, ok: dark > 0 };
})();

// ---------------------------------------------------------------------------
// 口径工具：卡片区域 / 文字掩膜 / 差值账本
// ---------------------------------------------------------------------------

/** 契约英寸 → px（**四舍五入**，与卡片在页面上的落位同口径）。 */
function roundPxOf(inches) {
  return pyRound((Number(inches) || 0) * PX_PER_IN);
}

/** 卡片在页面上的像素矩形 `[x0, y0, x1, y1]`（四条边界各自 round）。 */
function cardRegionPx(card) {
  return [
    roundPxOf(card.x_in),
    roundPxOf(card.y_in),
    roundPxOf((Number(card.x_in) || 0) + (Number(card.w_in) || 0)),
    roundPxOf((Number(card.y_in) || 0) + (Number(card.h_in) || 0)),
  ];
}

/**
 * 矩形并集的**补集**，拆成逐行的小盒（喂给 `comparePixels` 的 `boxes`）。
 *
 * 用来把「卡片区域之外」整块掩掉 —— 这样 `considered` 就恰好是「卡片区域内的
 * 非文字像素」，也就是任务书里 356810 那个口径。
 */
function complementBoxes(width, height, rects) {
  const boxes = [];
  for (let y = 0; y < height; y += 1) {
    const spans = rects
      .filter(([, y0, , y1]) => y >= y0 && y < y1)
      .map(([x0, , x1]) => [Math.max(0, x0), Math.min(width, x1)])
      .filter(([x0, x1]) => x1 > x0)
      .sort((a, b) => a[0] - b[0]);
    let cursor = 0;
    for (const [x0, x1] of spans) {
      if (x0 > cursor) boxes.push([cursor, y, x0, y + 1]);
      cursor = Math.max(cursor, x1);
    }
    if (cursor < width) boxes.push([cursor, y, width, y + 1]);
  }
  return boxes;
}

/**
 * 页面上全部文字掩膜盒：卡片内文字平移到页坐标 + 页级整版块的契约块几何。
 *
 * 卡片文字必须**先**平移再掩（`ox`/`oy` 用卡片的 round 落位），否则掩的是卡片
 * 左上角那一小块，卡里的字全部留在判据里 —— 而字体差异是已知的（设计文档 D16），
 * 混进百分比会把「形状对不上」和「字形不一样」搅在一起。
 */
function pageTextBoxes(doc, width, height) {
  const boxes = [];
  for (const card of doc.cards || []) {
    const [ox, oy] = cardRegionPx(card);
    const elements = (card.spec && card.spec.elements) || [];
    boxes.push(...textMaskBoxes(elements, {
      ox, oy, width, height,
    }));
  }
  for (const block of doc.blocks || []) {
    boxes.push(...textMaskBoxes([{
      type: 'text',
      x_in: block.x_in,
      y_in: block.y_in,
      w_in: block.w_in,
      h_in: block.h_in,
    }], {
      ox: 0, oy: 0, width, height,
    }));
  }
  return boxes;
}

/**
 * `0.5` 平局位置清单（R12/R36 遗留：half-to-even 与 `Math.round` 在这里分歧）。
 *
 * 只扫 `x_in`/`y_in` —— `font_pt` 的平局（`9 * 100 / 72 === 12.5`）落在文字盒里，
 * 已被文字掩膜整体掩掉，进不了像素账本，所以用单元断言钉（见「平局用例」组）。
 */
function tieBands(doc) {
  const bands = [];
  for (const card of doc.cards || []) {
    const elements = (card.spec && card.spec.elements) || [];
    for (const el of elements) {
      const x1 = roundPxOf((Number(el.x_in) || 0) + (Number(el.w_in) || 0));
      const y1 = roundPxOf((Number(el.y_in) || 0) + (Number(el.h_in) || 0));
      for (const axis of ['x_in', 'y_in']) {
        const px = (Number(el[axis]) || 0) * PX_PER_IN;
        if (!Number.isFinite(px) || Math.abs(px - Math.trunc(px)) !== 0.5) continue;
        const at = Math.trunc(px);
        bands.push({
          card: card.name,
          id: el.id,
          axis,
          px,
          pyRound: pyRound(px),
          mathRound: Math.round(px),
          band: axis === 'y_in'
            ? [roundPxOf(el.x_in), at - 1, x1, at + 2]
            : [at - 1, roundPxOf(el.y_in), at + 2, y1],
        });
      }
    }
  }
  return bands;
}

/** 差值账本里的一行，供打印。 */
function fmt(result) {
  return `considered=${result.considered} exact=${result.exactPct.toFixed(2)}%`
    + ` 1px=${result.within1Pct.toFixed(2)}% diff=${result.diffCount}`
    + ` e/i=${result.edgeDiff}/${result.innerDiff}`
    + ` edgeShare=${result.edgeShareOfDiffPct.toFixed(1)}%`;
}

/**
 * 断言「差值记账」：描边差占全部差异 ≥60%，并把剩下的内部差异**打印出来**。
 *
 * 剩下的那 1~2% 实测只有三类（都不是结构性错位）：
 * - Pillow `draw.ellipse(..., outline=...)` 是整数宽度描边，SVG 的 stroke 是
 *   半分宽居中描边 → 灯泡圆周边上的抗锯齿灰边（卡1 的 9 个像素）；
 * - Pillow `pieslice` 的整数 1px 轮廓 vs SVG 扇形的 0.5pt 描边 → 扇形边上的
 *   单像素毛边（卡2 的 19 个像素）；
 * - `ticks` 的 1 单位取整差（金样本 201,201,201 vs 我方 200,200,201，1 个像素）。
 */
function expectEdgeShareOfDiff(result, label) {
  if (result.diffCount === 0) {
    // 一个差异都没有就没有「占比」可言 —— 打印出来，别静默通过。
    console.log(`[${label}] 零差异，无需记账`);
    return;
  }
  const share = result.edgeShareOfDiffPct;
  const innerLines = result.innerSamples.map(
    (sample) => `    (${sample.x},${sample.y}) 金样本=${sample.golden.join(',')}`
      + ` 我方=${sample.mine.join(',')}`,
  );
  console.log(
    `[${label}] 差值记账：描边差 ${result.edgeDiff}/${result.diffCount}`
    + ` = ${share.toFixed(1)}%（阈值 ≥${MIN_EDGE_SHARE_PCT}%）`
    + `，内部差 ${result.innerDiff}${innerLines.length ? `：\n${innerLines.join('\n')}` : ''}`,
  );
  expect(
    share,
    `${label}: 描边差占比 ${share.toFixed(1)}% < ${MIN_EDGE_SHARE_PCT}%`
    + `（边缘差 ${result.edgeDiff} / 内部差 ${result.innerDiff}），差值分类失守`,
  ).toBeGreaterThanOrEqual(MIN_EDGE_SHARE_PCT);
}

// ---------------------------------------------------------------------------
// 组 1：合成 doc —— **不依赖金样本**，永远跑
// ---------------------------------------------------------------------------

describe('合成 doc（不依赖金样本）：光栅化尺寸与背景色', () => {
  it('外层 <svg> 的展示尺寸必须改写成 viewBox 尺寸：不改写是 960×1440，改写后 1000×1500', async () => {
    const { svg } = renderPage(null, SYNTH_DOC);
    const xml = toSvgString(svg);

    // 1) 渲染器的缺省口径就是 960×1440（scale=96），viewBox 是 1000×1500。
    expect(xml).toMatch(/<svg\b[^>]*\swidth="960"/);
    expect(xml).toMatch(/<svg\b[^>]*\sheight="1440"/);
    expect(xml).toMatch(/viewBox="0 0 1000 1500"/);

    // 2) 不改写直接光栅化 → 960×1440，与金样本 preview.png 尺寸不符。
    const raw = await svgToPng(xml, { width: 960, height: 1440 });
    const rawImage = await decodePng(raw.buffer);
    expect({ width: rawImage.width, height: rawImage.height })
      .toEqual({ width: 960, height: 1440 });

    // 3) helper 缺省就会改写：展示尺寸替换成 viewBox 尺寸。
    const sized = rewriteDisplaySize(xml);
    expect(sized.display).toEqual({ width: '960', height: '1440' });
    expect({ width: sized.width, height: sized.height }).toEqual(SYNTH_PAGE);

    // 4) 改写后的光栅化尺寸就是金样本口径（1000×1500）。
    const image = await decodePng((await svgToPng(svg)).buffer);
    expect({ width: image.width, height: image.height }).toEqual(SYNTH_PAGE);
  });

  it('整页背景色 = theme.surface（FDF6E3），四角与中部都对', async () => {
    const { svg } = renderPage(null, SYNTH_DOC);
    const image = await decodePng((await svgToPng(svg)).buffer);
    const surface = rgbOf(SYNTH_THEME.palette.surface);
    const corners = {
      '左上 (0,0)': [0, 0],
      '右上 (999,0)': [image.width - 1, 0],
      '左下 (0,1499)': [0, image.height - 1],
      '右下 (999,1499)': [image.width - 1, image.height - 1],
      '中部 (500,1400)': [500, 1400],
    };
    for (const [label, [x, y]] of Object.entries(corners)) {
      expect(pixelAt(image, x, y), `${label} 应当是 theme.surface`).toEqual(surface);
    }
    // 反向护栏：背景色不是白色（夹具刻意用的 FDF6E3），避免「白色对上白色」的假通过。
    expect(surface).not.toEqual([255, 255, 255]);
  });

  it('单卡光栅化尺寸 = 卡片契约尺寸（4×3 英寸 → 400×300），边框恰 1px', async () => {
    const { svg } = renderPage(null, SYNTH_DOC);
    const cardNode = svg.querySelector('[data-card-name="synth_card"]');
    expect(cardNode, '卡片没有渲染成嵌套 <svg>').not.toBeNull();
    expect(cardNode.getAttribute('viewBox')).toBe('0 0 400 300');

    const image = await decodePng((await svgToPng(wrapCard(cardNode))).buffer);
    expect({ width: image.width, height: image.height }).toEqual(SYNTH_CARD);

    const border = rgbOf('A8AEB6');
    const white = rgbOf('FFFFFF');
    // frame 描边压在卡片边界上：第 0 列/行是边框色，第 1、2 列/行已经是白底。
    expect(pixelAt(image, 0, 150), '左边框 (0,150)').toEqual(border);
    expect(pixelAt(image, 1, 150), '(1,150) 应当已进白底').toEqual(white);
    expect(pixelAt(image, 2, 150), '(2,150) 应当还是白底').toEqual(white);
    expect(pixelAt(image, 200, 0), '上边框 (200,0)').toEqual(border);
    expect(pixelAt(image, 200, 1), '(200,1) 应当已进白底').toEqual(white);
    // 实心圆：盒 0.2,2 → 1.2,3 英寸 = (20,200)-(120,300)，中心 (70,250)。
    expect(pixelAt(image, 70, 250), '圆心 (70,250)').toEqual(rgbOf('1F4E79'));
    expect(pixelAt(image, 20, 200), '圆的盒角 (20,200) 不在圆里').toEqual(white);
  });

  it('文字掩膜用契约盒：只掩文字盒 + 外扩 2px，不掩整卡（粗估会多掩一大片）', () => {
    const elements = SYNTH_DOC.cards[0].spec.elements;
    const boxes = textMaskBoxes(elements, { width: 400, height: 300 });
    // headline: x 0.1 → 10px, y 0.1 → 10px, w 3.8 → 390px, h 0.6 → 70px；外扩 2px。
    expect(boxes).toEqual([[8, 8, 392, 72]]);
    const masked = maskedCount(400, 300, boxes);
    expect(masked).toBe((392 - 8) * (72 - 8));
    // 掩膜必须只占一小块（粗估写法会掩到 30%+，这里实测 20.48%）。
    expect(masked / (400 * 300)).toBeLessThan(0.25);
  });
});

// ---------------------------------------------------------------------------
// 组 2：`0.5` 平局用例（R12/R36 遗留）—— 不依赖金样本
// ---------------------------------------------------------------------------

describe('0.5 平局：half-to-even 与 Math.round 的分歧（账本单独记）', () => {
  it('font_pt=9.0 的标签字号：pyRound(12.5)=12，而 Math.round(12.5)=13', () => {
    // `9pt × 100/72` 恰好是 12.5（不是 12.4999…），所以这是真平局。
    expect((9 * PX_PER_IN) / 72).toBe(12.5);
    expect(pyRound(12.5)).toBe(12);
    expect(Math.round(12.5)).toBe(13);
    // 两个口径分歧 = 1px。这一处差异落在**文字盒**里，已被文字掩膜整体掩掉，
    // 进不了像素百分比 —— 所以单独在这里钉死，不许它悄悄消失。
    expect(Math.round(12.5) - pyRound(12.5)).toBe(1);
  });

  it('y_in=1.825 的坐标取整：pyRound(182.5)=182，而 Math.round(182.5)=183', () => {
    expect(1.825 * PX_PER_IN).toBe(182.5);
    expect(pyRound(182.5)).toBe(182);
    expect(Math.round(182.5)).toBe(183);
    expect(Math.round(182.5) - pyRound(182.5)).toBe(1);
    // 另一侧护栏：73.5 是平局但两者同值（74），说明「平局」不等于「分歧」。
    expect(pyRound(73.5)).toBe(74);
    expect(Math.round(73.5)).toBe(74);
  });

  it('合成页上 0.4 英寸卡片落位用 pyRound：x=40（不是 39/41）', () => {
    expect(roundPxOf(0.4)).toBe(40);
    // 只有英寸值乘 100 **恰好**落在 .5 上才是平局；0.15 英寸 × 100 = 15（整数，
    // 不是平局），所以真正的平局样本要用 1/8 的整数倍（二进制精确）。
    expect(0.15 * PX_PER_IN).toBe(15);
    expect(roundPxOf(0.15)).toBe(15);
    expect(roundPxOf(0.125)).toBe(12); // 12.5 → 12（Math.round 会给 13）
    expect(Math.round(0.125 * PX_PER_IN)).toBe(13);
    expect(roundPxOf(0.375)).toBe(38); // 37.5 → 38，两者同值（偶数侧）
    expect(Math.round(0.375 * PX_PER_IN)).toBe(38);
    expect(roundPxOf(0.625)).toBe(62); // 62.5 → 62（Math.round 会给 63）
    expect(Math.round(0.625 * PX_PER_IN)).toBe(63);
  });
});

// ---------------------------------------------------------------------------
// 组 3：金样本逐像素对拍（缺金样本 / 缺字体一律 skip，但组 1、2 永远跑）
// ---------------------------------------------------------------------------

describe.skipIf(!HAS_GOLDEN)('金样本：V2 像素对拍（11 份 demo 图纸）', () => {
  it(`字形可用（否则像素对拍无意义）：sharp 渲染中文得 ${FONT_PROBE.dark} 个深色像素`, () => {
    expect(FONT_PROBE.dark).toBeGreaterThan(0);
  });

  it.skipIf(!FONT_PROBE.ok)('整页区域口径在 1000×1500 上成立（不是 960×1440）', async () => {
    const sample = SAMPLES.find((item) => item.relPath.includes('auto_layout/pagelayout.json'));
    const { svg } = renderPage(null, sample.doc, { resolveAsset: resolveAssetFromRepo });
    const gold = await decodePng(readFileSync(goldenPath(pageGoldenPath(sample))));
    const mine = await decodePng((await svgToPng(svg)).buffer);
    expect({ width: gold.width, height: gold.height }).toEqual(SYNTH_PAGE);
    expect({ width: mine.width, height: mine.height }).toEqual(SYNTH_PAGE);
  });

  it.skipIf(!FONT_PROBE.ok)('插图真的被读进来了（resolveAsset 没全落空）', () => {
    expect(assetHits.hits).toBeGreaterThan(0);
    expect(assetHits.misses).toEqual([]);
  });

  for (const sample of SAMPLES) {
    const cards = (sample.doc.cards || []);
    const withGoldens = cards
      .map((card, index) => ({ card, index, relPath: cardGoldenPath(sample, card, index) }))
      .filter((item) => existsSync(goldenPath(item.relPath)));

    if (withGoldens.length === 0) {
      // `auto_layout/_plain` 就是这一档：0 卡 3 块。不能只写一句
      // 「确实 0 张卡」就交差（那是恒真断言，等于整组静默变绿）——
      // 这里按整页全画面口径真跑一次：文字全在掩膜里，剩下的背景与分栏必须逐像素对得上。
      it.skipIf(!FONT_PROBE.ok)(
        `${sample.name}：0 张卡（无单卡金样本）→ 改用整页全画面口径`,
        async () => {
          expect(withGoldens).toHaveLength(0);
          const { svg } = renderPage(null, sample.doc, { resolveAsset: resolveAssetFromRepo });
          const gold = await decodePng(readFileSync(goldenPath(pageGoldenPath(sample))));
          const mine = await decodePng((await svgToPng(svg)).buffer);
          expect({ width: gold.width, height: gold.height }).toEqual(SYNTH_PAGE);
          const result = await comparePixels(gold, mine, {
            width: gold.width,
            height: gold.height,
            boxes: pageTextBoxes(sample.doc, gold.width, gold.height),
          });
          console.log(`  [${sample.name}/全画面] ${fmt(result)}`);
          expect(result.considered).toBeGreaterThan(0);
          expect(
            result.within1Pct,
            `${sample.name}/全画面: 1px 容差 ${result.within1Pct.toFixed(2)}% < ${MIN_WITHIN_1PX_PCT}%`,
          ).toBeGreaterThanOrEqual(MIN_WITHIN_1PX_PCT);
          expectEdgeShareOfDiff(result, `${sample.name}/全画面`);
        },
      );
      continue;
    }

    describe(sample.name, () => {
      let page = null;

      /** 懒光栅化整页（同一样本的多条用例共用一次）。 */
      async function renderPageOnce() {
        if (!page) {
          const { svg } = renderPage(null, sample.doc, { resolveAsset: resolveAssetFromRepo });
          page = {
            gold: await decodePng(readFileSync(goldenPath(pageGoldenPath(sample)))),
            mine: await decodePng((await svgToPng(svg)).buffer),
            svg,
          };
        }
        return page;
      }

      for (const { card, index, relPath } of withGoldens) {
        it.skipIf(!FONT_PROBE.ok)(
          `主判据｜卡 ${index} ${card.name}：1px 容差 ≥${MIN_WITHIN_1PX_PCT}% 且差值记账`,
          async () => {
            const { svg } = await renderPageOnce();
            const cardNode = svg.querySelector(`[data-card-name="${card.name}"]`);
            expect(cardNode, `卡片 ${card.name} 没渲染成嵌套 <svg>`).not.toBeNull();

            const mine = await decodePng((await svgToPng(wrapCard(cardNode))).buffer);
            const gold = await decodePng(readFileSync(goldenPath(relPath)));
            // 尺寸必须与金样本一致 —— 不一致时 comparePixels 会先抛 SIZE MISMATCH。
            expect({ width: gold.width, height: gold.height })
              .toEqual({ width: mine.width, height: mine.height });

            const mask = {
              width: gold.width,
              height: gold.height,
              boxes: textMaskBoxes((card.spec && card.spec.elements) || [], {
                width: gold.width,
                height: gold.height,
              }),
            };
            const result = await comparePixels(gold, mine, mask);
            console.log(`  [${sample.name}/${card.name}] ${fmt(result)}`);
            expect(result.considered, '非文字像素太少，掩膜算错了').toBeGreaterThan(0);
            expect(
              result.within1Pct,
              `${sample.name}/${card.name}: 1px 容差 ${result.within1Pct.toFixed(2)}%`
              + ` < ${MIN_WITHIN_1PX_PCT}%（exact ${result.exactPct.toFixed(2)}%，${fmt(result)}）`,
            ).toBeGreaterThanOrEqual(MIN_WITHIN_1PX_PCT);
            expectEdgeShareOfDiff(result, `${sample.name}/${card.name}`);
          },
        );
      }

      it.skipIf(!FONT_PROBE.ok)(
        `整页｜卡片区域内：1px 容差 ≥${MIN_WITHIN_1PX_PCT}%（非文字像素只数卡片区域）`,
        async () => {
          const { gold, mine } = await renderPageOnce();
          const regions = cards.map(cardRegionPx);
          const boxes = pageTextBoxes(sample.doc, gold.width, gold.height)
            .concat(complementBoxes(gold.width, gold.height, regions));
          const result = await comparePixels(gold, mine, {
            width: gold.width, height: gold.height, boxes,
          });
          const regionArea = regions.reduce(
            (sum, [x0, y0, x1, y1]) => sum + (x1 - x0) * (y1 - y0),
            0,
          );
          console.log(
            `  [${sample.name}/页区] ${fmt(result)}`
            + `（卡片区域 ${regions.length} 块 / ${regionArea} px）`,
          );
          expect(result.considered).toBeGreaterThan(0);
          expect(result.considered).toBeLessThanOrEqual(regionArea);
          expect(
            result.within1Pct,
            `${sample.name}/页区: 1px 容差 ${result.within1Pct.toFixed(2)}%`
            + ` < ${MIN_WITHIN_1PX_PCT}%（${fmt(result)}）`,
          ).toBeGreaterThanOrEqual(MIN_WITHIN_1PX_PCT);
          expectEdgeShareOfDiff(result, `${sample.name}/页区`);
        },
      );
    });
  }
});

// ---------------------------------------------------------------------------
// 组 4：`0.5` 平局像素账本 —— 单独统计，不进上面的总体百分比
// ---------------------------------------------------------------------------

describe.skipIf(!HAS_GOLDEN)('金样本：0.5 平局的像素账本（单独统计）', () => {
  it.skipIf(!FONT_PROBE.ok)(
    'heat_age 的 y_in=1.825 平局带：差异全在边缘带、内部差为 0，且逐条打印',
    async () => {
      const sample = SAMPLES.find((item) => item.relPath.includes('auto_layout/pagelayout.json'));
      const card = sample.doc.cards.find((item) => item.name === 'heat_age');
      expect(card, 'auto_layout 里没有 heat_age 卡').toBeDefined();
      expect(cardGoldenPath(sample, card, 1)).toContain('card_01_heat_age.png');

      const { svg } = renderPage(null, sample.doc, { resolveAsset: resolveAssetFromRepo });
      const cardNode = svg.querySelector('[data-card-name="heat_age"]');
      const mine = await decodePng((await svgToPng(wrapCard(cardNode))).buffer);
      const gold = await decodePng(readFileSync(goldenPath(cardGoldenPath(sample, card, 1))));

      const bands = tieBands({ cards: [card] });
      expect(bands.length, 'heat_age 的平局元素数变了').toBeGreaterThan(0);
      for (const entry of bands) {
        console.log(
          `  ${entry.id}.${entry.axis} = ${entry.px}px`
          + ` → pyRound ${entry.pyRound} / Math.round ${entry.mathRound}`
          + `（${entry.pyRound === entry.mathRound ? '同值，不分歧' : '分歧 1px'}）`,
        );
      }
      // 五条 sector + 五条 legend 都在 y_in=1.825 → 10 条平局
      expect(bands).toHaveLength(10);
      expect(bands.filter((entry) => entry.pyRound !== entry.mathRound).length).toBe(10);

      const textBoxes = textMaskBoxes((card.spec && card.spec.elements) || [], {
        width: gold.width,
        height: gold.height,
      });
      // 账本口径：只看平局带内、文字掩膜之外的像素。
      const ledger = await comparePixels(gold, mine, {
        width: gold.width,
        height: gold.height,
        boxes: textBoxes.concat(complementBoxes(
          gold.width,
          gold.height,
          bands.map((entry) => entry.band),
        )),
      });
      console.log(`  [平局账本] ${fmt(ledger)}`);
      expect(ledger.considered, '平局带里一个像素都没统计到，说明带算错了').toBeGreaterThan(0);
      // 实测 190 个差异，190 落在金样本 4 邻域边缘带、0 个内部差 —— 也就是
      // 「half-to-even 的 1px 位移全部落在描边上」，与组 3 的总体账互不影响。
      expect(ledger.diffCount).toBeGreaterThan(0);
      expect(ledger.innerDiff, '平局带里出现了内部差，说明不是边缘位移').toBe(0);
      expect(ledger.edgeDiff).toBe(ledger.diffCount);
    },
  );
});

// ---------------------------------------------------------------------------
// 组 5：任务书的三个口径逐条复现（数字对齐 + 全画面口径只诊断不设判据）
// ---------------------------------------------------------------------------

describe.skipIf(!HAS_GOLDEN)('金样本：任务书三个口径的数字', () => {
  it.skipIf(!FONT_PROBE.ok)(
    'auto_layout：卡1 / 卡2 / 整页卡片区域 三档数字全部 ≥98%（全画面口径只打印）',
    async () => {
      const sample = SAMPLES.find((item) => item.relPath.includes('auto_layout/pagelayout.json'));
      const { svg } = renderPage(null, sample.doc, { resolveAsset: resolveAssetFromRepo });
      const pageGold = await decodePng(readFileSync(goldenPath(pageGoldenPath(sample))));
      const pageMine = await decodePng((await svgToPng(svg)).buffer);
      expect({ width: pageGold.width, height: pageGold.height }).toEqual(SYNTH_PAGE);

      const rows = [];
      for (const [index, card] of sample.doc.cards.entries()) {
        const relPath = cardGoldenPath(sample, card, index);
        const cardNode = svg.querySelector(`[data-card-name="${card.name}"]`);
        const mine = await decodePng((await svgToPng(wrapCard(cardNode))).buffer);
        const gold = await decodePng(readFileSync(goldenPath(relPath)));
        const result = await comparePixels(gold, mine, {
          width: gold.width,
          height: gold.height,
          boxes: textMaskBoxes((card.spec && card.spec.elements) || [], {
            width: gold.width, height: gold.height,
          }),
        });
        rows.push({ label: `${card.name} (${gold.width}×${gold.height})`, result });
        console.log(`  ${rows[rows.length - 1].label}: ${fmt(result)}`);
        expect(result.within1Pct).toBeGreaterThanOrEqual(MIN_WITHIN_1PX_PCT);
        expectEdgeShareOfDiff(result, `口径/${card.name}`);
      }

      const regions = sample.doc.cards.map(cardRegionPx);
      const regionResult = await comparePixels(pageGold, pageMine, {
        width: pageGold.width,
        height: pageGold.height,
        boxes: pageTextBoxes(sample.doc, pageGold.width, pageGold.height)
          .concat(complementBoxes(pageGold.width, pageGold.height, regions)),
      });
      console.log(`  整页卡片区域: ${fmt(regionResult)}`);
      expect(regionResult.considered).toBe(356810);
      expect(regionResult.within1Pct).toBeGreaterThanOrEqual(MIN_WITHIN_1PX_PCT);
      expectEdgeShareOfDiff(regionResult, '口径/整页卡区');

      // 整页**全画面**口径：只打印，不设判据。这里的大头是插图位图重采样
      // （Pillow 缩放 vs librsvg 缩放），差异没有结构意义；任务书也把它划在诊断侧。
      const fullResult = await comparePixels(pageGold, pageMine, {
        width: pageGold.width,
        height: pageGold.height,
        boxes: pageTextBoxes(sample.doc, pageGold.width, pageGold.height),
      });
      console.log(`  [诊断·全画面，不设判据] ${fmt(fullResult)}`);
      // 唯一的护栏是「别炸成一片」：低于 90% 说明渲染整体崩了，不是插图的锅。
      expect(fullResult.within1Pct).toBeGreaterThan(90);
    },
  );
});

// ---------------------------------------------------------------------------
// 组 6：掩膜口径护栏（防止有人把「契约盒」改回「粗估」）
// ---------------------------------------------------------------------------

describe('文字掩膜口径护栏（掩多了就假红，掩少了就假绿）', () => {
  it('文字盒是契约盒外扩 2px：x_in=0.1 → 8，w_in=3.8 → 392（不是按字数×字号粗估）', () => {
    const boxes = textMaskBoxes([
      {
        type: 'text', x_in: 0.1, y_in: 0.1, w_in: 3.8, h_in: 0.6, font_pt: 12, lines: ['一二三四五六'],
      },
    ], { width: 400, height: 300 });
    // 粗估口径：6 个字 × 12pt → 约 100px 宽的一大片；契约盒口径与字号、字数无关。
    expect(boxes).toEqual([[8, 8, 392, 72]]);
  });

  it('非 text 元素不进文字掩膜（形状像素必须留在判据里）', () => {
    const boxes = textMaskBoxes([
      { type: 'rect', x_in: 0, y_in: 0, w_in: 4, h_in: 3 },
      { type: 'ellipse', x_in: 0.2, y_in: 2, w_in: 1, h_in: 1 },
      { type: 'arc', x_in: 1, y_in: 1, w_in: 1, h_in: 1 },
      { type: 'text', x_in: 0.1, y_in: 0.1, w_in: 0.5, h_in: 0.2 },
    ], { width: 400, height: 300 });
    expect(boxes).toHaveLength(1);
    expect(boxes[0]).toEqual([8, 8, 62, 32]);
  });

  it('maskOf 的盒是半开区间、且被裁进画面', () => {
    const mask = maskOf(10, 10, [[-5, -5, 2, 2], [8, 8, 20, 20]]);
    expect(maskedCount(10, 10, [[-5, -5, 2, 2]])).toBe(4);
    expect(maskedCount(10, 10, [[8, 8, 20, 20]])).toBe(4);
    expect(mask.filter((value) => value === 1)).toHaveLength(8);
  });
});
