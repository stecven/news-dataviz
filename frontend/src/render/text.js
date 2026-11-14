/**
 * 单个 `text` 元素 → 一个 `<g>`（内含至多四个 `<text>`）。
 *
 * 坐标系与取整口径全部来自 `units.js`：盒坐标走 `boxPxTrunc`（四个边界各自
 * `Math.trunc`，与 `loop/preview.py` 的 `int(x*100)` 一致），字号走
 * `pxFromPt`，行距走 `lineHeightPx`，基线抬升走 `ascentPx`（= Pillow
 * `getmetrics()[0]` 在 6..64 像素区间零偏差）。
 *
 * 为什么不折行、不量宽：契约里 `lines` 已经是排版结果，客户端只需按行落笔。
 * 更重要的是浏览器侧量宽只有 `getBBox` / `getComputedTextLength`，jsdom 两个都
 * 没有，而用墨迹宽度回算的 `x` 在真浏览器里又会和 Pillow 差一个字形宽度。所以
 * 对齐一律交给 `text-anchor` + 盒宽（R29），`x` 只依赖盒边与锚点。
 *
 * 基线用 alphabetic（`y` 直接给基线位置）。**不要**改用
 * `dominant-baseline="text-before-edge"`：实测它会在浏览器里相对升部再漂一整行高。
 */
import {
  PX_PER_IN, ascentPx, boxPxTrunc, lineHeightPx, pxFromPt,
} from '../units.js';

const SVG_NS = 'http://www.w3.org/2000/svg';

/** 一屏最多画几行。契约的排版结果一般不超过这个数，超了按 `preview.py` 截断。 */
export const MAX_LINES = 4;

const ANCHORS = { left: 'start', center: 'middle', right: 'end' };

/** 把 `align` 归一成三档之一，未知值（含缺省）当 `center`（同 Python 侧）。 */
function normalizeAlign(raw) {
  const value = String(raw || 'center').toLowerCase();
  return Object.prototype.hasOwnProperty.call(ANCHORS, value) ? value : 'center';
}

/**
 * 取出要画的文本行。
 *
 * `card` 模式：行来自 `el.lines`（契约冻结的排版结果）；0.x 老样本没有 `lines`，
 * 退回把 `el.text` 当唯一一行，**不崩**。
 *
 * `block` 模式：行来自 `geometry.lines`（整版块的换行结果是排版阶段算好的，
 * 分栏在 `geometry.line_groups`，本轮不消费），`el.lines` 与 `el.text` 依次兜底。
 */
function linesFor(el, mode) {
  const geometry = el && el.geometry && typeof el.geometry === 'object' ? el.geometry : null;
  const candidates = mode === 'block'
    ? [geometry && geometry.lines, el && el.lines]
    : [el && el.lines, geometry && geometry.lines];
  for (const candidate of candidates) {
    if (Array.isArray(candidate) && candidate.length > 0) {
      return candidate.map((line) => (line == null ? '' : String(line)));
    }
  }
  // 兜底：0.x 老样本的路径 —— 整段 `text` 当成**唯一一行**画，**不折行**。
  // 所以超长 `text` 会横向溢出盒外（没有 `<textLength>`、也没有裁剪），
  // 与 Pillow 侧现场折行的结果不一致。这是刻意的：[契约 1.0 的 `lines` 由排版
  // 阶段冻结]，这里只负责「老样本别崩」，不接管折行职责。要折行得先有字体度量，
  // 而 jsdom 没有（R29）。
  if (el && el.text != null && String(el.text) !== '') return [String(el.text)];
  return [];
}

/**
 * 按 `mode` 取字号（磅）。
 *
 * `font_pt` 缺省（`null` / `undefined` / `''`）时**直接抛**：`Number(null)` 与
 * `Number('')` 都是 0，过去会让 `Number.isFinite` 放行，于是静默把字号画成零
 * —— 文字彻底不可见，而且不报错、不留痕。宁可崩在调用点。
 * **`font_pt = 0` 不抛**：0 是合法数值，是否可见由排版阶段负责。
 */
