/**
 * JS 渲染器的公开入口。
 *
 * P2 只做**只读渲染**：把一份 `pagelayout.json` 画成一页 SVG、发发警告。
 * 编辑相关的接口（`change` 事件、`exportSVG`、`relayout`）是 P3 的事，这里
 * 既不实现、也不写"会抛错的假 stub"——留注释说明位置就够了，免得调用方以为
 * 它已经能用了。
 */
import { normalizeDoc } from './doc.js';
import { renderPage } from './render/stage.js';
import { createTheme } from './theme.js';

/**
 * 挂载一页图纸，返回一个可继续订阅警告的小句柄。
 *
 * @param {Element|string|null} container 挂载点（选择器 / DOM 节点 / `null` 只建不挂）
 * @param {object} doc 解析好的 `pagelayout.json`
 * @param {{scale?: number, assetsBase?: string, resolveAsset?: Function}} [opts]
 * @returns {{svg: SVGSVGElement, doc: object,
 *            on: (type: string, fn: Function) => Function,
 *            destroy: () => void}}
 *
 * 返回值里的 `doc` 是**归一化后的副本**（`normalizeDoc` 深拷贝，补了缺省键），
 * 不是调用方传进来的那个对象：P2 不改图纸，但让调用方能看见"渲染器眼中的图纸"
 * ——比如老样本缺 `images` 时，这里读到的就是 `[]`。
 */
export function mountPage(container, doc, opts = {}) {
  // 先归一化再渲染：`renderPage` 内部也会归一化一次，但这里需要把 warning 收集
  // 到句柄上（`on('warning')` 要能补发挂载时就已产生的那些），而且 `doc` 要回传。
  const { doc: normalized, warnings } = normalizeDoc(doc);
  // theme 缺失时这里就抛（`createTheme` 拒绝渲染）—— 在动手建 DOM 之前炸，
  // 免得页面上留一棵画了一半的空 SVG。
  createTheme(normalized.theme);

  const listeners = new Map();
  let destroyed = false;

  /** 把一条警告发给订阅者；没有订阅者就丢弃（警告同时在 `warnings` 里留档）。 */
  function emit(type, payload) {
    const bucket = listeners.get(type);
    if (!bucket) return;
    for (const fn of bucket) fn(payload);
  }

  const rendered = renderPage(container, normalized, opts);
  // **两份警告都要转发**：`normalizeDoc` 报的是"图纸怎么被宽松读的"（缺 `version`
  // / `images` …），`renderPage` 报的是"画的时候降级了什么"（卡片缺 `spec.elements`、
  // 插图取不到资源 …）。只收前者会让渲染期的降级**彻底静默**——而 `on('warning')`
  // 是 v1 唯一的公开降级通道。顺序保持「先 normalize 后 render」，与发生顺序一致。
  const allWarnings = warnings.concat(rendered.warnings || []);

  allWarnings.forEach((message) => emit('warning', message));

  return {
    svg: rendered.svg,
    doc: normalized,

    /**
     * 订阅事件。v1 只认 `'warning'`；`'change'` / `'exportSVG'` 是 P3 的接口，
     * 现在注册不抛（免得调用方为了兼容写 try/catch），但也永远不会有事件。
     */
    on(type, fn) {
      if (destroyed) {
        throw new Error('mountPage: 句柄已 destroy，不能再订阅事件');
      }
      if (typeof fn !== 'function') {
        throw new Error(`mountPage: on(${JSON.stringify(type)}) 的回调必须是函数`);
      }
      // 补发挂载阶段就已经产生的警告：调用方拿到句柄时这些事已经发生了，
      // 若只发"未来的"，`on('warning')` 就会静默漏掉最该看的那几条。
      // 补发的是**合集**（normalize + render），两者缺一都会让降级静默。
      if (type === 'warning') allWarnings.forEach((message) => fn(message));
      if (!listeners.has(type)) listeners.set(type, []);
      listeners.get(type).push(fn);
      return fn;
    },

    /** 摘掉 svg 并让句柄失效。重复调用是安全的（第二次什么都不做）。 */
    destroy() {
      if (destroyed) return;
      destroyed = true;
      listeners.clear();
      if (rendered.svg && rendered.svg.parentNode) {
        rendered.svg.parentNode.removeChild(rendered.svg);
      }
    },
  };
}

export { renderPage } from './render/stage.js';
export { normalizeDoc, assertDoc, ContractError } from './doc.js';
export { createTheme } from './theme.js';
export { CONTRACT_VERSION } from './version.js';
