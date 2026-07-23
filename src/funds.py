"""板块 3：基金涨跌。

数据源：天天基金 pingzhongdata 公开接口
    https://fund.eastmoney.com/pingzhongdata/{code}.js
从中解析基金名称与历史净值序列 Data_netWorthTrend，
取最新一日的单位净值与当日涨跌幅（equityReturn 字段）。
实时估值接口 fundgz 已失效，改用净值序列（T-1 收盘净值，稳定可靠）。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

import requests

logger = logging.getLogger(__name__)

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
_BASE = "https://fund.eastmoney.com/pingzhongdata/{code}.js"


@dataclass
class FundQuote:
    code: str
    name: str
    alias: str = ""
    nav: float | None = None            # 最新单位净值
    nav_date: str = ""                  # 净值日期
    change_pct: float | None = None     # 当日涨跌幅 %
    prev_nav: float | None = None
    recent_5d_pct: float | None = None  # 近5个净值日累计涨跌 %
    ok: bool = False
    error: str = ""
    dip_alert: bool = False
    trend: list[float] = field(default_factory=list)  # 近若干日净值，用于迷你走势


def _ts_to_date(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def fetch_fund(code: str, alias: str = "", dip_alert_pct: float = 1.0) -> FundQuote:
    q = FundQuote(code=code, name=alias or code, alias=alias)
    try:
        r = requests.get(
            _BASE.format(code=code),
            headers={"User-Agent": _UA, "Referer": "https://fund.eastmoney.com/"},
            timeout=20,
        )
        r.encoding = "utf-8"
        text = r.text
        if not text or "Data_netWorthTrend" not in text:
            q.error = "接口无净值数据"
            return q

        m_name = re.search(r'fS_name\s*=\s*"([^"]+)"', text)
        if m_name:
            q.name = m_name.group(1)

        m_trend = re.search(r"Data_netWorthTrend\s*=\s*(\[.*?\]);", text)
        if not m_trend:
            q.error = "未找到净值序列"
            return q
        arr = json.loads(m_trend.group(1))
        if not arr:
            q.error = "净值序列为空"
            return q

        last = arr[-1]
        q.nav = round(float(last["y"]), 4)
        q.nav_date = _ts_to_date(int(last["x"]))
        er = last.get("equityReturn")
        q.change_pct = round(float(er), 2) if er is not None else None
        if len(arr) >= 2:
            q.prev_nav = round(float(arr[-2]["y"]), 4)
        # 近 5 个净值日累计涨跌
        if len(arr) >= 6:
            base = float(arr[-6]["y"])
            if base:
                q.recent_5d_pct = round((q.nav - base) / base * 100, 2)
        q.trend = [round(float(x["y"]), 4) for x in arr[-15:]]

        if q.change_pct is not None and q.change_pct <= -abs(dip_alert_pct):
            q.dip_alert = True
        q.ok = True
    except Exception as exc:  # noqa: BLE001
        q.error = str(exc)
        logger.warning("基金 %s 抓取失败: %s", code, exc)
    return q


def fetch_funds(cfg: dict) -> list[FundQuote]:
    holdings = cfg.get("holdings", []) or []
    dip = float(cfg.get("dip_alert_pct", 1.0))
    out: list[FundQuote] = []
    for h in holdings:
        code = str(h.get("code", "")).strip()
        if not code:
            continue
        out.append(fetch_fund(code, alias=h.get("alias", ""), dip_alert_pct=dip))
    return out
