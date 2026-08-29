"""财报数据层。

数据源（按可靠性）：
- 新浪三大报表（akshare stock_financial_report_sina）：100+ 期累计值，推导单季与同比 —— 财报趋势主源
- 新浪财务指标（akshare stock_financial_analysis_indicator）：ROE/毛利率/净利率/负债率/增长率
- 腾讯 F10（cwbb/search）：最新一期快照 + 营收构成 + 分红历史
所有来源可失败，失败则该字段为 None，报告自动省略对应图表。
"""

import warnings

import pandas as pd

warnings.filterwarnings("ignore")


# ---------------------------------------------------------------- 新浪

def sina_income(symbol: str) -> pd.DataFrame | None:
    try:
        import akshare as ak

        df = ak.stock_financial_report_sina(stock=symbol, symbol="利润表")
    except Exception:
        return None
    if df is None or df.empty:
        return None
    keep = ["报告日", "营业总收入", "归属于母公司所有者的净利润"]
    cols = [c for c in keep if c in df.columns]
    if len(cols) < 3:
        return None
    out = df[cols].copy()
    out.columns = ["period", "revenue", "net_profit"]
    out["period"] = out["period"].astype(str)
    for c in ("revenue", "net_profit"):
        out[c] = pd.to_numeric(out[c], errors="coerce")
    return out.dropna().sort_values("period").reset_index(drop=True)


def sina_indicators(code: str) -> pd.DataFrame | None:
    try:
        import akshare as ak

        df = ak.stock_financial_analysis_indicator(symbol=code, start_year="2021")
    except Exception:
        return None
    if df is None or df.empty:
        return None
    df = df.copy()
    df["日期"] = pd.to_datetime(df["日期"]).dt.strftime("%Y%m%d")
    return df.sort_values("日期").reset_index(drop=True)


def _pick(df: pd.DataFrame, period: str, *candidates) -> float | None:
    row = df[df["日期"] == period]
    if row.empty:
        return None
    for c in candidates:
        if c in df.columns:
            v = pd.to_numeric(row[c].iloc[0], errors="coerce")
            if pd.notna(v):
                return round(float(v), 2)
    return None


# ---------------------------------------------------------------- 单季推导

def _quarter_label(period: str) -> str:
    y, m = period[:4], period[4:6]
    q = {"03": 1, "06": 2, "09": 3, "12": 4}[m]
    return f"{y}Q{q}"


def build_quarters(income: pd.DataFrame) -> list[dict]:
    """累计值 → 单季值 + 同比。返回按时间升序的列表。"""
    if income is None or income.empty:
        return []
    rows = income.to_dict("records")
    by_period = {r["period"]: r for r in rows}
    out = []
    for r in rows:
        p = r["period"]
        y, m = p[:4], p[4:6]
        prev_end = {"06": "0331", "09": "0630", "12": "0930"}.get(m)
        prev_q = f"{y}{prev_end}" if prev_end else None
        yoy_p = f"{int(y) - 1}{p[4:]}"

        def _single(key: str) -> float | None:
            cum = r[key]
            if m == "03":
                return cum
            prev = by_period.get(prev_q)
            return cum - prev[key] if prev is not None else None

        rev, np_ = _single("revenue"), _single("net_profit")
        yoy_row = by_period.get(yoy_p)

        def _yoy(key: str, single: float | None) -> float | None:
            if single is None or yoy_row is None:
                return None
            cur_prev = yoy_row[key]
            if m != "03":
                pp_end = {"06": "0331", "09": "0630", "12": "0930"}[m]
                pp_row = by_period.get(f"{int(y) - 1}{pp_end}")
                if pp_row is not None:
                    cur_prev = cur_prev - pp_row[key]
            return round((single / cur_prev - 1) * 100, 1) if cur_prev else None

        out.append({
            "period": p, "label": _quarter_label(p),
            "revenue_yi": round(rev / 1e8, 1) if rev is not None else None,
            "profit_yi": round(np_ / 1e8, 1) if np_ is not None else None,
            "revenue_yoy": _yoy("revenue", rev),
            "profit_yoy": _yoy("net_profit", np_),
        })
    return out


def build_financials(code: str, symbol: str) -> dict:
    """汇总财报数据包。任何一步失败都降级为 None 字段。"""
    income = sina_income(symbol)
    indicators = sina_indicators(code)
    quarters = build_quarters(income)

    if indicators is not None and quarters:
        for q in quarters:
            p = q["period"]
            q["roe"] = _pick(indicators, p, "净资产收益率(%)", "加权净资产收益率(%)")
            q["gross_margin"] = _pick(indicators, p, "销售毛利率(%)")
            q["net_margin"] = _pick(indicators, p, "销售净利率(%)")
            q["debt_ratio"] = _pick(indicators, p, "资产负债率(%)")
            q["eps"] = _pick(indicators, p, "摊薄每股收益(元)", "每股收益_调整后(元)")
            q["ocf_ps"] = _pick(indicators, p, "每股经营性现金流(元)")

    annual = [q for q in quarters if q["period"].endswith("1231")][-5:]
    latest_q = quarters[-1] if quarters else None
    annual_summary = None
    if annual:
        last = annual[-1]
        annual_summary = {
            "period": last["period"][:4],
            "revenue_yi": last["revenue_yi"],
            "profit_yi": last["profit_yi"],
            "revenue_yoy": last["revenue_yoy"],
            "profit_yoy": last["profit_yoy"],
        }

    return {
        "quarters": quarters[-12:],        # 近12个单季
        "annual": annual,                  # 近5年
        "latest": latest_q,
        "annual_summary": annual_summary,
        "available": bool(quarters),
    }
