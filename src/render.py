"""把三个板块渲染成一封全中文 HTML 邮件（含纯文本兜底）。

设计原则（参考阮一峰周刊 / HF Daily Papers 中文解读）：
  - 全中文，论文标题保留英文（用户要求）。
  - 一眼看懂：每篇论文用「中文标签 + 一句话大白话看点」代替英文摘要；
    每条新闻用「中文标题 + 一句话中文摘要 + 分类标签」。
  - 不堆术语、不堆摘要。
配色遵循 A 股习惯：涨=红，跌=绿。样式全部内联，兼容主流邮箱客户端。
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

# ------ 颜色 ------
UP = "#d1434b"       # 涨 红
DOWN = "#2f9e5c"     # 跌 绿
FLAT = "#888888"
INK = "#1f2328"
SUB = "#57606a"
LINE = "#e6e8eb"
BG = "#f6f7f9"
CARD = "#ffffff"
ACCENT = "#3b5bdb"
CHIP = "#eef2ff"
CHIP_TX = "#3b5bdb"


_WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _cn_date(tz_name: str = "Asia/Shanghai") -> str:
    d = datetime.now(ZoneInfo(tz_name))
    return f"{d.year}年{d.month}月{d.day}日 {_WEEKDAYS[d.weekday()]}"


def _fmt_pct(v):
    if v is None:
        return ("—", FLAT, "")
    color = UP if v > 0 else (DOWN if v < 0 else FLAT)
    arrow = "▲" if v > 0 else ("▼" if v < 0 else "•")
    sign = "+" if v > 0 else ""
    return (f"{arrow} {sign}{v:.2f}%", color, arrow)


def _section_title(text: str, emoji: str) -> str:
    return (
        f'<tr><td style="padding:26px 28px 6px 28px;">'
        f'<div style="font-size:17px;font-weight:700;color:{INK};letter-spacing:.3px;">'
        f'{emoji} {text}</div>'
        f'<div style="height:2px;width:38px;background:{ACCENT};margin-top:8px;border-radius:2px;"></div>'
        f'</td></tr>'
    )


# --------------------------- 基金 ---------------------------
def _advice_chip(level: str) -> str:
    """加仓建议的 action chip 染色（与涨跌幅红绿区分开）。"""
    style = {
        "buy":  ("#0c8599", "#e6fcf5"),   # 青绿：建议买/加仓
        "hold": ("#3b5bdb", "#eef2ff"),   # 蓝：持有/定投
        "warn": ("#c92a2a", "#fff0f0"),   # 红：观望/减仓
    }.get(level, ("#57606a", "#f1f3f5"))
    fg, bg = style
    return (f'display:inline-block;padding:2px 9px;border-radius:11px;'
            f'background:{bg};color:{fg};font-size:11.5px;font-weight:700;')


def _funds_html(funds) -> str:
    if not funds:
        return f'<tr><td style="padding:8px 28px 4px;color:{SUB};font-size:13px;">暂无基金数据</td></tr>'
    rows = []
    for f in funds:
        if not f.ok:
            rows.append(
                f'<tr><td style="padding:10px 28px;">'
                f'<div style="font-size:14px;color:{INK};font-weight:600;">{f.alias or f.code} '
                f'<span style="color:{SUB};font-weight:400;">({f.code})</span></div>'
                f'<div style="font-size:12px;color:{FLAT};margin-top:2px;">数据获取失败：{f.error}</div>'
                f'</td></tr>'
            )
            continue
        pct_txt, pct_color, _ = _fmt_pct(f.change_pct)
        d5_txt, d5_color, _ = _fmt_pct(f.recent_5d_pct)
        alert = ('<span style="display:inline-block;margin-left:8px;padding:1px 7px;border-radius:10px;'
                 f'background:#fdecec;color:{UP};font-size:11px;font-weight:600;">跌幅偏大 · 可关注定投</span>') if f.dip_alert else ""
        card = (
            f'<tr><td style="padding:12px 28px;border-bottom:1px solid {LINE};">'
            f'<table width="100%" cellpadding="0" cellspacing="0"><tr>'
            f'<td style="vertical-align:top;">'
            f'<div style="font-size:14px;color:{INK};font-weight:600;">{f.alias or f.name}{alert}</div>'
            f'<div style="font-size:12px;color:{SUB};margin-top:3px;">{f.name} · {f.code} · 净值日 {f.nav_date}</div>'
            f'</td>'
            f'<td style="vertical-align:top;text-align:right;white-space:nowrap;">'
            f'<div style="font-size:18px;color:{pct_color};font-weight:700;">{pct_txt}</div>'
            f'<div style="font-size:12px;color:{SUB};margin-top:3px;">净值 {f.nav}　'
            f'近5日 <span style="color:{d5_color};">{d5_txt}</span></div>'
            f'</td></tr></table>'
        )
        # —— 加仓建议子块 ——
        adv = getattr(f, "advice", None)
        if adv and getattr(adv, "ok", False):
            rows.append(card)
            rows.append(
                f'<tr><td style="padding:0 28px 14px;">'
                f'<div style="background:{BG};border-radius:10px;padding:11px 14px;'
                f'border-left:3px solid {ACCENT};">'
                f'<div style="margin-bottom:6px;">'
                f'<span style="{_advice_chip(adv.level)}">{adv.verdict_label}</span>'
                f'<span style="font-size:11.5px;color:{SUB};margin-left:8px;">'
                f'近1周 {("+" if adv.ret_1w and adv.ret_1w>0 else "")}{adv.ret_1w:.2f}% · '
                f'近1月 {("+" if adv.ret_1m and adv.ret_1m>0 else "")}{adv.ret_1m:.2f}% · '
                f'近1年 {("+" if adv.ret_1y and adv.ret_1y>0 else "")}{adv.ret_1y:.2f}%</span>'
                f'</div>'
                f'<div style="font-size:12.5px;color:{INK};line-height:1.65;">{adv.text}</div>'
                f'</div>'
                f'</td></tr>'
            )
            continue
        rows.append(card)
    return "".join(rows)


def _opportunities_html(opportunities) -> str:
    """新机会：与现有持仓互补、可关注配置的基金。"""
    opps = opportunities or []
    if not opps:
        return f'<tr><td style="padding:8px 28px 4px;color:{SUB};font-size:13px;">暂无新机会配置</td></tr>'
    rows = []
    for o in opps:
        if not o.ok:
            rows.append(
                f'<tr><td style="padding:10px 28px;">'
                f'<div style="font-size:14px;color:{INK};font-weight:600;">{o.alias or o.code} '
                f'<span style="color:{SUB};font-weight:400;">({o.code})</span></div>'
                f'<div style="font-size:12px;color:{FLAT};margin-top:2px;">获取失败：{o.error}</div>'
                f'</td></tr>'
            )
            continue
        pct_txt, pct_color, _ = _fmt_pct(o.change_pct)
        adv = getattr(o, "advice", None)
        verdict_chip = r1m = r1y = adv_text = ""
        if adv and getattr(adv, "ok", False):
            verdict_chip = f'<span style="{_advice_chip(adv.level)}">{adv.verdict_label}</span>'
            r1m = f"{adv.ret_1m:+.2f}%" if adv.ret_1m is not None else "—"
            r1y = f"{adv.ret_1y:+.2f}%" if adv.ret_1y is not None else "—"
            adv_text = adv.text
        rows.append(
            f'<tr><td style="padding:12px 28px;border-bottom:1px solid {LINE};">'
            f'<table width="100%" cellpadding="0" cellspacing="0"><tr>'
            f'<td style="vertical-align:top;">'
            f'<div style="font-size:14px;color:{INK};font-weight:600;">{o.alias or o.name} '
            f'<span style="color:{SUB};font-weight:400;font-size:12px;">({o.code})</span></div>'
            f'<div style="font-size:12px;color:{SUB};margin-top:3px;">净值 {o.nav} · '
            f'当日 <span style="color:{pct_color};font-weight:600;">{pct_txt}</span> · '
            f'近1月 {r1m} · 近1年 {r1y}</div>'
            f'</td>'
            f'<td style="vertical-align:top;text-align:right;white-space:nowrap;padding-top:2px;">'
            f'{verdict_chip}</td></tr></table>'
            f'<div style="font-size:12.5px;color:{INK};line-height:1.65;margin-top:7px;">{adv_text}</div>'
            f'</td></tr>'
        )
    return "".join(rows)


# --------------------------- 大模型福利 ---------------------------
def _benefits_html(benefits) -> str:
    if not benefits:
        return f'<tr><td style="padding:8px 28px 4px;color:{SUB};font-size:13px;">今日暂无大模型福利/新活动（以官方 App / 公众号公告为准）</td></tr>'
    rows = []
    for i, b in enumerate(benefits, 1):
        chip = (f'<span style="display:inline-block;margin-left:6px;padding:0 7px;border-radius:8px;'
                f'background:{CHIP};color:{CHIP_TX};font-size:10px;font-weight:600;">{b.benefit_type}</span>')
        meta = " · ".join(x for x in (b.source, b.published) if x)
        metaline = f'<div style="font-size:11px;color:{FLAT};margin-top:5px;">{meta}</div>' if meta else ""
        summary = f'<div style="font-size:12.5px;color:{SUB};line-height:1.6;margin-top:5px;">{b.summary}</div>' if b.summary else ""
        rows.append(
            f'<tr><td style="padding:11px 28px;border-bottom:1px solid {LINE};">'
            f'<div style="font-size:14px;line-height:1.5;">'
            f'<span style="color:{SUB};font-weight:700;">{i:02d}.</span> '
            f'<a href="{b.url}" style="color:{INK};text-decoration:none;font-weight:600;">{b.title}</a>{chip}</div>'
            f'{summary}{metaline}'
            f'</td></tr>'
        )
    return "".join(rows)


# --------------------------- 新闻 ---------------------------
def _news_html(news) -> str:
    if not news:
        return f'<tr><td style="padding:8px 28px 4px;color:{SUB};font-size:13px;">今日暂无科技新闻</td></tr>'
    rows = []
    for i, n in enumerate(news, 1):
        chip = (f'<span style="display:inline-block;margin-left:6px;padding:0 7px;border-radius:8px;'
                f'background:{CHIP};color:{CHIP_TX};font-size:10px;font-weight:600;">{n.category}</span>')
        summary = f'<div style="font-size:12.5px;color:{SUB};line-height:1.6;margin-top:5px;">{n.summary}</div>' if n.summary else ""
        rows.append(
            f'<tr><td style="padding:11px 28px;border-bottom:1px solid {LINE};">'
            f'<div style="font-size:14px;line-height:1.5;">'
            f'<span style="color:{SUB};font-weight:700;">{i:02d}.</span> '
            f'<a href="{n.url}" style="color:{INK};text-decoration:none;font-weight:600;">{n.title}</a>{chip}</div>'
            f'{summary}'
            f'</td></tr>'
        )
    return "".join(rows)


# --------------------------- 论文 ---------------------------
def _papers_html(papers) -> str:
    if not papers:
        return f'<tr><td style="padding:8px 28px 4px;color:{SUB};font-size:13px;">今日未检索到匹配论文（源站可能暂时不可达）</td></tr>'
    rows = []
    for i, p in enumerate(papers, 1):
        # 中文方向标签
        tags = ""
        if p.tags:
            tags = "<div style='margin-top:7px;'>" + "".join(
                f'<span style="display:inline-block;margin:0 5px 0 0;padding:1px 8px;border-radius:10px;'
                f'background:{CHIP};color:{CHIP_TX};font-size:11px;font-weight:600;">{t}</span>'
                for t in p.tags[:5]
            ) + "</div>"
        # 一句话中文看点
        highlight = (f'<div style="font-size:13px;color:{INK};line-height:1.65;margin-top:7px;">{p.highlight}</div>'
                     ) if p.highlight else ""
        # 元信息：来源 + 作者数 + 日期
        meta_bits = []
        if p.venue:
            meta_bits.append(p.venue)
        if p.authors:
            meta_bits.append(f"{len(p.authors)} 位作者")
        if p.published:
            meta_bits.append(p.published.strftime("%Y-%m-%d"))
        meta = " · ".join(meta_bits)
        rows.append(
            f'<tr><td style="padding:15px 28px;border-bottom:1px solid {LINE};">'
            f'<div style="font-size:14.5px;line-height:1.5;">'
            f'<span style="color:{SUB};font-weight:700;">{i:02d}.</span> '
            f'<a href="{p.url}" style="color:{INK};text-decoration:none;font-weight:700;">{p.title}</a></div>'
            f'{tags}'
            f'{highlight}'
            f'<div style="font-size:11.5px;color:{FLAT};margin-top:6px;">{meta}</div>'
            f'</td></tr>'
        )
    return "".join(rows)


# --------------------------- 今日速览 ---------------------------
def _summary_html(papers, benefits, news, funds) -> str:
    papers = papers or []
    benefits = benefits or []
    news = news or []
    funds = funds or []
    pc = len(papers) if papers else 0
    bc = len(benefits) if benefits else 0
    nc = len(news) if news else 0
    parts = [
        f'<span style="margin-right:18px;">📄 <b>{pc}</b> 篇论文精选</span>',
        f'<span style="margin-right:18px;">🎁 <b>{bc}</b> 条大模型福利</span>',
        f'<span style="margin-right:18px;">📰 <b>{nc}</b> 条科技新闻</span>',
    ]
    for f in funds:
        if f.ok and f.change_pct is not None:
            txt, color, _ = _fmt_pct(f.change_pct)
            name = f.alias or f.name or f.code
            verdict = ""
            adv = getattr(f, "advice", None)
            if adv and getattr(adv, "ok", False):
                verdict = f' <b style="color:{ACCENT};">{adv.verdict}</b>'
            parts.append(
                f'<span style="margin-right:18px;">💰 {name} '
                f'<b style="color:{color};">{txt}</b>{verdict}</span>'
            )
        else:
            parts.append(f'<span style="margin-right:18px;">💰 {f.alias or f.code} 数据缺失</span>')
    return (
        f'<tr><td style="padding:14px 28px;background:{BG};">'
        f'<div style="font-size:13.5px;color:{INK};">{"".join(parts)}</div>'
        f'</td></tr>'
    )


# --------------------------- 组装 ---------------------------
def render_html(title: str, papers, benefits=None, news=None, funds=None, opportunities=None, tz_label: str = "Asia/Shanghai") -> str:
    papers = papers or []
    benefits = benefits or []
    news = news or []
    funds = funds or []
    date_str = _cn_date(tz_label)
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:{BG};font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Hiragino Sans GB','Microsoft YaHei',sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:{BG};padding:24px 12px;">
<tr><td align="center">
<table width="640" cellpadding="0" cellspacing="0" style="max-width:640px;width:100%;background:{CARD};border-radius:14px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.06);">

  <!-- header -->
  <tr><td style="background:linear-gradient(135deg,#3b5bdb,#5c7cfa);padding:28px 28px 24px;">
    <div style="font-size:22px;font-weight:800;color:#ffffff;letter-spacing:.5px;">☀️ {title}</div>
    <div style="font-size:13px;color:#dbe4ff;margin-top:6px;">{date_str} · 论文 / 大模型福利 / 科技新闻 / 基金 一览</div>
  </td></tr>

  {_summary_html(papers, benefits, news, funds)}

  {_section_title("论文精选", "📄")}
  {_papers_html(papers)}

  {_section_title("大模型福利 · 新活动 / 限时免费 / 新模型", "🎁")}
  {_benefits_html(benefits)}

  {_section_title("科技新闻", "📰")}
  {_news_html(news)}

  {_section_title("基金涨跌", "💰")}
  {_funds_html(funds)}

  {_section_title("新机会 · 可关注配置", "✨")}
  {_opportunities_html(opportunities)}

  <!-- footer -->
  <tr><td style="padding:22px 28px;background:{BG};">
    <div style="font-size:11.5px;color:{FLAT};line-height:1.7;">
      本邮件由 good-morning-brief 自动生成 · 论文来源 arXiv · 大模型福利来源 IT之家 / Hacker News · 新闻来源 IT之家 · 基金来源 天天基金<br>
      基金涨跌颜色遵循 A 股习惯（涨红跌绿）· 净值为 T-1 收盘口径 · 仅供参考，不构成投资建议
    </div>
  </td></tr>

</table>
</td></tr></table>
</body></html>"""


