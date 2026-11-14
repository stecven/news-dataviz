// theme.js 的口径测试。
//
// theme 是图纸自带的主题（`loop/palette.py::summary()` 的原样产物）：色板、
// 字号层级、画布基准、`role_to_font` 全在里面。渲染库不自己带色板，一切从
// 图纸读 —— 这些用例钉的就是“读对了没有”。
//
// 真实样本：`out/demo/auto_layout/pagelayout.json`（相对仓库根）。fresh clone
// 里没有 `out/`，那就跳过依赖样本的那几条，其余照跑。
import { existsSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import {
  BORDER_ROLE,
  LINE_HEIGHT_RATIO,
  ROLE_ALIASES,
  createTheme,
} from '../src/theme.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const SAMPLE = resolve(HERE, '../../out/demo/auto_layout/pagelayout.json');
const HAS_SAMPLE = existsSync(SAMPLE);

/** 读真实样本里的 theme（不存在就返回 null，供 skipIf 用）。 */
function sampleTheme() {
  return HAS_SAMPLE ? JSON.parse(readFileSync(SAMPLE, 'utf8')).theme : null;
}

describe('theme: 常量表（契约里没有，出处 loop/palette.py）', () => {
  it('line_height_ratio_matches_python_constant', () => {
    expect(LINE_HEIGHT_RATIO).toBe(1.35);
  });

  it('role_aliases_matches_python_constant', () => {
    // 逐条抄 loop/palette.py::ROLE_ALIASES。整体相等，防止只改漏一处。
    expect(ROLE_ALIASES).toEqual({
      liquid: 'primary',
      track: 'surface',
      outline: 'neutral_hairline',
      ticks: 'neutral_hairline',
      text: 'neutral_dark',
      placeholder_stroke: 'neutral_strong',
      placeholder_mid: 'neutral_mid',
      placeholder_light: 'neutral_light',
      canvas: 'surface',
    });
    expect(ROLE_ALIASES.liquid).toBe('primary');
  });

  it('border_role_is_neutral_mid', () => {
    expect(BORDER_ROLE).toBe('neutral_mid');
  });
});

describe.skipIf(!HAS_SAMPLE)('theme: 从真实样本读色板', () => {
  it('color_resolves_alias_then_palette', () => {
    const theme = createTheme(sampleTheme());
    // ROLE_ALIASES.text → neutral_dark → palette.neutral_dark = "222222"
    expect(theme.color('text')).toBe('#222222');
  });

  it('color_hits_palette_directly_without_alias', () => {
    const theme = createTheme(sampleTheme());
    expect(theme.color('neutral_mid')).toBe('#A8AEB6');
  });

  it('color_throws_on_unknown_role', () => {
    const theme = createTheme(sampleTheme());
    // 对齐 Python 的“故意不设默认值”：拼错角色名应当立刻炸。
    expect(() => theme.color('nope')).toThrow(/nope/);
  });

  it('color_covers_every_palette_key', () => {
    const raw = sampleTheme();
    const theme = createTheme(raw);
    // 11 个键逐个可读，且都带上前导 '#'。
    for (const [name, value] of Object.entries(raw.palette)) {
      expect(theme.color(name), name).toBe(`#${value}`);
    }
  });
});

describe.skipIf(!HAS_SAMPLE)('theme: 字号', () => {
  it('font_pt_resolves_semantic_role_via_role_to_font', () => {
    const theme = createTheme(sampleTheme());
    // role_to_font.value === 'body' → font_sizes.body === 11
    expect(theme.fontPt('value')).toBe(11);
  });

  it('font_pt_resolves_design_role_directly', () => {
    const theme = createTheme(sampleTheme());
    // 设计角色直接命中 font_sizes —— T4 的整版块传的就是 style（title/body/…）。
    // 只走 role_to_font 会把 subtitle 悄悄降级成 note，所以两类都必须能读。
    expect(theme.fontPt('title')).toBe(20);
    expect(theme.fontPt('subtitle')).toBe(14);
    expect(theme.fontPt('body')).toBe(11);
    expect(theme.fontPt('label')).toBe(9);
    expect(fontPtOfNote(theme)).toBe(8);
  });

  it('font_pt_throws_when_both_tables_miss', () => {
    const theme = createTheme(sampleTheme());
    // 与 Python 的 DEFAULT_FONT_ROLE 不同：JS 侧宁可炸，也不静默兜到 note。
    expect(() => theme.fontPt('certainly_not_a_role')).toThrow(/certainly_not_a_role/);
  });

  it('sector_stroke_pt_comes_from_theme', () => {
    const theme = createTheme(sampleTheme());
    expect(theme.sectorStrokePt()).toBe(0.5);
  });
});

/** 单独拎出来，避免上面那条断言里出现 `fontPt('note')` 之外的字号字面量。 */
function fontPtOfNote(theme) {
  return theme.fontPt('note');
}

describe('theme: 缺色板要炸，不许静默给空板', () => {
  it('create_theme_throws_without_palette', () => {
    expect(() => createTheme({ font_sizes: { body: 11 } })).toThrow(/palette/);
  });

  it('create_theme_throws_without_font_sizes', () => {
    expect(() => createTheme({ palette: { primary: 'E8A08C' } })).toThrow(/font_sizes/);
  });

  it('create_theme_throws_on_null', () => {
    expect(() => createTheme(null)).toThrow();
  });

  it('palette_is_exposed_readonly', () => {
    // 渲染层要能拿到原始字典（sector_order 之类），但不该拿到字符串而忘了换算。
    const theme = createTheme({
      palette: { primary: 'E8A08C' },
      font_sizes: { body: 11 },
    });
    expect(theme.palette.primary).toBe('E8A08C');
    expect(theme.color('primary')).toBe('#E8A08C');
  });
});
