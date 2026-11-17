// units.js 的口径测试。
//
// 每条断言都用**夹具里的真实数字**（`out/demo/auto_layout/pagelayout.json`、
// `tests/fixtures/contract/legacy/*.json`），不编造。
//
// 这个文件钉的是 Plan 的 Review Focus #1：`Math.trunc` 与 `Math.round` 两套
// 取整**不可互换**——差 1px 会让整页错位累积。卡内单卡渲染（T3）走 Python
// `int()` 的截断口径，整版合成（T4）走 Python `int(round())` 的四舍五入口径。
//
// 第二组判据是 R36：**`int(round(x))` 不是 `Math.round(x)`**——Python 的 `round()`
// 是 half-to-even（银行家舍入）。真实产物里 `font_pt = 9.0`（→ 12.5）与插图
// `rect[1] = 1.065`（→ 106.5）都恰好落在中点，两侧会分叉。见下面两组用例。
import { describe, expect, it } from 'vitest';

import {
  PX_PER_IN,
  PX_PER_PT,
  ascentPx,
  boxPxRound,
  boxPxTrunc,
  cardScale,
  lineHeightPx,
  pageScale,
  pxFromIn,
  pxFromPt,
  pyRound,
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
    // 这条与下面 `box_trunc_and_round_differ_on_real_card_frame` 各管一半：
    //   本条管**四舍五入**本身（四个坐标都落在 .5 以下但非零小数位），
    //   :55 管两套口径**不可互换**（真实卡片 frame 上差 1px）。
    //
    // 夹具必须挑得让 round 与 trunc 在**四个坐标上全都不同**，否则把
    // `boxPxRound` 误实现成走 trunc 时这条不会红 —— 之前用上面那个 `box`
    // （0.45/0.3/5.172/0.5，四个数都是整 px）就正是这个问题：两套口径同值，
    // 断言看起来在测四舍五入，实际什么都没测。
    //   实测（node 直跑 boxPxRound / boxPxTrunc）：
    //     round: [45, 31, 145, 131]
    //     trunc: [44, 30, 144, 130]
    //   x0 = 0.446 → 44.6 → round 45 / trunc 44
    //   y0 = 0.306 → 30.6 → round 31 / trunc 30
    //   x1 = 0.446+1 = 1.446 → 144.6 → round 145 / trunc 144
    //   y1 = 0.306+1 = 1.306 → 130.6 → round 131 / trunc 130
    const roundBox = { x_in: 0.446, y_in: 0.306, w_in: 1.0, h_in: 1.0 };
    expect(boxPxRound(roundBox)).toEqual([45, 31, 145, 131]);
    // 对照组：同输入走截断必须**全部**不同（区分力自检，不是重复断言）。
    expect(boxPxTrunc(roundBox)).toEqual([44, 30, 144, 130]);
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

  it('px_from_pt_uses_banker_rounding_like_python', () => {
    // R36：真实产物里 12 个 `title` 元素用 font_pt = 9.0。
    // 9 * (100/72) 在双精度里**恰好**是 12.5（`=== 12.5` 为真，不需要 eps 兜底）。
    // Python `int(round(12.5))` = 12（half-to-even 取偶）；`Math.round(12.5)` = 13。
    expect(9 * (100 / 72)).toBe(12.5);
    expect(pxFromPt(9)).toBe(12);
    // 对照组：证明两者确实不同 —— 哪天有人把 pyRound 换回 Math.round，上面那行会红。
    expect(Math.round(9 * (100 / 72))).toBe(13);

    // 同一条判据在 .5 的两侧都要成立（half-to-even 不是「一律向下」）。
    expect(pxFromPt(11.26)).toBe(16); // 15.6388… → 16
    expect(pxFromPt(6)).toBe(8); // 8.3333… → 8
  });
});

