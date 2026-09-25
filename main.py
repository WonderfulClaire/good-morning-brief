"""Daily source-checked technical-report reading guide; no paid API."""
from __future__ import annotations
import argparse
from datetime import date, datetime
from html import escape
import json
import logging
import os
from pathlib import Path
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
import requests
from src.config import load_config
from src.mailer import send_email

LOG = logging.getLogger("technical-report")

def load_catalog(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    required = {"id", "title", "organization", "published", "url", "priority",
                "why", "mechanism", "sections", "questions", "exercise", "checked"}
    ids = set()
    for report in data:
        if not required <= report.keys() or report["id"] in ids:
            raise ValueError("Incomplete or duplicate report")
        ids.add(report["id"])
        date.fromisoformat(report["published"])
        date.fromisoformat(report["checked"])
        if not report["url"].startswith("https://arxiv.org/html/"):
            raise ValueError("Report must link to reviewed primary-source full text")
        for field in ("why", "mechanism", "sections", "questions", "exercise"):
            if not report[field]:
                raise ValueError(f"Missing {field}")
    if not data:
        raise ValueError("Empty report catalog")
    return data

def select_report(reports, history, today):
    eligible = [r for r in reports if r["published"] <= today]
    unseen = [r for r in eligible if r["id"] not in history.get("reports", {})]
    if unseen:
        return max(unseen, key=lambda r: (r["priority"], r["published"], r["id"])), False
    if not eligible:
        raise ValueError("No eligible reports")
    return min(eligible, key=lambda r: (history["reports"][r["id"]], -r["priority"])), True

def render(report, today, cfg, review=False):
    title = cfg["brief"]["title"]
    kind = "间隔复习" if review else "今日精读"
    blocks = [
        ("为什么现在读", [report["why"]]),
        ("关键机制", report["mechanism"]),
        ("建议阅读章节（约 25–40 分钟）", report["sections"]),
        ("对应面试问题", report["questions"]),
        ("读完做一个小练习", [report["exercise"]]),
    ]
    intro = f'{report["organization"]} · 发布 {report["published"]} · 导读核验 {report["checked"]}'
    text = f'{title} · {today}\n{kind}：{report["title"]}\n{intro}\n原文：{report["url"]}\n'
    body = f'<p style="color:#546577">{escape(today)} · {kind}</p><h1>{escape(report["title"])}</h1><p>{escape(intro)}</p>'
    body += f'<p><a href="{escape(report["url"], quote=True)}">打开官方报告原文 →</a></p>'
    for heading, paragraphs in blocks:
        text += "\n" + heading + "\n" + "\n".join(f"{i+1}. {p}" for i, p in enumerate(paragraphs)) + "\n"
        body += f'<h2 style="font-size:19px;margin-top:28px">{escape(heading)}</h2><ol>'
        body += "".join(f"<li style='margin:10px 0'>{escape(p)}</li>" for p in paragraphs) + "</ol>"
    note = "导读与练习是学习建议；实验结论以原文设置为准。已推送不等于已读或已掌握。"
    if review:
        note += " 本轮已核验报告均已推送，今天复习较早的一篇；补入新报告后优先发送未推送的导读。"
    age = (date.fromisoformat(today) - date.fromisoformat(cfg["reports"]["profile_updated"])).days
    if age > 14:
        note += f" 选题方向距上次更新已有 {age} 天，仍沿用已核验阅读池。"
    text += "\n" + note
    html = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{escape(title)}</title><body style="margin:0;background:#f4f6f8;color:#172b3a;font:16px/1.8 Arial,sans-serif">'
            '<main style="max-width:740px;margin:24px auto;padding:28px;background:white;border-radius:12px">'
            f'<p style="color:#14746f;font-weight:bold">{escape(title)}</p>{body}'
            f'<hr><p style="font-size:13px;color:#667">{escape(note)}</p></main></body></html>')
    return html, text

def verify_source(report):
    response = requests.get(report["url"], timeout=30, headers={"User-Agent": "TechnicalReportReadingGuide/1.0"})
    response.raise_for_status()
    if report["id"] not in response.url or report["title"].casefold() not in response.text.casefold():
        raise ValueError("Primary source identity check failed")

def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    load_dotenv()
    parser = argparse.ArgumentParser(description="每日大厂技术报告精读")
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--no-send", action="store_true")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--date", help="Preview date YYYY-MM-DD; never used for sending")
    args = parser.parse_args()
    preview = args.preview or args.no_send
    if args.date and not preview:
        parser.error("--date requires --preview or --no-send")
    cfg = load_config(args.config)
    today = args.date or datetime.now(ZoneInfo(cfg["brief"]["timezone"])).date().isoformat()
    date.fromisoformat(today)
    state_path = Path(cfg["reports"].get("state_path", "delivery-state.json"))
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {"dates": {}, "reports": {}}
    if not preview and today in state["dates"]:
        LOG.info("Already sent for %s; skipping duplicate", today)
        return
    report, review = select_report(load_catalog(cfg["reports"]["catalog"]), state, today)
    verify_source(report)
    html, text = render(report, today, cfg, review)
    out = Path("briefs")
    out.mkdir(exist_ok=True)
    (out / f"{today}.html").write_text(html, encoding="utf-8")
    (out / f"{today}.txt").write_text(text, encoding="utf-8")
    LOG.info("Selected %s: %s (review=%s)", report["id"], report["title"], review)
    if preview:
        LOG.info("Preview only; no mail and no delivery state changed")
        return
    os.environ["SMTP_TO"] = cfg["brief"]["recipient"]
    subject = f'{cfg["brief"]["title"]} · {today} · {report["title"]}'
    if not send_email(subject, html, text):
        raise SystemExit("SMTP delivery failed; state not advanced")
    state["dates"][today] = report["id"]
    state["reports"][report["id"]] = today
    temporary = state_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(state_path)
    LOG.info("SMTP accepted message; delivery state saved (inbox receipt is not observable)")

if __name__ == "__main__":
    main()

