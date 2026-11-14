/**
 * 一个契约元素 → 若干 SVG 节点。
 *
 * 分支顺序**严格照抄** `loop/preview.py:66-127`（`render_preview` 里的 if/elif 链）：
 * `text` → `frame` → `title_band` → `ticks` → `outline` → `ellipse` → `arc` →
 * `image` → `track` → 兜底。顺序不是风格问题：`track` / `liquid` 都是
 * `type: "rect"`，只有 role 能把它们分开；先判 type 再判 role 会把 `role: "track"`
 * 的管子画成普通矩形。同理 `title_band` 必须在兜底之前，否则它会白得一条描边。
 *
 * 颜色的唯一来源是 `ctx.theme`；这里一个色值都不写死（V6 守卫会扫）。元素的
 * `fill` 是契约给的十六进制串（不带前缀），补前缀属于**数据搬运**而不是配色决策。
 *
 * 缺资源不抛：`image` 取不到资源、`type: "chart"`、以及未知 `type` 一律画虚线
 * 占位框并往 `ctx.warnings` 记一条中文告警（spec D13 / 计划不变式 6）。Python 侧
 * 在这里会抛 `ValueError` / `FileNotFoundError`，JS 侧改成「退化但不崩」。
 */
import {
  PX_PER_IN, boxPxTrunc, pxFromIn, truncPx,
} from '../units.js';
import { BORDER_ROLE } from '../theme.js';
import { optional } from '../shapes/required.js';
import { tickRects } from '../shapes/ticks.js';
import { outlinePolyline } from '../shapes/outline.js';
import { renderText } from './text.js';

const SVG_NS = 'http://www.w3.org/2000/svg';

/** 与 `doc.js` 的 `ELEMENT_TYPES` 同一张表：不在这张表里的 type 一律画占位。 */
const KNOWN_TYPES = ['rect', 'ellipse', 'arc', 'text', 'ticks', 'outline', 'image', 'chart'];

/** 占位框的虚线节奏（SVG 属性值，不是字号也不是色值）。 */
const PLACEHOLDER_DASH = '6 4';

/** 框架描边宽度。Pillow 的 `width=2` 向内画，SVG 居中画，差 1 像素是已知且接受的。 */
const FRAME_STROKE_WIDTH = 2;

/** 外轮廓折线宽度（`preview.py` 的 `draw.line(..., width=3)`）。 */
const OUTLINE_STROKE_WIDTH = 3;

/**
 * 把契约里的十六进制串补成 SVG 认的形式；空值返回 `null` 交给调用方兜底。
 *
 * 契约里 `fill` 是 `"E8A08C"` 这种裸串（Python 侧 `_hex` 负责补井号），
 * 这里做同一件事：只补前缀，不改值。
 */
function asHex(value) {
  const text = value == null ? '' : String(value).trim();
  if (text === '') return null;
  return text.startsWith('#') ? text : `#${text}`;
}

/** 元素填充色：契约给了就用，没给就用主题的画布色（Python 侧 `_hex` 同款兜底）。 */
function fillOf(el, theme) {
  return asHex(el && el.fill) || theme.color('surface');
}

/** 建一个带 `data-el-id` 的节点。`null` 值的属性直接不写（不是写成空串）。 */
function make(el, name, attrs) {
  const node = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attrs)) {
    if (value == null) continue;
    node.setAttribute(key, String(value));
  }
  node.setAttribute('data-el-id', el.id);
  return node;
}

/** 盒的像素几何：起点各自取整，宽高取「两端分别取整后相减」。 */
function boxRect(el) {
  const [x0, y0, x1, y1] = boxPxTrunc(el);
  return {
    x: x0, y: y0, width: x1 - x0, height: y1 - y0,
  };
}

/** 英寸盒 → 像素盒，逐边界取整（ticks 的每个小矩形都走这条）。 */
function inchRectToPx(x, y, w, h) {
  const x0 = truncPx(x);
  const y0 = truncPx(y);
  return {
    x: x0,
    y: y0,
    width: truncPx(x + w) - x0,
    height: truncPx(y + h) - y0,
  };
}

/** 一个矩形节点，`fill` 必给，描边按需。 */
function rectNode(el, box, fill, stroke, strokeWidth) {
  return make(el, 'rect', {
    x: box.x,
    y: box.y,
    width: box.width,
    height: box.height,
    fill,
    stroke: stroke || null,
    'stroke-width': stroke == null ? null : strokeWidth,
  });
}

/**
 * Pillow 的角度 → 屏幕坐标。
 *
 * `pieslice` 的 0 度在 3 点方向，角度顺时针增大，而屏幕的 y 轴向下，所以
 * `x = cx + r*cos(a)`、`y = cy + r*sin(a)` 直接给出顺时针前进的点，
 * **不要**再对 y 取反（那会把半圆翻到下半边）。
 */
