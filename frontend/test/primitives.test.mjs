// @vitest-environment jsdom
/**
 * 图元渲染（P2 Task 3）的结构与属性断言。
 *
 * 判据来源：`docs/superpowers/plans/2026-11-14-js-renderer-readonly-render-p2.md`
 * 的 Task 3（Step 1 与 Step 4 两批），逐条对应：
 *
 *   - `lines` 六行只出四个 `<text>`，第五、六行的文字不许出现在序列化字符串里；
 *   - `font_pt = 11.26`、`align='left'`、盒高恰好一个行高时，第一个 `<text>` 的
 *     `y` === 盒顶 + `ascentPx(16)`（= 47），且行间距 === `lineHeightPx(11.26)`（= 21）；
 *   - `align` 三档的 `text-anchor` 与 `x`；`left` 多行整体垂直居中，其它档 `dy = 0`；
 *   - `lines` 为空而 `text` 有值的 0.x 老样本要退回单行，不崩；
 *   - 八个图元各自的节点数、填充/描边、几何属性；
 *   - 缺资源（`resolveAsset` 返回 `null`）/ `chart` / 未知类型 → 虚线占位 + 一条警告，
 *     **绝不抛**（spec D13）。
 *
 * 这里**不测文本宽度**：jsdom 既没有 `getBBox` 也没有 `textlength`。对齐一律靠
 * `text-anchor` + 盒宽算出的 `x`（R29），绝不用墨迹宽度回算。
 *
 * 需要 DOM（`createElementNS` / `innerHTML`），所以文件首行指定 jsdom 环境；
 * `vitest.config.mjs` 是 `environment: 'node'` 且本轮不许改，只能按文件覆盖。
 */
import { readFileSync, existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, describe, expect, it } from 'vitest';

import { createTheme } from '../src/theme.js';
import {
  ascentPx, boxPxTrunc, lineHeightPx, pxFromIn, pxFromPt, truncPx,
} from '../src/units.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const SAMPLE = resolve(HERE, '../../out/demo/auto_layout/pagelayout.json');
const HAS_SAMPLE = existsSync(SAMPLE);
const PAGE = HAS_SAMPLE ? JSON.parse(readFileSync(SAMPLE, 'utf8')) : null;

const SVG_NS = 'http://www.w3.org/2000/svg';

/** 新建一个挂到 body 的 `<svg>` 当父节点，返回 `[svg, theme]`。 */
function stage() {
  const svg = document.createElementNS(SVG_NS, 'svg');
  document.body.appendChild(svg);
  return { svg, theme: createTheme(PAGE.theme) };
}

/** 从真实夹具里按 `id` 取一个元素的深拷贝（防止实现对入参就地改写）。 */
function elementById(id) {
  for (const card of PAGE.cards) {
    for (const el of card.spec.elements) {
      if (el.id === id) return structuredClone(el);
    }
  }
  throw new Error(`夹具里没有元素 ${id}`);
}

/** `align='left'` 时的竖直居中偏移（R30）：`max(0, (盒高 - 行高*行数) / 2)`。 */
function dyFor(el, align, lineCount) {
  if (align !== 'left') return 0;
  const [, y0, , y1] = boxPxTrunc(el);
  const pt = Number(el.font_pt);
  const n = Math.min(lineCount, 4);
  return Math.max(0, ((y1 - y0) - lineHeightPx(pt) * n) / 2);
}

afterEach(() => {
  document.body.innerHTML = '';
});

