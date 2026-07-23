"""板块 1：论文精选。

主源：arXiv API（免费、无 key）
兜底：Semantic Scholar Graph API（arXiv 不可达时）
按关注方向 / 前沿方向 / 会议 / 新鲜度加权排序，取 top N。
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from urllib.parse import quote_plus

import requests

logger = logging.getLogger(__name__)

_UA = "good-morning-brief/1.0 (mailto:wk1924321@163.com)"
_ARXIV = "http://export.arxiv.org/api/query"
_S2 = "https://api.semanticscholar.org/graph/v1/paper/search"


@dataclass
class Paper:
    source: str
    title: str
    abstract: str = ""
    authors: list[str] = field(default_factory=list)
    venue: str = ""
    year: int | None = None
    published: date | None = None
    url: str = ""
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)


# --------------------------- 抓取 ---------------------------
def _search_arxiv(query: str, max_results: int, days_back: int) -> list[Paper]:
    cutoff = date.today() - timedelta(days=days_back)
    params = {
        "search_query": f"all:{quote_plus(query)}",
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    try:
        resp = requests.get(_ARXIV, params=params, headers={"User-Agent": _UA}, timeout=30)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
    except (requests.RequestException, ET.ParseError) as exc:
        logger.warning("arXiv 查询失败: %s", exc)
        return []

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    papers: list[Paper] = []
    for entry in root.findall("atom:entry", ns):
        title = (entry.findtext("atom:title", default="", namespaces=ns) or "").replace("\n", " ").strip()
        abstract = (entry.findtext("atom:summary", default="", namespaces=ns) or "").replace("\n", " ").strip()
        updated = entry.findtext("atom:updated", default="", namespaces=ns)
        pub = None
        if updated:
            try:
                pub = datetime.strptime(updated[:10], "%Y-%m-%d").date()
            except ValueError:
                pub = None
        if pub and pub < cutoff:
            continue
        url = ""
        for link in entry.findall("atom:link", ns):
            href = link.attrib.get("href", "")
            if href and "abs" in href:
                url = href
                break
        authors = [
            a.findtext("atom:name", default="", namespaces=ns)
            for a in entry.findall("atom:author", ns)
            if a.findtext("atom:name", default="", namespaces=ns)
        ]
        papers.append(Paper(
            source="arxiv", title=title, abstract=abstract, authors=authors,
            venue="arXiv", year=pub.year if pub else None, published=pub, url=url,
        ))
    return papers


def _search_s2(query: str, max_results: int) -> list[Paper]:
    try:
        resp = requests.get(
            _S2,
            params={"query": query, "limit": min(max_results, 20),
                    "fields": "title,abstract,year,url,venue,authors"},
            headers={"User-Agent": _UA}, timeout=30,
        )
        if resp.status_code != 200:
            logger.warning("Semantic Scholar 返回 %s", resp.status_code)
            return []
        data = resp.json().get("data", []) or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("Semantic Scholar 查询失败: %s", exc)
        return []
    papers: list[Paper] = []
    for p in data:
        papers.append(Paper(
            source="semantic_scholar",
            title=(p.get("title") or "").strip(),
            abstract=(p.get("abstract") or "").strip(),
            authors=[a.get("name", "") for a in (p.get("authors") or [])],
            venue=p.get("venue") or "",
            year=p.get("year"),
            url=p.get("url") or "",
        ))
    return papers


# --------------------------- 排序 ---------------------------
def _score(paper: Paper, cfg: dict) -> Paper:
    w = cfg.get("ranking_weights", {})
    focus = [t.lower() for t in (cfg.get("focus_topics") or [])]
    frontier = [t.lower() for t in (cfg.get("frontier_topics") or [])]
    venues = [v.lower() for v in (cfg.get("venues_high_priority") or [])]
    text = f"{paper.title} {paper.abstract}".lower()

    score = 0.0
    hit_focus = [t for t in focus if t in text]
    if focus:
        score += w.get("keyword_match", 0.4) * min(len(hit_focus) / max(len(focus), 1) * 3, 1.0)
        if hit_focus:
            paper.reasons.append("命中方向: " + ", ".join(hit_focus[:2]))

    hit_frontier = [t for t in frontier if t in text]
    if frontier and hit_frontier:
        score += w.get("frontier_bonus", 0.2) * min(len(hit_frontier) / 2, 1.0)
        paper.reasons.append("前沿: " + ", ".join(hit_frontier[:2]))

    vtext = f"{paper.venue}".lower()
    if any(v in vtext for v in venues):
        score += w.get("venue_priority", 0.15)
        paper.reasons.append(f"会议/期刊: {paper.venue}")

    if paper.published:
        age = (date.today() - paper.published).days
        recency = max(0.0, 1.0 - age / 30.0)
        score += w.get("recency", 0.25) * recency
    elif paper.year and paper.year >= date.today().year - 1:
        score += w.get("recency", 0.25) * 0.5

    paper.score = round(score, 4)
    return paper


def fetch_papers(cfg: dict) -> list[Paper]:
    focus = cfg.get("focus_topics") or []
    frontier = cfg.get("frontier_topics") or []
    query = " ".join((focus[:5] + frontier[:2]) or ["speech enhancement"])
    days_back = int(cfg.get("days_back", 14))
    max_per = int(cfg.get("max_results_per_source", 40))
    top_n = int(cfg.get("pick_top_n", 3))

    papers = _search_arxiv(query, max_per, days_back)
    if not papers:
        logger.info("arXiv 无结果，尝试 Semantic Scholar 兜底")
        papers = _search_s2(query, max_per)

    # 去重
    seen, unique = set(), []
    for p in papers:
        key = p.title.strip().lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(p)

    ranked = sorted((_score(p, cfg) for p in unique), key=lambda x: x.score, reverse=True)
    return ranked[:top_n]
