// 温度计复合图元的照抄测试：`tickRects` / `outlinePolyline`。
//
// 判据是**逐点与 Python 完全一致**，不是「看起来像」。期望值全部来自
// `fixtures/thermo_shapes.json`，而那份夹具由 `out/scratch/gen_thermo_shapes.py`
// 直接 import `loop/thermo_shape.py` 算出来——没有一个是手抄的。
//
// 为什么容差是 1e-9 而不是 0：两边都是 IEEE-754 双精度、同一串四则运算，理论上
// 可以严格相等；但跨语言的 mid-expression 舍入/融合乘加没有规范保证，用 1e-9 既
// 拦得住「口径抄错」（第一根刻度差半格就是 1e-2 量级），又不会被末位差误伤。
// 夹具的浮点已量化到 12 位，量化误差 ≤5e-13，比容差小三个数量级。
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { outlinePolyline, quad } from '../src/shapes/outline.js';
import { tickRects } from '../src/shapes/ticks.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const FIXTURE = JSON.parse(
  readFileSync(resolve(HERE, 'fixtures/thermo_shapes.json'), 'utf8'),
);

/** 英寸级的跨语言比对容差。 */
const TOLERANCE = 1e-9;

/** `loop/thermo_shape.py` 的口径常数，测试独立复述一份，不 import 实现。 */
const OUTLINE_POINT_COUNT = 74;

/**
 * 自写的近似相等断言：两侧都是英寸，用绝对差。
 *
 * 失败消息把期望值、实际值、绝对差、容差一次全打出来——跨语言比对时最需要看的是
 * 「差多少」，只写「不相等」等于没写。
 */
function assertClose(actual, expected, label) {
  if (typeof actual !== 'number' || !Number.isFinite(actual)) {
    throw new Error(`${label}: 期望有限数字，实际是 ${JSON.stringify(actual)}`);
  }
  const delta = Math.abs(actual - expected);
  if (!(delta <= TOLERANCE)) {
    throw new Error(
      `${label}: expected ${expected}, got ${actual}（差 ${delta}，容差 ${TOLERANCE}）`,
    );
  }
}

/** 从夹具的 `box` + `geometry` 复原出实现认的元素（英寸，非像素）。 */
function element(spec) {
  const [x_in, y_in, w_in, h_in] = spec.box;
  // 深拷贝 `geometry`：实现在不改输入时与浅拷贝无差别，但**「实现不许就地改输入」
  // 这条不变量不能靠注释声明**——那种注释不会红，变异加一行 `g.__mutated = true`
  // 照样全绿。真正的保护是下面 `keeps_geometry_unmutated` 里的深比较断言。
  return { x_in, y_in, w_in, h_in, geometry: structuredClone(spec.geometry) };
}

/**
 * 夹具里的 `count` 按 Python `int()` 的**向零截断**口径取值。
 *
 * 与 `ticks.js` 里 `Math.trunc(required(g, 'count'))` 是同一件事，测试独立复述一份、
 * 不 import 实现。`derived/ticks_count_13_7` 就是为这条路准备的：`int(13.7) == 13`。
 */
function countOf(spec) {
  return Math.trunc(Number(spec.geometry.count));
}

/** 按 kind 取夹具条目，保持 key 排序（`sort_keys` 落的盘），失败顺序稳定。 */
function casesOf(kind) {
  return Object.entries(FIXTURE).filter(([, spec]) => spec.kind === kind);
}

