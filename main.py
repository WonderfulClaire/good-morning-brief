"""good-morning-brief 主编排。

用法：
    python main.py            # 抓取三板块，保存 HTML，并按环境变量发信
    python main.py --preview  # 仅抓取并保存 HTML 预览，不发信（本地调试用）
    python main.py --no-send  # 抓取并保存，但不发信
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from src.config import load_config
from src.papers import fetch_papers
from src.news import fetch_news
from src.funds import fetch_funds, fetch_opportunities
from src.advice import build_advice, build_opportunity
from src.render import render_html, render_text
from src.mailer import send_email


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="每日简报：论文/科技新闻/基金")
    ap.add_argument("--preview", action="store_true", help="只生成 HTML 预览，不发信")
    ap.add_argument("--no-send", action="store_true", help="生成并保存，但不发信")
    ap.add_argument("--config", default="config.yaml")
    return ap.parse_args()


def main() -> None:
    setup_logging()
    log = logging.getLogger("main")
    load_dotenv()
    args = parse_args()

    cfg = load_config(args.config)
    brief = cfg.get("brief", {})
    title = brief.get("title", "每日简报")

    papers = fetch_papers(cfg.get("papers", {})) if cfg.get("papers", {}).get("enabled", True) else []
    log.info("论文 %d 篇", len(papers))
    news = fetch_news(cfg.get("news", {})) if cfg.get("news", {}).get("enabled", True) else []
    log.info("新闻 %d 条", len(news))
    funds = fetch_funds(cfg.get("funds", {})) if cfg.get("funds", {}).get("enabled", True) else []
    log.info("基金 %d 只", len(funds))
    # 为每只基金计算加仓建议（数据驱动，best-effort）
    for f in funds:
        try:
            f.advice = build_advice(f)
        except Exception as exc:  # noqa: BLE001
            log.warning("加仓建议计算失败 %s: %s", f.code, exc)
            f.advice = None
    # 新机会：互补观察池（数据驱动，best-effort）
    opportunities = fetch_opportunities(cfg.get("funds", {})) if cfg.get("funds", {}).get("enabled", True) else []
    log.info("新机会 %d 只", len(opportunities))
    for o in opportunities:
        try:
            o.advice = build_opportunity(o, getattr(o, "reason", ""))
        except Exception as exc:  # noqa: BLE001
            log.warning("新机会建议计算失败 %s: %s", o.code, exc)
            o.advice = None

    html = render_html(title, papers, news, funds, opportunities, brief.get("timezone", "Asia/Shanghai"))
    text = render_text(title, papers, news, funds, opportunities)

    out_dir = Path("briefs")
    out_dir.mkdir(exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    html_path = out_dir / f"{today}.html"
    html_path.write_text(html, encoding="utf-8")
    log.info("HTML 已保存: %s", html_path)

    if args.preview or args.no_send:
        log.info("跳过发信（%s）", "preview" if args.preview else "no-send")
        return

    subject = f"☀️ {title} · {today}"
    ok = send_email(subject, html, text)
    log.info("发信状态: %s", "已发送" if ok else "跳过/失败")


if __name__ == "__main__":
    main()
