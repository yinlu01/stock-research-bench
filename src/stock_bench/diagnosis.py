"""量化诊断：五维评分（趋势/动量/资金/财务质量/估值），纯规则、完全可解释。

每一维 0-100，综合分按权重合成。所有加减分都记录 reasons，页面可展示依据。
数据缺失的维度记 50（中性）并标注"数据缺失"。
"""


def _clamp(v: float) -> int:
    return int(max(0, min(100, round(v))))


def diagnose(ind: dict, bundle) -> dict:
    reasons: dict = {}

    # ---- 趋势（均线结构 + 位置）----
    c, ma = ind["close"], ind["ma"]
    t = 50.0
    tr = []
    if ma[20]:
        if c > ma[20]:
            t += 15; tr.append("站上20日线")
        else:
            t -= 15; tr.append("跌破20日线")
    if ma[20] and ma[60]:
        if ma[20] > ma[60]:
            t += 10; tr.append("20日线在60日线上方")
        else:
            t -= 10; tr.append("20日线在60日线下方")
    if ind["alignment"] == "多头排列":
        t += 15; tr.append("均线多头排列")
    elif ind["alignment"] == "空头排列":
        t -= 15; tr.append("均线空头排列")
    if ind["pos60_pct"] > 92:
        t -= 5; tr.append("60日区间高位")
    elif ind["pos60_pct"] < 8:
        t += 5; tr.append("60日区间低位")
    reasons["趋势"] = tr or ["结构中性"]

    # ---- 动量（MACD + RSI + 短期涨幅）----
    m = 50.0
    mr = []
    hist, hist_prev = ind["macd"]["hist"], ind["macd"]["hist_prev"]
    if hist > 0:
        m += 10; mr.append("MACD 红柱")
        if hist > hist_prev:
            m += 5; mr.append("红柱放大")
    else:
        m -= 10; mr.append("MACD 绿柱")
        if hist < hist_prev:
            m -= 5; mr.append("绿柱放大")
    rsi = ind["rsi14"]
    if rsi == rsi:  # not NaN
        if rsi > 78:
            m -= 5; mr.append(f"RSI {rsi} 超买")
        elif rsi < 22:
            m += 5; mr.append(f"RSI {rsi} 超卖")
        elif 50 <= rsi <= 70:
            m += 5; mr.append(f"RSI {rsi} 强势区")
        elif rsi < 40:
            m -= 5; mr.append(f"RSI {rsi} 偏弱")
    if ind["ret_5d"] is not None:
        m += max(-10, min(10, ind["ret_5d"]))
        mr.append(f"5日涨幅 {ind['ret_5d']}%")
    reasons["动量"] = mr

    # ---- 资金（近5日主力合计）----
    f = 50.0
    fr = []
    if bundle.fundflow:
        total = sum(x["main_yi"] for x in bundle.fundflow)
        f = 50 + max(-35, min(35, total * 10))
        fr.append(f"近5日主力净{'流入' if total >= 0 else '流出'} {abs(total):.1f} 亿")
        pos_days = sum(1 for x in bundle.fundflow if x["main_yi"] > 0)
        fr.append(f"{pos_days}/{len(bundle.fundflow)} 天净流入")
    else:
        fr.append("东财资金流本次不可用，按中性计")
    reasons["资金"] = fr

    # ---- 财务质量（ROE / 净利率 / 负债 / 最新同比）----
    q = 50.0
    qr = []
    fin = bundle.fin or {}
    quarters = fin.get("quarters") or []
    latest = fin.get("latest") or (quarters[-1] if quarters else {}) or {}
    if (fin.get("available", bool(quarters))) and latest:
        roe = latest.get("roe")
        if roe is not None:
            if roe >= 20:
                q += 25; qr.append(f"ROE {roe}% 优秀")
            elif roe >= 10:
                q += 15; qr.append(f"ROE {roe}% 良好")
            elif roe >= 5:
                q += 5; qr.append(f"ROE {roe}% 一般")
            else:
                q -= 10; qr.append(f"ROE {roe}% 偏低")
        nm = latest.get("net_margin")
        if nm is not None and nm >= 25:
            q += 10; qr.append(f"净利率 {nm}%")
        dr = latest.get("debt_ratio")
        if dr is not None:
            if dr < 40:
                q += 5; qr.append(f"负债率 {dr}% 低")
            elif dr > 70:
                q -= 10; qr.append(f"负债率 {dr}% 偏高")
        py = latest.get("profit_yoy")
        if py is not None:
            q += 5 if py > 0 else -5
            qr.append(f"最新单季净利同比 {py:+}%")
    else:
        qr.append("财报数据缺失，按中性计")
    reasons["财务质量"] = qr

    # ---- 估值（同业相对 → 否则绝对分档 + 股息）----
    v = 50.0
    vr = []
    peers = bundle.peers or {}
    pe_self = bundle.realtime.get("pe_ttm")
    peer_pes = [p["pe"] for p in peers.get("stocks", [])
                if p.get("pe") and p["pe"] > 0 and not p.get("is_self")]
    if pe_self and peer_pes:
        med = sorted(peer_pes)[len(peer_pes) // 2]
        diff = (pe_self / med - 1) * 100
        v = 50 - max(-30, min(30, diff))     # 比同业便宜 → 加分
        vr.append(f"PE {pe_self} vs 同业中位 {med:.1f}（{diff:+.0f}%）")
    elif pe_self:
        if pe_self < 15:
            v = 75; vr.append(f"PE {pe_self} 绝对低位区")
        elif pe_self < 25:
            v = 62; vr.append(f"PE {pe_self} 合理区")
        elif pe_self < 40:
            v = 48; vr.append(f"PE {pe_self} 偏高")
        else:
            v = 32; vr.append(f"PE {pe_self} 高估值区")
    else:
        vr.append("估值数据缺失，按中性计")
    from .sector import dividend_yield

    dy = dividend_yield((bundle.sector or {}).get("dividends", []), bundle.realtime.get("price"))
    if dy:
        v += min(10, dy * 2.5)
        vr.append(f"股息率约 {dy}%")
    reasons["估值"] = vr

    values = {
        "趋势": _clamp(t), "动量": _clamp(m), "资金": _clamp(f),
        "财务质量": _clamp(q), "估值": _clamp(v),
    }
    weights = {"趋势": 0.25, "动量": 0.20, "资金": 0.15, "财务质量": 0.25, "估值": 0.15}
    overall = _clamp(sum(values[k] * w for k, w in weights.items()))
    grade = ("强", "较强", "中性", "较弱", "弱")[
        0 if overall >= 75 else 1 if overall >= 60 else 2 if overall >= 45 else 3 if overall >= 30 else 4]
    return {"labels": list(values), "values": list(values.values()),
            "overall": overall, "grade": grade, "reasons": reasons,
            "weights": weights}