function pointOnCircle(cx, cy, r, degs) {
  const rad = (degs * Math.PI) / 180;
  return [cx + r * Math.cos(rad), cy + r * Math.sin(rad)];
}

/** 由盒（bbox 口径，与 `pieslice` 的闭区间外接盒一致）取圆心与半径。 */
function circleOfBox(box) {
  return {
    cx: box.x + box.width / 2,
    cy: box.y + box.height / 2,
    r: box.width / 2,
  };
}

/**
 * 虚线占位框 + 一条告警。
 *
 * 占位框里挂一个 `<title>`：鼠标悬停能看到原因，等于 spec D13 说的「在图上标注」，
 * 又不引入任何字号常量（占位文案的排版交给浏览器默认）。
 */
function placeholder(parent, el, ctx, message) {
  const theme = ctx.theme;
  const box = boxRect(el);
  const node = make(el, 'rect', {
    x: box.x,
    y: box.y,
    width: box.width,
    height: box.height,
    fill: 'none',
    stroke: theme.color('placeholder_stroke'),
    'stroke-dasharray': PLACEHOLDER_DASH,
  });
  const note = document.createElementNS(SVG_NS, 'title');
  note.textContent = message;
  node.appendChild(note);
  parent.appendChild(node);
  if (Array.isArray(ctx.warnings)) ctx.warnings.push(message);
  return [node];
}

/** `role: "frame"`：矩形 + 描边，描边色取 `geometry.border`，缺省用主题的角色色。 */
function drawFrame(parent, el, ctx) {
  const theme = ctx.theme;
  const geometry = el.geometry && typeof el.geometry === 'object' ? el.geometry : {};
  const stroke = asHex(geometry.border) || theme.color(BORDER_ROLE);
  const node = rectNode(el, boxRect(el), fillOf(el, theme), stroke, FRAME_STROKE_WIDTH);
  parent.appendChild(node);
  return [node];
}

/** `role: "title_band"`：纯色底，**不描边**（描边会在标题带上沿压出一条灰线）。 */
function drawTitleBand(parent, el, ctx) {
  const node = rectNode(el, boxRect(el), fillOf(el, ctx.theme), null, null);
  parent.appendChild(node);
  return [node];
}

/** `type: "ticks"`：每个刻度一个小矩形，填充取元素自己的 `fill`。 */
function drawTicks(parent, el, ctx) {
  const theme = ctx.theme;
  const fill = fillOf(el, theme);
  const nodes = [];
  for (const [x, y, w, h] of tickRects(el)) {
    const node = rectNode(el, inchRectToPx(x, y, w, h), fill, null, null);
    parent.appendChild(node);
    nodes.push(node);
  }
  return nodes;
}

/** `type: "outline"`：一条闭合折线，只描不填。 */
function drawOutline(parent, el, ctx) {
  const theme = ctx.theme;
  const points = outlinePolyline(el)
    .map(([px, py]) => `${pxFromIn(px)},${pxFromIn(py)}`)
    .join(' ');
  const node = make(el, 'polyline', {
    points,
    fill: 'none',
    stroke: asHex(el.fill) || theme.color('outline'),
    'stroke-width': OUTLINE_STROKE_WIDTH,
    'stroke-linejoin': 'round',
  });
  parent.appendChild(node);
  return [node];
}

/** `type: "ellipse"`：椭圆，填充 + 中间调描边。 */
function drawEllipse(parent, el, ctx) {
  const theme = ctx.theme;
  const box = boxRect(el);
  const node = make(el, 'ellipse', {
    cx: box.x + box.width / 2,
    cy: box.y + box.height / 2,
    rx: box.width / 2,
    ry: box.height / 2,
    fill: fillOf(el, theme),
    stroke: theme.color(BORDER_ROLE),
  });
  parent.appendChild(node);
  return [node];
}

/** `type: "arc"`：`pieslice` 的等价物，一个 `<path>`（圆心 → 起点，弧，闭合）。 */
function drawArc(parent, el, ctx) {
  const theme = ctx.theme;
  const geometry = el.geometry && typeof el.geometry === 'object' ? el.geometry : {};
  // 缺省值照 `preview.py` 的 `g.get("start_angle", 180.0)` / `g.get("end_angle", 360.0)`。
  const start = optional(geometry, 'start_angle', 180, 'arc');
  const end = optional(geometry, 'end_angle', 360, 'arc');
  const { cx, cy, r } = circleOfBox(boxRect(el));
  const [sx, sy] = pointOnCircle(cx, cy, r, start);
  const [ex, ey] = pointOnCircle(cx, cy, r, end);
  const largeArc = end - start > 180 ? 1 : 0;
  // sweep 取 1：屏幕坐标里角度顺时针增大，与 Pillow 的走向一致。
  const d = `M${cx},${cy} L${sx},${sy} A${r} ${r} 0 ${largeArc} 1 ${ex},${ey} Z`;
  const node = make(el, 'path', {
    d,
    fill: fillOf(el, theme),
    stroke: theme.color(BORDER_ROLE),
  });
  parent.appendChild(node);
  return [node];
}

