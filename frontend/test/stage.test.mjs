// @vitest-environment jsdom
/**
 * P2 Task 4：整版渲染骨架（`renderPage`）与公开 API（`mountPage`）。
 *
 * 这里的期望值全部是从 Python 侧实测拿来的**字面量**（`out/demo/auto_layout`
 * 那张页的取值），不是"用实现再算一遍"：整页 1000×1500；卡1 贴在 (40, 239)、
 * PNG 尺寸 607×337；卡2 (40, 667)、607×496；标题首行 y=75、x=500；三段正文
 * 首行 y=139 / 199 / 627；两张插图 (677, 266, 283, 283) 与 (677, 774, 283, 283)。
 *
 * 金样本（`out/`）不入版本库：读不到时整组 skip，而不是红。
 */
import { afterEach, describe, expect, it } from 'vitest';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { renderPage } from '../src/render/stage.js';
import { mountPage } from '../src/index.js';
import {
  ascentPx, lineHeightPx, pxFromPt, roundPx,
} from '../src/units.js';
import { createTheme } from '../src/theme.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, '..', '..');

/** 读一份金样本；不存在返回 `null`（`out/` 被 gitignore，CI 上没有）。 */
function loadGolden(relPath) {
  const full = resolve(REPO_ROOT, relPath);
  if (!existsSync(full)) return null;
  return JSON.parse(readFileSync(full, 'utf8'));
}

const AUTO = loadGolden('out/demo/auto_layout/pagelayout.json');
const PLAIN = loadGolden('out/demo/auto_layout/_plain/pagelayout.json');
const MULTICOL = loadGolden('out/demo/multicol/_spread/pagelayout.json');
const ILLUSTRATED = loadGolden('out/demo/illustrated/pagelayout.json');

const hosts = [];

/** 造一个挂载点并渲染，登记以便每次测试后清理。 */
function render(doc, opts) {
  const host = document.createElement('div');
  document.body.appendChild(host);
  hosts.push(host);
  const out = renderPage(host, doc, opts);
  return { host, ...out };
}

afterEach(() => {
  while (hosts.length) hosts.pop().remove();
});

/** 深拷贝一份图纸，换掉 `blocks`，并清空卡片/插图让断言更干净。 */
function withBlocks(doc, blocks) {
  const copy = JSON.parse(JSON.stringify(doc));
  copy.blocks = blocks;
  copy.cards = [];
  copy.images = [];
  return copy;
}

/** 取某个 `data-el-id` 下的所有 `<text>`。 */
function textsOf(svg, elId) {
  return Array.from(svg.querySelectorAll(`text[data-el-id="${elId}"]`));
}

describe.skipIf(!AUTO)('renderPage：整页尺寸与两套取整口径', () => {
  it('viewBox 用内部像素坐标（roundPx 口径）；width/height 是 scale 决定的展示尺寸', () => {
    const { svg } = render(AUTO);
    // 内部坐标：10in × 15in，每英寸 100 像素 → 1000 × 1500（round，不是 trunc）
    expect(svg.getAttribute('viewBox')).toBe('0 0 1000 1500');
    // 展示尺寸：默认 scale = 96（每英寸展示像素），只影响外层 width/height
    expect(svg.getAttribute('width')).toBe('960');
    expect(svg.getAttribute('height')).toBe('1440');
  });

  it('scale 只改展示尺寸，一个内部坐标都不动', () => {
    const a = render(AUTO).svg;
    const b = render(AUTO, { scale: 192 }).svg;
    expect(b.getAttribute('viewBox')).toBe(a.getAttribute('viewBox'));
    expect(b.getAttribute('width')).toBe('1920');
    expect(b.getAttribute('height')).toBe('2880');
    // 卡片与文字的属性必须逐字相同 —— scale 混进取整口径就会在这里露馅
    const cardA = a.querySelector('[data-card-name]');
    const cardB = b.querySelector('[data-card-name]');
    expect(cardB.outerHTML).toBe(cardA.outerHTML);
    const textA = a.querySelector('text');
    const textB = b.querySelector('text');
    expect(textB.outerHTML).toBe(textA.outerHTML);
  });

  it('scale=100 时展示尺寸恰好等于内部像素尺寸（口径自证）', () => {
    const { svg } = render(AUTO, { scale: 100 });
    expect(svg.getAttribute('width')).toBe('1000');
    expect(svg.getAttribute('height')).toBe('1500');
    expect(svg.getAttribute('viewBox')).toBe('0 0 1000 1500');
  });

  it('画布底色是主题的 surface 角色，覆盖整页', () => {
    const { svg } = render(AUTO);
    const bg = svg.querySelector('[data-role="page-background"]');
    expect(bg).not.toBeNull();
    expect(bg.getAttribute('width')).toBe('1000');
    expect(bg.getAttribute('height')).toBe('1500');
    expect(bg.getAttribute('fill')).toBe(createTheme(AUTO.theme).color('surface'));
    // 底色不是契约元素，不许打 data-el-id（否则 V1 节点口径会被污染）
    expect(bg.hasAttribute('data-el-id')).toBe(false);
  });

  it('不手设 xmlns（XMLSerializer 自己会补，手设会让 sharp 报 redefined）', () => {
    const { svg } = render(AUTO);
    expect(svg.hasAttribute('xmlns')).toBe(false);
  });

  it('干净的样本不产任何 warning', () => {
    const { warnings } = render(AUTO);
    expect(warnings).toEqual([]);
  });
});

