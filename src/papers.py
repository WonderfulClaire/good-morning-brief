"""板块 1：论文精选。

取数策略（按可靠性从高到低串联兜底）：
  1) arXiv **RSS 订阅源**（纯 XML，几乎不限流，最稳）→ 主源
  2) OpenAlex API（免费、限流宽松）→ 主力兜底
  3) Semantic Scholar Graph API → 末位兜底

任一源成功即采用。聚合后按关注方向 / 前沿方向 / 会议 / 新鲜度加权排序，取 top N。
"""
from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import requests

logger = logging.getLogger(__name__)

_UA = "good-morning-brief/1.0 (mailto:wk1924321@163.com)"
_ARXIV_RSS = "https://rss.arxiv.org/rss/{cat}"
_OPENALEX = "https://api.openalex.org/works"
_S2 = "https://api.semanticscholar.org/graph/v1/paper/search"

_NS = {
    "dc": "http://purl.org/dc/elements/1.1/",
    "arxiv": "http://arxiv.org/schemas/atom",
    "content": "http://purl.org/rss/1.0/modules/content/",
}

# --------------------------- 中文“一句话看点”字典 ---------------------------
# (英文关键词, 中文标签, 大白话解释)。扫描标题+摘要命中即生成中文标签与看点。
_TOPIC_ZH = [
    ("speech enhancement", "语音增强", "让录音里的人声更清楚、把背景噪声压下去"),
    ("beamforming", "波束形成", "用一排麦克风像“聚光灯”一样只收某个方向的声音、抑制别处噪声"),
    ("multi-channel", "多通道", "用麦克风阵列从多个位置一起收音再融合"),
    ("microphone-array", "麦克风阵列", "用多个麦克风排成阵列来定向收音"),
    ("target speaker", "目标说话人分离", "从一堆人同时说话里单独抽出某一个的声音"),
    ("speaker extraction", "目标说话人分离", "从一堆人同时说话里单独抽出某一个的声音"),
    ("source separation", "声音分离", "把混在一起的多个人声/乐器声拆开"),
    ("speech separation", "声音分离", "把混在一起的多个人声拆开"),
    ("noise reduction", "降噪", "压制环境噪声、保留干净人声"),
    ("noise suppression", "降噪", "压制环境噪声、保留干净人声"),
    ("wake word", "唤醒词", "用特定词（如“小爱同学”）唤醒设备"),
    ("wake-word", "唤醒词", "用特定词（如“小爱同学”）唤醒设备"),
    ("speech recognition", "语音识别", "把人说的话转成文字"),
    ("asr", "语音识别", "把人说的话转成文字"),
    ("text-to-speech", "语音合成", "把文字念成自然的人声"),
    ("tts", "语音合成", "把文字念成自然的人声"),
    ("large language model", "大语言模型", "类似 ChatGPT 那样能对话、写代码的大模型"),
    ("llm", "大语言模型", "类似 ChatGPT 那样能对话、写代码的大模型"),
    ("retrieval-augmented", "检索增强生成", "先去查资料、再让模型回答，减少胡说八道"),
    ("rag", "检索增强生成", "先去查资料、再让模型回答，减少胡说八道"),
    ("agent", "智能体", "能自己规划步骤、调用工具去完成任务的 AI"),
    ("multi-agent", "多智能体", "好几个 AI 分工协作完成复杂任务"),
    ("multimodal", "多模态", "同时理解文字、声音、图像等多种信息"),
    ("vision", "视觉", "让 AI 看懂图片/视频"),
    ("on-device", "端侧部署", "直接在手机等设备本地运行，不用把数据传上云"),
    ("edge", "边缘计算", "在靠近数据源的设备上计算，更快更省电"),
    ("distill", "模型蒸馏", "把大模型的能力压缩到小模型上跑"),
    ("quantiz", "模型量化", "把模型“瘦身”到更小体积、更快推理"),
    ("foundation model", "基础模型", "在海量数据上先预训练、可再定制的通用大模型"),
    ("pose", "姿态估计", "识别人体关键点、判断动作姿势"),
    ("keypoint", "关键点检测", "在图像里标出关键位置（如关节、人脸点）"),
    ("reinforcement", "强化学习", "靠“试错+奖励”让 AI 自己学会策略"),
    ("diffusion", "扩散模型", "一类主流的生成模型，常用于生图/生视频"),
    ("self-supervised", "自监督学习", "不靠人工标注、从数据本身学特征"),
    ("embedding", "向量嵌入", "把文字/图变成一串数字，方便比对相似度"),
    ("recommend", "推荐系统", "猜你喜欢、给你推内容"),
    ("graph neural", "图神经网络", "在“关系网”上做学习的模型"),
    ("time series", "时间序列", "对随时间变化的数据做预测/分析"),
    ("anomaly", "异常检测", "从数据里找出不对劲的地方"),
    ("signal", "信号处理", "对声音/传感器信号做降噪、提取特征"),
    ("embodied", "具身智能", "让 AI 拥有身体、能在真实世界里行动"),
]