/** `type: "image"`：资源取到就贴图，取不到退化占位。 */
function drawImage(parent, el, ctx) {
  const theme = ctx.theme;
  const path = el.image_path;
  if (path == null || String(path) === '') {
    return placeholder(
      parent, el, ctx,
      `元素 ${JSON.stringify(el.id)} 的 type="image" 没有 image_path，画虚线占位框`,
    );
  }
  const resolveAsset = typeof ctx.resolveAsset === 'function' ? ctx.resolveAsset : null;
  const href = resolveAsset ? resolveAsset(path) : null;
  if (href == null || String(href) === '') {
    return placeholder(
      parent, el, ctx,
      `元素 ${JSON.stringify(el.id)} 的图片资源 ${JSON.stringify(path)} 取不到，画虚线占位框`,
    );
  }
  const box = boxRect(el);
  const node = make(el, 'image', {
    x: box.x,
    y: box.y,
    width: box.width,
    height: box.height,
    href,
  });
  parent.appendChild(node);
  return [node];
}

/**
 * `role: "track"`：温度计管子 —— 管身矩形 + 顶端半圆，共两个节点，都不描边。
 *
 * 描边会在管口横一道直角灰线把半圆顶切成方形；`preview.py` 这里也刻意只填不描。
 */
function drawTrack(parent, el, ctx) {
  const theme = ctx.theme;
  const fill = fillOf(el, theme);
  const box = boxRect(el);
  const body = rectNode(el, box, fill, null, null);
  parent.appendChild(body);

  // 半圆顶半径按 `preview.py:118` 的 `r = w_in * PX_PER_IN / 2` 算：用**未截断**的
  // `w_in` 而不是盒宽（`box.width` 是两个边界各自截断后相减，可能差 1px）。
  const capR = (el.w_in * PX_PER_IN) / 2;
  const capCx = box.x + box.width / 2;
  const capCy = box.y + capR;
  const d = `M${capCx - capR},${capCy}`
    + ` A${capR} ${capR} 0 0 1 ${capCx + capR},${capCy} Z`;
  const cap = make(el, 'path', { d, fill });
  parent.appendChild(cap);
  return [body, cap];
}

/**
 * 画一个元素。
 *
 * @param {SVGElement} parent 挂载点
 * @param {object} el 契约元素
 * @param {{theme: object, mode?: 'card'|'block', resolveAsset?: Function,
 *   warnings?: string[]}} ctx 渲染上下文（各 Task 间形状固定）
 * @returns {SVGElement[]} 本次落盘的节点，按绘制顺序
 */
export function renderElement(parent, el, ctx = {}) {
  const theme = ctx.theme;
  if (!theme) throw new Error('renderElement: 缺少 theme（色的唯一来源）');

  // 1. text：按 type 判，不看 role（`preview.py` 的第一条分支）。
  if (el.type === 'text') {
    return [renderText(parent, el, { theme, mode: ctx.mode })];
  }

  // 2. chart 与未知 type：退化占位，绝不崩。
  if (el.type === 'chart') {
    return placeholder(
      parent, el, ctx,
      `元素 ${JSON.stringify(el.id)} 的 type="chart" 未在 JS 渲染器实现，画虚线占位框`,
    );
  }
  if (!KNOWN_TYPES.includes(el.type)) {
    return placeholder(
      parent, el, ctx,
      `元素 ${JSON.stringify(el.id)} 的 type ${JSON.stringify(el.type)} 未知，画虚线占位框`,
    );
  }

  // 3. 其余分支的顺序即 `preview.py` 的 if/elif 链。
  if (el.role === 'frame') return drawFrame(parent, el, ctx);
  if (el.role === 'title_band') return drawTitleBand(parent, el, ctx);
  if (el.type === 'ticks') return drawTicks(parent, el, ctx);
  if (el.type === 'outline') return drawOutline(parent, el, ctx);
  if (el.type === 'ellipse') return drawEllipse(parent, el, ctx);
  if (el.type === 'arc') return drawArc(parent, el, ctx);
  if (el.type === 'image') return drawImage(parent, el, ctx);
  if (el.role === 'track') return drawTrack(parent, el, ctx);

  // 4. 兜底：普通矩形 + 中间调描边。`role: "liquid"` 走这里。
  const node = rectNode(
    el, boxRect(el), fillOf(el, theme), theme.color(BORDER_ROLE), null,
  );
  // 兜底描边沿用 Pillow 的默认宽度（1 像素），所以不传 stroke-width。
  parent.appendChild(node);
  return [node];
}