describe.skipIf(!AUTO)('renderPage：卡片 = 嵌套 svg（位置 round / 尺寸 trunc）', () => {
  it('卡片数量 === doc.cards.length', () => {
    const { svg } = render(AUTO);
    expect(svg.querySelectorAll('[data-card-name]').length).toBe(AUTO.cards.length);
  });

  it('卡1 贴在 (40, 239)，尺寸 607×337（位置 round、尺寸 trunc 的两套口径）', () => {
    const { svg } = render(AUTO);
    const card = svg.querySelector('[data-card-name="heat_ratio_top5"]');
    expect(card).not.toBeNull();
    expect(card.tagName.toLowerCase()).toBe('svg');
    // 位置：roundPx(0.4)=40、roundPx(2.3875)=239（trunc 会给 238）
    expect(card.getAttribute('x')).toBe('40');
    expect(card.getAttribute('y')).toBe('239');
    // 尺寸：truncPx(6.072)=607、truncPx(3.37654)=337（round 会给 338）
    expect(card.getAttribute('width')).toBe('607');
    expect(card.getAttribute('height')).toBe('337');
    expect(card.getAttribute('viewBox')).toBe('0 0 607 337');
    expect(card.getAttribute('overflow')).toBe('hidden');
  });

  it('卡2 贴在 (40, 667)，尺寸 607×496', () => {
    const { svg } = render(AUTO);
    const card = svg.querySelector('[data-card-name="heat_age"]');
    expect(card.getAttribute('x')).toBe('40');
    expect(card.getAttribute('y')).toBe('667');
    expect(card.getAttribute('width')).toBe('607');
    expect(card.getAttribute('height')).toBe('496');
    expect(card.getAttribute('viewBox')).toBe('0 0 607 496');
  });

  it('卡片容器本身不带 data-el-id（节点口径只数契约元素）', () => {
    const { svg } = render(AUTO);
    for (const card of svg.querySelectorAll('[data-card-name]')) {
      expect(card.hasAttribute('data-el-id')).toBe(false);
    }
  });

  it('Review Focus #5：单张卡片内所有 text 节点都晚于所有形状节点', () => {
    const { svg } = render(AUTO);
    for (const card of svg.querySelectorAll('[data-card-name]')) {
      const kinds = Array.from(card.children).map(
        (node) => (node.tagName.toLowerCase() === 'g' ? 'text' : 'shape'),
      );
      const lastShape = kinds.lastIndexOf('shape');
      const firstText = kinds.indexOf('text');
      expect(kinds.length).toBeGreaterThan(0);
      expect(kinds).toContain('text');
      expect(lastShape).toBeLessThan(firstText);
      // 一旦开始画文字，后面不许再出现形状
      expect(kinds.slice(firstText).every((kind) => kind === 'text')).toBe(true);
    }
  });

  it('卡片内元素的 data-el-id 是卡片局部 id，坐标相对卡片（不是 +40）', () => {
    const { svg } = render(AUTO);
    const card = svg.querySelector('[data-card-name="heat_ratio_top5"]');
    const first = AUTO.cards[0].spec.elements[0];
    const node = card.querySelector(`[data-el-id="${first.id}"]`);
    expect(node).not.toBeNull();
    // 卡1 frame 的 x_in = 0、卡片 x_in = 0.4 → 相对坐标必须是 0
    expect(first.x_in).toBe(0);
    expect(Number(node.getAttribute('x'))).toBe(0);
  });

  it('卡片缺 spec 不崩（老样本兜底）', () => {
    const doc = JSON.parse(JSON.stringify(AUTO));
    delete doc.cards[0].spec;
    const { svg, warnings } = render(doc);
    expect(svg.querySelectorAll('[data-card-name]').length).toBe(AUTO.cards.length);
    expect(warnings.some((w) => w.includes('spec'))).toBe(true);
  });
});

