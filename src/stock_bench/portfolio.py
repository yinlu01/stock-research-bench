"""持仓与组合级风险（PRD §3.1 S3 分析层 B，纯本地计算）。"""

import re


def parse_price(text: str | None, cur: float) -> float | None:
    """从文本里提第一个合理价位（0.2×~5× 现价），与前端正则同口径。"""
    if not text or not cur:
        return None
    for tok in re.findall(r"\d+(?:\.\d+)?", text):
        v = float(tok)
        if cur * 0.2 < v < cur * 5:
            return v
    return None


def build_portfolio(states: dict, holdings: list) -> dict | None:
    rows, skipped = [], []
    for h in holdings:
        st = states.get(h["code"])
        if not st:
            skipped.append(h["code"])
            continue
        b = st["bundle"]
        price = b.realtime.get("price")
        if not price:
            skipped.append(h["code"])
            continue
        cost = h.get("cost_price") or 0
        shares = h.get("shares") or 0
        mv = price * shares
        d = st["decision"]
        stop = (d.get("levels") or {}).get("stop")
        if stop is None:
            stop = parse_price(d.get("stop_loss"), price)
        rows.append({
            "code": h["code"], "name": b.name,
            "shares": shares, "cost": cost, "price": price,
            "mv": round(mv, 0),
            "pnl_pct": round((price / cost - 1) * 100, 1) if cost else None,
            "day_pct": b.realtime.get("change_pct"),
            "industry": (b.sector or {}).get("industry") or "未知",
            "stance": d.get("stance"), "action": d.get("action"),
            "stop": stop,
            "stop_dist": round((stop / price - 1) * 100, 1) if stop else None,
        })

    if not rows:
        return None

    total = sum(r["mv"] for r in rows) or 1
    for r in rows:
        r["weight_pct"] = round(r["mv"] / total * 100, 1)

    ind_w: dict = {}
    for r in rows:
        ind_w[r["industry"]] = ind_w.get(r["industry"], 0) + r["weight_pct"]
    weights = [{"name": k, "pct": round(v, 1)} for k, v in
               sorted(ind_w.items(), key=lambda x: -x[1])]
    hhi = round(sum((v / 100) ** 2 for v in ind_w.values()), 2)

    overlaps = [k for k, v in ind_w.items()
                if sum(1 for r in rows if r["industry"] == k) > 1]

    stances: dict = {}
    for r in rows:
        stances[r["stance"] or "未知"] = stances.get(r["stance"] or "未知", 0) + 1

    alerts = []
    if weights and weights[0]["pct"] > 40:
        alerts.append(f"行业集中：{weights[0]['name']} 占 {weights[0]['pct']}%（>40%）")
    for name in overlaps:
        alerts.append(f"同赛道重叠：{name} 持有 ≥2 只")
    for r in rows:
        if r["stop_dist"] is not None and -3 <= r["stop_dist"] < 0:
            alerts.append(f"{r['name']} 临近止损线（{r['stop_dist']}%）")
        if r["pnl_pct"] is not None and r["pnl_pct"] < -10:
            alerts.append(f"{r['name']} 浮亏 {r['pnl_pct']}%，检查止损纪律")

    return {
        "rows": rows, "total_mv": round(total, 0),
        "industry_weights": weights, "hhi": hhi,
        "overlaps": overlaps, "stances": stances, "alerts": alerts,
        "skipped": skipped,
    }