describe('units: roundPx 的银行家舍入（R36）', () => {
  it('round_px_uses_banker_rounding_like_python', () => {
    // 5 张插图的 rect[1] = 1.065 英寸 → 106.5 精确。Python 106 / Math.round 107。
    expect(1.065 * 100).toBe(106.5);
    expect(roundPx(1.065)).toBe(106);
    expect(Math.round(1.065 * 100)).toBe(107); // 对照组：确认这确实是一处差异

    // 0.5625 英寸 → 56.25（**不是** 56.5）：两侧同值，这条只是钉住「别改成向上取」。
    // 真值不落中点，所以它不能区分 half-up 与 half-to-even；能区分的是上面那条。
    expect(0.5625 * 100).toBe(56.25);
    expect(roundPx(0.5625)).toBe(56);

    // 真实卡片 frame 的 h_in：337.654 → 338。这条**不能变**（原有判据）。
    expect(roundPx(3.37654)).toBe(338);
  });

  it('boxPxRound 自动继承 half-to-even（它只调 roundPx）', () => {
    // 四个坐标里塞两个恰好落 .5 的地方（1.065 → 106.5，两侧分歧）：
    //   x0/y0 = 1.065            → 106.5 → 106（half-up 会给 107）
    //   x1/y1 = 1.065 + 0.005    → 1.0699999999999998 → 106.99999999999999 → 107
    // 这条同时钉住「boxPxRound 内部不许自己写取整」：只要它绕开 roundPx 用
    // Math.round，x0/y0 就会变 107，前两个位置立刻红。
    const box = { x_in: 1.065, y_in: 1.065, w_in: 0.005, h_in: 0.005 };
    expect(boxPxRound(box)).toEqual([106, 106, 107, 107]);
    // 对照组：截断口径在 x1/y1 上必须不同（106），否则这条没有区分力。
    expect(boxPxTrunc(box)).toEqual([106, 106, 106, 106]);
  });

  it('py_round_matches_python_on_ties', () => {
    // 全部 11 个边界值已逐点对过 CPython 的 `int(round(x))`。
    const cases = [
      [12.5, 12], [182.5, 182], [106.5, 106], [57.5, 58],
      [0.5, 0], [1.5, 2], [2.5, 2],
      [-0.5, 0], [-1.5, -2], [-2.5, -2], [-12.5, -12],
    ];
    for (const [input, expected] of cases) {
      expect(pyRound(input), `pyRound(${input})`).toBe(expected);
      // 每个点都必须与 Math.round 的结论对照一次：要么相同（非中点），
      // 要么不同（中点且取偶方向与 half-up 相反）。全相同就说明这条没测到东西。
    }
    // 真正落在中点（|x| 的小数部分恰为 .5）的 9 个点，逐个确认与 Math.round 分叉。
    for (const [input, expected] of cases) {
      const frac = Math.abs(input) % 1;
      if (frac !== 0.5) continue;
      const halfUp = Math.round(input);
      if (expected === halfUp) {
        // 取偶方向恰与 half-up 同向（如 1.5 → 2、57.5 → 58），此时两者本就相同。
        expect(Math.abs(expected % 2)).toBe(0);
      } else {
        expect(halfUp).not.toBe(expected);
      }
    }
    // 浮点不做 eps 兜底：真值不落中点的就往它该去的方向走。
    // 0.565 * 100 = 56.499999999999993（真值 < 56.5）→ 56，而不是 57。
    expect(0.565 * 100).toBeLessThan(56.5);
    expect(pyRound(0.565 * 100)).toBe(56);

    // 非有限值原样透出，不静默变 0（与 truncPx/roundPx 的 Number(x)||0 是两回事）。
    expect(Number.isNaN(pyRound(NaN))).toBe(true);
    expect(pyRound(Infinity)).toBe(Infinity);
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

describe('units: 画布缩放比（pageScale，对齐 palette.canvas_scale）', () => {
  it('page_scale_is_min_of_the_two_dimension_ratios', () => {
    // 基准画布 10×6 的三档实测值（来自 loop/palette.py::canvas_scale）：
    //   10×15 → min(1.0, 2.5) = 1.0（demo 稿就是这一档，字号一个都不变）
    //   20×12 → min(2.0, 2.0) = 2.0（title 20→40，随后被钳到 24）
    //    8.5×11 → min(0.85, 1.8333…) = 0.85（取小的一维）
    expect(pageScale(10, 15)).toBe(1);
    expect(pageScale(20, 12)).toBe(2);
    expect(pageScale(8.5, 11)).toBe(0.85);
    // 只放大宽：min(20/10, 6/6) = 1，字号不许跟着溢出高度那一维
    expect(pageScale(20, 6)).toBe(1);
  });

  it('page_scale_falls_back_to_one_when_a_dimension_is_missing_or_zero', () => {
    // 对齐 loop/palette.py::canvas_scale 的兜底（任一维 ≤ 0 → 1.0）
    expect(pageScale(0, 11)).toBe(1);
    expect(pageScale(10, 0)).toBe(1);
    expect(pageScale(-10, 11)).toBe(1);
    expect(pageScale(undefined, undefined)).toBe(1);
    expect(pageScale(null, 12)).toBe(1);
  });

  it('page_scale_honours_an_explicit_base_canvas', () => {
    // 基准画布换成 8×5：min(8/8, 5/5) = 1；min(16/8, 10/5) = 2
    expect(pageScale(8, 5, [8, 5])).toBe(1);
    expect(pageScale(16, 10, [8, 5])).toBe(2);
  });

  it('cardScale_是_pageScale_的卡片版（同一套判据，不另写逻辑）', () => {
    // 同一组数字两条路必须同值，否则将来改一处会漂。
    const cases = [[6.072, 3.37654], [9.2, 4.97], [4.5, 2.84], [20, 6]];
    for (const [w, h] of cases) {
      expect(cardScale({ w_in: w, h_in: h }, [10, 6]))
        .toBe(pageScale(w, h, [10, 6]));
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