describe.skipIf(!AUTO)('renderPage：整版块（text-anchor 三档 + 无 dy）', () => {
  it('标题块：首行 y=45+30=75、居中 x=(40+960)/2=500、字号 28', () => {
    const { svg } = render(AUTO);
    const block = AUTO.blocks[0];
    const nodes = textsOf(svg, block.name);
    expect(nodes.length).toBe(block.lines.length);
    const node = nodes[0];
    expect(node.getAttribute('y')).toBe('75');
    expect(node.getAttribute('x')).toBe('500');
    expect(node.getAttribute('text-anchor')).toBe('middle');
    expect(node.getAttribute('font-size')).toBe('28');
    expect(node.textContent).toBe(block.lines[0]);
    // 期望值同时用公式表达一遍：y0 = roundPx(y_in + 0.05)
    const pt = createTheme(AUTO.theme).fontPt(block.style);
    expect(pt).toBe(20);
    expect(Number(node.getAttribute('y')))
      .toBe(roundPx(block.y_in + 0.05) + ascentPx(pxFromPt(pt)));
  });

  it('三段正文：首行 y=139/199/627、左对齐 x=40、字号 15（无竖直居中 dy）', () => {
    const { svg } = render(AUTO);
    const expected = [139, 199, 627];
    [1, 2, 3].forEach((i, k) => {
      const block = AUTO.blocks[i];
      const nodes = textsOf(svg, block.name);
      expect(nodes.length).toBe(1);
      const node = nodes[0];
      expect(Number(node.getAttribute('y'))).toBe(expected[k]);
      // 若把卡片那套 dy 带过来，这里会变成 139+4.x
      expect(Number(node.getAttribute('y')))
        .toBe(roundPx(block.y_in + 0.05) + ascentPx(pxFromPt(11)));
      expect(node.getAttribute('x')).toBe('40');
      expect(node.getAttribute('text-anchor')).toBe('start');
      expect(node.getAttribute('font-size')).toBe('15');
    });
  });

  it('多行块按 lineHeightPx 逐行下移，空行不落笔但仍占一行', () => {
    const { svg } = render(withBlocks(AUTO, [{
      name: 'b_multi',
      style: 'body',
      align: 'left',
      x_in: 0.4,
      y_in: 1.175,
      w_in: 9.2,
      h_in: 0.7,
      lines: ['第一行', '', '第三行'],
      line_groups: [['第一行', '', '第三行']],
      columns: 1,
      column_gutter_in: 0,
    }]));
    const nodes = textsOf(svg, 'b_multi');
    expect(nodes.length).toBe(2);
    expect(Number(nodes[0].getAttribute('y'))).toBe(139);
    const lineH = lineHeightPx(11);
    expect(lineH).toBe(21);
    // 第 3 行落在第 1 行下方两个行距处（空行照样占位）
    expect(Number(nodes[1].getAttribute('y'))).toBe(139 + 2 * lineH);
  });

  it('右对齐用 text-anchor=end，x 取盒右边（R43：绝不用 getBBox）', () => {
    const { svg } = render(withBlocks(AUTO, [{
      name: 'b_right',
      style: 'body',
      align: 'right',
      x_in: 0.4,
      y_in: 1.175,
      w_in: 9.2,
      h_in: 0.30625,
      lines: ['右对齐一行'],
      line_groups: [['右对齐一行']],
      columns: 1,
      column_gutter_in: 0,
    }]));
    const node = textsOf(svg, 'b_right')[0];
    expect(node.getAttribute('text-anchor')).toBe('end');
    expect(node.getAttribute('x')).toBe('960');
  });

  it('块节点用 block.name 打 data-el-id（doc 层没有 id 字段）', () => {
    const { svg } = render(AUTO);
    for (const block of AUTO.blocks) {
      expect(textsOf(svg, block.name).length).toBeGreaterThan(0);
    }
  });
});

