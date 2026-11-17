// @vitest-environment jsdom
/**
 * P2 Task 5 / V1 结构对拍。
 *
 * 两条判据证明 JS 渲染结果与契约几何一致：
 * 1. **DOM 节点数**：带 `data-el-id` 的节点数必须由公式推导出来（不是写死总数），
 *    并且对每一份 demo 图纸逐份核对。
 * 2. **逐元素 bbox 回算**：把契约里的英寸几何按 `Math.trunc(*100)` 换算成 px，
 *    与渲染出来的属性**零容差**比对。
 *
 * 三条口径上的坑（都是实测踩出来的，写错会假红/假绿）：
 * - `data-el-id` 跨卡片会重名（`frame`/`title_band`/`title`/`scale_note` 每卡各一），
 *   所以索引键要按卡片定域，见 `collectByElId`。
 * - bbox 只能在 **px 空间**比对：渲染按整像素截断，回算成英寸必然差到 1px = 0.01in。
 *   实测全 11 份 `max |trunc(boundary) - inch*100| = 1.0`；写成 `< 1e-6` 英寸的话，
 *   光卡1 的 68 个分量里就有 63 个假 FAIL。英寸那条断言只用来让报错好读。
 * - 不是所有元素都能回算 bbox（`track`/`ticks`/`outline`/`arc`/`text` 都不能），
 *   跳过的那部分必须**显式计数断言**，不许静默 `continue`。
 *
 * `out/` 被 gitignore：金样本读不到时整组 `skip`。为了 fresh clone 上也能真跑一条，
 * 文件末尾另有一组**完全手写、不依赖金样本**的合成 doc 判据。
 */
import { describe, expect, it } from 'vitest';

import { renderPage } from '../src/render/stage.js';
import {
  attrToInch, boxOf, cardKey, collectByElId,
} from './helpers/svgwalk.mjs';
import { demoLayoutPaths, demoLayouts, goldenDoc } from './helpers/golden.mjs';

/** 与 `src/render/text.js` 的 `MAX_LINES` 同口径（一屏最多画几行）。 */
const MAX_LINES = 4;

/** 与 `src/render/primitives.js` 的 `KNOWN_TYPES` 同口径。 */
const KNOWN_TYPES = ['rect', 'ellipse', 'arc', 'text', 'ticks', 'outline', 'image', 'chart'];

/** px 空间截断：期望值一律这样算，**不调 `src/units.js`**（免得用实现算期望）。 */
function truncPx(inches) {
  return Math.trunc((Number(inches) || 0) * 100);
}

/** 契约盒 → px 四条边界 `[x0, y0, x1, y1]`（逐边界截断）。 */
function truncBox(el) {
  return [
    truncPx(el.x_in),
    truncPx(el.y_in),
    truncPx((Number(el.x_in) || 0) + (Number(el.w_in) || 0)),
    truncPx((Number(el.y_in) || 0) + (Number(el.h_in) || 0)),
  ];
}

/**
 * 卡片里一个元素该出几种「档」——分支顺序与 `renderElement()` 一致。
 * @returns {'text'|'placeholder'|'ticks'|'outline'|'ellipse'|'arc'|'image'|'track'|'rect'}
 */
function classifyElement(el) {
  const type = el && el.type;
  if (type === 'text') return 'text';
  if (type === 'chart') return 'placeholder'; // 未实现的图表类型 → 虚线占位框
  if (!KNOWN_TYPES.includes(type)) return 'placeholder'; // 未知 type → 虚线占位框
  if (type === 'ticks') return 'ticks';
  if (type === 'outline') return 'outline';
  if (type === 'ellipse') return 'ellipse';
  if (type === 'arc') return 'arc';
  if (type === 'image') return 'image';
  if (el.role === 'track') return 'track';
  return 'rect'; // 含 role='frame' / 'title_band' / 兜底 rect
}

/** 能精确回算 bbox 的类别（`rect` 非 track / `ellipse` / `image` / 占位）。 */
const BBOX_CHECKABLE = ['rect', 'ellipse', 'image', 'placeholder'];

/**
 * 这个元素会不会被画成占位框（`chart` / 未知 type / 取不到图）。
 * 占位框也是「1 个节点、盒几何照样打得出来」，所以它仍属可回算那一类；
 * 这个判定只用来找「占位卡」。
 */
function isPlaceholderElement(el) {
  if (!el) return false;
  if (el.type === 'chart') return true;
  if (!KNOWN_TYPES.includes(el.type)) return true;
  return el.role === 'placeholder';
}

/** 卡片内 text 元素的行：与 `renderText():linesFor(el, 'card')` 同口径的候选链。 */
function cardLines(el) {
  const candidates = [el && el.lines, el && el.geometry && el.geometry.lines];
  for (const candidate of candidates) {
    if (Array.isArray(candidate) && candidate.length > 0) return candidate.map(String);
  }
  if (el && el.text != null && String(el.text) !== '') return [String(el.text)];
  return [];
}