def render_text(title: str, papers, benefits=None, news=None, funds=None, opportunities=None) -> str:
    papers = papers or []
    benefits = benefits or []
    news = news or []
    funds = funds or []
    pc = len(papers) if papers else 0
    bc = len(benefits) if benefits else 0
    nc = len(news) if news else 0
    fund_txt = " / ".join(
        f"{(f.alias or f.code)} {('+%.2f%%' % f.change_pct) if (f.ok and f.change_pct is not None) else '—'}"
        for f in funds
    )
    lines = [f"☀️ {title}", _cn_date(),
             f"📄 {pc} 篇 · 🎁 {bc} 条 · 📰 {nc} 条 · 💰 {fund_txt}", ""]
    lines.append("== 论文精选 ==")
    if papers:
        for i, p in enumerate(papers, 1):
            lines.append(f"{i}. {p.title}")
            if p.tags:
                lines.append(f"   方向：{'、'.join(p.tags[:5])}")
            if p.highlight:
                lines.append(f"   {p.highlight}")
            lines.append(f"   链接：{p.url}")
    else:
        lines.append("(今日无匹配论文)")
    lines.append("\n== 大模型福利 · 新活动 / 限时免费 / 新模型 ==")
    if benefits:
        for i, b in enumerate(benefits, 1):
            lines.append(f"{i}. [{b.benefit_type}] {b.title}")
            if b.summary:
                lines.append(f"   {b.summary}")
            meta = " · ".join(x for x in [b.source, b.published] if x)
            if meta:
                lines.append(f"   （{meta}）")
            lines.append(f"   链接：{b.url}")
    else:
        lines.append("（今日暂无大模型福利/新活动）")
    lines.append("\n== 科技新闻 ==")
    if news:
        for i, n in enumerate(news, 1):
            lines.append(f"{i}. [{n.category}] {n.title}")
            if n.summary:
                lines.append(f"   {n.summary}")
            lines.append(f"   链接：{n.url}")
    else:
        lines.append("(今日无新闻)")
    lines.append("\n== 基金涨跌 ==")
    for f in funds:
        if f.ok:
            pct = f"{f.change_pct:+.2f}%" if f.change_pct is not None else "—"
            lines.append(f"- {f.alias or f.name} ({f.code}) 净值{f.nav} 当日{pct} 净值日{f.nav_date}")
            adv = getattr(f, "advice", None)
            if adv and getattr(adv, "ok", False):
                r1w = f"{adv.ret_1w:+.2f}%" if adv.ret_1w is not None else "—"
                r1m = f"{adv.ret_1m:+.2f}%" if adv.ret_1m is not None else "—"
                r1y = f"{adv.ret_1y:+.2f}%" if adv.ret_1y is not None else "—"
                lines.append(f"   加仓建议【{adv.verdict}】近1周{r1w} 近1月{r1m} 近1年{r1y}")
                lines.append(f"   {adv.text}")
        else:
            lines.append(f"- {f.alias or f.code} 获取失败: {f.error}")
    lines.append("\n== 新机会 · 可关注配置 ==")
    for o in (opportunities or []):
        if o.ok:
            pct = f"{o.change_pct:+.2f}%" if o.change_pct is not None else "—"
            lines.append(f"- {o.alias or o.name} ({o.code}) 净值{o.nav} 当日{pct} 净值日{o.nav_date}")
            adv = getattr(o, "advice", None)
            if adv and getattr(adv, "ok", False):
                r1m = f"{adv.ret_1m:+.2f}%" if adv.ret_1m is not None else "—"
                r1y = f"{adv.ret_1y:+.2f}%" if adv.ret_1y is not None else "—"
                lines.append(f"   建议【{adv.verdict}】近1月{r1m} 近1年{r1y}")
                lines.append(f"   {adv.text}")
        else:
            lines.append(f"- {o.alias or o.code} 获取失败: {o.error}")
    lines.append("\n-- good-morning-brief 自动生成，仅供参考，不构成投资建议 --")
    return "\n".join(lines)
