/**
 * P2 Task 5 / V1 结构对拍：SVG 结构遍历小工具。
 *
 * 渲染器给每个契约元素的所有节点都打上 `data-el-id`（占位框的 `<title>` 除外，
 * 它本来就不该带）。但 `data-el-id` **不是全局唯一**的——契约里的元素 id
 * 只在「卡片内」或「页面级」各自唯一，跨卡片会重名。
 *
 * 实测（`out/demo/auto_layout`，54 个卡片元素）：`frame` / `title_band` /
 * `title` / `scale_note` 这四个 id **每张卡片里都各有一个**；11 份样本里凡
 * 卡片数 ≥2 的全部是 `dups=4`。若按裸 `elId` 建索引，卡1 的 `frame`
 * (0, 0, 607, 337) 与卡2 的 `frame` (0, 0, 607, 496) 会被合并成一个 union
 * bbox `[0, 0, 607, 496]`，于是「逐元素 bbox 回算」对卡1 的 frame 直接假 FAIL。
 *
 * 所以 `collectByElId` 的键**按卡片定域**：
 * - 卡片内元素：`` `${cardName}\u0000${elId}` ``（卡片名取 `[data-card-name]` 容器的属性值）
 * - 页面级块 / 插图：`elId` 本身
 *
 * 说明：本文件刻意不 import `src/units.js`，期望值一律在测试里内联算，
 * 免得「用实现算期望」自证。
 */

/** 渲染器的内部像素密度：1 英寸 = 100 用户单位（与契约一致，见 `src/units.js`）。 */
export const PX_PER_IN = 100;

/** 卡片定域键的分隔符（NUL，不可能出现在元素 id 或卡片名里）。 */
export const CARD_KEY_SEP = '\u0000';

/** 读一个数值属性；缺失或非数值返回 `null`。 */
function numAttr(node, attr) {
  if (!node || typeof node.getAttribute !== 'function') return null;
  const raw = node.getAttribute(attr);
  if (raw == null || raw === '') return null;
  const value = Number.parseFloat(raw);
  return Number.isFinite(value) ? value : null;
}

/**
 * 把属性值换算成英寸。
 * @param {SVGElement} node
 * @param {string} attr 例如 `'x'` / `'width'` / `'cx'`
 * @returns {number|null}
 */
export function attrToInch(node, attr) {
  const value = numAttr(node, attr);
  return value == null ? null : value / PX_PER_IN;
}

/**
 * 取单个节点的几何盒（px，`[x0, y0, x1, y1]`）。
 *
 * 两种属性组：`rect`/`image`/占位框是 `x,y,width,height`；`ellipse` 是
 * `cx,cy,rx,ry`（换算回外接盒）。`<g>` / `<text>` 没有任何几何属性（jsdom
 * 也没有 `getBBox`），返回 `null`。
 */
export function geomBox(node) {
  const x = numAttr(node, 'x');
  const y = numAttr(node, 'y');
  const width = numAttr(node, 'width');
  const height = numAttr(node, 'height');
  if (x != null && y != null && width != null && height != null) {
    return [x, y, x + width, y + height];
  }
  const cx = numAttr(node, 'cx');
  const cy = numAttr(node, 'cy');
  const rx = numAttr(node, 'rx');
  const ry = numAttr(node, 'ry');
  if (cx != null && cy != null && rx != null && ry != null) {
    return [cx - rx, cy - ry, cx + rx, cy + ry];
  }
  return null;
}

/**
 * 一组节点的几何并集盒（px，`[x0, y0, x1, y1]`）；一个几何都没有时返回 `null`。
 *
 * 注意：对 `track` / `ticks` / `outline` / `arc` 这类「一个元素多个节点、且并集
 * 不等于元素盒」的元素**不要**用它做 bbox 回算（见测试里的可覆盖类型清单）。
 *
 * @param {SVGElement[]|null} nodes
 * @returns {[number, number, number, number]|null}
 */
export function boxOf(nodes) {
  if (!Array.isArray(nodes) || nodes.length === 0) return null;
  let box = null;
  for (const node of nodes) {
    const one = geomBox(node);
    if (one == null) continue;
    if (box == null) {
      box = [one[0], one[1], one[2], one[3]];
    } else {
      box[0] = Math.min(box[0], one[0]);
      box[1] = Math.min(box[1], one[1]);
      box[2] = Math.max(box[2], one[2]);
      box[3] = Math.max(box[3], one[3]);
    }
  }
  return box;
}

/**
 * 按 `data-el-id` 收集节点，**键按卡片定域**。
 *
 * 卡片内元素 = `` `${cardName}\u0000${elId}` ``；页面级块 / 插图 = `elId` 本身。
 * 返回值保持文档顺序（同一键下的多个节点即多栏块共用同一 `data-el-id` 的情形）。
 *
 * @param {SVGSVGElement} svg 整页根 `<svg>`
 * @returns {Map<string, SVGElement[]>}
 */
export function collectByElId(svg) {
  /** @type {Map<string, SVGElement[]>} */
  const byKey = new Map();
  const push = (key, node) => {
    const bucket = byKey.get(key);
    if (bucket) bucket.push(node);
    else byKey.set(key, [node]);
  };

  const cards = Array.from(svg.querySelectorAll('[data-card-name]'));
  for (const cardNode of cards) {
    const cardName = cardNode.getAttribute('data-card-name');
    for (const node of cardNode.querySelectorAll('[data-el-id]')) {
      push(`${cardName}${CARD_KEY_SEP}${node.getAttribute('data-el-id')}`, node);
    }
  }
  for (const node of svg.querySelectorAll('[data-el-id]')) {
    // 卡片内的节点已经以定域键收过一遍，这里跳过。
    if (node.closest('[data-card-name]')) continue;
    push(node.getAttribute('data-el-id'), node);
  }
  return byKey;
}

/** 卡片定域键（与 `collectByElId` 的规则一致）。 */
export function cardKey(cardName, elId) {
  return `${cardName}${CARD_KEY_SEP}${elId}`;
}
