"""板块 3 的增值部分：加仓建议。

完全基于基金自身净值序列（来自 funds.py 已抓取的 navs）做数据分析，
不依赖任何外部检索，因此在 CI / 定时任务里稳定可跑：

  - 近 1 周 / 1 月 / 1 年收益（相对净值序列回溯）
  - 当前净值在「近 60 个净值日」区间所处的分位（偏低=便宜，偏高=贵）
  - 与 20 日 / 60 日均线的位置关系（趋势强弱）
  - 若标记为 QDII（fx=true），best-effort 抓取 USD/CNY 作为汇率提示

最终产出一句「分析 + 今天该多买 / 持有 / 减仓」的结论。
所有结论均为规则化生成，仅供参考、不构成投资建议。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import requests

logger = logging.getLogger(__name__)

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# 情绪/动作分档（仅供前端染色，不与涨跌幅红绿混淆）
LEVEL_BUY = "buy"      # 加仓 / 逢低加仓
LEVEL_HOLD = "hold"   # 持有 / 继续定投
LEVEL_WARN = "warn"   # 观望 / 不宜追高 / 减仓


@dataclass
class FundAdvice:
    ok: bool = False
    verdict: str = ""            # 简短动作：逢低加仓 / 继续定投 / 建议观望 ...
    verdict_label: str = ""      # 带图标的 chip 文案
    level: str = LEVEL_HOLD      # buy / hold / warn（前端染色）
    ret_1w: float | None = None
    ret_1m: float | None = None
    ret_1y: float | None = None
    pctile_60: float | None = None   # 当前净值在近60日区间的分位(0-100)
    ma_signal: str = ""         # above / below / neutral
    text: str = ""
    fx_note: str = ""


def _ret_at(navs: list[float], offset: int) -> float | None:
    """相对当前回溯 offset 个净值日（约 offset 个交易日）的累计收益%。"""
    n = len(navs)
    if n < 2:
        return None
    idx = max(0, n - 1 - offset)
    base = navs[idx]
    if not base:
        return None
    return round((navs[-1] / base - 1) * 100, 2)


def _fetch_usdcny() -> float | None:
    """best-effort：抓 USD/CNY 即期，失败返回 None。"""
    try:
        r = requests.get("https://open.er-api.com/v6/latest/USD",
                         headers={"User-Agent": _UA}, timeout=8)
        rate = r.json().get("rates", {}).get("CNY")
        if rate:
            return round(float(rate), 4)
    except Exception as exc:  # noqa: BLE001
        logger.warning("USD/CNY 抓取失败（不影响其余分析）: %s", exc)
    return None


def build_advice(f) -> FundAdvice:
    """根据 FundQuote 生成加仓建议。f 应已带 navs / benchmark / fx。"""
    navs = getattr(f, "navs", None) or []
    if not getattr(f, "ok", False) or len(navs) < 6:
        return FundAdvice(ok=False, verdict="数据不足", verdict_label="⚠️ 数据不足",
                          level=LEVEL_WARN,
                          text="净值数据不足，暂无法给出加仓建议；可查看上方净值与涨跌。")

    ret_1w = _ret_at(navs, 5)
    ret_1m = _ret_at(navs, 21)
    ret_1y = _ret_at(navs, 252)

    # 近 1 月（约 30 个净值日，不足则取全部历史）区间分位，刻画“相对近期中枢”高低
    win = navs[-30:] if len(navs) >= 30 else navs
    lo, hi = min(win), max(win)
    pctile = round((navs[-1] - lo) / (hi - lo) * 100, 1) if hi > lo else 50.0

    # 均线位置
    ma20 = sum(navs[-20:]) / min(len(navs), 20)
    ma60 = sum(navs[-60:]) / min(len(navs), 60)
    vs_ma60 = round((navs[-1] / ma60 - 1) * 100, 2) if ma60 else 0.0
    if navs[-1] >= ma20:
        ma_signal, ma_txt = "above", "站上20日线"
    else:
        ma_signal, ma_txt = "below", "跌破20日线"

    benchmark = getattr(f, "benchmark", "") or "对应指数"
    fx_note = ""
    if getattr(f, "fx", False):
        cny = _fetch_usdcny()
        if cny is not None:
            if cny < 6.85:
                fx_note = f"汇率方面人民币偏强（USD/CNY≈{cny}），对 QDII 收益有小幅拖累。"
            elif cny > 6.90:
                fx_note = f"汇率方面人民币偏弱（USD/CNY≈{cny}），对 QDII 收益略有增厚。"
            else:
                fx_note = f"汇率方面 USD/CNY≈{cny}，人民币中性，对 QDII 收益影响有限。"

    # —— 规则化结论 ——
    # 用「相对60日中枢的偏离」衡量贵贱更稳健（比单纯 min-max 分位更平滑）：
    #   vs_ma60 明显为负（低于中枢）→ 便宜，适合逢低布局；明显为正 → 偏贵。
    cheap = vs_ma60 <= -3.0          # 低于60日中枢 3% 以上
    expensive = vs_ma60 >= 4.0       # 高于60日中枢 4% 以上
    drawdown = ret_1m is not None and ret_1m <= -3.0   # 近1月明显回撤
    up_1m = ret_1m is not None and ret_1m >= 5.0
    parabolic = pctile > 85 and ret_1m is not None and ret_1m > 8

    if parabolic:
        verdict, label, level = "可考虑减仓", "🔻 可考虑减仓", LEVEL_WARN
        reason = "短期涨幅过大、已处历史高位，追高性价比低，宜分批止盈。"
    elif (cheap or drawdown) and not expensive:
        verdict, label, level = "逢低加仓", "✅ 建议逢低加仓", LEVEL_BUY
        reason = "近期回调且低于近期中枢，是定投/加仓的好窗口，忌单笔重仓。"
    elif pctile <= 35 or vs_ma60 < 0:
        verdict, label, level = "可小幅加仓", "🟢 可小幅加仓", LEVEL_BUY
        reason = "净值处近期偏低位置，安全边际较高，可逢回调小幅加仓。"
    elif expensive or (up_1m and pctile > 55):
        verdict, label, level = "建议观望", "⚠️ 建议观望", LEVEL_WARN
        reason = "净值已处近期高位，短期追高性价比有限，宜等回调再布局。"
    else:
        verdict, label, level = "继续定投", "➡️ 继续持有 / 定投", LEVEL_HOLD
        reason = "净值处于近期中枢，趋势平稳，维持原有定投节奏即可。"

    pos_word = ("偏低" if (cheap or pctile <= 35) else "偏高" if expensive else "适中")
    ret_1m_s = f"{ret_1m:+.2f}%" if ret_1m is not None else "—"
    ret_1y_s = f"{ret_1y:+.2f}%" if ret_1y is not None else "—"

    text = (f"对应{benchmark}近1月 {ret_1m_s}、近1年 {ret_1y_s}；"
            f"当前净值处近1月约 {pctile:.0f}% 分位（{pos_word}），{ma_txt}。"
            f"{fx_note}{reason}")

    return FundAdvice(
        ok=True, verdict=verdict, verdict_label=label, level=level,
        ret_1w=ret_1w, ret_1m=ret_1m, ret_1y=ret_1y,
        pctile_60=pctile, ma_signal=ma_signal, text=text, fx_note=fx_note,
    )


def build_opportunity(f, reason: str = "") -> FundAdvice:
    """「新机会」互补基金的轻量建议（与持仓的加仓建议逻辑解耦）。

    机会基金多为黄金/红利/债券等底仓型资产，不适合用「分位高低」判断买卖，
    因此只基于近1月涨跌给一个温和的建仓提示：
      - 近1月明显回调 → 回调可吸纳
      - 近1月大涨（如黄金） → 已涨较多，谨慎追
      - 其余 → 可分批建仓（长期底仓）
    结论仅供参考、不构成投资建议。
    """
    navs = getattr(f, "navs", None) or []
    if not getattr(f, "ok", False) or len(navs) < 6:
        return FundAdvice(ok=False, verdict="数据不足", verdict_label="⚠️ 数据不足",
                          level=LEVEL_WARN, text="净值数据不足，暂无法展示。")
    ret_1m = _ret_at(navs, 21)
    ret_1y = _ret_at(navs, 252)
    r1m = ret_1m if ret_1m is not None else 0.0

    if r1m <= -3.0:
        verdict, label, level = "回调可吸纳", "🟢 回调可吸纳", LEVEL_BUY
    elif r1m >= 8.0:
        verdict, label, level = "已涨较多·谨慎追", "⚠️ 已涨较多", LEVEL_WARN
    else:
        verdict, label, level = "可分批建仓", "🔵 可分批建仓", LEVEL_HOLD

    ret_1m_s = f"{ret_1m:+.2f}%" if ret_1m is not None else "—"
    ret_1y_s = f"{ret_1y:+.2f}%" if ret_1y is not None else "—"
    text = (f"近1月 {ret_1m_s}、近1年 {ret_1y_s}；{reason}"
            f"（与现有持仓互补，可作为底仓、分批建仓平滑组合波动）。")
    return FundAdvice(
        ok=True, verdict=verdict, verdict_label=label, level=level,
        ret_1m=ret_1m, ret_1y=ret_1y, text=text,
    )
