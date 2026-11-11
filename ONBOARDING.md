# 新人上手（协作者第一份要读的东西）

你手上拿到的可能只是别人转给你的一段话。这个文件才是完整、最新、可追溯的版本——直接照做。

## 0. 你要做的是什么

本项目把**新闻稿 + 数据集**自动排成可编辑的报纸风格信息图。流水线分两条线，**你只碰其中一条**：

| 工作线 | 目录 | 干的事 |
|---|---|---|
| **素材线（你）** | `ingest/`、`assets/`、`db/` | 爬取数据图、清洗成统一尺寸、登记进素材库、打语义标签 |
| 前端线（别人） | `frontend/`、`loop/` | 调绘图引擎把数据排成图 |

**别动 `frontend/` 和 `loop/`。** 公共目录 `tests/`、`docs/`、`.superpowers/` 要改先在 PR 里说明。

## 1. Fork，不要直接建新仓库

1. 打开 https://github.com/stecven/news-dataviz （Public，搜 `stecven/news-dataviz` 也能找到）
2. 右上角 **Fork** → Create fork

这一下你在 GitHub 上就有了自己的 `github.com/<你的用户名>/news-dataviz`——**它就是你的项目**，你想怎么改都行，弄坏了也影响不到原仓库。改动通过 Pull Request 回贡。

## 2. 配好你自己的推送凭据

这一步只能你自己做。原作者的密钥只存在他自己的电脑上，跟你无关，**不要向任何人索取私钥**。

- **SSH**：`ssh-keygen -t ed25519 -C "你的邮箱"`，然后把 `~/.ssh/id_ed25519.pub` 的内容贴到 GitHub → Settings → SSH and GPG keys → New SSH key
- **或者 HTTPS**：用 Personal Access Token（GitHub 早就不支持用密码推送）

## 3. Clone 你自己的 fork（不是原仓库）

```bash
git clone git@github.com:<你的用户名>/news-dataviz.git
cd news-dataviz

# 把原仓库加成上游：原作者在前面走，你得能跟上他的更新
git remote add upstream git@github.com:stecven/news-dataviz.git
git fetch upstream
```

> **如果你本地已经有一份拷贝**（比如别人发的压缩包）：**不要** `git init` 重开一遍——那会和原仓库的历史变成两棵互不相干的树，PR 提不了。正确做法是 clone 你这个 fork，再把自己的文件拷进去。

## 4. 读这两个文件

- [CONTRIBUTING.md](../CONTRIBUTING.md) —— 协作全约
- [ingest/README.md](../ingest/README.md) —— 你这条件线的作业指引：已有家当、标准入库四步、命名规则

## 5. 干活

```bash
git switch -c ingest/crawl-500          # 分支命名 ingest/xxx

# 写你的爬取/清洗脚本到 ingest/，图片落到 assets/
python ingest/<你的脚本>.py

# 登记进素材库（幂等，重复跑不会插两次）
python scripts/register_icons.py --list
python scripts/register_icons.py

# 打语义标签（词表里没有的标签先加词条，别在代码里硬编码）
python scripts/tag_assets.py --dry-run
python scripts/tag_assets.py

# 体检：必须 9 项全 0 行
python scripts/migrate_db.py --audit
```

## 6. 提交与 PR

```bash
git add -A
git commit -m "ingest: 爬取 120 张取暖电器图片并入库"
git push -u origin ingest/crawl-500
```

然后去 GitHub 开 Pull Request：`<你的用户名>:ingest/crawl-500` → `stecven/news-dataviz` 的 `main`。

**PR 描述里必须贴这三样**（因为 `db/assets.db` 是二进制，对方在 PR 页面看不到 diff，只能靠这几个数判断）：

```
新增 assets 行数：120（id 29-148）
新增 asset_tags：340 条（semantic / appearance / season）
migrate_db.py --audit：9 项全部返回 0 行
```

## 7. 几条硬规则

1. **`db/assets.db` 你是唯一写者**，前端线只读。别人要素材会开 issue 找你。
2. **不要手工合并数据库**。如果 `git fetch upstream` 发现库更新了，别 merge 那个二进制文件——重跑一遍入库脚本重新生成即可（迁移是幂等的）。
3. **图片瘦身**：统一 400×400 RGBA PNG，单张 ≤ 200KB，一批总量 ≤ 50MB。超了走 Git LFS，或者只提交清单（路径 + sha256 + 来源 URL）+ 下载脚本。参考 `scripts/make_icons.py`（4 倍超采样后缩到 400×400）。
4. **文件名带语义或来源前缀**（如 `heat_pump_01.png`），避免和别人的图同名却被 git 当成同一个文件的两个版本。
5. **不要提交** `out/`、`db/*.bak*`、`scratch/`、任何私钥——`.gitignore` 已经挡了，别用 `git add -f` 绕过。
6. **爬取请遵守目标站点的 robots 与版权**，在 `ingest/` 里写清来源与许可。
7. 提交前跑一遍全量测试，确认没弄坏别人的东西：

   ```bash
   python -m unittest discover -s tests -q      # 应全绿
   ```

## 8. 遇到冲突怎么办

| 冲突文件 | 处理方式 |
|---|---|
| `*.py` / `*.md` | 正常手工合并，合完**必须跑全量测试** |
| `db/assets.db` | **不要手工合并**。取上游版本为底，重跑入库脚本，再提交 |
| `assets/*.png` | 同名不同内容 → 双方确认留哪张；建议改文件名避免再次相撞 |

拿不准就在 PR 里问，别硬推 `main`。