describe('shapes: 夹具本身的完整性', () => {
  it('covers_both_geometry_groups', () => {
    // 两组 real 参数：`auto_layout` 的卡内小温度计，和单卡渲染的 pagespec。
    expect(FIXTURE['auto_layout:ticks_1']).toBeTruthy();
    expect(FIXTURE['auto_layout:outline_1']).toBeTruthy();
    expect(FIXTURE['end_to_end/thermometer:ticks_1']).toBeTruthy();
    expect(FIXTURE['end_to_end/thermometer:outline_1']).toBeTruthy();
  });

  it('covers_optional_key_branches', () => {
    // 真实样本里 30 个 ticks 全带 pad_top/pad_bottom、30 个 outline 全不带
    // flare_deg——两条「可选键」分支都走不到。派生样本补的就是这两条。
    expect(FIXTURE['derived/ticks_no_pads']).toBeTruthy();
    expect(FIXTURE['derived/ticks_explicit_zero_pads']).toBeTruthy();
    expect(FIXTURE['derived/outline_explicit_default_flare']).toBeTruthy();
    expect(FIXTURE['derived/outline_flare_20deg']).toBeTruthy();

    // 缺键取默认 0 与显式给 0，必须逐位同值；否则「默认值」这条就没被证明。
    expect(FIXTURE['derived/ticks_no_pads'].points).toEqual(
      FIXTURE['derived/ticks_explicit_zero_pads'].points,
    );
    // 显式写 35.0 与不写，必须同值（`_FLARE_DEG` 的默认分支）。
    expect(FIXTURE['derived/outline_explicit_default_flare'].points).toEqual(
      FIXTURE['auto_layout:outline_1'].points,
    );
    // 而 20° 必须与之不同，证明 flare_deg 真的被读进去了、不是写死的常量。
    // 注意这条只是**分支存在性提示**（两串点不同 ≠ 20° 是对的），单靠它分不清
    // 「读了 20°」与「读了 21° / 读了 35° 但别处算错」。20° 的正确性由逐点比对
    // 用例（`shapes/outline: 逐条与 Python 逐点一致 > derived/outline_flare_20deg`）
    // 保证——那条才有 Python 算出来的期望值。
    expect(FIXTURE['derived/outline_flare_20deg'].points).not.toEqual(
      FIXTURE['auto_layout:outline_1'].points,
    );
  });

  it('covers_count_truncation_branch', () => {
    // `int(13.7) == 13`：真实样本的 count 全是整数 13，截断口径在它们身上无从体现。
    expect(FIXTURE['derived/ticks_count_13_7'].geometry.count).toBe(13.7);
    expect(FIXTURE['derived/ticks_count_13_7'].points).toHaveLength(13);
  });
});

describe('shapes/ticks: 逐条与 Python 逐点一致', () => {
  for (const [key, spec] of casesOf('ticks')) {
    it(key, () => {
      const rects = tickRects(element(spec));

      // 条数先钉死：少一根就说明 count 的口径（int 截断 vs 四舍五入）抄错了。
      expect(rects.length).toBe(countOf(spec));
      expect(rects.length).toBe(spec.points.length);

      for (let i = 0; i < rects.length; i += 1) {
        expect(rects[i]).toHaveLength(4);
        for (let j = 0; j < 4; j += 1) {
          assertClose(
            rects[i][j],
            spec.points[i][j],
            `${key} rect[${i}][${j}]`,
          );
        }
      }
    });
  }
});

