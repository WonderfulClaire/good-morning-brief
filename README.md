# ☀️ good-morning-brief

**专属每日简报**，每天早上一封邮件送到你的邮箱，包含三个板块：

| 板块 | 内容 | 数据源 |
|------|------|--------|
| 📄 论文精选 | 按你的研究方向 + 前沿方向精选 top 3 | arXiv（主）/ Semantic Scholar（兜底） |
| 📰 科技新闻 | 当日高热度科技/AI 新闻 | Hacker News 官方 API |
| 💰 基金涨跌 | 你的持仓当日涨跌 + 定投提示 | 天天基金（东方财富） |

邮件顶部还有一条 **「今日速览」**：一句话汇总「N 篇论文 · N 条新闻 · 各基金涨跌（涨红跌绿）」，一眼看完今天的重点，不用点开也能快速扫读。

> 这是 `good-morning-paper` 的进化版：从「只发论文」升级为「论文 + 新闻 + 基金」三合一 HTML 邮件。原 `good-morning-paper` 仓库保持不动。

---

## 🚀 快速开始（你只需配置邮箱）

代码和定时任务都已就绪，**你只需要在 GitHub 上配置 6 个邮箱 Secret**，简报就会每天早上 7:00（北京时间）自动发到你邮箱。

### 第 1 步：拿到 163 邮箱授权码

163 邮箱不能直接用登录密码发信，需要「授权码」：

1. 登录 [163 邮箱网页版](https://mail.163.com) → 顶部 **设置** → **POP3/SMTP/IMAP**
2. 开启 **SMTP 服务**（会要求手机短信验证）
3. 记下生成的 **授权码**（一串字母，形如 `ABCD1234EFGH5678`）

### 第 2 步：在仓库里配置 Secrets

进入本仓库 → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**，逐个添加：

| Secret 名称 | 值 |
|-------------|-----|
| `SMTP_HOST` | `smtp.163.com` |
| `SMTP_PORT` | `465` |
| `SMTP_USERNAME` | `wk1924321@163.com` |
| `SMTP_PASSWORD` | 上一步拿到的**授权码**（不是登录密码！） |
| `SMTP_FROM` | `wk1924321@163.com` |
| `SMTP_TO` | `wk1924321@163.com`（收件人，可填多个用逗号隔开） |

### 第 3 步：手动跑一次验证

进入 **Actions** → 左侧选 **daily-brief** → **Run workflow** → 选 `send` → 运行。
几十秒后去邮箱查收第一封简报。若没收到，看 Actions 日志里的 `发信状态`。

搞定后就不用管了，每天早上 7:00 自动发。

---

## ⚙️ 自定义

所有设置都在 [`config.yaml`](./config.yaml)：

- **论文方向**：改 `papers.focus_topics`（核心方向）和 `frontier_topics`（前沿方向）
- **论文篇数**：`papers.pick_top_n`
- **新闻条数/热度门槛**：`news.top_n` / `news.min_score`
- **基金持仓**：`funds.holdings`（加减基金代码即可）
- **定投提示阈值**：`funds.dip_alert_pct`（单日跌幅超过该值时标注「可关注定投」）

### 改发送时间

编辑 [`.github/workflows/daily.yml`](./.github/workflows/daily.yml) 里的 cron。
注意用的是 **UTC**：`0 23 * * *` = 北京时间次日 07:00。想改成早 8 点就写 `0 0 * * *`。

---

## 💻 本地测试（可选）

```bash
pip install -r requirements.txt

# 只生成 HTML 预览，不发信（在 briefs/ 下）
python main.py --preview

# 配好 .env（参考 .env.example）后本地发信测试
python main.py
```

---

## 📁 结构

```
good-morning-brief/
├── main.py                 # 编排：抓三板块 → 渲染 → 发信
├── config.yaml             # 所有可调设置
├── requirements.txt
├── src/
│   ├── papers.py           # arXiv + Semantic Scholar
│   ├── news.py             # Hacker News
│   ├── funds.py            # 天天基金净值/涨跌
│   ├── render.py           # HTML 邮件渲染（涨红跌绿）
│   ├── mailer.py           # SMTP 发信（163/QQ SSL）
│   └── config.py
└── .github/workflows/daily.yml   # 每日定时
```

## 📝 说明

- 基金净值为 **T-1 收盘口径**（天天基金实时估值接口已失效，改用官方净值序列，更稳定）。
- 涨跌配色遵循 A 股习惯：**涨=红，跌=绿**。
- 仅供参考，**不构成投资建议**。
- 其他邮箱：QQ 邮箱用 `smtp.qq.com` + 端口 `465` + 授权码；Gmail 用 `smtp.gmail.com` + `587` + 应用专用密码。
