"""大盘行情：指数 + 黄金 + 科技赛道（代表ETF）+ 市场温度分。失败用当日缓存兜底。

温度分（白盒，见 PRD §3.1）：
  基线 = 四指数"收盘价相对20日线偏离"映射 0-100 的均值（权重 0.6）
  量能 = 当日量 / 20日均量 映射 0-100 的均值（权重 0.4）
"""

import json
import time
from pathlib import Path

from .config import ROOT
from .data_feed import tencent_futures, tencent_kline, tencent_realtime

INDICES = [
    ("sh000001", "上证指数"),
    ("sz399001", "深证成指"),
    ("sz399006", "创业板指"),
    ("sh000300", "沪深300"),
]
SECTORS = [
    ("sh512480", "半导体"),
    ("sh515070", "人工智能"),
    ("sh515790", "光伏"),
]
GOLD_SYM = "hf_XAU"


def _clip01(v: float) -> float:
    return max(0.0, min(100.0, v))


def _dev_score(dev_pct: float) -> float:
    """偏离20日线 -3%..+3% → 0..100。"""
    return _clip01((dev_pct + 3) / 6 * 100)


def _vol_score(ratio: float) -> float:
    """量比 0.5..1.5 → 0..100。"""
    return _clip01((ratio - 0.5) / 1.0 * 100)


def temperature_label(score: float) -> str:
    return ("冰" if score < 20 else "冷" if score < 40 else
            "温" if score < 60 else "热" if score < 80 else "过热")


def _quote_with_spark(sym: str, name: str, days: int = 40) -> dict | None:
    q = tencent_realtime(sym)
    if not q:
        return None
    k = tencent_kline(sym, days)
    out = {
        "name": name, "symbol": sym,
        "price": q.get("price"), "pct": q.get("change_pct"),
        "amount_yi": round((q.get("amount_wan") or 0) / 1e4, 0),
        "spark": [round(float(c), 2) for c in k["close"].tail(30)] if k is not None else [],
    }
    # 温度分需要的中间量
    if k is not None and len(k) >= 21 and q.get("price"):
        ma20 = float(k["close"].rolling(20).mean().iloc[-1])
        vr = float(k["volume_hand"].iloc[-1]) / float(k["volume_hand"].tail(20).mean())
        out["_dev"] = _dev_score((q["price"] / ma20 - 1) * 100)
        out["_vol"] = _vol_score(vr)
    return out


def fetch_market() -> dict:
    out = {"asof": time.strftime("%Y-%m-%d %H:%M"), "indices": [], "gold": None,
           "sectors": [], "temperature": None}

    for sym, name in INDICES:
        e = _quote_with_spark(sym, name)
        if e:
            out["indices"].append(e)
    for sym, name in SECTORS:
        e = _quote_with_spark(sym, name)
        if e:
            out["sectors"].append(e)
    out["gold"] = tencent_futures(GOLD_SYM)

    devs = [e["_dev"] for e in out["indices"] if "_dev" in e]
    vols = [e["_vol"] for e in out["indices"] if "_vol" in e]
    if devs:
        baseline = sum(devs) / len(devs)
        vol = (sum(vols) / len(vols)) if vols else 50.0
        score = round(0.6 * baseline + 0.4 * vol, 1)
        out["temperature"] = {
            "score": score, "label": temperature_label(score),
            "baseline": round(baseline, 1), "volume": round(vol, 1),
        }

    # 清理内部字段
    for e in out["indices"] + out["sectors"]:
        e.pop("_dev", None)
        e.pop("_vol", None)

    if out["indices"]:
        try:
            cache = ROOT / "data" / f"market_{time.strftime('%Y-%m-%d')}.json"
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
        return out

    try:
        cache = ROOT / "data" / f"market_{time.strftime('%Y-%m-%d')}.json"
        if cache.exists():
            data = json.loads(cache.read_text(encoding="utf-8"))
            data["asof"] += "（缓存）"
            return data
    except (OSError, ValueError):
        pass
    return out
