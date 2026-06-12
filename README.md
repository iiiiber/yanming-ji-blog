# 鹏飞日记 - yan-ming-ji

一封每周三到的邮件，写给想慢下来的人。

## 风格
暗色 IDE / 终端风 + 等宽字体 + 代码语法高亮配色。JetBrains Mono + IBM Plex Sans SC。

## 文件
- `index.html` - 首页（hero + this week + recent + author）
- `article.html` - 单篇文章页（IDE 风格代码块 + 行号 + 语法高亮）—— **模板**
- `archive.html` - 所有文章列表（带分类筛选）
- `<slug>.html` - 每篇文章一个 HTML 文件
- `data/articles.json` - 文章元数据源（脚本用）
- `scripts/new_article.py` - 新增/更新文章的工具
- `scripts/md2html.py` - markdown → HTML 转换（用于技术类长文）

## 新增一篇文章

```bash
python3 scripts/new_article.py <slug> \
    --title "文章标题" \
    --excerpt "archive 列表摘要（80-120 字）" \
    --tag tech \
    --read 12 \
    --article-tags "Docker,运维"

# 完整参数
python3 scripts/new_article.py --help
```

脚本会自动：
1. 从 `article.html` 模板复制 + patch title/h1/tags
2. 重算所有文章的 prev/next 链接
3. 更新 `archive.html` 列表（按日期倒序，置顶置顶）
4. 更新 `index.html` 的 recent 段（最新 4 篇）
5. 更新 `data/articles.json` 数据源
6. git add + commit + push + wrangler deploy

## 仅更新 prev/next 链接

加新文章后，旧文章的 next 链接需要重算：

```bash
python3 scripts/new_article.py <any-slug> --update-nav-only
```

## 初始化数据源（首次或 archive 大改后）

```bash
python3 scripts/new_article.py --init-from-archive
```

会从 `archive.html` 反向解析已有文章，生成 `data/articles.json`。

## 本地预览

```bash
python3 -m http.server 8080
# 访问 http://127.0.0.1:8080/
```

## 部署

Cloudflare Pages。脚本会自动：
1. `git add -A` + `git commit -m "add: <slug>"`
2. `git push origin main`
3. `npx wrangler pages deploy . --project-name=yanming-ji-blog`

跳过部署用 `--no-deploy`，只打印改动用 `--dry-run`。

## 设计原则

- **Patch 而非重写**：脚本只动 4 个位置（title/h1/tags/nav），正文（article-body）永远不动 —— 用户自己维护
- **idempotent**：重复跑同一篇文章不会重复插入
- **数据驱动**：`data/articles.json` 是单一数据源，archive/index 总是从它重生成
- **可逆**：每步操作都是文件级 + git commit 级，错了能 revert

