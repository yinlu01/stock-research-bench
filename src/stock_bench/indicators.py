"""技术指标：只依赖 pandas，全部从日K计算。"""

import numpy as np
import pandas as pd


def rsi(close: pd.Series, n: int = 14) -> float:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(n).mean()
    loss = (-delta.clip(upper=0)).rolling(n).mean()
    rs = gain / loss.replace(0, np.nan)
    val = (100 - 100 / (1 + rs)).iloc[-1]
    return round(float(val), 1) if pd.notna(val) else float("nan")


def macd(close: pd.Series) -> dict:
    dif, dea, hist = macd_series(close)
    return {"dif": round(float(dif[-1]), 3),
            "dea": round(float(dea[-1]), 3),
            "hist": round(float(hist[-1]), 3),
            "hist_prev": round(float(hist[-2]), 3) if len(hist) > 1 else 0.0}


def macd_series(close: pd.Series) -> tuple[list, list, list]:
    """返回与 close 对齐的 DIF/DEA/HIST 数组（供图表）。"""
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    hist = (dif - dea) * 2
    fmt = lambda s: [None if pd.isna(v) else round(float(v), 3) for v in s]
    return fmt(dif), fmt(dea), fmt(hist)


def compute(df: pd.DataFrame) -> dict:
    """入参是 data_feed.tencent_kline 的 DataFrame。"""
    c, h, l, v = df["close"], df["high"], df["low"], df["volume_hand"]
    last = float(c.iloc[-1])

    ma = {n: round(float(c.rolling(n).mean().iloc[-1]), 2) if len(c) >= n else None
          for n in (5, 10, 20, 60)}
    m = macd(c)
    ret = lambda n: round((last / float(c.iloc[-1 - n]) - 1) * 100, 2) if len(c) > n else None

    win = df.tail(60)
    low60, high60 = float(win["low"].min()), float(win["high"].max())
    pos60 = round((last - low60) / (high60 - low60) * 100, 1) if high60 > low60 else 50.0
    drawdown = round((last / high60 - 1) * 100, 2)

    logret = np.log(c / c.shift(1)).dropna()
    vol20 = round(float(logret.tail(20).std() * np.sqrt(252) * 100), 1) if len(logret) >= 20 else None

    vol_ma5 = float(v.rolling(5).mean().iloc[-1]) if len(v) >= 5 else None
    vol_vs = round(float(v.iloc[-1]) / vol_ma5, 2) if vol_ma5 else None

    streak = 0
    for i in range(len(c) - 1, 0, -1):
        d = float(c.iloc[i] - c.iloc[i - 1])
        if d == 0:
            break
        s = 1 if d > 0 else -1
        if streak == 0:
            streak = s
        elif (streak > 0) == (s > 0):
            streak += s
        else:
            break

    alignment = "多头排列" if ma[5] and ma[20] and ma[60] and ma[5] > ma[20] > ma[60] else \
                "空头排列" if ma[5] and ma[20] and ma[60] and ma[5] < ma[20] < ma[60] else "均线纠缠"

    return {
        "close": last, "ma": ma, "rsi14": rsi(c),
        "macd": m,
        "ret_5d": ret(5), "ret_20d": ret(20), "ret_60d": ret(60),
        "low60": low60, "high60": high60, "pos60_pct": pos60,
        "drawdown_from_60d_high_pct": drawdown,
        "vol20_annualized_pct": vol20, "vol_vs_ma5": vol_vs,
        "streak": streak, "alignment": alignment,
    }


def brief(ind: dict) -> str:
    """给技术分析师看的文字摘要。"""
    ma = ind["ma"]
    m = ind["macd"]
    lines = [
        f"收盘 {ind['close']}；MA5={ma[5]} MA10={ma[10]} MA20={ma[20]} MA60={ma[60]}，形态：{ind['alignment']}",
        f"RSI14={ind['rsi14']}；MACD dif={m['dif']} dea={m['dea']} 柱={m['hist']}（前一日 {m['hist_prev']}，{'放大' if abs(m['hist']) > abs(m['hist_prev']) else '收敛'}）",
        f"区间涨幅：5日 {ind['ret_5d']}% / 20日 {ind['ret_20d']}% / 60日 {ind['ret_60d']}%",
        f"位于60日区间 {ind['pos60_pct']}% 分位（低点 {ind['low60']} / 高点 {ind['high60']}），距60日高点回撤 {ind['drawdown_from_60d_high_pct']}%",
        f"20日年化波动率 {ind['vol20_annualized_pct']}%；当日量/5日均量={ind['vol_vs_ma5']}",
        f"连续{'上涨' if ind['streak'] > 0 else '下跌'} {abs(ind['streak'])} 天" if ind["streak"] != 0 else "当日方向不明",
    ]
    return "\n".join(lines)