def _venue_zh(venue: str) -> str:
    if not venue:
        return ""
    s = venue.lower()
    if "arxiv" in s:
        return "arXiv 预印本"
    if "icassp" in s:
        return "声学与信号处理顶会 ICASSP"
    if "interspeech" in s:
        return "语音领域会议 Interspeech"
    if "acl" in s and "acl" in s:
        return "自然语言处理顶会 ACL"
    if "cvpr" in s:
        return "计算机视觉顶会 CVPR"
    if any(k in s for k in ("icml", "neurips", "iclr")):
        return f"机器学习顶会 {venue}"
    if "taslp" in s:
        return "音频领域期刊 IEEE TASLP"
    return venue


def _kw_match(kw: str, text: str) -> bool:
    """多词关键词用子串；单词用词边界前缀匹配，避免 pose↔propose、edge↔knowledge 之类误命中。"""
    if " " in kw:
        return kw in text
    return re.search(r"\b" + re.escape(kw), text) is not None


def _annotate(paper: Paper, focus: list[str]) -> Paper:
    """根据标题+摘要命中方向字典，生成中文标签与一句话看点。"""
    text = f"{paper.title} {paper.abstract}".lower()
    focus_low = [t.lower() for t in focus]

    seen_tags: dict[str, str] = {}  # 标签 -> 大白话
    explainers: list[str] = []
    for kw, tag, plain in _TOPIC_ZH:
        if _kw_match(kw, text) and tag not in seen_tags:
            seen_tags[tag] = plain
            explainers.append(plain)

    tags = list(seen_tags.keys())
    paper.tags = tags

    # 是否命中你的核心方向
    focus_hit = any(f in text for f in focus_low) or any(
        t for t in tags if t in ("语音增强", "波束形成", "多通道", "麦克风阵列",
                                 "目标说话人分离", "声音分离", "降噪", "语音识别", "语音合成", "唤醒词")
    )

    lead = "你的方向" if focus_hit else ""
    if tags:
        lead = (lead + " · " if lead else "") + "、".join(tags[:4])

    if explainers:
        plain = explainers[0]
        if len(explainers) > 1 and len(explainers[0]) + len(explainers[1]) < 40:
            plain = explainers[0] + "，" + explainers[1]
        hl = f"{lead}。简单说，{plain}。" if lead else f"简单说，{plain}。"
    else:
        hl = (lead + "。") if lead else "方向偏综合，建议点开标题看原文。"

    vz = _venue_zh(paper.venue)
    if vz:
        hl += f" 来源：{vz}。"
    paper.highlight = hl
    return paper


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
    tags: list[str] = field(default_factory=list)      # 中文方向标签
    highlight: str = ""                                 # 中文一句话看点