describe.skipIf(!MULTICOL)('renderPage：多栏整版块逐栏渲染（R44 修订口径）', () => {
  it('两栏块产出 4 个 text 节点，两栏各自从 40 / 510 起排', () => {
    const { svg, warnings } = render(MULTICOL);
    const block = MULTICOL.blocks[3];
    expect(block.columns).toBe(2);
    expect(block.line_groups.map((g) => g.length)).toEqual([2, 2]);
    const nodes = textsOf(svg, block.name);
    expect(nodes.length).toBe(4);

    const inner = (block.w_in - (block.line_groups.length - 1) * block.column_gutter_in)
      / block.line_groups.length;
    const gutter = block.column_gutter_in;
    const x0First = roundPx(block.x_in);
    const x0Second = roundPx(block.x_in + (inner + gutter));
    expect(x0First).toBe(40);
    expect(x0Second).toBe(510);

    const y0 = roundPx(block.y_in + 0.05) + ascentPx(pxFromPt(11));
    const lineH = lineHeightPx(11);
    const rows = nodes.map((n) => [Number(n.getAttribute('x')), Number(n.getAttribute('y'))]);
    expect(rows).toEqual([
      [x0First, y0],
      [x0First, y0 + lineH],
      [x0Second, y0],
      [x0Second, y0 + lineH],
    ]);
    // 多栏不许降级、不许告警
    expect(warnings).toEqual([]);
  });

  it('缺 line_groups 时退回 block.lines', () => {
    const { svg } = render(withBlocks(MULTICOL, [{
      name: 'b_fallback',
      style: 'body',
      align: 'left',
      x_in: 0.4,
      y_in: 1.175,
      w_in: 9.2,
      h_in: 0.30625,
      lines: ['只有 lines'],
      columns: 1,
      column_gutter_in: 0,
    }]));
    const nodes = textsOf(svg, 'b_fallback');
    expect(nodes.length).toBe(1);
    expect(nodes[0].textContent).toBe('只有 lines');
    expect(nodes[0].getAttribute('x')).toBe('40');
  });
});

