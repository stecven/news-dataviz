// units.js 的口径测试。
//
// 每条断言都用**夹具里的真实数字**（`out/demo/auto_layout/pagelayout.json`、
// `tests/fixtures/contract/legacy/*.json`），不编造。
//
// 这个文件钉的是 Plan 的 Review Focus #1：`Math.trunc` 与 `Math.round` 两套
// 取整**不可互换**——差 1px 会让整页错位累积。卡内单卡渲染（T3）走 Python
// `int()` 的截断口径，整版合成（T4）走 Python `int(round())` 的四舍五入口径。
import { describe, expect, it } from 'vitest';

import {
  PX_PER_IN,
  PX_PER_PT,
  ascentPx,
  boxPxRound,
  boxPxTrunc,
  cardScale,
  lineHeightPx,
  pxFromIn,
  pxFromPt,
  roundPx,
  truncPx,
} from '../src/units.js';

describe('units: 取整口径', () => {
  // Review Focus #1：真实夹具里的 3.37654 in。
  // 337 vs 338 就是这两套口径的分水岭，不许任何一处“默认取整”。
  it('trunc_and_round_are_not_interchangeable', () => {
    expect(truncPx(3.37654)).toBe(337);
    expect(roundPx(3.37654)).toBe(338);
  });

  it('px_per_in_is_100_not_96', () => {
    // 与 loop/preview.py:13 同值。96 是外层 <svg> 的展示 scale，不是内部换算。
    expect(PX_PER_IN).toBe(100);
    expect(PX_PER_PT).toBeCloseTo(100 / 72, 12);
    expect(pxFromIn(1)).toBe(100);
  });
});

describe('units: 盒子四元组', () => {
  // 四个值各自截断，不是“整体包围盒”式截断：x0=45, y0=30, x1=562, y1=80。
  // 夹具里卡片 spec.elements[0] 的 frame 用的是 6.072 / 3.37654 一类的数。
  const box = { x_in: 0.45, y_in: 0.3, w_in: 5.172, h_in: 0.5 };

  it('box_truncates_each_coordinate_separately', () => {
    expect(boxPxTrunc(box)).toEqual([45, 30, 562, 80]);
  });

  it('box_rounds_each_coordinate_separately', () => {
    // x1 = 0.45 + 5.172 = 5.622 → 562.2 → round 562；y1 = 0.3 + 0.5 = 0.8 → 80
    expect(boxPxRound(box)).toEqual([45, 30, 562, 80]);
  });

  it('box_trunc_and_round_differ_on_real_card_frame', () => {
    // 真实卡片 frame：x=0, y=0, w=6.072, h=3.37654（auto_layout.pagelayout.json cards[0]）
    const frame = { x_in: 0.0, y_in: 0.0, w_in: 6.072, h_in: 3.37654 };
    expect(boxPxTrunc(frame)).toEqual([0, 0, 607, 337]);
    expect(boxPxRound(frame)).toEqual([0, 0, 607, 338]);
  });

  it('box_falls_back_to_zero_size_when_fields_are_absent', () => {
    // 老样本/占位元素可能缺 w_in/h_in；不许因此得到 NaN。
    expect(boxPxTrunc({ x_in: 0.1, y_in: 0.2 })).toEqual([10, 20, 10, 20]);
  });
});

describe('units: pt → px', () => {
  // 夹具里 thermometer 卡的元素 font_pt 写的是 11.26（= 9pt * 1.25 之类的换算产物）。
  it('px_from_pt_uses_100_per_inch', () => {
    expect(pxFromPt(11.26)).toBe(16); // round(11.26 * 100 / 72) = round(15.6388)
  });

  it('line_height_is_ratio_of_the_unrounded_px', () => {
    // 注意：不是 round(16 * 1.35) = 22，而是 round(11.26 * 100/72 * 1.35) = 21
    // 对齐 loop/palette.py::line_height_px。
    expect(lineHeightPx(11.26)).toBe(21);
  });
});

describe('units: 基线（Pillow getmetrics()[0] 等价）', () => {
  // 实测 12/12 全中的常数：ceil(px * 1.058)。
  // 1.059 在 px=17/34/51 就错，1.0625 错 19 处 —— 别“顺手修正”。
  it('ascent_matches_pillow_metrics', () => {
    const cases = [
      [6, 7], [7, 8], [16, 17], [17, 18], [18, 20], [21, 23],
      [22, 24], [24, 26], [26, 28], [28, 30], [31, 33], [32, 34],
    ];
    for (const [px, expected] of cases) {
      expect(ascentPx(px), `ascentPx(${px})`).toBe(expected);
    }
  });
});

describe('units: 卡片缩放比', () => {
  it('card_scale_matches_palette_canvas_scale', () => {
    // cards[0].w_in=6.072 / h_in=3.37654，基准画布 10×6
    const scale = cardScale({ w_in: 6.072, h_in: 3.37654 }, [10, 6]);
    expect(scale).toBeCloseTo(0.562757, 6);
    // min(0.6072, 0.562757) —— 取小的一维
    expect(scale).toBe(3.37654 / 6);
  });

  it('card_scale_falls_back_to_one_when_size_is_zero', () => {
    // 对齐 loop/palette.py::canvas_scale 的兜底
    expect(cardScale({ w_in: 0, h_in: 3.37654 }, [10, 6])).toBe(1);
    expect(cardScale({ w_in: 6.072, h_in: 0 }, [10, 6])).toBe(1);
    expect(cardScale({}, [10, 6])).toBe(1);
  });

  it('card_scale_prefers_the_smaller_dimension_when_only_one_is_large', () => {
    // 只放大宽：min(20/10, 6/6) = 1，字号不许跟着放大到溢出另一维
    expect(cardScale({ w_in: 20, h_in: 6 }, [10, 6])).toBe(1);
    // 只放大高：min(10/10, 12/6) = 1
    expect(cardScale({ w_in: 10, h_in: 12 }, [10, 6])).toBe(1);
  });
});
