"""把三个板块渲染成一封 HTML 邮件（含纯文本兜底）。

配色遵循 A 股习惯：涨=红，跌=绿。
样式全部内联，兼容主流邮箱客户端。
"""
from __future__ import annotations

from datetime import datetime

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
def _funds_html(funds) -> str:
    if not funds:
        return ('<tr><td style="padding:8px 28px 4px;color:%s;font-size:13px;">暂无基金数据</td></tr>' % SUB)
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
        rows.append(
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
            f'</td></tr>'
        )
    return "".join(rows)


# --------------------------- 新闻 ---------------------------
def _news_html(news) -> str:
    if not news:
        return ('<tr><td style="padding:8px 28px 4px;color:%s;font-size:13px;">今日暂无满足条件的科技新闻</td></tr>' % SUB)
    rows = []
    for i, n in enumerate(news, 1):
        tag = ('<span style="display:inline-block;margin-left:6px;padding:0 6px;border-radius:8px;'
               f'background:#eef2ff;color:{ACCENT};font-size:10px;font-weight:600;">关注</span>') if n.matched else ""
        rows.append(
            f'<tr><td style="padding:10px 28px;border-bottom:1px solid {LINE};">'
            f'<div style="font-size:14px;line-height:1.5;">'
            f'<span style="color:{SUB};font-weight:700;">{i:02d}.</span> '
            f'<a href="{n.url}" style="color:{INK};text-decoration:none;font-weight:600;">{n.title}</a>{tag}</div>'
            f'<div style="font-size:12px;color:{SUB};margin-top:3px;">🔥 {n.score} 赞　·　'
            f'<a href="{n.hn_url}" style="color:{ACCENT};text-decoration:none;">HN 讨论</a></div>'
            f'</td></tr>'
        )
    return "".join(rows)


# --------------------------- 论文 ---------------------------
def _papers_html(papers) -> str:
    if not papers:
        return ('<tr><td style="padding:8px 28px 4px;color:%s;font-size:13px;">今日未检索到匹配论文（源站可能暂时不可达）</td></tr>' % SUB)
    rows = []
    for i, p in enumerate(papers, 1):
        authors = ", ".join(p.authors[:4]) + (" 等" if len(p.authors) > 4 else "")
        meta = " · ".join([x for x in [p.venue, str(p.year) if p.year else "", p.source] if x])
        reasons = ""
        if p.reasons:
            chips = "".join(
                f'<span style="display:inline-block;margin:2px 4px 0 0;padding:1px 7px;border-radius:10px;'
                f'background:#f0f3ff;color:{ACCENT};font-size:11px;">{r}</span>' for r in p.reasons[:3]
            )
            reasons = f'<div style="margin-top:6px;">{chips}</div>'
        abs = (p.abstract[:220] + "…") if len(p.abstract) > 220 else p.abstract
        rows.append(
            f'<tr><td style="padding:14px 28px;border-bottom:1px solid {LINE};">'
            f'<div style="font-size:14px;line-height:1.5;">'
            f'<span style="color:{SUB};font-weight:700;">{i:02d}.</span> '
            f'<a href="{p.url}" style="color:{INK};text-decoration:none;font-weight:700;">{p.title}</a></div>'
            f'<div style="font-size:12px;color:{SUB};margin-top:4px;">{authors}</div>'
            f'<div style="font-size:12px;color:{FLAT};margin-top:2px;">{meta}</div>'
            f'{reasons}'
            f'<div style="font-size:12.5px;color:{SUB};line-height:1.6;margin-top:6px;">{abs}</div>'
            f'</td></tr>'
        )
    return "".join(rows)


# --------------------------- 今日速览 ---------------------------
def _summary_html(papers, news, funds) -> str:
    pc = len(papers) if papers else 0
    nc = len(news) if news else 0
    parts = [
        f'<span style="margin-right:18px;">📄 <b>{pc}</b> 篇论文精选</span>',
        f'<span style="margin-right:18px;">📰 <b>{nc}</b> 条科技新闻</span>',
    ]
    for f in funds:
        if f.ok and f.change_pct is not None:
            txt, color, _ = _fmt_pct(f.change_pct)
            name = f.alias or f.name or f.code
            parts.append(
                f'<span style="margin-right:18px;">💰 {name} <b style="color:{color};">{txt}</b></span>'
            )
        else:
            parts.append(f'<span style="margin-right:18px;">💰 {f.alias or f.code} 数据缺失</span>')
    return (
        f'<tr><td style="padding:14px 28px;background:{BG};">'
        f'<div style="font-size:13.5px;color:{INK};">{"".join(parts)}</div>'
        f'</td></tr>'
    )


# --------------------------- 组装 ---------------------------
def render_html(title: str, papers, news, funds, tz_label: str = "Asia/Shanghai") -> str:
    now = datetime.now().strftime("%Y-%m-%d %A")
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
    <div style="font-size:13px;color:#dbe4ff;margin-top:6px;">{now} · 论文 / 科技新闻 / 基金一览</div>
  </td></tr>

  {_summary_html(papers, news, funds)}

  {_section_title("论文精选", "📄")}
  {_papers_html(papers)}

  {_section_title("科技新闻", "📰")}
  {_news_html(news)}

  {_section_title("基金涨跌", "💰")}
  {_funds_html(funds)}

  <!-- footer -->
  <tr><td style="padding:22px 28px;background:{BG};">
    <div style="font-size:11.5px;color:{FLAT};line-height:1.7;">
      本邮件由 good-morning-brief 自动生成 · 数据源：arXiv / Semantic Scholar / Hacker News / 天天基金<br>
      基金涨跌颜色遵循 A 股习惯（涨红跌绿）· 净值为 T-1 收盘口径 · 仅供参考，不构成投资建议
    </div>
  </td></tr>

</table>
</td></tr></table>
</body></html>"""


def render_text(title: str, papers, news, funds) -> str:
    pc = len(papers) if papers else 0
    nc = len(news) if news else 0
    fund_txt = " / ".join(
        f"{(f.alias or f.code)} {('+%.2f%%' % f.change_pct) if (f.ok and f.change_pct is not None) else '—'}"
        for f in funds
    )
    lines = [f"☀️ {title}", datetime.now().strftime("%Y-%m-%d"),
             f"📄 {pc} 篇 · 📰 {nc} 条 · 💰 {fund_txt}", ""]
    lines.append("== 论文精选 ==")
    if papers:
        for i, p in enumerate(papers, 1):
            lines.append(f"{i}. {p.title}\n   {p.url}")
    else:
        lines.append("(今日无匹配论文)")
    lines.append("\n== 科技新闻 ==")
    if news:
        for i, n in enumerate(news, 1):
            lines.append(f"{i}. {n.title} ({n.score}赞)\n   {n.url}")
    else:
        lines.append("(今日无新闻)")
    lines.append("\n== 基金涨跌 ==")
    for f in funds:
        if f.ok:
            pct = f"{f.change_pct:+.2f}%" if f.change_pct is not None else "—"
            lines.append(f"- {f.alias or f.name} ({f.code}) 净值{f.nav} 当日{pct} 净值日{f.nav_date}")
        else:
            lines.append(f"- {f.alias or f.code} 获取失败: {f.error}")
    lines.append("\n-- good-morning-brief 自动生成，仅供参考，不构成投资建议 --")
    return "\n".join(lines)
