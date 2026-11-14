import { defineConfig } from 'vitest/config';

// ``include`` 相对**本文件所在目录**解析（不是相对 cwd、也不是相对仓库根）：
// 写成裸 ``['*.test.mjs']`` 会得到 ``No test files found``。
// 测试一律是纯 Node 环境（不碰 DOM），所以 ``environment: 'node'``。
export default defineConfig({
  test: {
    environment: 'node',
    include: ['test/**/*.test.mjs'],
  },
});