/** 一组行的落笔数：只画前 `MAX_LINES` 行，空行不落笔（空行只占行距）。 */
function inkedLines(lines) {
  const count = Math.min(lines.length, MAX_LINES);
  return lines.slice(0, count).filter((line) => line !== '').length;
}

/**
 * 卡片节点数公式（逐元素累加，每个分支一行）：
 * 形状各 1；`track` 2（矩形 + 下半圆 `<path>`）；`text` 1 个 `<g>` + 逐行 `<text>`；
 * `ticks` = `geometry.count` 个 rect；`outline` 1 条 `<polyline>`；占位 1。
 *
 * 11 份样本里卡片内 text 全是单行，所以这里等价于 `1 + min(非空行数, 4)`。
 */
function expectedCardNodes(card) {
  const elements = card && card.spec && Array.isArray(card.spec.elements) ? card.spec.elements : [];
  let expected = 0;
  for (const el of elements) {
    const kind = classifyElement(el);
    if (kind === 'text') {
      expected += 1 + inkedLines(cardLines(el)); // <g> + 逐行 <text>
    } else if (kind === 'ticks') {
      expected += Math.trunc(Number(el.geometry && el.geometry.count) || 0); // count 个 rect
    } else if (kind === 'track') {
      expected += 2; // 矩形 + 下半圆 <path>
    } else {
      expected += 1; // rect / ellipse / arc / outline / image / 占位：各 1 个
    }
  }
  return expected;
}

/**
 * 页面级节点数公式：每块 = `line_groups.length` 个 `<g>`（多栏块出多个 `<g>`，
 * 共用同一个 `data-el-id`）+ 逐行 `<text>`；每张插图 1。
 */
function expectedBlockNodes(block) {
  const groups = Array.isArray(block.line_groups) && block.line_groups.length > 0
    ? block.line_groups
    : [Array.isArray(block.lines) ? block.lines : []];
  let expected = groups.length; // 每栏一个 <g>
  for (const group of groups) {
    expected += inkedLines((Array.isArray(group) ? group : []).map(String));
  }
  return expected;
}

/** 页面级（卡片以外）节点数。 */
function expectedPageNodes(doc) {
  const blocks = Array.isArray(doc.blocks) ? doc.blocks : [];
  const images = Array.isArray(doc.images) ? doc.images : [];
  let expected = 0;
  for (const block of blocks) expected += expectedBlockNodes(block);
  expected += images.length; // 每张插图 1 个 <image> / 占位 rect
  return expected;
}

/** 渲染成一棵游离的 `<svg>`（`container = null`，不挂 DOM，V1 判据不需要布局）。 */
function renderFree(doc) {
  const { svg } = renderPage(null, doc);
  return svg;
}

/** 每张卡片里带 `data-el-id` 的节点数。 */
function actualCardNodes(svg) {
  const out = {};
  for (const cardNode of svg.querySelectorAll('[data-card-name]')) {
    out[cardNode.getAttribute('data-card-name')] = cardNode.querySelectorAll('[data-el-id]').length;
  }
  return out;
}

/** 卡片以外（页级块 / 插图）带 `data-el-id` 的节点数。 */
function actualPageNodes(svg) {
  let n = 0;
  for (const node of svg.querySelectorAll('[data-el-id]')) {
    if (!node.closest('[data-card-name]')) n += 1;
  }
  return n;
}

/** 全页带 `data-el-id` 的节点数（含重名节点，逐个算）。 */
function actualTotalNodes(svg) {
  return svg.querySelectorAll('[data-el-id]').length;
}

/** 卡片容器节点（按名字）。 */
function cardNodeOf(svg, cardName) {
  for (const cardNode of svg.querySelectorAll('[data-card-name]')) {
    if (cardNode.getAttribute('data-card-name') === cardName) return cardNode;
  }
  return null;
}

