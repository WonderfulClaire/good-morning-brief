"""Daily source-checked technical-report reading guide; no paid API."""
from __future__ import annotations
import argparse
from datetime import date, datetime
from html import escape
from html.parser import HTMLParser
import hashlib
import json
import logging
import os
from pathlib import Path
import re
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
import requests
from src.config import load_config
from src.mailer import send_email

LOG = logging.getLogger("technical-report")

class SourceText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

def normalized(text):
    return " ".join(text.split()).casefold()

def validate_source_metadata(report):
    # The catalog is editorially reviewed; HTTPS alone does not prove provenance.
    parsed = urlparse(report["url"])
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("A reviewed HTTPS primary-source URL is required")
    form = report.get("source_format", "html")
    if form not in ("html", "pdf"):
        raise ValueError("Unsupported source format")
    if form == "pdf" and not re.fullmatch(r"[0-9a-f]{64}", report.get("pdf_sha256", "")):
        raise ValueError("PDF requires the SHA-256 of the reviewed original")

def load_catalog(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    required = {"id", "title", "organization", "published", "url", "priority",
                "why", "mechanism", "sections", "questions", "exercise", "checked",
                "lesson", "answers", "exercise_answer", "lesson_checked"}
    ids = set()
    for report in data:
        if not required <= report.keys() or report["id"] in ids:
            raise ValueError("Incomplete or duplicate report")
        ids.add(report["id"])
        date.fromisoformat(report["published"])
        date.fromisoformat(report["checked"])
        date.fromisoformat(report["lesson_checked"])
        if not isinstance(report["lesson"], list) or not report["lesson"]:
            raise ValueError("A self-contained lesson is required")
        for section in report["lesson"]:
            if (not isinstance(section, dict)
                    or not isinstance(section.get("heading"), str) or not section["heading"].strip()
                    or not isinstance(section.get("paragraphs"), list) or not section["paragraphs"]
                    or any(not isinstance(p, str) or not p.strip() for p in section["paragraphs"])):
                raise ValueError("Incomplete lesson section")
        if (not isinstance(report["answers"], list)
                or len(report["answers"]) != len(report["questions"])
                or any(not isinstance(a, str) or not a.strip() for a in report["answers"])
                or not isinstance(report["exercise_answer"], str)
                or not report["exercise_answer"].strip()):
            raise ValueError("Questions and exercise need complete reference answers")
        validate_source_metadata(report)
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
    blocks = [("为什么现在学", [report["why"]])]
    blocks += [(s["heading"], s["paragraphs"]) for s in report["lesson"]]
    blocks += [
        ("对应面试问题：先自己回答", [f'{i+1}. {q}' for i, q in enumerate(report["questions"])]),
        ("面试问题参考答案", [f'{i+1}. {a}' for i, a in enumerate(report["answers"])]),
        ("动手练习", [report["exercise"]]),
        ("练习参考解答", [report["exercise_answer"]]),
        ("继续读原文（选读）", report["sections"]),
    ]
    intro = f'{report["organization"]} · 发布 {report["published"]} · 讲解核验 {report["lesson_checked"]}'
    text = f'{title} · {today}\n{kind}：{report["title"]}\n{intro}\n原文：{report["url"]}\n'
    body = f'<p style="color:#546577">{escape(today)} · {kind}</p><h1>{escape(report["title"])}</h1><p>{escape(intro)}</p>'
    lead = "今天的核心内容已在邮件里展开。先跟着例子理解，再尝试回答；原文留作进一步核对与延伸。"
    text += "\n" + lead + "\n"
    body += f'<p style="padding:16px;background:#edf6f4;border-left:4px solid #14746f">{escape(lead)}</p>'
    for heading, paragraphs in blocks:
        text += "\n" + heading + "\n" + "\n\n".join(paragraphs) + "\n"
        body += f'<h2 style="font-size:21px;line-height:1.5;margin:32px 0 14px;color:#125e59">{escape(heading)}</h2>'
        body += "".join(f'<p style="margin:14px 0">{escape(p)}</p>' for p in paragraphs)
    body += f'<p><a href="{escape(report["url"], quote=True)}">阅读原文与实验设置 →</a></p>'
    note = "机制讲解、推导与教学算例为自行编写；具体报告结论对应上方原文章节，教学数字不冒充实验结果。已推送不等于已掌握。"
    if review:
        note += " 本轮已核验报告均已推送，今天复习较早的一篇；补入新报告后优先发送未推送的导读。"
    age = (date.fromisoformat(today) - date.fromisoformat(cfg["reports"]["profile_updated"])).days
    if age > 14:
        note += f" 选题方向距上次更新已有 {age} 天，仍沿用已核验阅读池。"
    text += "\n" + note
    html = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{escape(title)}</title><body style="margin:0;background:#f4f6f8;color:#172b3a;font:17px/1.9 Arial,Microsoft YaHei,sans-serif;overflow-wrap:anywhere">'
            '<main style="max-width:700px;margin:16px auto;padding:20px;background:white;border-radius:12px">'
            f'<p style="color:#14746f;font-weight:bold">{escape(title)}</p>{body}'
            f'<hr><p style="font-size:13px;color:#667">{escape(note)}</p></main></body></html>')
    return html, text

def verify_source(report):
    validate_source_metadata(report)
    response = requests.get(report["url"], timeout=30, headers={"User-Agent": "TechnicalReportReadingGuide/1.0"})
    response.raise_for_status()
    allowed = {urlparse(report["url"]).hostname, *report.get("redirect_hosts", [])}
    resolved = urlparse(response.url)
    if resolved.scheme != "https" or resolved.hostname not in allowed:
        raise ValueError("Unreviewed primary-source redirect")
    if report.get("source_format", "html") == "pdf":
        if not response.content.startswith(b"%PDF-") or hashlib.sha256(response.content).hexdigest() != report["pdf_sha256"]:
            raise ValueError("Reviewed PDF changed; review before sending")
        return
    parser = SourceText()
    parser.feed(response.text)
    title = normalized(report.get("source_title", report["title"]))
    if not title or title not in normalized(" ".join(parser.parts)):
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
    # Retired queued runs must not send later, even on a different calendar day.
    run_id = os.getenv("GITHUB_RUN_ID")
    blocked_runs = {str(value) for value in cfg.get("delivery", {}).get("blocked_run_ids", [])}
    if not preview and run_id and run_id in blocked_runs:
        raise SystemExit("Retired workflow run: sending is blocked; use the verified replacement run")
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

