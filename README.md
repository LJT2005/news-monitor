# 新闻监控系统

实时监控全球各大机构（央行、智库、国际组织等）的最新研究论文和报告，支持关键词筛选推送、自动翻译、多平台通知。

## 功能特性

- **多源监控** — 支持 HTML 网页、RSS 订阅、JSON API 三种抓取方式，内置 70+ 机构源
- **智能抓取** — 轻量 `requests+BS4` 优先，动态页面自动降级 Selenium；请求缓存 + 5 分钟 TTL 避免重复
- **关键词筛选** — 多组规则，支持 OR（任意匹配）和 AND（全部匹配）模式，只推送关心的新闻
- **LLM 筛选** — 接入 DeepSeek 等大模型，自动评估新闻相关性并翻译标题
- **自动翻译** — 支持 DeepLX 翻译 API，也可由 LLM 筛选时附带翻译
- **多端推送** — 支持 Bark（iOS）、Server酱（微信）、Telegram、飞书、钉钉、Discord、邮件通知
- **容错机制** — CSS 选择器失效时三级降级（通用选择器 → 链接文本筛选 → 标题标签）；网络请求指数退避重试
- **健康检查** — `/api/health` 端点，返回数据库状态、失败站点数、待推送量，可接入监控系统
- **Web 管理** — 现代化 Web 界面，配置、新闻浏览、日志查看一站搞定
- **跨平台** — Windows / macOS / Linux / WSL 全平台支持

## 快速安装

### 方式一：下载预编译包（推荐）

从 [Releases](https://github.com/signxer/news-monitor/releases/latest) 页面下载对应平台的安装包：

| 平台 | 文件 | 说明 |
|------|------|------|
| Windows x64 | `news_monitor.exe` | 双击运行 |
| Linux x64 | `news-monitor_*_amd64.deb` | `sudo dpkg -i` 安装 |
| Linux arm64 | `news-monitor_*_arm64.deb` | `sudo dpkg -i` 安装 |
| macOS Intel | `NewsMonitor-macOS-x64.dmg` | 打开 DMG 双击运行 |
| macOS Apple Silicon | `NewsMonitor-macOS-arm64.dmg` | 打开 DMG 双击运行 |

> ⚠️ 运行前需确保系统已安装 [Google Chrome](https://www.google.com/chrome/) 浏览器，ChromeDriver 会在首次运行时自动下载。

### 方式二：源码运行

```bash
git clone https://github.com/LJT2005/news-monitor.git
cd news-monitor
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

启动后浏览器自动打开 `http://localhost:5000`。

> **WSL 用户**：需要在 `config.json` 中设置 `"headless": true`（Chrome 无头模式），否则会因缺少桌面环境而崩溃。

## 使用说明

### 1. 配置通知

在「配置」页面填写推送地址：

| 渠道 | 配置方式 | 说明 |
|------|---------|------|
| **Bark** | 填写推送 URL | iOS 专属，格式 `https://api.day.app/your_key` |
| **Server酱** | 填写 SendKey | 推送到微信，在 [sct.ftqq.com](https://sct.ftqq.com/) 获取 |
| **Telegram** | Bot Token + Chat ID | 创建 Bot 获取 Token，填入目标 Chat ID |
| **飞书** | Webhook URL | 在群机器人中添加自定义机器人获取 |
| **钉钉** | Webhook URL | 在群设置中添加机器人获取 |
| **Discord** | Webhook URL | 在频道设置中创建 Webhook |
| **邮件** | SMTP 配置 | 支持 SSL/STARTTLS，Gmail 需用应用专用密码 |

支持同时配置多个渠道，每条新闻推送到所有已启用的渠道。

### 2. 添加新闻源

每个网站需要配置：
- **网站名称** — 显示名称
- **网站 URL** — 新闻列表页地址
- **网站类型** — HTML、RSS 或 API
- **标题选择器** — CSS 选择器（HTML 类型需要）

内置 IMF、世界银行、美联储、欧央行、BIS 等 70+ 机构源，可直接启用。

### 3. 关键词筛选

在「配置」页面开启关键词筛选，添加规则：

- **任意匹配（OR）** — 规则内任一关键词出现即推送，如：`economy, inflation, GDP`
- **全部匹配（AND）** — 规则内所有关键词同时出现才推送，如：`China` + `digital currency`

多条规则之间是 OR 关系，命中任一规则即推送。匹配范围包括原标题和翻译标题，大小写不敏感。

### 4. 翻译设置

两种翻译方式（可同时开启）：

- **独立翻译** — 配置 DeepLX 等翻译 API，抓取时自动翻译标题
- **LLM 附带翻译** — 开启大模型筛选后，DeepSeek 打分的同时自动翻译（推荐）

### 5. 大模型筛选

开启后在抓取阶段调用 LLM（默认 DeepSeek）对每条新闻打分。需配置 API Key 和提示词。低于相关性阈值的新闻自动标记为主题无关，不推送。

## 项目结构

```
news-monitor/
├── app.py                      # 入口（仅 15 行）
├── paths.py                    # 跨平台路径管理
├── requirements.txt            # Python 依赖
├── config.json                 # 运行时配置
├── news.db                     # SQLite 数据库
├── news_monitor/               # 核心模块
│   ├── __init__.py             # NewsMonitor 主类（协调者）
│   ├── config.py               # 配置加载/保存 + 默认源列表
│   ├── database.py             # 数据库操作（CRUD + 统计）
│   ├── scraper.py              # 抓取引擎（轻量 + Selenium + 缓存）
│   ├── translator.py           # DeepLX 翻译
│   ├── llm_filter.py           # LLM 打分 + 关键词匹配
│   ├── notifier.py             # 多平台推送（Bark/Server酱/Telegram/飞书/钉钉/Discord/邮件）
│   ├── scheduler.py            # 日志清理
│   └── web.py                  # Flask 路由 + 应用工厂
├── templates/                  # Web 前端模板
│   ├── base.html
│   ├── index.html              # 首页（新闻列表 + 分页）
│   ├── config.html             # 配置页
│   ├── sites.html              # 站点管理
│   └── logs.html               # 日志查看
└── .github/workflows/
    └── build.yml               # GitHub Actions 自动构建
```

运行时数据（配置、数据库、日志）存储在平台标准目录：
- macOS：`~/Library/Application Support/news-monitor/`
- Windows：`%APPDATA%/news-monitor/`
- Linux：`~/.local/share/news-monitor/`

## API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/config` | GET/POST | 获取/更新配置 |
| `/api/config/restore-news-sites` | POST | 恢复默认新闻源 |
| `/api/news?page=1&per_page=20` | GET | 分页获取新闻（支持 site/pushed 筛选） |
| `/api/check_now` | GET | 立即检查更新 |
| `/api/push_pending` | POST | 手动推送待发新闻 |
| `/api/site_stats` | GET | 站点抓取统计 |
| `/api/retry_llm` | POST | 重试 LLM 打分 |
| `/api/status` | GET | 系统状态（运行状态/进度/下次检查） |
| `/api/health` | GET | 健康检查（DB状态/失败站点/监控用） |
| `/api/logs` | GET | 系统日志（最后 100 行） |
| `/api/test_notification` | POST | 测试推送通知 |
| `/api/restart` | POST | 重启服务 |

## 自行构建

```bash
pip install pyinstaller -r requirements.txt
pyinstaller news_monitor.spec
```

产物在 `dist/` 目录下。推送 `v*` 格式的 tag 会自动触发 GitHub Actions 构建所有平台的安装包：

```bash
git tag v1.1.0
git push origin v1.1.0
```

## 许可证

MIT License