// ---------------------------------------------------------------------------
// 实测基准（`out/demo/**` 现有 11 份，逐份核对过：节点公式 11/11 零偏差）
//
// ⚠ 对齐的是 **PR-B 时代的排版产物**（HEAD f6c3508）。相对 PR-A 的基准，只有三个键变过，
// 每一处都逐份实测并核对过来源：
//   cards.heat_age 23 → 24：PR-B 起卡片外框是等比缩放后的真实尺寸，illustrated /
//     multicol / theme_match 的 heat_age 外框宽由格子宽 4.5in 缩到 3.165in，卡内
//     `scale_note`（31 字）由 1 行折成 2 行 ⇒ text 节点 = 1 个 <g> + 2 行 = 3（原 2）。
//     auto_layout（外框 4.94625in）与 page/paper 的 semi（4.4475in）仍 1 行，故不变。
//   page 15 → 14（illustrated / illustrated/_no_asset / multicol）：heat_ratio_top5
//     升到整行（8.2384in）后不再与插图并排，`illustration_17` 被放弃 ⇒ images 2 → 1。
//     块公式不变（2+3+4+4=13），13 + 1 = 14。
//   page 14 → 13（theme_match）：`illustration_17` 下移到与末块同排，该块由 span=2
//     （2 个 <g>，各 1 行 → 4 节点）压成 span=1（1 个 <g>，2 行 → 3 节点）。
//   total +1（illustrated/_spread 151→152、multicol/_spread 159→160）：只有 scale_note
//     那一处 +1，page 未变（这两份没有可被放弃的并排插图）。
// elements / checked / skipped / skipHist 11 份全部未变。
// ---------------------------------------------------------------------------
const GOLDEN_STRUCTURE = {
  auto_layout: {
    total: 149, page: 10, cards: { heat_ratio_top5: 116, heat_age: 23 },
    elements: 54, checked: 14, skipped: 40,
    skipHist: { text: 20, track: 5, outline: 5, ticks: 5, arc: 5 },
  },
  'auto_layout/_plain': {
    total: 6, page: 6, cards: {}, // 0 张卡片：3 块 × (1 个 <g> + 1 行 <text>)
    elements: 0, checked: 0, skipped: 0, skipHist: {},
  },
  illustrated: {
    // total 154 = cards(116+24) + page 14：heat_age +1 与 page −1 相抵
    total: 154, page: 14, cards: { heat_ratio_top5: 116, heat_age: 24 },
    elements: 54, checked: 14, skipped: 40,
    skipHist: { text: 20, track: 5, outline: 5, ticks: 5, arc: 5 },
  },
  'illustrated/_no_asset': {
    total: 154, page: 14, cards: { heat_ratio_top5: 116, heat_age: 24 },
    elements: 54, checked: 14, skipped: 40,
    skipHist: { text: 20, track: 5, outline: 5, ticks: 5, arc: 5 },
  },
  'illustrated/_spread': {
    // page 不变（12），total +1 全在 heat_age 的 scale_note 多折一行
    total: 152, page: 12, cards: { heat_ratio_top5: 116, heat_age: 24 },
    elements: 54, checked: 14, skipped: 40,
    skipHist: { text: 20, track: 5, outline: 5, ticks: 5, arc: 5 },
  },
  multicol: {
    total: 154, page: 14, cards: { heat_ratio_top5: 116, heat_age: 24 },
    elements: 54, checked: 14, skipped: 40,
    skipHist: { text: 20, track: 5, outline: 5, ticks: 5, arc: 5 },
  },
  'multicol/_spread': {
    total: 160, page: 13, cards: { heat_ratio_top5: 116, heat_age: 24, placeholder: 7 },
    elements: 59, checked: 17, skipped: 42,
    skipHist: { text: 22, track: 5, outline: 5, ticks: 5, arc: 5 },
  },
  page: {
    total: 146, page: 0, cards: { thermo: 116, semi: 23, ph: 7 },
    elements: 59, checked: 17, skipped: 42,
    skipHist: { text: 22, track: 5, outline: 5, ticks: 5, arc: 5 },
  },
  paper: {
    total: 155, page: 9, cards: { thermo: 116, semi: 23, ph: 7 },
    elements: 59, checked: 17, skipped: 42,
    skipHist: { text: 22, track: 5, outline: 5, ticks: 5, arc: 5 },
  },
  theme_match: {
    // total 153 = cards(116+24) + page 13：heat_age +1 与 page −1 相抵
    total: 153, page: 13, cards: { heat_ratio_top5: 116, heat_age: 24 },
    elements: 54, checked: 14, skipped: 40,
    skipHist: { text: 20, track: 5, outline: 5, ticks: 5, arc: 5 },
  },
  'theme_match/_no_theme': {
    // 这份图纸的卡片名带 `_prov` 后缀（换主题后重生成过），与其它样本不同名。
    // 它的唯一卡片是 heat_ratio_top5_prov（116），没有 heat_age，故不受影响。
    total: 123, page: 7, cards: { heat_ratio_top5_prov: 116 },
    elements: 39, checked: 12, skipped: 27,
    skipHist: { text: 12, track: 5, outline: 5, ticks: 5 }, // 该份没有 arc
  },
};

/** 占位卡（`chart` / 未知 type / 取不到图）每张 7 个节点。 */
const PLACEHOLDER_CARD_NODES = 7;

// ---------------------------------------------------------------------------
// 手写合成 doc：**不依赖金样本**（fresh clone 上金样本组会 skip，这条不能 skip）
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
    surface: 'FFFFFF',
  },
  font_sizes: {
    title: 20, subtitle: 14, body: 11, label: 9, note: 8,
  },
  base_canvas_in: [10, 6],
  font_pt_clamp: [6, 24],
  role_to_font: {
    title: 'title', scale_note: 'note', legend: 'label', label: 'label', value: 'body', center: 'subtitle',
  },
};

