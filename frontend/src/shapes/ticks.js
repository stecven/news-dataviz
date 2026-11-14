// `ticks` 复合图元的几何展开：把一个元素展开成一串短横刻度矩形。
//
// 这是 `loop/thermo_shape.py:17-34` 的逐行照抄。判据不是「看起来像」，是**每个
// 数字都与 Python 相同**（测试容差 1e-9）。改动本文件前请先改 Python 侧，再回来抄。
//
// 单位：输入（`el.x_in/y_in/w_in/h_in` 与 `geometry`）和输出**全是英寸**。
// 像素换算属 T3 的事，本模块不碰 `PX_PER_IN`，也不产出任何颜色/字号——主题归
// `theme.js`，这里只管几何。

import { optional, required } from './required.js';

/**
 * 把 `ticks` 元素展开成 `[[x, y, w, h], ...]`（英寸，y 向下）。
 *
 * 刻度贴在**管身右缘内侧**：右端恒等于管右缘（`x_in + w_in`）。刻度带上下各留
 * 一段 inset：上让出半圆管口的圆顶（否则最上面一条会从弧顶戳出来），下让出锥形
 * 收口（原版刻度到颈口为止）。
 *
 * 取参口径见 `required.js`：缺必需键抛错，非有限数值（`"abc"` / `null` / `NaN`）
 * 也抛错——不然一串 `NaN` 会安静地流进 SVG 属性里。
 *
 * @param {{x_in: number, y_in: number, w_in: number, h_in: number, geometry: object}} el
 * @returns {number[][]} 每个 `[x, y, w, h]`，**自下而上**排列。
 */
export function tickRects(el) {
  const g = el.geometry || {};
  // Python 是 `int(g["count"])`，对浮点**向零截断**；照抄成 Math.trunc，不是 Math.round。
  // 截断这一步留在调用处：`required()` 只保证「是个有限数字」，不保证是整数。
  const count = Math.trunc(required(g, 'count', 'ticks'));
  const length = required(g, 'len', 'ticks');
  const thick = required(g, 'thick', 'ticks');
  // 这两个是可选的：Python 是 `g.get("pad_top", 0.0)`，缺键按 0 处理。
  const padTop = optional(g, 'pad_top', 0.0, 'ticks');
  const padBottom = optional(g, 'pad_bottom', 0.0, 'ticks');

  const right = el.x_in + el.w_in;
  const top = el.y_in + padTop;
  const step = (el.h_in - padTop - padBottom) / count;

  const rects = [];
  for (let i = 0; i < count; i += 1) {
    // `count - 1 - i` 而不是 `i`：**自下而上**。i=0 那根 y 最大（y 轴向下 ⇒ 最靠下），
    // 最后一根贴着刻度带上沿。改成 `i` 会让整串刻度上下颠倒，而肉眼在 13 根等距短线
    // 上极难分辨——所以测试里有一条专门的「第一根在最下」断言钉着它。
    rects.push([right - length, top + (count - 1 - i) * step, length, thick]);
  }
  return rects;
}
