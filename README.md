# 鹏飞日记 - yan-ming-ji

一封每周三到的邮件，写给想慢下来的人。

## 风格
暗色 IDE / 终端风 + 等宽字体 + 代码语法高亮配色。JetBrains Mono + IBM Plex Sans SC。

## 文件
- index.html - 首页（hero + this week + recent + author）
- article.html - 单篇文章页（IDE 风格代码块 + 行号 + 语法高亮）
- archive.html - 所有文章列表（带分类筛选 + 分页）

## 本地预览
python3 -m http.server 8080
# 访问 http://127.0.0.1:8080/

## 部署
Cloudflare Pages 自动部署。push 到 main 分支触发。
