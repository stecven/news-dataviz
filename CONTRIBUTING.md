# 协作约定

两个人的活是按「流水线阶段」分开的，所以**物理上就不该碰同一个文件**。这份约定就是那条分界线。

> 第一次来？先看 [ONBOARDING.md](ONBOARDING.md)——fork 到 PR 的完整流程。

## 一、两条工作线

| 工作线 | 目录 | 干的事 | 产出 |
|---|---|---|---|
| **素材线**（采集入库） | `ingest/`、`assets/`、`db/` | 爬取数据图、清洗成统一尺寸、登记进素材库、打语义标签 | `db/assets.db` 里多出可检索的素材 |
| **前端线**（调用出图） | `frontend/`、`loop/` | 调绘图引擎，把数据 + 素材排成可编辑的图像 | 图表卡片、整版页面、前端界面 |
| **公共** | `tests/`、`docs/`、`.superpowers/` | 测试、文档、实施台账 | 两边都会改，改动前在 PR 描述里说清楚改了什么 |

判断标准很简单：**改动落在哪条线，就写在哪条线的目录里**。要动公共目录，先在 PR 里说明。

## 二、最重要的一条：`db/assets.db` 是二进制，只允许一个写者

SQLite 文件没法做「行级合并」——git 只能整文件二选一。所以：

1. **素材线是唯一写者**，前端线一律只读（代码里已经是 `mode=ro`）。
2. 前端线需要新素材 → **开 issue**，不要自己改库。
3. 素材线提交数据库前必须跑：

   ```bash
   python scripts/migrate_db.py --audit     # 必须 9 项体检全部返回 0 行
   ```

4. 素材线如果发现 `git pull` 后 main 上的库更新了，**不要手工合并**，重新跑一遍入库脚本生成即可：

   ```bash
   git pull --rebase
   python scripts/migrate_db.py              # 幂等，重复跑不会重复插
   python scripts/tag_assets.py              # 需要时
   python scripts/migrate_db.py --audit
   ```

   幂等性是设计好的：迁移按 `PRAGMA table_info` / `sqlite_master` / 词表 diff 判断，重复执行返回「无变更」。
5. 提交信息里写清「这次入库了多少行、新增哪些标签」，方便对方判断要不要重新拉。

## 三、分支与 PR

- `main` 已加保护：**禁止直接 push**，只能经 Pull Request 合入。
- 分支命名：

  | 前缀 | 用途 | 例 |
  |---|---|---|
  | `ingest/` | 素材线 | `ingest/crawl-500-images` |
  | `frontend/` | 前端线 | `frontend/render-api` |
  | `fix/` | 修 bug | `fix/legend-overflow` |

- 一个 PR 只做一件事；小而勤，别攒一个几百文件的 PR。
- 合入前必须：

  ```bash
  python -m unittest discover -s tests -q     # 现在应 676 个全绿
  ```

## 四、不要提交这些

| 路径 | 原因 |
|---|---|
| `out/` | 生成物，30M 预览图，多人协作里最大的冲突源；由 `scripts/` 重建 |
| `db/*.bak*` | 迁移前的数据库快照，只是本地保险 |
| `.dev-keys/` | 本机 SSH 私钥，**永远不要入库** |
| `scratch/` | 测试用临时目录（`mkdtemp` 产物） |

已经在 `.gitignore` 里，但如果 `git add -f` 绕过，后果自负。

## 五、素材线的额外注意：500 张图会撑爆仓库

- 统一尺寸与格式：参考 `scripts/make_icons.py` 的做法（4 倍超采样后缩到 **400×400**、RGBA PNG）。
- 目标体积：**单张 ≤ 200KB，总量 ≤ 50MB**。超了就走 Git LFS：

  ```bash
  git lfs install
  git lfs track "assets/**/*.png"
  ```

  或者干脆**图片不入库**，只提交一份 manifest（路径 + sha256 + 来源 URL）+ 下载脚本，谁需要谁自己拉。
- 入库时带上 `sha256` 与 `bytes`（`assets` 表已有这两列），能直接查重，避免同一张图进来两次。
- 爬取请遵守目标站点的 robots 与版权；`ingest/` 里请写清来源与许可。

## 六、前端线的额外注意

- 渲染层**不许出现十六进制色值和写死的字号**，一律走 `loop/palette.py`（有测试守着）。
- 新增图元要走 `PageSpec` + 渲染适配器，别把几何写死在渲染代码里——模板里只许出现 `@参数名` 与约束表达式。
- 出图入口就这几个：
  - 单卡：`loop/scaffold.py::build_pagespec(...)`
  - 整版：`loop/layout.py::flow_layout(...)` + `loop/render_page.py::render_layout(...)`
  - 全自动：`loop/compose.py::compose_page(text, out_dir, ...)`

## 七、遇到冲突怎么办

git 报冲突时按类型处理：

| 冲突文件 | 处理方式 |
|---|---|
| `*.py` / `*.md` | 正常手工合并，合完**必须跑全量测试** |
| `db/assets.db` | **不要手工合并**。取对方版本为底，重跑入库脚本，再提交 |
| `assets/*.png` | 二进制同名不同内容 → 双方确认留哪张；建议改文件名（用素材 id 或语义命名）避免同名 |

拿不准就开 PR 让人看，别硬推 `main`。