describe.skipIf(!HAS_SAMPLE)('renderText（card 模式）', () => {
  it('六行只产出四个 text 节点，且第五、六行不进入序列化字符串', async () => {
    const { renderText } = await import('../src/render/text.js');
    const { svg, theme } = stage();
    const el = {
      id: 'six',
      type: 'text',
      role: 'title',
      x_in: 0.3,
      y_in: 0.3,
      w_in: 2,
      h_in: 0.9,
      geometry: { align: 'left' },
      lines: ['甲行', '乙行', '丙行', '丁行', '戊行', '己行'],
      font_pt: 11.26,
      fill: null,
    };
    const group = renderText(svg, el, { theme, mode: 'card' });

    expect(group.tagName.toLowerCase()).toBe('g');
    expect(group.querySelectorAll('text').length).toBe(4);

    const serialized = svg.innerHTML;
    expect(serialized).toContain('甲行');
    expect(serialized).toContain('丁行');
    expect(serialized).not.toContain('戊行');
    expect(serialized).not.toContain('己行');
  });

  it('Review Focus #3：首行 y === 盒顶 + ascentPx(16) === 47', async () => {
    const { renderText } = await import('../src/render/text.js');
    const { svg, theme } = stage();
    // 盒高 21 恰好等于一个行高，于是「左对齐多行居中」的 dy 正好是 0，
    // 这条用例就只考基线公式本身。
    const el = {
      id: 'rf3',
      type: 'text',
      role: 'title',
      x_in: 0.3,
      y_in: 0.3,
      w_in: 2,
      h_in: 0.21,
      geometry: { align: 'left' },
      lines: ['a'],
      font_pt: 11.26,
      fill: null,
    };
    const px = pxFromPt(11.26);
    expect(px).toBe(16);
    expect(Math.ceil(px * 1.058)).toBe(17);
    expect(ascentPx(px)).toBe(17);

    const group = renderText(svg, el, { theme, mode: 'card' });
    const first = group.querySelector('text');
    const boxTop = boxPxTrunc(el)[1];
    expect(boxTop).toBe(30);
    expect(Number(first.getAttribute('y'))).toBe(boxTop + ascentPx(px));
    expect(Number(first.getAttribute('y'))).toBe(47);
    expect(first.getAttribute('font-size')).toBe(String(px));
    expect(first.getAttribute('font-size')).toBe('16');
    expect(first.textContent).toBe('a');
  });

  it('行间距 === lineHeightPx(11.26) === 21', async () => {
    const { renderText } = await import('../src/render/text.js');
    const { svg, theme } = stage();
    expect(lineHeightPx(11.26)).toBe(21);
    const el = {
      id: 'lines3',
      type: 'text',
      role: 'value',
      x_in: 0.3,
      y_in: 0.3,
      w_in: 2,
      h_in: 0.9,
      geometry: { align: 'left' },
      lines: ['a', 'b', 'c'],
      font_pt: 11.26,
      fill: null,
    };
    const group = renderText(svg, el, { theme, mode: 'card' });
    const ys = Array.from(group.querySelectorAll('text')).map((n) => Number(n.getAttribute('y')));
    expect(ys.length).toBe(3);
    expect(ys[1] - ys[0]).toBe(21);
    expect(ys[2] - ys[1]).toBe(21);
  });

  it('align=left 多行整体垂直居中（dy 不小于 0）', async () => {
    const { renderText } = await import('../src/render/text.js');
    const { svg, theme } = stage();
    const el = {
      id: 'left2',
      type: 'text',
      role: 'body',
      x_in: 0.3,
      y_in: 0.3,
      w_in: 2,
      h_in: 1,
      geometry: { align: 'left' },
      lines: ['a', 'b'],
      font_pt: 11.26,
      fill: null,
    };
    const group = renderText(svg, el, { theme, mode: 'card' });
    const [, y0, , y1] = boxPxTrunc(el);
    expect(y1 - y0).toBe(100);
    const dy = dyFor(el, 'left', 2);
    expect(dy).toBe(29);
    const first = group.querySelector('text');
    expect(Number(first.getAttribute('y'))).toBe(y0 + dy + ascentPx(16));
  });

  it('align=left 且盒比内容矮时 dy 取 0，不出现负偏移', async () => {
    const { renderText } = await import('../src/render/text.js');
    const { svg, theme } = stage();
    const el = {
      id: 'tight',
      type: 'text',
      role: 'body',
      x_in: 0.3,
      y_in: 0.3,
      w_in: 2,
      h_in: 0.1,
      geometry: { align: 'left' },
      lines: ['a', 'b'],
      font_pt: 11.26,
      fill: null,
    };
    const group = renderText(svg, el, { theme, mode: 'card' });
    const first = group.querySelector('text');
    expect(Number(first.getAttribute('y'))).toBe(boxPxTrunc(el)[1] + ascentPx(16));
  });

  it('真实夹具的 title：左对齐单行，dy === (50-21)/2 === 14.5', async () => {
    const { renderText } = await import('../src/render/text.js');
    const { svg, theme } = stage();
    const el = elementById('title');
    expect(el.font_pt).toBe(11.26);
    expect(el.lines.length).toBe(1);
    const group = renderText(svg, el, { theme, mode: 'card' });
    const first = group.querySelector('text');
    const [, y0, , y1] = boxPxTrunc(el);
    expect(y1 - y0).toBe(50);
    expect(Number(first.getAttribute('y'))).toBe(y0 + 14.5 + ascentPx(16));
    expect(first.textContent).toBe('取暖电器细分品类成交额环比增速TOP5');
  });

  it('align 三档：left/center(缺省)/right 的 text-anchor 与 x', async () => {
    const { renderText } = await import('../src/render/text.js');
    const { theme } = stage();
    const base = {
      id: 'align-probe',
      type: 'text',
      role: 'label',
      x_in: 0.45,
      y_in: 0.3,
      w_in: 2,
      h_in: 0.3,
      lines: ['a'],
      font_pt: 6,
      fill: null,
    };
    const [x0, , x1] = boxPxTrunc(base);
    const width = x1 - x0;

    const cases = [
      ['left', 'start', x0],
      ['center', 'middle', x0 + width / 2],
      ['right', 'end', x0 + width],
    ];
    for (const [align, anchor, expectedX] of cases) {
      const { svg, theme: t } = stage();
      const group = renderText(svg, { ...base, geometry: { align } }, { theme: t, mode: 'card' });
      const node = group.querySelector('text');
      expect(node.getAttribute('text-anchor')).toBe(anchor);
      expect(Number(node.getAttribute('x'))).toBe(expectedX);
    }

    // geometry 里没有 align → 缺省 center。
    const { svg: svg2 } = stage();
    const group2 = renderText(svg2, { ...base, geometry: null }, { theme, mode: 'card' });
    const node2 = group2.querySelector('text');
    expect(node2.getAttribute('text-anchor')).toBe('middle');
    expect(Number(node2.getAttribute('x'))).toBe(x0 + width / 2);
  });

  it('非 left 档的 dy 恒为 0', async () => {
    const { renderText } = await import('../src/render/text.js');
    for (const align of ['center', 'right']) {
      const { svg, theme } = stage();
      const el = {
        id: `noddy-${align}`,
        type: 'text',
        role: 'label',
        x_in: 0.45,
        y_in: 0.3,
        w_in: 2,
        h_in: 1,
        geometry: { align },
        lines: ['a', 'b'],
        font_pt: 11.26,
        fill: null,
      };
      const group = renderText(svg, el, { theme, mode: 'card' });
      const first = group.querySelector('text');
      expect(Number(first.getAttribute('y'))).toBe(boxPxTrunc(el)[1] + ascentPx(16));
    }
  });

  it('lines 为空而 text 有值：退回按 text 单行画', async () => {
    const { renderText } = await import('../src/render/text.js');
    const { svg, theme } = stage();
    const el = {
      id: 'legacy',
      type: 'text',
      role: 'label',
      x_in: 0.3,
      y_in: 0.3,
      w_in: 2,
      h_in: 0.3,
      text: '0.x 老样本',
      lines: [],
      font_pt: 6,
      fill: null,
    };
    const group = renderText(svg, el, { theme, mode: 'card' });
    const nodes = group.querySelectorAll('text');
    expect(nodes.length).toBe(1);
    expect(nodes[0].textContent).toBe('0.x 老样本');
  });

  it('lines 整个缺省而 text 有值也不崩', async () => {
    const { renderText } = await import('../src/render/text.js');
    const { svg, theme } = stage();
    const el = {
      id: 'legacy2',
      type: 'text',
      role: 'label',
      x_in: 0.3,
      y_in: 0.3,
      w_in: 2,
      h_in: 0.3,
      text: '只有 text',
      font_pt: 6,
      fill: null,
    };
    const group = renderText(svg, el, { theme, mode: 'card' });
    const nodes = group.querySelectorAll('text');
    expect(nodes.length).toBe(1);
    expect(nodes[0].textContent).toBe('只有 text');
  });

  it('data-el-id 同时打在 <g> 与每个 <text> 上', async () => {
    const { renderText } = await import('../src/render/text.js');
    const { svg, theme } = stage();
    const el = elementById('label_1');
    const group = renderText(svg, el, { theme, mode: 'card' });
    expect(group.getAttribute('data-el-id')).toBe('label_1');
    const nodes = group.querySelectorAll('text');
    expect(nodes.length).toBe(1);
    for (const node of nodes) {
      expect(node.getAttribute('data-el-id')).toBe('label_1');
    }
  });

  it('文字颜色取 theme.color("text")，忽略元素的 fill', async () => {
    const { renderText } = await import('../src/render/text.js');
    const { svg, theme } = stage();
    const el = elementById('title');
    expect(el.fill).toBe(null);
    const group = renderText(svg, el, { theme, mode: 'card' });
    const node = group.querySelector('text');
    expect(node.getAttribute('fill')).toBe(theme.color('text'));
    expect(node.getAttribute('fill')).toBe('#222222');
  });

  it('不用 dominant-baseline（实测 text-before-edge 会多漂一个行高）', async () => {
    const { renderText } = await import('../src/render/text.js');
    const { svg, theme } = stage();
    const el = elementById('title');
    const group = renderText(svg, el, { theme, mode: 'card' });
    const node = group.querySelector('text');
    expect(node.hasAttribute('dominant-baseline')).toBe(false);
    expect(node.hasAttribute('alignment-baseline')).toBe(false);
  });

  it('block 模式：字号按 theme.fontPt(role) 查表，行取 geometry.lines', async () => {
    const { renderText } = await import('../src/render/text.js');
    const { svg, theme } = stage();
    const el = {
      id: 'block-1',
      type: 'text',
      role: 'title',
      x_in: 0.4,
      y_in: 0.4,
      w_in: 9.2,
      h_in: 0.475,
      geometry: { align: 'center', lines: ['第一行', '第二行'] },
      lines: [],
      font_pt: null,
    };
    const group = renderText(svg, el, { theme, mode: 'block' });
    const nodes = group.querySelectorAll('text');
    expect(nodes.length).toBe(2);
    const expectedPt = theme.fontPt('title');
    expect(expectedPt).toBe(20);
    const expectedPx = pxFromPt(expectedPt);
    for (const node of nodes) {
      expect(node.getAttribute('font-size')).toBe(String(expectedPx));
      expect(node.getAttribute('text-anchor')).toBe('middle');
    }
    expect(nodes[0].textContent).toBe('第一行');
    expect(nodes[1].textContent).toBe('第二行');
  });
});

