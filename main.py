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
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from src.config import load_config
from src.papers import fetch_papers
from src.news import fetch_news
from src.funds import fetch_funds, fetch_opportunities
from src.advice import build_advice, build_opportunity
from src.render import render_html, render_text
from src.benefits import fetch_benefits
from src.mailer import send_email
import os


def _push_wechat(text: str, date_str: str, sendkey: str, failed: bool = False) -> bool:
    """通过 Server酱(ServerChan) 把简报摘要推到微信。无 key / 失败均静默跳过，不影响主流程。"""
    import requests
    log = logging.getLogger("main")
    try:
        title = ("\u26a0\ufe0f 每日简报邮件发送失败（微信兜底）" if failed
                 else f"\u2600\ufe0f Claire 的每日简报 \u00b7 {date_str} 已送达")
        resp = requests.post(
            f"https://sctapi.ftqq.com/{sendkey}.send",
            data={"title": title, "desp": text},
            timeout=15,
        )
        data = resp.json()
        if data.get("code") == 0:
            log.info("微信推送成功")
            return True
        log.warning("微信推送返回异常: %s", data)
        return False
    except Exception as exc:  # noqa: BLE001
        log.warning("微信推送失败（不影响邮件）: %s", exc)
        return False




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
    tz_name = brief.get("timezone", "Asia/Shanghai")

    papers = fetch_papers(cfg.get("papers", {})) if cfg.get("papers", {}).get("enabled", True) else []
    log.info("论文 %d 篇", len(papers))
    benefits = fetch_benefits(cfg.get("benefits", {})) if cfg.get("benefits", {}).get("enabled", True) else []
    log.info("大模型福利 %d 条", len(benefits))
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

    html = render_html(title, papers, benefits, news, funds, opportunities, tz_name)
    text = render_text(title, papers, benefits, news, funds, opportunities)

    out_dir = Path("briefs")
    out_dir.mkdir(exist_ok=True)
    today = datetime.now(ZoneInfo(tz_name)).strftime("%Y-%m-%d")
    html_path = out_dir / f"{today}.html"
    html_path.write_text(html, encoding="utf-8")
    log.info("HTML 已保存: %s", html_path)

    if args.preview or args.no_send:
        log.info("跳过发信（%s）", "preview" if args.preview else "no-send")
        return

    subject = f"☀️ {title} · {today}"
    ok = False
    try:
        ok = send_email(subject, html, text)
    except Exception as exc:  # noqa: BLE001
        log.exception("发信异常: %s", exc)
        ok = False
    log.info("发信状态: %s", "已发送" if ok else "失败")

    # 微信推送（Server酱）：有 key 就推，正常/失败都推，作为双保险 + 兜底提醒
    sendkey = os.environ.get("WECHAT_SENDKEY", "").strip()
    if sendkey:
        _push_wechat(text, today, sendkey, failed=not ok)

    if not ok:
        # 发信失败应让 job 以非 0 退出，使 workflow 变红、便于告警，
        log.error("邮件发送失败，任务以非 0 状态退出以便告警")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
