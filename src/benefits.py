"""板块：大模型福利 / 新活动。

捕捉「大模型使用」相关的福利与活动：
  - 新模型发布 / 上线 / 公测 / 内测
  - 限时免费、免费额度、会员/Plus 体验
  - 开源权重、开放使用
  - 降价、免费延期、重置卡/赠送活动

数据源（免费、无需密钥）：
  1) IT之家 RSS（中文科技 / AI 新闻主源）
  2) Hacker News Algolia API（国际 LLM / 免费 / 新模型新闻，可检索）

说明：App 内推送的「重置卡」等偶发型福利可能无法被公开源捕捉，
     此类请以官方 App / 公众号公告为准（邮件 footer 已注明）。
"""
from __future__ import annotations

import email.utils
import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

_UA = "good-morning-brief/1.0"
_IT_HOME = "https://www.ithome.com/rss/"
_HN = "https://hn.algolia.com/api/v1/search_by_date"

# 大模型 / LLM 专属锚点词（命中才视为本板块主题）。
# 仅保留「大模型 / 聊天机器人 / 模型 API」相关词，避免手机 OTA、汽车 OTA、AI 卫星等蹭词噪声。
_AI_KW = [
    # 通用大模型概念
    "大模型", "大语言模型", "语言模型", "llm", "foundation model", "基座模型",
    "多模态大模型", "推理模型", "对话模型", "聊天机器人", "chatbot", "ai 助手", "ai助手",
    # 国际厂商 / 模型
    "gpt", "chatgpt", "openai", "claude", "anthropic", "gemini", "google ai",
    "llama", "mistral", "perplexity", "grok", "xai", "copilot", "cursor",
    "free tier", "free api", "open weights", "open-source model",
    # 国产厂商 / 模型
    "文心", "通义", "千问", "qwen", "kimi", "豆包", "智谱", "glm", "deepseek",
    "元宝", "百川", "讯飞星火", "月之暗面", "minimax", "阶跃", "混元", "abab",
    # 模型发布 / 开源 / 免费额度（即使没有品牌名也算命中）
    "新模型", "模型发布", "开源模型", "开源权重", "权重开放", "免费额度", "免费 api",
    "模型 api", "模型开放", "模型开源", "大模型发布",
]

# 硬件 / 设备类噪声词：命中即剔除（即使带了福利信号），避免手机/汽车/卫星等蹭 AI 的新闻混进来。
_EXCLUDE_KW = [
    "手机", "机型", "平板", "笔记本", "电脑", "汽车", "车型", "ota", "卫星", "火箭",
    "发射", "芯片", "处理器", "显卡", "内存", "固态", "主板", "固件", "系统升级",
    "推送更新", "耳机", "手表", "电视", "空调", "冰箱", "路由器", "数码", "家电",
    "机圈", "新机", "发布会", "预热", "真我", "小米", "vivo", "oppo", "荣耀",
    "iphone", "android", "鸿蒙", "ios",
]

# 福利 / 活动信号词，按类型分组（命中即打该类标签）。
# 注意：本板块聚焦「明确的福利 / 权限 / 大模型发布」信号，避免把普通产品上线也算进来。
_BENEFIT_GROUPS = {
    # 仅限大模型本身的发布/开源模型，避免「ChatGPT Health 上线」这类功能上线混入
    "新模型发布": ["新模型", "大模型发布", "开源模型", "基座模型", "多模态模型",
                "new model", "released model", "foundation model", "模型发布"],
    "免费/限时": ["免费", "限时", "限免", "0元", "白嫖", "免费用", "免费开放", "免费额度",
                "免费试用", "公测", "内测", "体验版", "体验", "限时免费", "开放使用",
                "free", "free tier", "free trial", "限时免费体验"],
    "福利/赠": ["福利", "赠送", "礼包", "优惠", "额度", "重置", "重置卡", "会员",
               "充值", "赠", "打折", "券", "卡", "礼遇", "回馈", "送", "免费送",
               "送额度", "体验卡"],
    "降价/延期": ["降价", "延期", "延长", "取消收费", "cheaper", "免费延期",
                "限时降价", "延长期", "费用调整"],
    "开源": ["开源", "open source", "权重开放", "开源权重", "开放权重", "open weights"],
}

# HN 定向检索词（偏向「福利 / 新模型 / 免费」角度）
_HN_QUERIES = [
    "OpenAI GPT free",
    "Claude free tier",
    "LLM API free",
    "open source model released",
    "Gemini free",
    "Mistral free",
    "DeepSeek free",
    "Qwen open source",
    "Kimi free",
    "Perplexity free",
    "GPT reset",
    "Anthropic free",
    "new AI model released",
    "free API credits",
]


@dataclass
class BenefitItem:
    title: str
    url: str
    summary: str = ""
    benefit_type: str = "活动"
    source: str = ""
    published: str = ""
    age_days: float = 999.0


_KW_CACHE: dict[str, re.Pattern | None] = {}


def _compile(kw: str):
    """英文关键词按「词边界（排除连字符相邻）」编译，避免 free→freeze 误伤；
    中文关键词返回 None，改用子串匹配。"""
    if kw in _KW_CACHE:
        return _KW_CACHE[kw]
    if kw.isascii():
        pat = re.compile(r"(?<![a-z0-9-])" + re.escape(kw) + r"(?![a-z0-9-])")
    else:
        pat = None
    _KW_CACHE[kw] = pat
    return pat


def _has_kw(text_lower: str, kw: str) -> bool:
    if kw.isascii():
        pat = _compile(kw)
        assert pat is not None
        return bool(pat.search(text_lower))
    return kw in text_lower


