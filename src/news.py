"""板块 2：科技新闻。

数据源：Hacker News 官方 Firebase API（免费、无需 key）
    topstories / beststories -> item 详情
按赞数过滤，命中科技/AI 关键词的条目优先靠前。
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)

_UA = "good-morning-brief/1.0"
_TOP = "https://hacker-news.firebaseio.com/v0/topstories.json"
_ITEM = "https://hacker-news.firebaseio.com/v0/item/{id}.json"


@dataclass
class NewsItem:
    title: str
    url: str
    score: int
    hn_url: str
    matched: bool = False


def _fetch_item(item_id: int) -> dict | None:
    try:
        r = requests.get(_ITEM.format(id=item_id), headers={"User-Agent": _UA}, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception:  # noqa: BLE001
        return None


def fetch_news(cfg: dict) -> list[NewsItem]:
    top_n = int(cfg.get("top_n", 6))
    min_score = int(cfg.get("min_score", 80))
    prefer = [k.lower() for k in (cfg.get("prefer_keywords") or [])]

    try:
        ids = requests.get(_TOP, headers={"User-Agent": _UA}, timeout=15).json()[:80]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Hacker News 榜单抓取失败: %s", exc)
        return []

    items: list[dict] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for it in pool.map(_fetch_item, ids):
            if it and it.get("type") == "story" and it.get("title"):
                items.append(it)

    scored: list[NewsItem] = []
    for it in items:
        score = int(it.get("score", 0))
        if score < min_score:
            continue
        title = it.get("title", "")
        url = it.get("url") or f"https://news.ycombinator.com/item?id={it.get('id')}"
        matched = any(k in title.lower() for k in prefer) if prefer else False
        scored.append(NewsItem(
            title=title,
            url=url,
            score=score,
            hn_url=f"https://news.ycombinator.com/item?id={it.get('id')}",
            matched=matched,
        ))

    # 命中关键词优先，其次按赞数
    scored.sort(key=lambda n: (n.matched, n.score), reverse=True)
    return scored[:top_n]
