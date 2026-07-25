"""板块 4：Xmart 每日一讲。

来源：上海交大 X-LANCE 实验室的「Xmart青年论坛」归档仓库（X-LANCE/Xmart），
存放历届学生论坛与前沿讲座的视频回放和讲义 PDF。

逻辑：
  - 抓取仓库 README 中「往期学生论坛回放」「往期前沿讲座回放」两张表；
  - 合并全部场次，按下标 = 当年第几天(Asia/Shanghai) % 总场次 取一场，
    实现每天自动轮换、稳定覆盖全部、无需外部记忆；
  - 用 GitHub commits API 取仓库最近一次 commit 日期，作为「仓库最近更新」。
数据全部来自公开仓库，无需密钥；任一环节失败都安全降级为 None。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

logger = logging.getLogger(__name__)

_UA = "good-morning-brief/1.0 (mailto:wk1924321@163.com)"


@dataclass
class XmartTalk:
    kind: str                  # "学生论坛" / "前沿讲座"
    issue: str = ""            # "第二十期"
    date: str = ""             # "2026/03/25"
    speaker: str = ""
    title: str = ""
    duration: str = ""
    video_url: str = ""
    slides_url: str | None = None
    repo_updated: str | None = None
    why: str = ""              # 一句话「为什么值得看」


# 与 Claire 研究方向（多通道语音增强 / 音频 AI / 申博）的关联映射
_RELEVANCE = [
    ("语音分离", "贴合你的多通道语音分离 / 语音增强方向"),
    ("speech separation", "贴合你的多通道语音分离 / 语音增强方向"),
    ("语音增强", "直接对口你的核心研究方向：语音增强"),
    ("speech enhancement", "直接对口你的核心研究方向：语音增强"),
    ("波束形成", "和你的麦克风阵列 / 波束形成强相关"),
    ("beamform", "和你的麦克风阵列 / 波束形成强相关"),
    ("麦克风阵列", "和你的阵列信号处理基础直接相关"),
    ("microphone-array", "和你的阵列信号处理基础直接相关"),
    ("语音合成", "与语音合成 / 生成方向相关，可作研究灵感"),
    ("text-to-speech", "与语音合成 / 生成方向相关，可作研究灵感"),
    ("tts", "与语音合成 / 生成方向相关，可作研究灵感"),
    ("音频大模型", "音频大模型前沿，紧跟你的赛道"),
    ("audio foundation", "音频大模型前沿，紧跟你的赛道"),
    ("音频", "音频 AI 方向，值得跟进"),
    ("audio", "音频 AI 方向，值得跟进"),
    ("音乐生成", "音乐生成方向，扩展音频生成视野"),
    ("music", "音乐生成方向，扩展音频生成视野"),
    ("大模型", "大语言模型 / 基础模型前沿"),
    ("llm", "大语言模型 / 基础模型前沿"),
    ("检索增强", "检索增强生成（RAG）相关"),
    ("rag", "检索增强生成（RAG）相关"),
    ("智能体", "AI 智能体方向，跨领域启发"),
    ("agent", "AI 智能体方向，跨领域启发"),
    ("多模态", "多模态方向，贴合语音+视觉交叉"),
    ("multimodal", "多模态方向，贴合语音+视觉交叉"),
    ("具身智能", "具身智能前沿，拓宽研究视野"),
    ("embodied", "具身智能前沿，拓宽研究视野"),
    ("长思维链", "推理 / 长思维链，和你的建模思路相关"),
    ("推理", "推理方向，和你的建模思路相关"),
]


def _extract_url(cell: str) -> str | None:
    m = re.search(r"\]\((https?://[^)\s]+)\)", cell)
    return m.group(1) if m else None


def _slice_section(text: str, heading: str) -> str:
    """返回某二级标题到下一个二级标题之间的文本。"""
    lines = text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if ln.strip().startswith("##") and heading in ln:
            start = i
            break
    if start is None:
        return ""
    for j in range(start + 1, len(lines)):
        if lines[j].strip().startswith("##") and j > start:
            return "\n".join(lines[start + 1:j])
    return "\n".join(lines[start + 1:])


def _parse_tables(text: str) -> list[XmartTalk]:
    """扫描 README，提取两张讲座表。"""
    talks: list[XmartTalk] = []

    sections = {
        "学生论坛": _slice_section(text, "往期学生论坛回放"),
        "前沿讲座": _slice_section(text, "往期前沿讲座回放"),
    }

    for kind, sec in sections.items():
        if not sec:
            continue
        for line in sec.splitlines():
            line = line.strip()
            if not line.startswith("|"):
                continue
            # 跳过表头与分隔行
            if "日期" in line or set(line) <= set("|-: "):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) < 6:
                continue
            date_cell, speaker, title, duration, video_cell, slides_cell = cells[:6]
            if not title:
                continue
            issue_m = re.search(r"第\s*([一二三四五六七八九十百\d]+)\s*期", date_cell)
            issue = f"第{issue_m.group(1)}期" if issue_m else ""
            date_m = re.search(r"\d{4}[/-]\d{1,2}[/-]\d{1,2}", date_cell)
            date = date_m.group(0) if date_m else ""
            talks.append(XmartTalk(
                kind=kind,
                issue=issue,
                date=date,
                speaker=speaker,
                title=title,
                duration=duration,
                video_url=_extract_url(video_cell) or "",
                slides_url=_extract_url(slides_cell),
            ))
    return talks


def _repo_updated(repo: str) -> str | None:
    try:
        url = f"https://api.github.com/repos/{repo}/commits?per_page=1"
        r = requests.get(url, headers={"User-Agent": _UA}, timeout=20)
        if not r.ok:
            return None
        data = r.json()
        if not data:
            return None
        d = (data[0].get("commit", {}).get("committer", {}).get("date")
             or data[0].get("commit", {}).get("author", {}).get("date"))
        return d[:10] if d else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Xmart 取仓库更新失败（不影响主流程）: %s", exc)
        return None


def _annotate(talk: XmartTalk) -> XmartTalk:
    text = f"{talk.title} {talk.speaker}".lower()
    hits = [note for kw, note in _RELEVANCE if kw.lower() in text]
    if hits:
        # 去重并保持顺序
        seen = []
        for h in hits:
            if h not in seen:
                seen.append(h)
        talk.why = "为什么看：" + "；".join(seen) + "。"
    else:
        talk.why = "作为日常研究补给，碎片时间过一遍也很有收获。"
    return talk


def fetch_xmart(cfg: dict) -> XmartTalk | None:
    cfg = cfg or {}
    if not cfg.get("enabled", True):
        return None
    repo = cfg.get("repo", "X-LANCE/Xmart")
    branch = cfg.get("branch", "main")
    try:
        url = f"https://raw.githubusercontent.com/{repo}/{branch}/README.md"
        r = requests.get(url, headers={"User-Agent": _UA}, timeout=30)
        r.raise_for_status()
        talks = _parse_tables(r.text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Xmart README 抓取/解析失败: %s", exc)
        return None

    if not talks:
        logger.warning("Xmart 未解析到任何场次")
        return None

    try:
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        doy = now.timetuple().tm_yday
        talk = talks[doy % len(talks)]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Xmart 选场失败，回退到第一场: %s", exc)
        talk = talks[0]

    talk.repo_updated = _repo_updated(repo)
    return _annotate(talk)