describe.skipIf(!AUTO)('renderPage：插图（rect 是盒内真实绘制矩形）', () => {
  it('两张图各自 1 个 image，位置与尺寸来自 rect 而不是外盒', () => {
    const { svg } = render(AUTO);
    const images = Array.from(svg.querySelectorAll('image'));
    expect(images.length).toBe(AUTO.images.length);
    const expected = [
      ['illustration_17', 677, 266, 283, 283],
      ['illustration_26', 677, 774, 283, 283],
    ];
    expected.forEach(([name, x, y, w, h]) => {
      const node = svg.querySelector(`image[data-el-id="${name}"]`);
      expect(node).not.toBeNull();
      expect(Number(node.getAttribute('x'))).toBe(x);
      expect(Number(node.getAttribute('y'))).toBe(y);
      expect(Number(node.getAttribute('width'))).toBe(w);
      expect(Number(node.getAttribute('height'))).toBe(h);
    });
  });

  it('resolveAsset 收到的是 image_path 原文，不是拼好的 URL', () => {
    const seen = [];
    const { svg } = render(AUTO, {
      resolveAsset: (path) => {
        seen.push(path);
        return `../../${path}`;
      },
    });
    expect(seen).toEqual(AUTO.images.map((img) => img.path));
    expect(seen[0]).toBe('assets/icons/radiator_soft.png');
    const node = svg.querySelector('image[data-el-id="illustration_17"]');
    expect(node.getAttribute('href')).toBe('../../assets/icons/radiator_soft.png');
  });

  it('缺省 resolveAsset = assetsBase + "/" + path（assetsBase 缺省 assets）', () => {
    const { svg } = render(AUTO);
    const node = svg.querySelector('image[data-el-id="illustration_17"]');
    expect(node.getAttribute('href')).toBe(`assets/${AUTO.images[0].path}`);
    const withBase = render(AUTO, { assetsBase: '/static' }).svg;
    expect(withBase.querySelector('image').getAttribute('href'))
      .toBe(`/static/${AUTO.images[0].path}`);
  });

  it('取不到资源 → 虚线占位 + title 提示 + warning，不抛', () => {
    const { svg, warnings } = render(AUTO, { resolveAsset: () => null });
    expect(svg.querySelectorAll('image').length).toBe(0);
    const holder = svg.querySelector('rect[data-el-id="illustration_17"]');
    expect(holder).not.toBeNull();
    expect(holder.getAttribute('stroke-dasharray')).toBeTruthy();
    expect(holder.querySelector('title')).not.toBeNull();
    expect(warnings.some((w) => w.includes('取不到'))).toBe(true);
  });
});

describe.skipIf(!ILLUSTRATED)('renderPage：rect 带偏移时按真实绘制矩形落位', () => {
  it('illustrated 的 rect=[0.83, 0, 2.84, 2.84] → (593, 260, 284, 284)', () => {
    const { svg } = render(ILLUSTRATED);
    const img = ILLUSTRATED.images[0];
    const node = svg.querySelector(`image[data-el-id="${img.name}"]`);
    expect(Number(node.getAttribute('x'))).toBe(roundPx(img.x_in + img.rect[0]));
    expect(Number(node.getAttribute('y'))).toBe(roundPx(img.y_in + img.rect[1]));
    expect(Number(node.getAttribute('width'))).toBe(roundPx(img.rect[2]));
    expect(Number(node.getAttribute('height'))).toBe(roundPx(img.rect[3]));
    // 外盒 w_in = 4.5（450px）—— 若按外盒拉伸，这里会是 450
    expect(Number(node.getAttribute('width'))).toBe(284);
  });
});

describe.skipIf(!AUTO)('renderPage：老样本兜底', () => {
  it('images 缺失 → 当空数组，不抛，并给出 warning', () => {
    const doc = JSON.parse(JSON.stringify(AUTO));
    delete doc.images;
    delete doc.version;
    const { svg, warnings } = render(doc);
    expect(svg).not.toBeNull();
    expect(svg.querySelectorAll('image').length).toBe(0);
    expect(warnings.some((w) => w.includes('images'))).toBe(true);
    expect(warnings.some((w) => w.includes('version'))).toBe(true);
  });

  it('blocks 缺失 → 当空数组，不抛', () => {
    const doc = JSON.parse(JSON.stringify(AUTO));
    delete doc.blocks;
    const { svg } = render(doc);
    // 卡片里本来就有文字（卡1/卡2 各若干行），所以数"整版块的文字"要排除卡片内部
    const outside = Array.from(svg.querySelectorAll('text')).filter(
      (node) => !node.closest('[data-card-name]'),
    );
    expect(outside.length).toBe(0);
    expect(svg.querySelectorAll('[data-card-name]').length).toBe(AUTO.cards.length);
  });

  it('rows 缺失同样不抛', () => {
    const doc = JSON.parse(JSON.stringify(AUTO));
    delete doc.rows;
    expect(() => render(doc)).not.toThrow();
  });

  it('theme 缺失时抛（有意：渲染器没有色板就不该静默画空白）', () => {
    const doc = JSON.parse(JSON.stringify(AUTO));
    delete doc.theme;
    expect(() => render(doc)).toThrow(/theme/i);
  });

  it('不调 assertDoc：缺 version 的老样本能画（契约宽松读）', () => {
    const doc = JSON.parse(JSON.stringify(AUTO));
    delete doc.version;
    expect(() => render(doc)).not.toThrow();
  });
});