function fontPtFor(el, theme, mode) {
  if (mode === 'block') return theme.fontPt(el.role);
  const raw = el == null ? undefined : el.font_pt;
  if (raw == null || raw === '') {
    throw new Error(
      `renderText: 元素 ${JSON.stringify(el && el.id)} 缺 font_pt，`
      + `实际是 ${JSON.stringify(raw)}（不许静默当 0 画成不可见文字）`,
    );
  }
  const pt = Number(raw);
  if (!Number.isFinite(pt)) {
    throw new Error(
      `renderText: 元素 ${JSON.stringify(el && el.id)} 的 font_pt 不是有限数值，`
      + `实际是 ${JSON.stringify(el && el.font_pt)}`,
    );
  }
  return pt;
}

/**
 * 画一个 `text` 元素。
 *
 * @param {SVGElement} parent 挂载点（通常是卡片的内嵌 `<svg>`）
 * @param {object} el 契约里的 text 元素
 * @param {{theme: object, pxPerIn?: number, mode?: 'card'|'block'}} opts
 * @returns {SVGGElement} 含至多 `MAX_LINES` 个 `<text>`；`<g>` 与每个 `<text>`
 *   都带 `data-el-id`（T5 的结构对拍靠它定位）
 */
export function renderText(parent, el, opts = {}) {
  const theme = opts.theme;
  if (!theme) throw new Error('renderText: 缺少 theme（色的唯一来源）');
  const mode = opts.mode === 'block' ? 'block' : 'card';
  // 几何取整口径固定 100 像素每英寸；`pxPerIn` 只是签名里留着，方便将来换算，
  // 但**不许**把它混进盒坐标与字号（那会和 Pillow 的取整错开）。
  if (opts.pxPerIn != null && Number(opts.pxPerIn) !== PX_PER_IN) {
    throw new Error(
      `renderText: pxPerIn 必须等于 ${PX_PER_IN}（取整口径固定），`
      + `实际是 ${JSON.stringify(opts.pxPerIn)}`,
    );
  }

  const group = document.createElementNS(SVG_NS, 'g');
  group.setAttribute('data-el-id', el.id);

  const geometry = el.geometry && typeof el.geometry === 'object' ? el.geometry : null;
  const align = normalizeAlign(geometry && geometry.align);
  const [x0, y0, x1, y1] = boxPxTrunc(el);
  const fontPt = fontPtFor(el, theme, mode);
  const px = pxFromPt(fontPt);
  const lineH = lineHeightPx(fontPt);
  const lines = linesFor(el, mode);
  const count = Math.min(lines.length, MAX_LINES);
  // 左对齐时整体在盒内竖直居中；其余两档按 Pillow 的做法从盒顶起排（dy 恒 0）。
  const dy = align === 'left' && count > 0
    ? Math.max(0, ((y1 - y0) - lineH * count) / 2)
    : 0;
  const anchor = ANCHORS[align];
  const x = align === 'left' ? x0 : (align === 'right' ? x1 : x0 + (x1 - x0) / 2);
  const fill = theme.color('text');
  const baseline = y0 + dy + ascentPx(px);

  for (let i = 0; i < count; i += 1) {
    const line = lines[i];
    // 空行不落笔，但照样占一个行距（与整版块的空行处理一致）。
    if (line === '') continue;
    const node = document.createElementNS(SVG_NS, 'text');
    node.setAttribute('data-el-id', el.id);
    node.setAttribute('x', String(x));
    node.setAttribute('y', String(baseline + i * lineH));
    node.setAttribute('text-anchor', anchor);
    node.setAttribute('font-size', String(px));
    node.setAttribute('fill', fill);
    node.textContent = line;
    group.appendChild(node);
  }

  parent.appendChild(group);
  return group;
}