describe('shapes/ticks: 自下而上', () => {
  // 单独一条断言钉死方向。只写「和 Python 一致」是不够的：`count - 1 - i` 被抄成
  // `i` 时，两边的期望值会一起错，比对照样通过——只有方向断言抓得住。
  //
  // ⚠️ 一条**实测到的数据事实**：`step = (h_in - pad_top - pad_bottom) / count` 的
  // 符号取决于盒子高度，而真实样本里有两组是**负的**——`auto_layout` 与
  // `illustrated/_no_asset` 的 ticks 盒子 `h_in` 只有 0.01704 / 0.004733（正好是
  // 管身长度 `tube_bottom - cap_top`），而 `pad_top + pad_bottom` 是 0.3045 / 0.2030，
  // 于是 step < 0，整串刻度被 Python 甩到盒子上方去。那是 Python 的真实行为，JS
  // 侧必须照抄（不能"顺手修正"），所以「第一根 y 最大」只在 step > 0 时成立。
  //
  // 对策：direction 断言跑在 step > 0 的子集上，另加一条**与符号无关**的断言钉住
  // `count - 1 - i` 这个反转本身（见 down_to_up_index_is_reversed）。
  function stepOf(spec) {
    const g = spec.geometry;
    const padTop = g.pad_top ?? 0;
    const padBottom = g.pad_bottom ?? 0;
    return (spec.box[3] - padTop - padBottom) / countOf(spec);
  }

  it('first_tick_is_bottommost', () => {
    // 只在 step > 0 的样本上断言方向——那是「刻度带真的比上下留白高」的正常情形。
    const usable = Object.entries(FIXTURE).filter(
      ([, spec]) => spec.kind === 'ticks' && stepOf(spec) > 0,
    );
    // 子集不能悄悄空掉（否则这条断言就变成了空循环，永远绿）。
    // 恰为 22 的构成：30 条真实 ticks 里 10 条（`auto_layout` 与
    // `illustrated/_no_asset` 各 5 条）的 step 是负的，被排除 → 20 条；
    // 再加 2 条派生样本（`derived/ticks_no_pads`、`derived/ticks_explicit_zero_pads`
    // 去掉了 pad，step 因此转正）→ 22。写成死数而不是 >=，是为了将来增删样本时
    // 立刻在**这里**报错，而不是让子集悄悄缩小、这条断言名存实亡。
    expect(usable.length).toBe(22);

    for (const [key, spec] of usable) {
      const rects = tickRects(element(spec));
      const count = rects.length;
      const firstY = rects[0][1];
      const lastY = rects[count - 1][1];

      // y 轴向下：y 越大越靠下，所以第一根（i=0）的 y 必须是最大值。
      expect(
        firstY > lastY,
        `${key}: 第一根刻度必须最靠下（rects[0][1]=${firstY} 应 > rects[${count - 1}][1]=${lastY}）`,
      ).toBe(true);

      // 顺便钉住「严格单调」：13 根刻度的 y 必须逐个递减，不许出现并列。
      for (let i = 1; i < count; i += 1) {
        expect(
          rects[i - 1][1] > rects[i][1],
          `${key}: rects[${i - 1}][1]=${rects[i - 1][1]} 应 > rects[${i}][1]=${rects[i][1]}`,
        ).toBe(true);
      }
    }
  });

  it('down_to_up_index_is_reversed', () => {
    // 与 step 符号**无关**地钉住 `count - 1 - i`：i=0 必须拿到 `(count-1)*step` 那一格，
    // i=count-1 必须拿到 `top + 0`。这正是「自下而上」在代码里的全部含义。
    // 若有人把 `count - 1 - i` 抄成 `i`，这条在**所有 30 条**样本上同时红。
    let checked = 0;
    for (const [key, spec] of casesOf('ticks')) {
      const rects = tickRects(element(spec));
      const g = spec.geometry;
      const padTop = g.pad_top ?? 0;
      const padBottom = g.pad_bottom ?? 0;
      const count = countOf(spec);
      const top = spec.box[1] + padTop;
      const step = (spec.box[3] - padTop - padBottom) / count;

      assertClose(rects[0][1], top + (count - 1) * step, `${key} 首根取到 (count-1)*step`);
      assertClose(rects[count - 1][1], top, `${key} 末根取到 top`);
      checked += 1;
    }
    // 全部 ticks 样本都过了一遍（真实 + 派生 + 派生截断样本）。
    expect(checked).toBe(casesOf('ticks').length);
    expect(checked).toBe(33);
  });
});

describe('shapes/outline: 逐条与 Python 逐点一致', () => {
  for (const [key, spec] of casesOf('outline')) {
    it(key, () => {
      const points = outlinePolyline(element(spec));

      // 点数必须与期望**完全相等**，不是 >=：多一个点就是球环步数抄错了。
      expect(points.length).toBe(spec.points.length);
      // 硬数字：9 + 1 + 6 + 50 + 6 + 1 + 1。
      expect(points.length).toBe(OUTLINE_POINT_COUNT);

      for (let i = 0; i < points.length; i += 1) {
        expect(points[i]).toHaveLength(2);
        assertClose(points[i][0], spec.points[i][0], `${key} point[${i}][0]`);
        assertClose(points[i][1], spec.points[i][1], `${key} point[${i}][1]`);
      }
    });
  }
});