describe.skipIf(!PLAIN)('renderPage：0 卡 3 块的老样本', () => {
  it('不抛，卡片为 0，块文字节点合计 3', () => {
    const { svg, warnings } = render(PLAIN);
    expect(svg.querySelectorAll('[data-card-name]').length).toBe(0);
    const texts = Array.from(svg.querySelectorAll('text[data-el-id]'));
    expect(texts.length).toBe(3);
    // 老样本的 lines 都是一行
    expect(warnings).toEqual([]);
  });
});

describe.skipIf(!AUTO)('renderPage：容器与返回结构', () => {
  it('返回 { svg, warnings }，svg 挂在容器里且是 svg 根节点', () => {
    const { host, svg, warnings } = render(AUTO);
    expect(svg.tagName.toLowerCase()).toBe('svg');
    expect(svg.parentNode).toBe(host);
    expect(Array.isArray(warnings)).toBe(true);
  });

  it('容器可以是选择器字符串', () => {
    const host = document.createElement('div');
    host.id = 'stage-by-selector';
    document.body.appendChild(host);
    hosts.push(host);
    const out = renderPage('#stage-by-selector', AUTO);
    expect(out.svg.parentNode).toBe(host);
  });

  it('容器可以省略（只建不挂）', () => {
    const out = renderPage(null, AUTO);
    expect(out.svg.tagName.toLowerCase()).toBe('svg');
    expect(out.svg.parentNode).toBeNull();
  });
});

describe.skipIf(!AUTO)('mountPage：公开 API', () => {
  it('挂载后返回 { svg, doc, on, destroy }', () => {
    const host = document.createElement('div');
    host.id = 'stage-mount';
    document.body.appendChild(host);
    hosts.push(host);
    const api = mountPage('#stage-mount', AUTO);
    expect(api.svg.parentNode).toBe(host);
    expect(typeof api.on).toBe('function');
    expect(typeof api.destroy).toBe('function');
    expect(api.doc.width_in).toBe(AUTO.width_in);
    // doc 是归一化后的副本（不是同一个对象）
    expect(api.doc).not.toBe(AUTO);
  });

  it("on('warning') 会补发挂载时已经产生的 warning", () => {
    const host = document.createElement('div');
    document.body.appendChild(host);
    hosts.push(host);
    const doc = JSON.parse(JSON.stringify(AUTO));
    delete doc.images;
    const api = mountPage(host, doc);
    const seen = [];
    api.on('warning', (message) => seen.push(message));
    expect(seen.length).toBe(1);
    expect(seen[0]).toContain('images');
  });

  it("on() 对 P3 才有的类型不抛（change/exportSVG 只是留注释）", () => {
    const host = document.createElement('div');
    document.body.appendChild(host);
    hosts.push(host);
    const api = mountPage(host, AUTO);
    expect(() => api.on('change', () => {})).not.toThrow();
    expect(() => api.on('exportSVG', () => {})).not.toThrow();
  });

  it('destroy() 摘掉 svg，之后再用会抛', () => {
    const host = document.createElement('div');
    document.body.appendChild(host);
    hosts.push(host);
    const api = mountPage(host, AUTO);
    api.destroy();
    expect(host.querySelector('svg')).toBeNull();
    expect(() => api.on('warning', () => {})).toThrow(/destroy/i);
  });

  it('theme 缺失时 mountPage 抛（不静默）', () => {
    const host = document.createElement('div');
    document.body.appendChild(host);
    hosts.push(host);
    const doc = JSON.parse(JSON.stringify(AUTO));
    delete doc.theme;
    expect(() => mountPage(host, doc)).toThrow(/theme/i);
  });
});