describe('renderElement（其余图元，Step 4 判据）', () => {
  const PAGE_SAMPLE = resolve(HERE, '../../out/demo/page/pagelayout.json');
  const HAS_PAGE = existsSync(PAGE_SAMPLE);
  const PAGE_DOC = HAS_PAGE ? JSON.parse(readFileSync(PAGE_SAMPLE, 'utf8')) : null;

  function pageElementById(id) {
    for (const card of PAGE_DOC.cards) {
      for (const el of card.spec.elements) {
        if (el.id === id) return structuredClone(el);
      }
    }
    throw new Error(`page 夹具里没有元素 ${id}`);
  }

  function ctxFor(theme, extra = {}) {
    return { theme, mode: 'card', resolveAsset: null, warnings: [], ...extra };
  }

  /** `<rect>` 的 px 几何：起点取 trunc，宽高取「先 trunc 两端再相减」。 */
  function rectBox(box) {
    return {
      x: truncPx(box[0]),
      y: truncPx(box[1]),
      width: truncPx(box[0] + box[2]) - truncPx(box[0]),
      height: truncPx(box[1] + box[3]) - truncPx(box[1]),
    };
  }

  it('rect + role="frame"：一个 rect，fill 带 #，stroke 取 geometry.border，线宽 2', async () => {
    const { renderElement } = await import('../src/render/primitives.js');
    const { svg, theme } = stage();
    const el = elementById('frame');
    const nodes = renderElement(svg, el, ctxFor(theme));

    expect(Array.isArray(nodes)).toBe(true);
    expect(nodes.length).toBe(1);
    const rect = nodes[0];
    expect(rect.tagName.toLowerCase()).toBe('rect');
    expect(rect.getAttribute('fill')).toBe('#FFFFFF');
    expect(rect.getAttribute('stroke')).toBe('#A8AEB6');
    expect(rect.getAttribute('stroke-width')).toBe('2');
    expect(rect.getAttribute('data-el-id')).toBe('frame');
    expect(svg.contains(rect)).toBe(true);

    const [x0, y0, x1, y1] = boxPxTrunc(el);
    expect(Number(rect.getAttribute('x'))).toBe(x0);
    expect(Number(rect.getAttribute('y'))).toBe(y0);
    expect(Number(rect.getAttribute('width'))).toBe(x1 - x0);
    expect(Number(rect.getAttribute('height'))).toBe(y1 - y0);
    expect(Number(rect.getAttribute('width'))).toBe(607);
  });

  it('rect + role="frame" 缺 geometry.border 时退回 BORDER_ROLE（neutral_mid）', async () => {
    const { renderElement } = await import('../src/render/primitives.js');
    const { svg, theme } = stage();
    const el = elementById('frame');
    el.geometry = null;
    const [rect] = renderElement(svg, el, ctxFor(theme));
    expect(rect.getAttribute('stroke')).toBe(theme.color('neutral_mid'));
    expect(rect.getAttribute('stroke')).toBe('#A8AEB6');
    expect(rect.getAttribute('stroke-width')).toBe('2');
  });

  it('rect + role="title_band"：一个 rect，无描边', async () => {
    const { renderElement } = await import('../src/render/primitives.js');
    const { svg, theme } = stage();
    const el = elementById('title_band');
    const nodes = renderElement(svg, el, ctxFor(theme));

    expect(nodes.length).toBe(1);
    const rect = nodes[0];
    expect(rect.tagName.toLowerCase()).toBe('rect');
    expect(rect.getAttribute('fill')).toBe('#D6DADF');
    expect(rect.getAttribute('stroke')).toBeNull();
    expect(rect.getAttribute('stroke-width')).toBeNull();
    expect(rect.getAttribute('data-el-id')).toBe('title_band');
  });

  it('rect + role="liquid"：走兜底分支，fill + neutral_mid 描边（不是 track）', async () => {
    const { renderElement } = await import('../src/render/primitives.js');
    const { svg, theme } = stage();
    const el = elementById('liquid_1');
    expect(el.role).toBe('liquid');
    const nodes = renderElement(svg, el, ctxFor(theme));

    expect(nodes.length).toBe(1);
    const rect = nodes[0];
    expect(rect.tagName.toLowerCase()).toBe('rect');
    expect(rect.getAttribute('fill')).toBe('#E8A08C');
    expect(rect.getAttribute('stroke')).toBe(theme.color('neutral_mid'));
    expect(rect.getAttribute('stroke')).toBe('#A8AEB6');
    expect(rect.getAttribute('data-el-id')).toBe('liquid_1');
    // 兜底分支只有一个节点：绝不能顺手加成 track 那样的两个。
    expect(svg.querySelectorAll('[data-el-id="liquid_1"]').length).toBe(1);
  });

  it('rect + role="track"：一个无描边 rect + 一个半圆 path，共 2 个节点', async () => {
    const { renderElement } = await import('../src/render/primitives.js');
    const { svg, theme } = stage();
    const el = elementById('track_1');
    const nodes = renderElement(svg, el, ctxFor(theme));

    expect(nodes.length).toBe(2);
    const [body, cap] = nodes;
    expect(body.tagName.toLowerCase()).toBe('rect');
    expect(body.getAttribute('fill')).toBe('#FFFFFF');
    // 管身不许描边：加描边会在管口横一道直角灰线，把半圆顶切成方形。
    expect(body.getAttribute('stroke')).toBeNull();
    expect(cap.tagName.toLowerCase()).toBe('path');
    // 半圆顶也用同一个填充，且同样无描边。
    expect(cap.getAttribute('fill')).toBe('#FFFFFF');
    expect(cap.getAttribute('stroke')).toBeNull();
    expect(cap.getAttribute('d')).toMatch(/A/);
    expect(cap.getAttribute('d').trim().endsWith('Z')).toBe(true);

    // 半圆顶：cap_r = w_in*100/2，圆心 ((box0+box2)/2, box1+cap_r)，扫 180°→360°（上半圆）。
    const [x0, y0, x1] = boxPxTrunc(el);
    const capR = (el.w_in * 100) / 2;
    const capCx = (x0 + x1) / 2;
    const capCy = y0 + capR;
    expect(cap.getAttribute('d').startsWith(`M${capCx - capR},${capCy}`)).toBe(true);
    expect(cap.getAttribute('d')).toContain(`A${capR} ${capR} 0 0 1 ${capCx + capR},${capCy}`);

    // 多节点图元的每个节点都打同一个 data-el-id。
    for (const node of nodes) expect(node.getAttribute('data-el-id')).toBe('track_1');
  });

  it('ellipse：一个 ellipse，fill + neutral_mid 描边，几何取盒中心与半轴', async () => {
    const { renderElement } = await import('../src/render/primitives.js');
    const { svg, theme } = stage();
    const el = elementById('bulb_1');
    const nodes = renderElement(svg, el, ctxFor(theme));

    expect(nodes.length).toBe(1);
    const ellipse = nodes[0];
    expect(ellipse.tagName.toLowerCase()).toBe('ellipse');
    expect(ellipse.getAttribute('fill')).toBe('#E8A08C');
    expect(ellipse.getAttribute('stroke')).toBe('#A8AEB6');
    expect(ellipse.getAttribute('data-el-id')).toBe('bulb_1');

    const [x0, y0, x1, y1] = boxPxTrunc(el);
    expect(Number(ellipse.getAttribute('cx'))).toBe((x0 + x1) / 2);
    expect(Number(ellipse.getAttribute('cy'))).toBe((y0 + y1) / 2);
    expect(Number(ellipse.getAttribute('rx'))).toBe((x1 - x0) / 2);
    expect(Number(ellipse.getAttribute('ry'))).toBe((y1 - y0) / 2);
  });

  it('arc：一个 path，含两段弧线与 Z，起点落在盒左端点', async () => {
    const { renderElement } = await import('../src/render/primitives.js');
    const { svg, theme } = stage();
    const el = elementById('sector_1');
    expect(el.geometry.start_angle).toBe(180);
    expect(el.geometry.end_angle).toBe(194.4);
    const nodes = renderElement(svg, el, ctxFor(theme));

    expect(nodes.length).toBe(1);
    const path = nodes[0];
    expect(path.tagName.toLowerCase()).toBe('path');
    expect(path.getAttribute('fill')).toBe('#E8A08C');
    // 扇区描边色取 theme 里 sector_stroke 对应的色板角色（缺省 neutral_mid）。
    expect(path.getAttribute('stroke')).toBe(theme.color('neutral_mid'));
    expect(path.getAttribute('data-el-id')).toBe('sector_1');

    const d = path.getAttribute('d');
    expect(d).toMatch(/^M/);
    expect(d.trim().endsWith('Z')).toBe(true);
    expect(d).toMatch(/A/);

    // Pillow 的 pieslice 用**盒**算圆心与半径（bbox 闭区间），180° 指向 3 点方向再顺时针转到左端。
    const [x0, y0, x1, y1] = boxPxTrunc(el);
    const cx = (x0 + x1) / 2;
    const cy = (y0 + y1) / 2;
    const r = (x1 - x0) / 2;
    expect(d.startsWith(`M${cx},${cy} L${cx - r},${cy}`)).toBe(true);
    // 14.4° < 180°，large-arc 位为 0、sweep 位为 1（y 向下顺时针）。
    expect(d).toContain('A' + `${r} ${r} 0 0 1`);
  });

  it('arc：跨过 180° 的扇区把 large-arc 置 1', async () => {
    const { renderElement } = await import('../src/render/primitives.js');
    const { svg, theme } = stage();
    const el = elementById('sector_1');
    el.geometry = { ...el.geometry, start_angle: 0, end_angle: 200 };
    const [path] = renderElement(svg, el, ctxFor(theme));
    const d = path.getAttribute('d');
    expect(d).toContain(' 1 1 ');
  });

  it('ticks：13 个 rect，fill 取元素 fill，逐个落在外接盒的 trunc 后位置', async () => {
    const { renderElement } = await import('../src/render/primitives.js');
    const { tickRects } = await import('../src/shapes/ticks.js');
    const { svg, theme } = stage();
    const el = elementById('ticks_1');
    const rects = tickRects(el);
    expect(rects.length).toBe(13);

    const nodes = renderElement(svg, el, ctxFor(theme));
    expect(nodes.length).toBe(13);
    for (let i = 0; i < nodes.length; i += 1) {
      const node = nodes[i];
      expect(node.tagName.toLowerCase()).toBe('rect');
      expect(node.getAttribute('fill')).toBe('#C9C9C9');
      expect(node.getAttribute('data-el-id')).toBe('ticks_1');
      const expected = rectBox(rects[i]);
      expect(Number(node.getAttribute('x'))).toBe(expected.x);
      expect(Number(node.getAttribute('y'))).toBe(expected.y);
      expect(Number(node.getAttribute('width'))).toBe(expected.width);
      expect(Number(node.getAttribute('height'))).toBe(expected.height);
    }
    // 第一个刻度（自下而上）的实测量：x=89、y=198、8×1。
    expect(Number(nodes[0].getAttribute('x'))).toBe(89);
    expect(Number(nodes[0].getAttribute('y'))).toBe(198);
    expect(svg.querySelectorAll('[data-el-id="ticks_1"]').length).toBe(13);
  });

  it('outline：一个 polyline，线宽 3、fill=none、圆角连接，点位 ×100', async () => {
    const { renderElement } = await import('../src/render/primitives.js');
    const { outlinePolyline } = await import('../src/shapes/outline.js');
    const { svg, theme } = stage();
    const el = elementById('outline_1');
    const expectedPts = outlinePolyline(el);

    const nodes = renderElement(svg, el, ctxFor(theme));
    expect(nodes.length).toBe(1);
    const line = nodes[0];
    expect(line.tagName.toLowerCase()).toBe('polyline');
    expect(line.getAttribute('fill')).toBe('none');
    expect(line.getAttribute('stroke')).toBe('#C9C9C9');
    expect(line.getAttribute('stroke-width')).toBe('3');
    expect(line.getAttribute('stroke-linejoin')).toBe('round');
    expect(line.getAttribute('data-el-id')).toBe('outline_1');

    const pairs = line.getAttribute('points').trim().split(/\s+/);
    expect(pairs.length).toBe(expectedPts.length);
    const [px0, py0] = pairs[0].split(',').map(Number);
    expect(px0).toBeCloseTo(pxFromIn(expectedPts[0][0]), 6);
    expect(py0).toBeCloseTo(pxFromIn(expectedPts[0][1]), 6);
    expect(px0).toBeCloseTo(70.89, 6);
    expect(py0).toBeCloseTo(224.605, 6);
    // 首末点重合（闭合环）。
    const last = pairs[pairs.length - 1].split(',').map(Number);
    expect(last[0]).toBeCloseTo(px0, 6);
    expect(last[1]).toBeCloseTo(py0, 6);
  });

  it('image：resolveAsset 取到资源时画一个 <image>，宽高等于盒的 trunc 后尺寸', async () => {
    const { renderElement } = await import('../src/render/primitives.js');
    const svg = document.createElementNS(SVG_NS, 'svg');
    document.body.appendChild(svg);
    const theme = createTheme(PAGE_DOC.theme);
    const el = pageElementById('placeholder_1');
    expect(el.image_path).toBe('assets/placeholders/placeholder_todo.png');

    const seen = [];
    const warnings = [];
    const nodes = renderElement(svg, el, {
      theme,
      mode: 'card',
      warnings,
      resolveAsset: (path) => {
        seen.push(path);
        return 'blob:fixture/placeholder_todo.png';
      },
    });

    expect(nodes.length).toBe(1);
    const img = nodes[0];
    expect(img.tagName.toLowerCase()).toBe('image');
    expect(img.getAttribute('href')).toBe('blob:fixture/placeholder_todo.png');
    expect(img.getAttribute('data-el-id')).toBe('placeholder_1');
    // 交给 resolveAsset 的是契约里的 image_path 原文。
    expect(seen).toEqual(['assets/placeholders/placeholder_todo.png']);
    expect(warnings).toEqual([]);

    const [x0, y0, x1, y1] = boxPxTrunc(el);
    expect(Number(img.getAttribute('x'))).toBe(x0);
    expect(Number(img.getAttribute('y'))).toBe(y0);
    expect(Number(img.getAttribute('width'))).toBe(x1 - x0);
    expect(Number(img.getAttribute('height'))).toBe(y1 - y0);
    expect(Number(img.getAttribute('width'))).toBe(220);
    expect(Number(img.getAttribute('height'))).toBe(220);
  });

  it('image：resolveAsset 返回 null 时画虚线占位 + 一条警告，绝不抛', async () => {
    const { renderElement } = await import('../src/render/primitives.js');
    const svg = document.createElementNS(SVG_NS, 'svg');
    document.body.appendChild(svg);
    const theme = createTheme(PAGE_DOC.theme);
    const el = pageElementById('placeholder_1');
    const warnings = [];

    const nodes = renderElement(svg, el, {
      theme,
      mode: 'card',
      warnings,
      resolveAsset: () => null,
    });

    expect(nodes.length).toBeGreaterThanOrEqual(1);
    const box = nodes[0];
    expect(box.tagName.toLowerCase()).toBe('rect');
    expect(box.getAttribute('stroke-dasharray')).toBeTruthy();
    expect(box.getAttribute('stroke')).toBe(theme.color('placeholder_stroke'));
    expect(box.getAttribute('fill')).toBe('none');
    expect(box.getAttribute('data-el-id')).toBe('placeholder_1');
    for (const node of nodes) expect(node.getAttribute('data-el-id')).toBe('placeholder_1');
    expect(warnings.length).toBe(1);
    expect(warnings[0]).toContain('placeholder_1');
  });

  it('Review Focus #6：chart 画虚线占位 + 一条警告，不抛', async () => {
    const { renderElement } = await import('../src/render/primitives.js');
    const { svg, theme } = stage();
    const el = {
      id: 'chart_degrades',
      type: 'chart',
      role: 'chart',
      x_in: 0.5,
      y_in: 0.5,
      w_in: 1,
      h_in: 1,
      fill: null,
      geometry: null,
    };
    const warnings = [];
    let nodes;
    expect(() => {
      nodes = renderElement(svg, el, ctxFor(theme, { warnings }));
    }).not.toThrow();
    expect(nodes.length).toBeGreaterThanOrEqual(1);
    const box = nodes[0];
    expect(box.tagName.toLowerCase()).toBe('rect');
    expect(box.getAttribute('stroke-dasharray')).toBeTruthy();
    expect(box.getAttribute('stroke')).toBe(theme.color('placeholder_stroke'));
    expect(box.getAttribute('data-el-id')).toBe('chart_degrades');
    expect(warnings.length).toBe(1);
    expect(warnings[0]).toContain('chart_degrades');
  });

  it('未知 type 画虚线占位 + 警告，不抛', async () => {
    const { renderElement } = await import('../src/render/primitives.js');
    const { svg, theme } = stage();
    const el = {
      id: 'pie3d_unknown',
      type: 'pie3d',
      role: 'unknown',
      x_in: 0.5,
      y_in: 0.5,
      w_in: 1,
      h_in: 0.5,
      fill: null,
      geometry: null,
    };
    const warnings = [];
    let nodes;
    expect(() => {
      nodes = renderElement(svg, el, ctxFor(theme, { warnings }));
    }).not.toThrow();
    expect(nodes[0].tagName.toLowerCase()).toBe('rect');
    expect(nodes[0].getAttribute('stroke-dasharray')).toBeTruthy();
    expect(nodes[0].getAttribute('data-el-id')).toBe('pie3d_unknown');
    expect(warnings.length).toBe(1);
    expect(warnings[0]).toContain('pie3d_unknown');
  });

  it('text 走 renderText：返回 <g>，其 data-el-id 与每个 text 一致', async () => {
    const { renderElement } = await import('../src/render/primitives.js');
    const { svg, theme } = stage();
    const el = elementById('title');
    const nodes = renderElement(svg, el, ctxFor(theme));
    expect(nodes.length).toBe(1);
    const group = nodes[0];
    expect(group.tagName.toLowerCase()).toBe('g');
    expect(group.getAttribute('data-el-id')).toBe('title');
    expect(group.querySelectorAll('text').length).toBe(1);
    expect(group.querySelector('text').textContent).toBe(el.lines[0]);
  });
});