describe('shapes/outline: 外接盒锚点只做平移', () => {
  // 32 条真实样本的 `ox = x_in - (cx - R)` / `oy = y_in - cap_top` **全部恰好为 0**
  // （生成时盒子就是按 `cx - R`、`cap_top` 摆的），所以把 `outline.js` 里的 `ox` 写死
  // 成 0、或把 `capTop` 的基准换成别的，85 条测试全绿——这条语义当时零覆盖。
  //
  // 合成样本补的就是它：**同一个 geometry** 塞进三个不同的 `box`（`shifted/` 前缀），
  // 期望点集由 `gen_thermo_shapes.py` 调 `loop.thermo_shape.outline_polyline` 算出。
  // 两条断言各管一件事：
  //   1. 绝对比对 `spec.points`——期望值来自 Python，`ox` 写死就会红；
  //   2. 相对基准的差值恰为 `(dx, dy)`——钉住「平移」这个语义本身（而不是碰巧
  //      x/y 都变了、幅度也可能抄串）。
  for (const [key, spec] of casesOf('outline').filter(([k]) => k.startsWith('shifted/'))) {
    it(key, () => {
      const [dx, dy] = spec.shift;
      const baseSpec = FIXTURE[spec.base];
      expect(baseSpec, `${key}: 基准样本 ${spec.base} 必须存在`).toBeTruthy();
      // 合成样本与原样本必须共用同一份 geometry，否则「纯平移」无从谈起。
      expect(spec.geometry).toEqual(baseSpec.geometry);
      expect(spec.box[2]).toBe(baseSpec.box[2]);
      expect(spec.box[3]).toBe(baseSpec.box[3]);

      const points = outlinePolyline(element(spec));
      const basePoints = outlinePolyline(element(baseSpec));
      expect(points).toHaveLength(OUTLINE_POINT_COUNT);
      expect(points.length).toBe(basePoints.length);

      for (let i = 0; i < points.length; i += 1) {
        // 1. 与 Python 的绝对期望一致。
        assertClose(points[i][0], spec.points[i][0], `${key} point[${i}][0]`);
        assertClose(points[i][1], spec.points[i][1], `${key} point[${i}][1]`);
        // 2. 相对基准恰为纯平移：逐分量加同一个 dx / dy，容差沿用 TOLERANCE。
        assertClose(points[i][0] - basePoints[i][0], dx, `${key} point[${i}][0] 相对于基准的 dx`);
        assertClose(points[i][1] - basePoints[i][1], dy, `${key} point[${i}][1] 相对于基准的 dy`);
      }
    });
  }
});

describe('shapes/outline: 闭合', () => {
  // 末点必须是首点的**同一个值**（Python 侧就是 `pts.append(pts[0])`）。
  it('first_point_equals_last_point', () => {
    for (const [key, spec] of casesOf('outline')) {
      const points = outlinePolyline(element(spec));
      const first = points[0];
      const last = points[points.length - 1];

      assertClose(last[0], first[0], `${key} 闭合点 x`);
      assertClose(last[1], first[1], `${key} 闭合点 y`);
      // 也顺手确认夹具自己就是闭合的，免得实现与坏夹具一起绿。
      expect(spec.points[0]).toEqual(spec.points[spec.points.length - 1]);
    }
  });
});

describe('shapes/outline: 二次贝塞尔采样', () => {
  // `_quad(p0, p1, p2, n=6)` 返回 n+1 = 7 点，**含两端点**。少取一端会让收口
  // 缺掉与侧壁/球环的接缝，轮廓上直接留一道豁口。
  it('quad_includes_both_endpoints', () => {
    const p0 = [0.25, 1.5];
    const p1 = [0.9, 2.5];
    const p2 = [1.75, 1.5];
    const points = quad(p0, p1, p2);

    expect(points).toHaveLength(7);
    assertClose(points[0][0], p0[0], 'quad 起点 x');
    assertClose(points[0][1], p0[1], 'quad 起点 y');
    assertClose(points[6][0], p2[0], 'quad 终点 x');
    assertClose(points[6][1], p2[1], 'quad 终点 y');

    // t=0.5 处的顶点：0.25*p0 + 0.5*p1 + 0.25*p2。
    assertClose(points[3][0], 0.25 * p0[0] + 0.5 * p1[0] + 0.25 * p2[0], 'quad 中点 x');
    assertClose(points[3][1], 0.25 * p0[1] + 0.5 * p1[1] + 0.25 * p2[1], 'quad 中点 y');
  });

  it('quad_defaults_to_six_segments', () => {
    // 不给 n 时就是 6 段——收口用它，改默认值等于改轮廓。
    expect(quad([0, 0], [1, 1], [2, 0])).toHaveLength(7);
    expect(quad([0, 0], [1, 1], [2, 0], 2)).toHaveLength(3);
    expect(quad([0, 0], [1, 1], [2, 0], 2)[1][0]).toBeCloseTo(1, 12);
  });
});

