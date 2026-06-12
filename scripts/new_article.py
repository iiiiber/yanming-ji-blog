#!/usr/bin/env python3
"""
鹏飞日记 — 新增/更新一篇文章的工具（patch 模式）。

设计原则：
    1. 从 article.html 复制（创建新文章）或直接读（更新现有文章）
    2. 只 patch 4 个位置：title / h1 / article-tags / article-nav
    3. 正文（article-body）永远不动 — 用户自己维护
    4. 同步更新 index.html / archive.html / data/articles.json
    5. 可选 git push + wrangler deploy

用法：
    python3 new_article.py <slug> [选项]

必填：
    <slug>                        文章 slug（最终文件名 = <slug>.html）
    --title "标题"                文章标题
    --excerpt "摘要"              archive 列表摘要

常用：
    --date 2026-06-12             发布日期（默认今天）
    --read 12                     阅读时长（分钟）
    --tag tech                    分类（tech/essay/lifestyle/tools/review/cover-story）
    --visual p1                   首页卡片背景（p1/p2/p3/p4）
    --article-tags "Docker,运维"   文章底部 #tag（逗号分隔）
    --top                         标记置顶（archive ★）
    --cover                       标记 this week cover story

操作：
    --dry-run                     只打印改动，不写文件
    --no-deploy                   写文件但不 git push + 不 wrangler deploy
    --init-from-archive           从 archive.html 反向解析已有文章，生成 data/articles.json
    --update-nav-only             只更新所有文章的 prev/next 链接（不重建任何文章）

示例：
    # 新建一篇文章
    python3 new_article.py vim-to-neovim \\
        --title "从 Vim 到 Neovim：一次完整的迁移记录" \\
        --excerpt "配置、插件、LSP、性能优化..." \\
        --tag tech --read 11

    # 把现有文章标记为置顶 + 改 tag
    python3 new_article.py hermes-install --top --tag tech

    # 改 prev/next 链接（任意文章）
    python3 new_article.py hermes-install --update-nav-only

    # 干跑看会改什么
    python3 new_article.py new-slug --title "x" --excerpt "y" --dry-run
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

# 站点根目录（脚本所在位置的上一级）+ 数据目录
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / 'data'
ARTICLE_HTML = ROOT / 'article.html'
DATA_JSON = DATA_DIR / 'articles.json'


# ---------- 数据源 ----------

def load_articles_from_json():
    if not DATA_JSON.exists():
        return None
    with open(DATA_JSON, encoding='utf-8') as f:
        return json.load(f)


def save_articles_to_json(articles):
    with open(DATA_JSON, 'w', encoding='utf-8') as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)


def load_articles_from_archive():
    """从 archive.html 反向解析已有文章。跳过 slug='article'（模板占位）。"""
    with open(ROOT / 'archive.html', encoding='utf-8') as f:
        html = f.read()
    pattern = re.compile(
        r'<a href="\./([^"]+)\.html" class="row">\s*'
        r'<span class="ln">([^<]+)</span>\s*'
        r'<div class="title-cell">\s*'
        r'<h3>([^<]+)</h3>\s*'
        r'<div><span class="tag">([^<]+)</span></div>\s*'
        r'<p class="excerpt">([^<]+)</p>\s*'
        r'</div>\s*'
        r'<span class="date">([^<]+)</span>\s*'
        r'<span class="read">([^<]+)</span>\s*'
        r'</a>',
        re.DOTALL
    )
    articles = []
    for m in pattern.finditer(html):
        slug, ln, title, tag, excerpt, dt, read = m.groups()
        if slug == 'article':
            continue
        top = ln.strip() == '★'
        read_match = re.search(r'\d+', read)
        read_min = int(read_match.group()) if read_match else 8
        articles.append({
            'slug': slug, 'title': title, 'date': dt.strip(),
            'read': read_min, 'tag': tag.strip(), 'excerpt': excerpt.strip(),
            'top': top, 'cover': False, 'visual': 'p1', 'article_tags': [],
        })
    return articles


# ---------- HTML 渲染 ----------

def esc(s):
    return (str(s)
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;'))


def render_recent_card(a):
    return f'''          <a href="./{a['slug']}.html" class="card article">
            <div class="visual {a.get('visual', 'p1')}"></div>
            <div class="body">
              <span class="card-tag">{esc(a['tag'])}</span>
              <h3>{esc(a['title'])}</h3>
              <p>{esc(a['excerpt'])}</p>
              <div class="row">
                <span class="ln">{a['date'].replace('-', '.')}</span><span class="v">{a['read']} min</span>
              </div>
            </div>
          </a>

'''


def render_thisweek_card(a, is_cover, ln):
    cmd_file = a['slug'] + '.md'
    tag_disp = 'cover story' if is_cover else a['tag']
    cls = 'card cover' if is_cover else 'card'
    return f'''          <a href="./{a['slug']}.html" class="{cls}">
            <div class="card-header">
              <div class="dots"><span></span><span></span><span></span></div>
              <div class="cmd"><span class="p">~</span> $ cat <span class="a">{esc(cmd_file)}</span></div>
              <div class="line-num">{ln}</div>
            </div>
            <div class="card-body">
              <span class="card-tag">{esc(tag_disp)}</span>
              <h3>{esc(a['title'])}</h3>
              <p>{esc(a['excerpt'])}</p>
              <div class="row">
                <span class="ln">author:</span><span class="v">鹏飞</span>
                <span class="ln">date:</span><span class="v">{a['date']}</span>
                <span class="ln">read:</span><span class="v">{a['read']}min</span>
              </div>
            </div>
          </a>

'''


def render_archive_row(a, ln):
    ln_disp = '★.' if a.get('top') else f'{ln:03d}.'
    return f'''        <a href="./{a['slug']}.html" class="row">
          <span class="ln">{ln_disp}</span>
          <div class="title-cell">
            <h3>{esc(a['title'])}</h3>
            <div><span class="tag">{esc(a['tag'])}</span></div>
            <p class="excerpt">{esc(a['excerpt'])}</p>
          </div>
          <span class="date">{a['date']}</span>
          <span class="read">{a['read']} min</span>
        </a>

'''


def render_prevnext_card(a, direction):
    if a is None:
        return '            <div></div>\n'
    if direction == 'prev':
        arrow, label, cls = '← ', 'cd ../previous', 'nav-card prev'
    else:
        arrow, label, cls = '', 'cd ../next', 'nav-card next'
    title_disp = a['title'] + (' →' if direction == 'next' else '')
    return f'''            <a href="./{a['slug']}.html" class="{cls}">
              <div class="label">{label}</div>
              <h4>{arrow}{esc(title_disp)}</h4>
            </a>
'''


# ---------- 文章 patch ----------

def patch_article_html(html, a, prev_a, next_a):
    """只 patch 4 个位置：title / h1 / article-tags / article-nav。"""
    # 1. title
    html = re.sub(
        r'<title>[^<]*?— 鹏飞日记</title>',
        f'<title>{esc(a["title"])} — 鹏飞日记</title>',
        html, count=1
    )
    # 2. h1
    html = re.sub(
        r'<h1 class="article-title">[^<]+</h1>',
        f'<h1 class="article-title">{esc(a["title"])}</h1>',
        html, count=1
    )
    # 3. article-tags：替换 <div class="tag-row">...</div>
    # 规则：如果新数据为空 + 原文件已有 tags，保留原文件 tags
    existing_tag_row = re.search(
        r'<div class="tag-row">(.*?)</div>', html, re.DOTALL
    )
    if a.get('article_tags'):
        new_tags_html = '\n            '.join(
            f'<a href="#">#{esc(t)}</a>' for t in a['article_tags']
        )
        replacement = f'<div class="tag-row">\n            {new_tags_html}\n          </div>'
    elif existing_tag_row and existing_tag_row.group(1).strip():
        # 保留原文件 tag-row 不动
        replacement = existing_tag_row.group(0)
    else:
        replacement = '<div class="tag-row"></div>'
    if existing_tag_row:
        html = html.replace(existing_tag_row.group(0), replacement, 1)
    # 4. article-nav
    prev_html = render_prevnext_card(prev_a, 'prev')
    next_html = render_prevnext_card(next_a, 'next')
    nav_html = f'''<div class="article-nav">
{prev_html}{next_html}          </div>'''
    html = re.sub(
        r'<div class="article-nav">\s*.*?\s*</div>',
        nav_html, html, count=1, flags=re.DOTALL
    )
    return html


# ---------- 工具 ----------

def sort_articles(articles):
    """按 top 优先 + date 倒序排序。"""
    def key(a):
        # 置顶 True 排前（用 0/1 反转），date 倒序
        return (0 if a.get('top') else 1, -int(a['date'].replace('-', '')))
    return sorted(articles, key=key)


def maybe_git_deploy(dry_run, no_deploy, msg):
    if dry_run or no_deploy:
        return
    print('\n▸ Git + deploy...')
    try:
        subprocess.run(['git', '-C', str(ROOT), 'add', '-A'], check=True)
        subprocess.run(['git', '-C', str(ROOT), 'commit', '-m', msg], check=True)
        subprocess.run(['git', '-C', str(ROOT), 'push', 'origin', 'main'],
                       check=True, timeout=120)
        subprocess.run([
            'npx', 'wrangler', 'pages', 'deploy', '.',
            '--project-name=yanming-ji-blog', '--commit-dirty=true'
        ], check=True, timeout=120, cwd=str(ROOT))
        print('  ✓ 部署完成')
    except subprocess.CalledProcessError as e:
        print(f'  ✗ 失败: {e}')
        sys.exit(1)


# ---------- 主流程 ----------

def main():
    ap = argparse.ArgumentParser(
        description='鹏飞日记 — 新增/更新文章（patch 模式）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    ap.add_argument('slug', nargs='?', help='文章 slug')
    ap.add_argument('--title', help='文章标题')
    ap.add_argument('--date', default=None, help='发布日期（默认今天）')
    ap.add_argument('--read', type=int, default=None, help='阅读时长（分钟）')
    ap.add_argument('--tag', default=None, help='分类')
    ap.add_argument('--excerpt', default=None, help='archive 列表摘要')
    ap.add_argument('--visual', default=None, help='recent 卡片 visual')
    ap.add_argument('--article-tags', default='', help='文章底部 #tag（逗号分隔）')
    ap.add_argument('--top', action='store_true', help='标记置顶')
    ap.add_argument('--cover', action='store_true', help='标记 this week cover story')
    ap.add_argument('--dry-run', action='store_true', help='只打印不写')
    ap.add_argument('--no-deploy', action='store_true', help='不 git/deploy')
    ap.add_argument('--init-from-archive', action='store_true',
                    help='从 archive.html 反向解析生成 data/articles.json')
    ap.add_argument('--update-nav-only', action='store_true',
                    help='只重算所有文章的 prev/next，不修改其他字段')
    args = ap.parse_args()

    # 特殊命令：--init-from-archive
    if args.init_from_archive:
        print('▸ 从 archive.html 反向解析...')
        articles = load_articles_from_archive()
        print(f'  解析到 {len(articles)} 篇')
        if args.dry_run:
            print(f'  [dry-run] 不写 {DATA_JSON}')
        else:
            save_articles_to_json(articles)
            print(f'  → {DATA_JSON}')
        return

    if not args.slug:
        ap.error('需要提供 slug（或用 --init-from-archive）')

    # 加载数据（先看 slug 在不在数据源里 —— 决定 title/excerpt 是否必填）
    articles = load_articles_from_json()
    if articles is None:
        print('  data/articles.json 不存在，从 archive.html 反向解析...')
        articles = load_articles_from_archive()
        print(f'  解析到 {len(articles)} 篇')
    slug_existing = any(a['slug'] == args.slug for a in articles)
    if not args.update_nav_only and not slug_existing and (not args.title or not args.excerpt):
        ap.error('--title 和 --excerpt 必填（除非是更新现有文章或 --update-nav-only）')

    print('▸ 加载数据...')
    article_tags = [t.strip() for t in args.article_tags.split(',') if t.strip()]

    # 2. upsert
    existing_idx = next((i for i, a in enumerate(articles) if a['slug'] == args.slug), None)
    if args.update_nav_only:
        if existing_idx is None:
            print(f'  ✗ 文章 {args.slug} 不在数据源中')
            sys.exit(1)
        print(f'  → 只重算 {args.slug} 的 prev/next')
    else:
        # 只把用户实际传的参数写进 new_entry；其它字段用旧值/默认值
        new_entry = {'slug': args.slug}
        if args.title: new_entry['title'] = args.title
        if args.date: new_entry['date'] = args.date
        if args.read is not None: new_entry['read'] = args.read
        if args.tag: new_entry['tag'] = args.tag
        if args.excerpt: new_entry['excerpt'] = args.excerpt
        if args.visual: new_entry['visual'] = args.visual
        if args.top: new_entry['top'] = True
        if args.cover: new_entry['cover'] = True
        if article_tags: new_entry['article_tags'] = article_tags

        if existing_idx is not None:
            # 保留旧 entry 的所有字段，新 entry 里的覆盖
            merged = dict(articles[existing_idx])
            merged.update(new_entry)
            new_entry = merged
            articles[existing_idx] = new_entry
            print(f'  ✓ 更新: {args.slug}')
        else:
            # 新增：填默认值（user 没传的字段）
            new_entry.setdefault('title', args.title or args.slug)
            new_entry.setdefault('date', args.date or date.today().isoformat())
            new_entry.setdefault('read', args.read if args.read is not None else 8)
            new_entry.setdefault('tag', args.tag or 'tech')
            new_entry.setdefault('excerpt', args.excerpt or '')
            new_entry.setdefault('visual', args.visual or 'p1')
            new_entry.setdefault('top', False)
            new_entry.setdefault('cover', False)
            new_entry.setdefault('article_tags', [])
            articles.append(new_entry)
            print(f'  ✓ 新增: {args.slug}')

    articles = sort_articles(articles)

    # 3. patch 每篇文章的 prev/next（+ 新文章的 title/h1/tags）
    print('\n▸ Patch 文章页...')
    with open(ARTICLE_HTML, encoding='utf-8') as f:
        template = f.read()
    for i, a in enumerate(articles):
        prev_a = articles[i-1] if i > 0 else None
        next_a = articles[i+1] if i < len(articles)-1 else None
        target = ROOT / f"{a['slug']}.html"
        if target.exists() and target != ARTICLE_HTML:
            with open(target, encoding='utf-8') as f:
                html = f.read()
            new_html = patch_article_html(html, a, prev_a, next_a)
            action = 'patch'
        else:
            # 从模板新建（slug != article 才新建，避免覆盖模板）
            if a['slug'] == 'article':
                continue
            new_html = patch_article_html(template, a, prev_a, next_a)
            action = 'create'
        if args.dry_run:
            print(f'  [dry-run] {action}: {target}')
        else:
            with open(target, 'w', encoding='utf-8') as f:
                f.write(new_html)
            print(f'  → {action}: {target}')

    # 4. 生成 archive.html
    print('\n▸ 生成 archive.html...')
    with open(ROOT / 'archive.html', encoding='utf-8') as f:
        arch = f.read()
    # 编号：置顶项不计编号（用 ★），非置顶项从 1 开始连续编号
    non_top = [a for a in articles if not a.get('top')]
    ln_map = {a['slug']: i+1 for i, a in enumerate(non_top)}
    rows = ''.join(
        render_archive_row(a, ln_map.get(a['slug'], 0))
        for a in articles
    )
    arch = re.sub(
        r'(<div class="article-list">)\s*.*?\s*(</div>\s*</div>\s*</main>)',
        f'\\1\n{rows}        \\2',
        arch, count=1, flags=re.DOTALL
    )
    # 顶部 stats
    total = len(articles)
    this_year = sum(1 for a in articles if a['date'].startswith(str(date.today().year)))
    avg_read = sum(a['read'] for a in articles) // total if total else 0
    new_stats = (
        f'<div class="stats-line">\n'
        f'        <div class="item"><span class="k">total:</span> <span class="v">{total}</span></div>\n'
        f'        <div class="item"><span class="k">this_year:</span> <span class="v">{this_year}</span></div>\n'
        f'        <div class="item"><span class="k">avg_read:</span> <span class="v">{avg_read} min</span></div>\n'
        f'        <div class="item"><span class="k">status:</span> <span class="ok">OK</span></div>\n'
        f'      </div>'
    )
    # 用非贪婪 + DOTALL，但确保匹配到外层 div 闭合
    # 思路：找 stats-line 起点 + 数 div 深度，直到深度回到 0
    stats_start = arch.find('<div class="stats-line">')
    if stats_start != -1:
        # 数 div 深度
        depth = 0
        i = stats_start
        end = -1
        while i < len(arch):
            if arch[i:i+5] == '<div ' or arch[i:i+5] == '<div>':
                depth += 1
            elif arch[i:i+6] == '</div>':
                depth -= 1
                if depth == 0:
                    end = i + 6
                    break
            i += 1
        if end != -1:
            arch = arch[:stats_start] + new_stats + arch[end:]
    if args.dry_run:
        print(f'  [dry-run] archive.html')
    else:
        with open(ROOT / 'archive.html', 'w', encoding='utf-8') as f:
            f.write(arch)
        print(f'  → archive.html')

    # 5. 生成 index.html
    print('\n▸ 生成 index.html...')
    with open(ROOT / 'index.html', encoding='utf-8') as f:
        idx_html = f.read()
    recent = articles[:4]
    recent_html = ''.join(render_recent_card(a) for a in recent)
    idx_html = re.sub(
        r'(<div class="articles">)\s*.*?\s*(</div>\s*</div>\s*</section>)',
        f'\\1\n{recent_html}        \\2',
        idx_html, count=1, flags=re.DOTALL
    )
    # this week
    thisweek = []
    cover_article = next((a for a in articles if a.get('cover')), None)
    if cover_article:
        thisweek.append((cover_article, True))
    top_articles = [a for a in articles if a.get('top') and a != cover_article]
    thisweek.extend((a, False) for a in top_articles[:2])
    if len(thisweek) < 3:
        for a in recent:
            if a not in [x[0] for x in thisweek]:
                thisweek.append((a, False))
            if len(thisweek) >= 3:
                break
    thisweek_html = ''.join(
        render_thisweek_card(a, is_cover, f'{i+1:03d}.')
        for i, (a, is_cover) in enumerate(thisweek)
    )
    idx_html = re.sub(
        r'(<div class="featured">)\s*.*?\s*(</div>\s*</div>\s*</section>)',
        f'\\1\n{thisweek_html}          \\2',
        idx_html, count=1, flags=re.DOTALL
    )
    if args.dry_run:
        print(f'  [dry-run] index.html')
    else:
        with open(ROOT / 'index.html', 'w', encoding='utf-8') as f:
            f.write(idx_html)
        print(f'  → index.html')

    # 6. 写数据源
    if not args.dry_run:
        print('\n▸ 保存数据源...')
        save_articles_to_json(articles)
        print(f'  → {DATA_JSON} ({len(articles)} 篇)')

    # 7. git + deploy
    msg = f"{'update' if existing_idx is not None else 'add'}: {args.slug}"
    maybe_git_deploy(args.dry_run, args.no_deploy, msg)

    print('\n✓ 完成')


if __name__ == '__main__':
    main()