def _retry(func, *args, tries: int = 2, sleep: float = 2.0, **kwargs):
    last = None
    for i in range(tries):
        try:
            return func(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            last = exc
            if i < tries - 1:
                time.sleep(sleep * (i + 1))
    logger.warning("%s 重试 %d 次后仍失败: %s", getattr(func, "__name__", "fn"), tries, last)
    return None


# --------------------------- arXiv RSS ---------------------------
def _search_arxiv_rss(categories: list[str], days_back: int) -> list[Paper]:
    cutoff = date.today() - timedelta(days=days_back)
    papers: list[Paper] = []

    def _fetch_one(cat: str) -> list[Paper]:
        url = _ARXIV_RSS.format(cat=cat)
        resp = requests.get(url, headers={"User-Agent": _UA}, timeout=30)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        items = root.findall(".//item")
        out: list[Paper] = []
        for it in items:
            title = (it.findtext("title") or "").replace("\n", " ").strip()
            if not title:
                continue
            link = (it.findtext("link") or "").strip()
            # 发布日期
            pub = None
            pd = it.findtext("pubDate")
            if pd:
                try:
                    pub = parsedate_to_datetime(pd).date()
                except (ValueError, TypeError):
                    pub = None
            if pub and pub < cutoff:
                continue
            # 作者（可能多个 dc:creator）
            authors = [
                (c.text or "").strip()
                for c in it.findall("dc:creator", _NS)
                if (c.text or "").strip()
            ]
            # 摘要：description 形如 "arXiv:XXXXv1 Announce Type: new \n Abstract: ..."
            desc = it.findtext("description") or ""
            abstract = ""
            if "Abstract:" in desc:
                abstract = desc.split("Abstract:", 1)[1].strip()
            elif "abstract:" in desc.lower():
                abstract = desc.split("abstract:", 1)[1].strip()
            else:
                abstract = desc.strip()
            out.append(Paper(
                source="arxiv-rss", title=title, abstract=abstract, authors=authors,
                venue=cat, year=pub.year if pub else None, published=pub, url=link,
            ))
        return out

    for cat in categories:
        res = _retry(lambda: _fetch_one(cat), tries=2, sleep=2)
        if res:
            logger.info("arXiv RSS[%s] 抓得 %d 篇", cat, len(res))
            papers.extend(res)
        else:
            logger.warning("arXiv RSS[%s] 抓取失败", cat)
    return papers


# --------------------------- OpenAlex ---------------------------
def _oa_abstract(inv_index) -> str:
    if not inv_index:
        return ""
    try:
        length = max(max(idxs) for idxs in inv_index.values()) + 1
    except Exception:
        return ""
    words = [""] * length
    for word, positions in inv_index.items():
        for pos in positions:
            if 0 <= pos < length:
                words[pos] = word
    return " ".join(words).strip()


def _search_openalex(query: str, max_results: int, days_back: int) -> list[Paper]:
    cutoff = date.today() - timedelta(days=days_back)
    from_date = cutoff.strftime("%Y-%m-%d")

    def _call():
        params = {
            "search": query,
            "filter": f"from_publication_date:{from_date},has_abstract:true",
            "sort": "publication_date:desc",
            "per_page": min(max_results, 50),
            "mailto": "wk1924321@163.com",
        }
        resp = requests.get(_OPENALEX, params=params, headers={"User-Agent": _UA}, timeout=45)
        resp.raise_for_status()
        return resp.json()

    data = _retry(_call, tries=2, sleep=2)
    if not data:
        logger.warning("OpenAlex 查询失败")
        return []

    papers: list[Paper] = []
    for item in data.get("results", []) or []:
        title = (item.get("display_name") or "").strip()
        if not title:
            continue
        abstract = _oa_abstract(item.get("abstract_inverted_index"))
        pub = None
        pd = item.get("publication_date") or ""
        if pd:
            try:
                pub = datetime.strptime(pd[:10], "%Y-%m-%d").date()
            except ValueError:
                pub = None
        authors = [
            a.get("author", {}).get("display_name", "")
            for a in (item.get("authorships") or [])
            if a.get("author", {}).get("display_name")
        ][:8]
        venue = (item.get("primary_location", {}) or {}).get("source", {}) or {}
        venue_name = venue.get("display_name") or ""
        url = item.get("doi") or item.get("id") or ""
        if url and url.startswith("https://openalex.org"):
            url = ""
        papers.append(Paper(
            source="openalex", title=title, abstract=abstract, authors=authors,
            venue=venue_name, year=item.get("publication_year"), published=pub, url=url,
        ))
    return papers


# --------------------------- Semantic Scholar ---------------------------
def _search_s2(query: str, max_results: int) -> list[Paper]:
    def _call():
        params = {"query": query, "limit": min(max_results, 20),
                  "fields": "title,abstract,year,url,venue,authors"}
        resp = requests.get(_S2, params=params, headers={"User-Agent": _UA}, timeout=30)
        if resp.status_code == 429:
            time.sleep(3)
            resp = requests.get(_S2, params=params, headers={"User-Agent": _UA}, timeout=30)
        if resp.status_code != 200:
            logger.warning("Semantic Scholar 返回 %s", resp.status_code)
            return None
        return resp.json().get("data", []) or []

    data = _retry(_call, tries=2, sleep=2)
    if not data:
        return []
    papers: list[Paper] = []
    for p in data:
        t = (p.get("title") or "").strip()
        if not t:
            continue
        papers.append(Paper(
            source="semantic_scholar", title=t,
            abstract=(p.get("abstract") or "").strip(),
            authors=[a.get("name", "") for a in (p.get("authors") or [])],
            venue=p.get("venue") or "", year=p.get("year"), url=p.get("url") or "",
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
    categories = cfg.get("paper_categories") or ["cs.SD", "eess.AS", "eess.SP"]
    core = set(c for c in (cfg.get("core_categories") or []))
    kw = [t.lower() for t in (focus + frontier)]

    # 主源：arXiv RSS
    papers = _search_arxiv_rss(categories, days_back)
    src_order = ["arxiv-rss"]

    # 兜底：OpenAlex → Semantic Scholar
    if not papers:
        oa = _search_openalex(query, max_per, days_back)
        if oa:
            papers, src_order = oa, ["openalex"]
    if not papers:
        s2 = _search_s2(query, max_per)
        if s2:
            papers, src_order = s2, ["semantic_scholar"]

    if not papers:
        logger.warning("全部论文源均不可用，今日论文板块为空")
        return []

    logger.info("论文源命中: %s，原始 %d 篇", " → ".join(src_order), len(papers))

    # 相关性预筛：核心类目直接保留；其余类目仅保留命中关键词者
    if core:
        pre = [p for p in papers if p.venue in core]
        extra = [
            p for p in papers
            if p.venue not in core and any(k in f"{p.title} {p.abstract}".lower() for k in kw)
        ]
        pre += extra
        if len(pre) >= top_n:
            papers = pre

    # 去重
    seen, unique = set(), []
    for p in papers:
        key = p.title.strip().lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(p)

    ranked = sorted((_score(p, cfg) for p in unique), key=lambda x: x.score, reverse=True)
    top = ranked[:top_n]
    for p in top:
        _annotate(p, focus)
    return top
