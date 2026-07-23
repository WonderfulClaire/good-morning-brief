"""板块 2：科技新闻。

数据源（按可靠性串联）：
  1) IT之家 RSS（国内科技新闻站，中文、实时、稳定）→ 主源
  2) V2EX 热帖（中文技术社区）→ 兜底

每条产出：中文标题 + 一句话中文摘要 + 中文分类标签 + 链接。
参考了「阮一峰科技爱好者周刊」的写法——一句话把事说清，不堆术语。
"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)

_UA = "good-morning-brief/1.0"
_IT_HOME = "https://www.ithome.com/rss/"
_V2EX = "https://www.v2ex.com/api/topics/hot.json"

# 中文分类规则（按顺序匹配，命中即打标签）
_CAT_RULES = [
    ("芯片半导体", ["芯片", "半导体", "英伟达", "英特尔", "高通", "算力", "gpu", "晶圆", "光刻",
                 "台积电", "arm", "存储", "内存", "ai芯片", "处理器", "cpu"]),
    ("AI 大模型", ["ai", "大模型", "智能体", "agent", "生成式", "机器人", "gpt", "机器学习",
                "深度学习", "神经网络", "开源模型", "语音"]),
    ("手机数码", ["小米", "华为", "苹果", "iphone", "手机", "平板", "手表", "耳机", "荣耀",
                "oppo", "vivo", "三星", "耳机", "平板"]),
    ("汽车新能源", ["汽车", "新能源", "电动车", "特斯拉", "比亚迪", "自动驾驶", "蔚来", "理想",
                 "小鹏", "锂电", "续航"]),
    ("软件互联网", ["微信", "抖音", "互联网", "平台", "应用", "软件", "开源", "github", "腾讯",
                 "阿里", "字节", "百度", "插件", "更新"]),
    ("硬件外设", ["显示器", "键盘", "鼠标", "硬盘", "显卡", "主板", "电源", "路由器", "笔记本"]),
]


def _classify(text: str) -> str:
    t = text.lower()
    for name, kws in _CAT_RULES:
        if any(k in t for k in kws):
            return name
    return "科技"


def _strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html or "").strip()


def _clean_summary(desc: str) -> str:
    """IT之家描述形如『IT之家 7 月 23 日消息，xxx……』，去掉前缀、取首句。"""
    text = _strip_tags(desc)
    text = re.sub(r"^IT之家.{0,30}?消息[，,]", "", text).strip()
    # 取第一句（中文句号/感叹/问号切分）
    first = re.split(r"[。！？]", text)[0].strip()
    if not first:
        first = text[:60]
    return first[:90]


@dataclass
class NewsItem:
    title: str
    url: str
    summary: str = ""
    category: str = "科技"
    source: str = "ithome"


def _fetch_ithome(top_n: int) -> list[NewsItem]:
    try:
        r = requests.get(_IT_HOME, headers={"User-Agent": _UA}, timeout=25)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        items = root.findall(".//item")
    except Exception as exc:  # noqa: BLE001
        logger.warning("IT之家 RSS 抓取失败: %s", exc)
        return []

    out: list[NewsItem] = []
    for it in items:
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        if not title or not link:
            continue
        desc = it.findtext("description") or ""
        summary = _clean_summary(desc)
        out.append(NewsItem(
            title=title, url=link, summary=summary,
            category=_classify(title + " " + summary), source="ithome",
        ))
        if len(out) >= top_n:
            break
    logger.info("IT之家 抓得 %d 条", len(out))
    return out


def _fetch_v2ex(top_n: int) -> list[NewsItem]:
    try:
        d = requests.get(_V2EX, headers={"User-Agent": _UA}, timeout=20).json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("V2EX 抓取失败: %s", exc)
        return []
    tech_nodes = {
        "程序员", "技术", "Python", "Linux", "Apple", "云计算", "硬件", "机器学习",
        "人工智能", "Go", "Node.js", "前端", "后端", "数据库", "Android", "iOS", "宽带接入商",
    }
    out: list[NewsItem] = []
    for it in d:
        node = (it.get("node") or {}).get("title", "")
        if node not in tech_nodes:
            continue
        title = (it.get("title") or "").strip()
        if not title:
            continue
        link = "https://www.v2ex.com/t/" + str(it.get("id", ""))
        out.append(NewsItem(title=title, url=link, category="开发者社区", source="v2ex"))
        if len(out) >= top_n:
            break
    logger.info("V2EX 抓得 %d 条", len(out))
    return out


def fetch_news(cfg: dict) -> list[NewsItem]:
    top_n = int(cfg.get("top_n", 6))
    items = _fetch_ithome(top_n)
    if not items:
        logger.warning("IT之家无结果，回退 V2EX")
        items = _fetch_v2ex(top_n)
    return items[:top_n]