def _ai_hits(text: str) -> int:
    t = text.lower()
    return sum(1 for k in _AI_KW if _has_kw(t, k))


def _has_exclude(text: str) -> bool:
    """命中硬件/设备黑名单（如手机 OTA、汽车 OTA、卫星发射）则视为噪声。"""
    t = text.lower()
    return any(k in t for k in _EXCLUDE_KW)


def _benefit_hits(text: str):
    """返回 (总命中数, 主要类型标签)。"""
    t = text.lower()
    total = 0
    best_group = None
    best_count = 0
    for group, kws in _BENEFIT_GROUPS.items():
        c = sum(1 for k in kws if _has_kw(t, k))
        total += c
        if c > best_count:
            best_count = c
            best_group = group
    return total, (best_group or "活动")


def _strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html or "").strip()


def _clean_summary(desc: str) -> str:
    text = _strip_tags(desc)
    text = re.sub(r"^IT之家.{0,30}?消息[，,]", "", text).strip()
    first = re.split(r"[。！？]", text)[0].strip()
    if not first:
        first = text[:60]
    return first[:90]


def _age_from_pubdate(pub: str) -> tuple[float, str]:
    """返回 (距今天数, 日期字符串 YYYY-MM-DD)。解析失败则 (999.0, '')。"""
    if not pub:
        return 999.0, ""
    dt = email.utils.parsedate_to_datetime(pub)
    if dt is None:
        return 999.0, ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0
    return age, dt.strftime("%Y-%m-%d")


def _fetch_ithome(limit: int, max_age_days: int) -> list[BenefitItem]:
    try:
        r = requests.get(_IT_HOME, headers={"User-Agent": _UA}, timeout=25)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        items = root.findall(".//item")
    except Exception as exc:  # noqa: BLE001
        logger.warning("IT之家 RSS 抓取失败: %s", exc)
        return []
    out: list[BenefitItem] = []
    for it in items:
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        if not title or not link:
            continue
        desc = it.findtext("description") or ""
        blob = title + " " + desc
        if _has_exclude(title):
            continue
        if _ai_hits(blob) == 0 or _benefit_hits(blob)[0] == 0:
            continue
        age, published = _age_from_pubdate(it.findtext("pubDate") or "")
        if age > max_age_days:
            continue
        _, btype = _benefit_hits(blob)
        out.append(BenefitItem(
            title=title, url=link, summary=_clean_summary(desc),
            benefit_type=btype, source="IT之家", published=published, age_days=age,
        ))
        if len(out) >= limit * 3:
            break
    logger.info("IT之家 命中 %d 条候选", len(out))
    return out


def _fetch_hn(limit: int, max_age_days: int, queries) -> list[BenefitItem]:
    cutoff = int(time.time()) - int(max_age_days * 86400)
    seen: set[tuple[str, str]] = set()
    out: list[BenefitItem] = []
    for q in queries:
        try:
            params = {
                "query": q,
                "tags": "story",
                "numericFilters": f"created_at_i>{cutoff}",
                "hitsPerPage": 15,
            }
            d = requests.get(_HN, params=params, headers={"User-Agent": _UA}, timeout=20).json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("HN 检索失败 (%s): %s", q, exc)
            continue
        for h in d.get("hits", []):
            title = (h.get("title") or h.get("story_title") or "").strip()
            link = h.get("url") or h.get("story_url") or ""
            if not title or not link:
                continue
            if _has_exclude(title):
                continue
            if _ai_hits(title) == 0 or _benefit_hits(title)[0] == 0:
                continue
            key = (title, link)
            if key in seen:
                continue
            seen.add(key)
            ci = h.get("created_at_i")
            if ci:
                published = datetime.utcfromtimestamp(ci).strftime("%Y-%m-%d")
                age = (time.time() - ci) / 86400.0
            else:
                published, age = "", 999.0
            if age > max_age_days:
                continue
            _, btype = _benefit_hits(title)
            out.append(BenefitItem(
                title=title, url=link, summary="", benefit_type=btype,
                source="Hacker News", published=published, age_days=age,
            ))
            if len(out) >= limit * 3:
                break
    logger.info("HN 命中 %d 条候选", len(out))
    return out


def fetch_benefits(cfg: dict) -> list[BenefitItem]:
    top_n = int(cfg.get("top_n", 5))
    max_age_days = int(cfg.get("max_age_days", 14))
    enabled_sources = cfg.get("sources", ["ithome", "hn"])
    candidates: list[BenefitItem] = []
    if "ithome" in enabled_sources:
        candidates += _fetch_ithome(top_n, max_age_days)
    if "hn" in enabled_sources:
        candidates += _fetch_hn(top_n, max_age_days, _HN_QUERIES)

    # 去重（同链接或高度相似标题）
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    deduped: list[BenefitItem] = []
    for b in candidates:
        norm = re.sub(r"\s+", "", b.title.lower())
        if b.url in seen_urls or norm in seen_titles:
            continue
        seen_urls.add(b.url)
        seen_titles.add(norm)
        deduped.append(b)

    # 打分：福利信号强度 + 时效（越新越高）
    def score(b: BenefitItem) -> float:
        blob = b.title + " " + b.summary
        benefit_total, _ = _benefit_hits(blob)
        recency = max(0.0, 1.0 - b.age_days / max_age_days)
        return benefit_total * 2.0 + recency * 1.5

    deduped.sort(key=score, reverse=True)
    return deduped[:top_n]