describe('shapes: 缺必需键就抛错，不给默认值', () => {
  // 口径是「拼错参数就炸」。静默兜一个 0 会让整根温度计画到画布左上角，
  // 而且渲染器不报错——这是最坏的一种错：看起来像成功。
  const TICKS_REQUIRED = ['count', 'len', 'thick'];
  const OUTLINE_REQUIRED = ['R', 'cap_r', 'cap_top', 'cx', 'cy', 'neck_h', 'tube_bottom'];
  const baseTicks = element(FIXTURE['auto_layout:ticks_1']);
  const baseOutline = element(FIXTURE['auto_layout:outline_1']);

  for (const key of TICKS_REQUIRED) {
    it(`ticks_missing_${key}_throws`, () => {
      const el = { ...baseTicks, geometry: { ...baseTicks.geometry } };
      delete el.geometry[key];
      expect(() => tickRects(el)).toThrow();
    });
  }

  for (const key of OUTLINE_REQUIRED) {
    it(`outline_missing_${key}_throws`, () => {
      const el = { ...baseOutline, geometry: { ...baseOutline.geometry } };
      delete el.geometry[key];
      expect(() => outlinePolyline(el)).toThrow();
    });
  }

  it('ticks_null_geometry_throws', () => {
    expect(() => tickRects({ ...baseTicks, geometry: null })).toThrow();
    expect(() => tickRects({ ...baseTicks, geometry: {} })).toThrow();
  });

  it('outline_null_geometry_throws', () => {
    expect(() => outlinePolyline({ ...baseOutline, geometry: null })).toThrow();
    expect(() => outlinePolyline({ ...baseOutline, geometry: {} })).toThrow();
  });

  it('missing_key_is_not_silently_zero', () => {
    // 兜 0 的写法会让缺 `len` 时返回 [-0, ...] 甚至 NaN 而不抛错；这里直接确认它炸。
    const broken = { ...baseTicks, geometry: { ...baseTicks.geometry } };
    delete broken.geometry.len;
    let threw = false;
    try {
      tickRects(broken);
    } catch {
      threw = true;
    }
    expect(threw).toBe(true);
  });

  it('optional_keys_keep_their_defaults', () => {
    // pad_top / pad_bottom / flare_deg 是**有意**的可选键，缺了不许抛错。
    const noPads = { ...baseTicks, geometry: { ...baseTicks.geometry } };
    delete noPads.geometry.pad_top;
    delete noPads.geometry.pad_bottom;
    expect(() => tickRects(noPads)).not.toThrow();

    expect(() => outlinePolyline(baseOutline)).not.toThrow();
    expect(baseOutline.geometry.flare_deg).toBeUndefined();
  });
});