/**
 * 极简合成图纸：1 张卡片（4 个元素）+ 1 个页级块。
 *
 * 四个元素故意覆盖四条公式分支：
 * - `frame`：`rect` → 1 个节点；且 `x_in = 0` 而卡片 `x_in = 0.4`，
 *   所以它的 `x` 属性必须是 `0`（相对卡片）而不是 `40`（Review Focus #4）。
 * - `headline`：`text` 但给了 **5 行** → `1 + min(5, 4) = 5` 个节点，
 *   去掉 `min(行数, 4)` 就会变 6 个（11 份金样本抓不到这条，只能靠合成用例）。
 * - `dot`：`ellipse` → 1 个节点。
 * - `chart_tile`：`type: 'chart'` → **占位分支**（`primitives.js::placeholder()`）→
 *   1 个虚线 `<rect>` + 一个**不带** `data-el-id` 的 `<title>`。
 *   11 份金样本里 `type='chart'` 与未知 type 各 **0** 个、没有 `image_path` 的插图
 *   也 **0** 个 ⇒ 只靠金样本时这条分支从未被执行，给占位框的 `<title>` 打上
 *   `data-el-id` 也能存活（评审 S5）。这个元素就是为了把那条分支真正跑起来。
 */
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
            h_in: 1.6,
            font_pt: 12,
            lines: ['第一行', '第二行', '第三行', '第四行', '第五行'],
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
          {
            // 未实现的图表类型：`renderElement()` 第 2 条分支 → `placeholder()`。
            // 盒 2.5,2.0 → 4.0,2.8（英寸边界在二进制里是精确值，trunc 后是
            // [250,200,400,280]）。刻意避开 2.4+1.2=3.5999999999999996 这种
            // 会因浮点截断掉 1px 的边界，免得这条断言在讲别的事。
            id: 'chart_tile',
            type: 'chart',
            role: 'chart',
            x_in: 2.5,
            y_in: 2,
            w_in: 1.5,
            h_in: 0.8,
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

/** 合成 doc 的改动版：给 `headline` 一个含空行的 3 行文本（空行不落笔）。 */
function synthWithEmptyLine() {
  const doc = JSON.parse(JSON.stringify(SYNTH_DOC));
  doc.cards[0].spec.elements[1].lines = ['有字', '', '也有字'];
  return doc;
}

const SAMPLES = demoLayouts();
const HAS_GOLDEN = SAMPLES.length > 0;

// ---------------------------------------------------------------------------
describe('golden helpers', () => {
  it('demoLayoutPaths() 只返回真实存在且已排序的路径', () => {
    const paths = demoLayoutPaths();
    expect(paths).toEqual([...paths].sort());
    for (const relPath of paths) {
      expect(goldenDoc(relPath)).not.toBeNull();
      expect(goldenDoc(relPath)).toBeTypeOf('object');
    }
  });

  it('goldenDoc() 对不存在的路径返回 null（不抛）', () => {
    expect(goldenDoc('out/demo/绝对不存在的样本/pagelayout.json')).toBeNull();
  });

  it('demoLayouts() 的短名与排序对得上', () => {
    for (const sample of SAMPLES) {
      expect(sample.relPath.startsWith('out/demo/')).toBe(true);
      expect(sample.relPath.endsWith('/pagelayout.json')).toBe(true);
      expect(sample.name).toBe(
        sample.relPath.replace(/^out\/demo\//, '').replace(/\/pagelayout\.json$/, ''),
      );
      expect(sample.doc).toBeTypeOf('object');
    }
  });
});

// ---------------------------------------------------------------------------
describe('合成 doc（不依赖金样本）', () => {
  it('节点数由公式推导：1 卡（rect + 5 行 text + ellipse + chart 占位）+ 1 块', () => {
    const svg = renderFree(SYNTH_DOC);
    const doc = SYNTH_DOC;

    // 卡片内：逐元素累加（与 `expectedCardNodes` 同口径，但在这里**独立写一遍**，
    // 免得「用被测的公式算期望」）。分支顺序同 `classifyElement`：
    //   text → 1 个 <g> + min(非空行数, 4) 个 <text>
    //   chart / 未知 type → 占位 1 个 <rect>（挂的 <title> 不带 data-el-id，不计入）
    //   rect / ellipse / 其它形状 → 1
    const elements = SYNTH_DOC.cards[0].spec.elements;
    expect(elements).toHaveLength(4); // 夹具形状护栏（不是节点数）
    let expectedCard = 0;
    for (const el of elements) {
      if (el.type === 'text') expectedCard += 1 + Math.min((el.lines || []).length, MAX_LINES);
      else if (el.type === 'ticks') expectedCard += Math.trunc((el.geometry || {}).count || 0);
      else expectedCard += 1;
    }

    // 页面级：synth_block = 1 个 <g> + 1 行 <text> = 2
    let expectedPage = 0;
    for (const group of SYNTH_DOC.blocks[0].line_groups) {
      expectedPage += 1; // 一个 line_group → 一个 <g>
      expectedPage += group.filter((line) => line !== '').length; // 非空行 → <text>
    }

    expect(actualCardNodes(svg)).toEqual({ synth_card: expectedCard });
    expect(actualPageNodes(svg)).toBe(expectedPage);
    expect(actualTotalNodes(svg)).toBe(expectedCard + expectedPage);

    // 与「公式推导」这条实现对齐：同一个 doc 走 helper 应得同样的数
    expect(expectedCardNodes(doc.cards[0])).toBe(expectedCard);
    expect(expectedPageNodes(doc)).toBe(expectedPage);
  });

  it('chart 占位：1 个 <rect>，挂的 <title> 不带 data-el-id（不计入节点数）', () => {
    const svg = renderFree(SYNTH_DOC);
    const nodes = collectByElId(svg).get(cardKey('synth_card', 'chart_tile'));
    expect(nodes, 'type="chart" 的元素没有渲染出带 data-el-id 的节点').toBeDefined();

    // 1) 只有 1 个带 data-el-id 的节点，且就是那个虚线框 <rect>
    expect(nodes).toHaveLength(1);
    const box = nodes[0];
    expect(box.tagName).toBe('rect');
    expect(box.getAttribute('stroke-dasharray')).toBe('6 4');
    expect(boxOf([box])).toEqual(truncBox(SYNTH_DOC.cards[0].spec.elements[3]));
    expect(boxOf([box])).toEqual([250, 200, 400, 280]);

    // 2) <title> 存在（spec D13「在图上标注」的唯一载体），但**不带** data-el-id。
    //    这一条才真正钉住占位框的 `<title>` 不是契约元素——给它的 `<title>` 也打上
    //    data-el-id 时，节点数会变成 2、`actualCardNodes` 也会 +1，两处同时红。
    const titles = box.querySelectorAll('title');
    expect(titles).toHaveLength(1);
    expect(titles[0].getAttribute('data-el-id')).toBeNull();
    expect(titles[0].textContent).toContain('未在 JS 渲染器实现');
    // 全卡带 data-el-id 的节点数仍然只按「每个元素 1 个（text 除外）」算
    expect(actualCardNodes(svg).synth_card).toBe(expectedCardNodes(SYNTH_DOC.cards[0]));
  });

  it('headline 是 1 个 <g> + 4 个 <text>：`min(行数, 4)` 这条口径真的在起作用', () => {
    const svg = renderFree(SYNTH_DOC);
    const byKey = collectByElId(svg);
    const nodes = byKey.get(cardKey('synth_card', 'headline'));
    expect(nodes).toHaveLength(5);
    const groups = nodes.filter((node) => node.tagName === 'g');
    const texts = nodes.filter((node) => node.tagName === 'text');
    expect(groups).toHaveLength(1);
    expect(texts).toHaveLength(4); // 第 5 行被 MAX_LINES 挡掉
    expect(texts.map((node) => node.textContent)).toEqual(['第一行', '第二行', '第三行', '第四行']);
  });

  it('text 里的空行不落笔（但占行距）：3 行含 1 个空行 → <g> + 2 个 <text>', () => {
    const doc = synthWithEmptyLine();
    const svg = renderFree(doc);
    const nodes = collectByElId(svg).get(cardKey('synth_card', 'headline'));
    expect(nodes).toHaveLength(3); // 1 个 <g> + 2 行有字
    expect(nodes.filter((node) => node.tagName === 'text')).toHaveLength(2);
    // 公式侧同样只算落笔的行：headline = 1 个 <g> + 2 行，其余 3 个元素各 1。
    // 期望值从夹具的**行内容**算出来（空行不落笔），不写「4」这个字面量。
    const headlineEl = doc.cards[0].spec.elements[1];
    const otherElements = doc.cards[0].spec.elements.length - 1;
    const inked = headlineEl.lines.slice(0, MAX_LINES).filter((line) => line !== '').length;
    expect(expectedCardNodes(doc.cards[0])).toBe(1 + inked + otherElements);
  });

  it('Review Focus #4：卡内元素的坐标是相对卡片的（x_in=0 → x="0"，不是 40）', () => {
    const svg = renderFree(SYNTH_DOC);
    const cardNode = cardNodeOf(svg, 'synth_card');
    expect(cardNode.getAttribute('x')).toBe('40'); // 卡片自身的 x = roundPx(0.4) = 40
    const frame = collectByElId(svg).get(cardKey('synth_card', 'frame'))[0];
    expect(frame.getAttribute('x')).toBe('0'); // 元素盒相对卡片：0，绝不是 40
    expect(frame.getAttribute('y')).toBe('0');
    expect(boxOf([frame])).toEqual([0, 0, 400, 300]);
  });

  it('ellipse 的 cx/cy/rx/ry 由盒中心与半宽半高算出', () => {
    const svg = renderFree(SYNTH_DOC);
    const dot = collectByElId(svg).get(cardKey('synth_card', 'dot'))[0];
    expect(dot.tagName).toBe('ellipse');
    // 盒 20,200 → 120,300：中心 (70, 250)、半宽半高 50
    expect(boxOf([dot])).toEqual([20, 200, 120, 300]);
    expect(Number(dot.getAttribute('cx'))).toBe(70);
    expect(Number(dot.getAttribute('cy'))).toBe(250);
    expect(Number(dot.getAttribute('rx'))).toBe(50);
    expect(Number(dot.getAttribute('ry'))).toBe(50);
  });

  it('collectByElId 的键是卡片定域的：卡内键带卡片名，页级键是裸 elId', () => {
    const svg = renderFree(SYNTH_DOC);
    const byKey = collectByElId(svg);
    expect(byKey.has(cardKey('synth_card', 'frame'))).toBe(true);
    expect(byKey.has('frame')).toBe(false); // 卡内元素不以裸 id 出现
    expect(byKey.has('synth_block')).toBe(true); // 页级块用裸 id
    expect(byKey.get('synth_block')).toHaveLength(2); // 1 个 <g> + 1 个 <text>
  });
});

// ---------------------------------------------------------------------------
describe.skipIf(!HAS_GOLDEN)('金样本：V1 结构对拍（11 份 demo 图纸）', () => {
  it('11 份图纸都在（少一份说明工作区没生成 demo，别把缺失当通过）', () => {
    expect(demoLayoutPaths()).toHaveLength(Object.keys(GOLDEN_STRUCTURE).length);
    expect(SAMPLES.map((sample) => sample.name).sort())
      .toEqual(Object.keys(GOLDEN_STRUCTURE).sort());
  });

  for (const sample of SAMPLES) {
    describe(sample.name, () => {
      const doc = sample.doc;
      const baseline = GOLDEN_STRUCTURE[sample.name];
      const svg = renderFree(doc);
      const byKey = collectByElId(svg);

      it('节点数：每张卡片 + 页级，全部由公式推导', () => {
        expect(baseline).toBeTypeOf('object'); // 新样本必须先补实测基准
        const cards = Array.isArray(doc.cards) ? doc.cards : [];
        const blocks = Array.isArray(doc.blocks) ? doc.blocks : [];
        const images = Array.isArray(doc.images) ? doc.images : [];

        const expectedPerCard = {};
        let expectedCardsTotal = 0;
        for (const card of cards) {
          const one = expectedCardNodes(card);
          expectedPerCard[card.name] = one;
          expectedCardsTotal += one;
        }

        let expectedPage = 0;
        for (const block of blocks) {
          // 每块：line_groups.length 个 <g> + 非空行数个 <text>
          expectedPage += expectedBlockNodes(block);
        }
        for (let i = 0; i < images.length; i += 1) expectedPage += 1; // 每张插图 1

        expect(actualCardNodes(svg)).toEqual(expectedPerCard);
        expect(actualPageNodes(svg)).toBe(expectedPage);
        expect(actualTotalNodes(svg)).toBe(expectedCardsTotal + expectedPage);

        // 与实测基准对拍（基准是「公式算出来的值」，两边必须一致）
        expect(expectedPerCard).toEqual(baseline.cards);
        expect(expectedCardsTotal).toBe(
          Object.values(baseline.cards).reduce((sum, one) => sum + one, 0),
        );
        expect(expectedPage).toBe(baseline.page);
        expect(actualTotalNodes(svg)).toBe(baseline.total);
      });

      it('每个契约元素都至少有一个 data-el-id 节点（漏打就是 MISSING≠0）', () => {
        for (const card of doc.cards || []) {
          for (const el of card.spec.elements || []) {
            const nodes = byKey.get(cardKey(card.name, el.id));
            expect(nodes, `卡 ${card.name} 的元素 ${el.id} 没有 data-el-id 节点`).toBeDefined();
            expect(nodes.length).toBeGreaterThan(0);
          }
        }
        for (const block of doc.blocks || []) {
          const nodes = byKey.get(block.name);
          expect(nodes, `页级块 ${block.name} 没有 data-el-id 节点`).toBeDefined();
          expect(nodes.length).toBeGreaterThan(0);
        }
        for (const image of doc.images || []) {
          const nodes = byKey.get(image.name);
          expect(nodes, `插图 ${image.name} 没有 data-el-id 节点`).toBeDefined();
          expect(nodes.length).toBeGreaterThan(0);
        }
      });

      it('逐元素 bbox 回算：px 空间零容差，跳过项显式计数', () => {
        const cards = Array.isArray(doc.cards) ? doc.cards : [];
        let elements = 0;
        let checked = 0;
        let skipped = 0;
        const skipHist = {};
        // 第二道闸门：逐分量绝对差的最大值。第一道闸门是下面的 `toEqual(expected)`；
        // 把 `toEqual` 弱化（例如改成 `toBeDefined()`）时，这条摘要断言仍然会红。
        // 见文件末尾合成 doc 组 + 报告里的定向破坏 3a。
        let maxAbsPxDiff = 0;

        for (const card of cards) {
          for (const el of card.spec.elements || []) {
            elements += 1;
            const kind = classifyElement(el);
            const nodes = byKey.get(cardKey(card.name, el.id));
            expect(nodes).toBeDefined();

            if (!BBOX_CHECKABLE.includes(kind)) {
              // 不可回算：track 是 2 节点且 cap 比盒底多 +22.36px；ticks 是 count 个 rect，
              // 并集不是元素盒；outline 只有 points；arc 只有 d；text 的 <g> 没有几何属性。
              skipped += 1;
              skipHist[kind] = (skipHist[kind] || 0) + 1;
              continue;
            }

            const expected = truncBox(el); // 逐边界 Math.trunc(*100)
            const actual = boxOf(nodes);
            expect(actual, `卡 ${card.name} / 元素 ${el.id}（${kind}）的 bbox 回算不上`)
              .toEqual(expected);
            checked += 1;

            // 累计逐分量绝对差（`actual` 取不到几何时按 `Infinity` 记，让摘要断言必红）。
            if (Array.isArray(actual) && actual.length === expected.length) {
              for (let i = 0; i < expected.length; i += 1) {
                maxAbsPxDiff = Math.max(
                  maxAbsPxDiff, Math.abs(Number(actual[i]) - Number(expected[i])),
                );
              }
            } else {
              maxAbsPxDiff = Infinity;
            }

            // 英寸空间的读数只用于让报错好读（1e-2 = 1px），**不做闸门**。
            // 注意 vitest 的 `toBeCloseTo(v, 2)` 是 0.005 不是 0.01；差值恰好是 1px 时
            // 浮点上会落到 0.010000000000000009，所以给一个极小的机器 epsilon。
            const node = nodes[0];
            if (node.getAttribute('x') != null) {
              expect(Math.abs(attrToInch(node, 'x') - (Number(el.x_in) || 0)))
                .toBeLessThanOrEqual(1e-2 + 1e-12);
              expect(Math.abs(attrToInch(node, 'y') - (Number(el.y_in) || 0)))
                .toBeLessThanOrEqual(1e-2 + 1e-12);
            }
          }
        }

        // 第二道闸门（值）：所有可回算元素的逐分量绝对差最大值为 0（px 零容差）。
        // 与上面的 `toEqual` 互为备份 —— 任何一方被弱化，另一方仍会红。
        //
        // `checked === 0` 只出现在 `_plain`（0 张卡片）：那份没有可比的元素，摘要断言
        // 天然真空，所以那种情形改为要求 `elements === 0`（不是「一个都没比也算过」）。
        if (checked > 0) {
          expect(maxAbsPxDiff, `${sample.name}：px 空间逐分量最大绝对差必须是 0`).toBe(0);
        } else {
          expect(elements, `${sample.name}：没有可回算元素时必须一个元素都没有`).toBe(0);
        }

        // 显式计数断言：不许把不可回算的元素静默丢掉。
        // 下面这条只是把「elements = checked + skipped」这个**定义**读一遍（两个计数器
        // 出自同一条分支，等式结构上恒成立），它自己抓不到错；真正咬人的是紧随其后的
        // 四条与实测基准对拍：elements / checked / skipped / skipHist 任一跑偏都会红。
        expect(elements).toBe(checked + skipped);
        expect(elements).toBe(baseline.elements);
        expect(checked).toBe(baseline.checked);
        expect(skipped).toBe(baseline.skipped);
        expect(skipHist).toEqual(baseline.skipHist);
      });

      it('arc：从 d 解析圆心得盒中心，半径得盒宽一半', () => {
        let arcs = 0;
        for (const card of doc.cards || []) {
          for (const el of card.spec.elements || []) {
            if (classifyElement(el) !== 'arc') continue;
            const node = byKey.get(cardKey(card.name, el.id))[0];
            expect(node.tagName).toBe('path');
            const d = node.getAttribute('d');
            // 形如 `M353.5,305.5 L… A123.5 123.5 0 … Z`
            const match = /^M(-?[\d.]+),(-?[\d.]+)\s+L(-?[\d.]+),(-?[\d.]+)\s+A(-?[\d.]+)\s+(-?[\d.]+)/.exec(d);
            expect(match, `卡 ${card.name} / 元素 ${el.id} 的 d 解析不了：${d}`).not.toBeNull();
            const [, cx, cy, , , r, r2] = match.map(Number);
            const [x0, y0, x1, y1] = truncBox(el);
            expect(cx).toBe((x0 + x1) / 2); // 圆心 x = 盒中心 x
            expect(cy).toBe((y0 + y1) / 2); // 圆心 y = 盒中心 y
            expect(r).toBe((x1 - x0) / 2); // 半径 = 盒宽一半
            expect(Number(r2)).toBe(r); // A 指令的两个半径相同
            arcs += 1;
          }
        }
        const expectedArcs = baseline.skipHist.arc || 0;
        expect(arcs).toBe(expectedArcs);
      });
    });
  }

  // -------------------------------------------------------------------------
  // 逐条点名、任务书里单列的判据
  // -------------------------------------------------------------------------
  describe('单列判据', () => {
    // 本组在 `describe.skipIf(!HAS_GOLDEN)` 里，走到这里说明金样本都在。
    const AUTO = goldenDoc('out/demo/auto_layout/pagelayout.json');
    const PLAIN = goldenDoc('out/demo/auto_layout/_plain/pagelayout.json');

    it('Review Focus #4：卡1 frame 的 x 属性是 0（相对卡片），卡片自己是 100', () => {
      const svg = renderFree(AUTO);
      const card = AUTO.cards.find((one) => one.name === 'heat_ratio_top5');
      // 卡片在格子里水平居中：格子 x=0.4、格子宽 6.072，画出来的真实外框 4.8656in
      // ⇒ x_in = 0.4 + (6.072 - 4.8656) / 2 = 1.0032（PR-B 前卡片贴格子左边，所以是 0.4）。
      expect(card.x_in).toBe(1.0032);
      const frameEl = card.spec.elements.find((el) => el.id === 'frame');
      expect(frameEl.x_in).toBe(0);
      const cardNode = cardNodeOf(svg, 'heat_ratio_top5');
      expect(cardNode.getAttribute('x')).toBe('100'); // roundPx(1.0032) = pyRound(100.32) = 100
      const frame = collectByElId(svg).get(cardKey('heat_ratio_top5', 'frame'))[0];
      expect(frame.getAttribute('x')).toBe('0');
      // 元素盒走 truncPx：trunc(4.8656*100) = 486、trunc(3.552267*100) = 355（不是 487/356）。
      expect(boxOf([frame])).toEqual([0, 0, 486, 355]);
    });

    it('collectByElId 按卡片定域：卡1/卡2 的同名 id 不会并成一个 union bbox', () => {
      const svg = renderFree(AUTO);
      const byKey = collectByElId(svg);
      // 裸 elId 会让卡1 的 frame(0,0,486,355) 与卡2 的 frame(0,0,494,495)
      // 合并成 union [0,0,494,495] → 卡1 直接假 FAIL。
      expect(byKey.has('frame')).toBe(false);
      expect(byKey.has('title')).toBe(false);
      expect(byKey.has('title_band')).toBe(false);
      expect(byKey.has('scale_note')).toBe(false);

      const frame1 = boxOf(byKey.get(cardKey('heat_ratio_top5', 'frame')));
      const frame2 = boxOf(byKey.get(cardKey('heat_age', 'frame')));
      expect(frame1).toEqual([0, 0, 486, 355]);
      expect(frame2).toEqual([0, 0, 494, 495]);
      expect(frame1).not.toEqual(frame2);

      // 页级块 / 插图不收在卡片里，键是裸 elId
      expect(byKey.has(AUTO.blocks[0].name)).toBe(true);
      expect(byKey.has(AUTO.images[0].name)).toBe(true);
    });

    it('_plain 夹具：0 张卡片不抛，页级字符节点数 === 6', () => {
      expect(PLAIN.cards).toHaveLength(0);
      const svg = renderFree(PLAIN); // 不抛即可
      expect(svg.querySelectorAll('[data-card-name]')).toHaveLength(0);
      // 3 块 × (1 个 <g> + 1 行 <text>) = 6
      expect(actualPageNodes(svg)).toBe(6);
      expect(actualTotalNodes(svg)).toBe(6);
      expect(actualPageNodes(svg)).toBe(expectedPageNodes(PLAIN));
    });

    it('占位卡每张 7 个节点（frame 1 + title_band 1 + title 2 + scale_note 2 + 占位 1）', () => {
      let found = 0;
      for (const sample of SAMPLES) {
        const withPlaceholder = (sample.doc.cards || []).filter(
          (card) => (card.spec.elements || []).some(isPlaceholderElement),
        );
        if (withPlaceholder.length === 0) continue;
        const svg = renderFree(sample.doc);
        for (const card of withPlaceholder) {
          expect(expectedCardNodes(card)).toBe(PLACEHOLDER_CARD_NODES);
          expect(actualCardNodes(svg)[card.name]).toBe(PLACEHOLDER_CARD_NODES);
          found += 1;
        }
      }
      expect(found).toBeGreaterThan(0); // 三份样本（multicol/_spread、page、paper）各有一张
    });
  });
});
