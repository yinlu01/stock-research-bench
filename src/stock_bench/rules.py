"""规则引擎：两种用途。

1. 没有 LLM Key 时的降级分析（数据模式照常出完整研报）
2. 风控节点里做确定性的红线检查（不管模型说什么，红线不过就打回）
"""

import re

NEG_KW = ["减持", "立案", "处罚", "警示", "商誉减值", "业绩预减", "业绩预亏", "下修",
          "终止", "违约", "质押", "诉讼", "下调", "亏损", "停牌"]
POS_KW = ["增长", "中标", "回购", "增持", "提价", "预增", "超预期", "签约", "分红"]

ACTIONS = [
    (70, "偏多", "趋势与资金面共振，可关注回调后的布局机会"),
    (55, "中性偏多", "结构尚可，持有观察，等待量能确认"),
    (45, "中性", "多空信号交织，建议观望等待方向明确"),
    (30, "中性偏空", "趋势走弱或资金流出，谨慎参与"),
    (0, "偏空", "多项信号告警，建议回避或降低仓位"),
]


def _keyword_scan(texts: list[str]) -> tuple[int, list[str], list[str]]:
    neg_hits, pos_hits = [], []
    for t in texts:
        for kw in NEG_KW:
            if kw in t:
                neg_hits.append(f"{kw}（{t[:30]}）")
        for kw in POS_KW:
            if kw in t:
                pos_hits.append(f"{kw}（{t[:30]}）")
    score = max(-12, -6 * len(neg_hits)) + min(8, 4 * len(pos_hits))
    return score, neg_hits[:5], pos_hits[:5]


def scorecard(bundle, ind: dict) -> dict:
    """输出 {score, action, stance, confidence, drivers, risks}"""
    score, drivers, risks = 50.0, [], []
    c, ma, m = ind["close"], ind["ma"], ind["macd"]

    # 趋势
    if ma[20] and c > ma[20]:
        score += 8; drivers.append("股价站上20日线")
    elif ma[20]:
        score -= 8; risks.append("股价跌破20日线")
    if ind["alignment"] == "多头排列":
        score += 7; drivers.append("均线多头排列")
    elif ind["alignment"] == "空头排列":
        score -= 7; risks.append("均线空头排列")

    # 动量
    if m["hist"] > 0 and m["hist"] > m["hist_prev"]:
        score += 6; drivers.append("MACD 红柱放大")
    elif m["hist"] > 0:
        score += 3
    elif m["hist"] < 0 and m["hist"] < m["hist_prev"]:
        score -= 6; risks.append("MACD 绿柱放大")
    elif m["hist"] < 0:
        score -= 3
    if ind["rsi14"] == ind["rsi14"]:   # not NaN
        if ind["rsi14"] > 78:
            score -= 4; risks.append(f"RSI {ind['rsi14']} 超买")
        elif ind["rsi14"] < 22:
            score += 4; drivers.append(f"RSI {ind['rsi14']} 超卖")

    # 量能配合
    vr, ret5 = ind["vol_vs_ma5"], ind["ret_5d"]
    if vr and ret5 is not None:
        if vr > 1.5 and ret5 > 0:
            score += 4; drivers.append("放量上行")
        elif vr > 1.5 and ret5 < 0:
            score -= 5; risks.append("放量下跌，疑似出货")

    # 资金流（近5日主力合计）
    if bundle.fundflow:
        total = round(sum(f["main_yi"] for f in bundle.fundflow), 2)
        if total > 1:
            score += 8; drivers.append(f"近5日主力净流入 {total} 亿")
        elif total < -1:
            score -= 8; risks.append(f"近5日主力净流出 {abs(total)} 亿")

    # 位置
    if ind["pos60_pct"] > 92:
        score -= 4; risks.append("处于60日区间高位，追高风险")
    elif ind["pos60_pct"] < 8:
        score += 2

    # 舆情/公告关键词
    texts = [a["title"] for a in (bundle.announcements or [])] + bundle.news_hits
    kw_score, neg_hits, pos_hits = _keyword_scan(texts)
    score += kw_score
    risks += [f"舆情提示：{h}" for h in neg_hits[:3]]
    drivers += [f"舆情提示：{h}" for h in pos_hits[:2]]

    score = max(0.0, min(100.0, score))
    stance, action = "中性", ACTIONS[-1][1] + "：" + ACTIONS[-1][2]
    for th, st, act in ACTIONS:
        if score >= th:
            stance, action = st, act
            break
    return {
        "score": round(score, 1),
        "stance": stance,
        "action": action,
        "confidence": int(min(85, 40 + abs(score - 50) * 1.6)),
        "drivers": drivers,
        "risks": risks,
        "neg_hits": neg_hits,
        "pos_hits": pos_hits,
    }


RISK_RED_LINES = [
    (r"(满仓|全仓|重仓买入)", "出现满仓/重仓类表述，必须降为仓位建议（单票≤30%）并给出止损条件"),
    (r"必涨|稳赚|保证收益|一定会涨", "出现收益承诺类表述，必须删除并改为概率化措辞"),
    (r"不设止损", "缺少止损安排，必须给出明确、可观测的止损条件"),
]


def red_line_check(text: str) -> list[str]:
    return [why for pat, why in RISK_RED_LINES if re.search(pat, text)]