describe('shapes: 非有限数值必须抛错，不许静默变 NaN', () => {
  // 这一组补的是评审 Minor #2：原来的 `required()` 只查「键在不在」，值是什么一概
  // 放行。当时 `geometry.len = 'abc'` 会安静地返回 `[NaN, NaN, NaN, NaN] × 13`，
  // 而 Python 抛 `ValueError: could not convert string to float: 'abc'`。
  //
  // 为什么必须对齐「抛」：T3 会把矩形坐标直接拼进 SVG 属性，`NaN` 在浏览器与 jsdom
  // 里都不报错——图悄悄不画，比抛错难查一个量级。
  //
  // `null` 尤其危险：`Number(null) === 0`，`geometry.thick = null` 会得到 0 粗细。
  const baseTicks = element(FIXTURE['auto_layout:ticks_1']);
  const baseOutline = element(FIXTURE['auto_layout:outline_1']);

  /** 造一份只改一个键的 geometry。 */
  function withValue(base, key, value) {
    return { ...base, geometry: { ...base.geometry, [key]: value } };
  }

  const BAD_NUMBERS = [
    ['string_not_a_number', 'abc'],
    ['null', null],
    ['nan', Number.NaN],
    ['positive_infinity', Number.POSITIVE_INFINITY],
    ['negative_infinity', Number.NEGATIVE_INFINITY],
    ['empty_string', ''],
    ['whitespace_string', '   '],
  ];

  for (const key of ['len', 'thick']) {
    for (const [tag, value] of BAD_NUMBERS) {
      it(`ticks_${key}_${tag}_throws`, () => {
        expect(() => tickRects(withValue(baseTicks, key, value))).toThrow();
      });
    }
  }

  for (const key of ['pad_top', 'pad_bottom']) {
    for (const [tag, value] of BAD_NUMBERS) {
      it(`ticks_${key}_${tag}_throws`, () => {
        // 可选键只豁免「缺键」，不豁免「给了坏值」。
        expect(() => tickRects(withValue(baseTicks, key, value))).toThrow();
      });
    }
  }

  for (const key of ['R', 'cap_r', 'cap_top', 'cx', 'cy', 'neck_h', 'tube_bottom']) {
    for (const [tag, value] of BAD_NUMBERS) {
      it(`outline_${key}_${tag}_throws`, () => {
        expect(() => outlinePolyline(withValue(baseOutline, key, value))).toThrow();
      });
    }
  }

  for (const [tag, value] of BAD_NUMBERS) {
    it(`outline_flare_deg_${tag}_throws`, () => {
      expect(() => outlinePolyline(withValue(baseOutline, 'flare_deg', value))).toThrow();
    });
  }

  it('count_is_the_documented_exception', () => {
    // `count` 走 `Math.trunc`，**不**要求是整数：13.7 与 13 必须同结果（Python 的
    // `int(13.7)` 也是 13）。但「非数值」仍旧要抛——`int("abc")` 在 Python 里同样炸。
    const fractional = withValue(baseTicks, 'count', 13.7);
    expect(tickRects(fractional)).toHaveLength(13);
    expect(tickRects(fractional)).toEqual(tickRects(baseTicks));

    // 负的 count：`range(-1)` 是空，Python 返回 `[]`，JS 也必须空。
    expect(tickRects(withValue(baseTicks, 'count', -1))).toEqual([]);

    expect(() => tickRects(withValue(baseTicks, 'count', 'abc'))).toThrow();
    expect(() => tickRects(withValue(baseTicks, 'count', null))).toThrow();
  });
});

describe('shapes: 不许就地改写传入的 geometry', () => {
  // 原来的测试文件里只有一句注释声称「geometry 传浅拷贝，实现若就地改输入，后面几条
  // 用例会立刻红」——这是**假保护**：给实现加一行 `g.__mutated = true`，85 条照样全绿，
  // 因为没有任何断言在看输入。这里换成真断言：调用前后各拍一份深拷贝快照，逐键比对。
  it('ticks_keeps_geometry_unmutated', () => {
    for (const [, spec] of casesOf('ticks')) {
      const el = element(spec);
      const before = structuredClone(el.geometry);
      tickRects(el);

      // 键集合也要相等：多一个键（实现往里塞缓存/标记）同样是就地改写。
      expect(Object.keys(el.geometry).sort()).toEqual(Object.keys(before).sort());
      expect(el.geometry).toEqual(before);
      for (const key of Object.keys(before)) {
        expect(el.geometry[key]).toBe(before[key]);
      }
    }
  });

  it('outline_keeps_geometry_unmutated', () => {
    for (const [, spec] of casesOf('outline')) {
      const el = element(spec);
      const before = structuredClone(el.geometry);
      outlinePolyline(el);

      expect(Object.keys(el.geometry).sort()).toEqual(Object.keys(before).sort());
      expect(el.geometry).toEqual(before);
      for (const key of Object.keys(before)) {
        expect(el.geometry[key]).toBe(before[key]);
      }
    }
  });

  it('ticks_keeps_element_fields_unmutated', () => {
    // `x_in` / `y_in` / `w_in` / `h_in` 同样不许被改（浮动的小抄）——
    // 盒子是调用方的数据，挪一下能让后面算的 `right` 全错。
    const el = element(FIXTURE['auto_layout:ticks_1']);
    const before = { ...el };
    tickRects(el);
    expect(el).toEqual(before);

    const elOutline = element(FIXTURE['auto_layout:outline_1']);
    const beforeOutline = { ...elOutline };
    outlinePolyline(elOutline);
    expect(elOutline).toEqual(beforeOutline);
  });
});
