"""数据层：腾讯为主、东财为辅（带重试）、财联社电报做新闻。

实测结论（2026-08-28，本机网络）：
- 东财 push2his 对 Python 客户端 TLS 指纹敏感且间歇性拒绝，一律重试 3 次，失败降级为 None，不阻塞主流程。
- 腾讯 qt.gtimg.cn / ifzq.gtimg.cn / proxy.finance.qq.com 用 requests 直连稳定。
- 财联社电报走 akshare stock_info_global_cls，按股票名过滤。
"""

import re
import time
from dataclasses import dataclass, field

import pandas as pd
import requests

UA = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
}
TIMEOUT = 10


# ---------------------------------------------------------------- 基础

def normalize_code(code: str) -> dict:
    """600519 -> {market:sh, symbol:sh600519, secid:1.600519}"""
    code = code.strip().upper().replace("SH", "").replace("SZ", "").replace("BJ", "")
    code = re.sub(r"[^0-9]", "", code)
    if code.startswith(("6", "9")):
        mkt, sec = "sh", f"1.{code}"
    elif code.startswith(("4", "8")):
        mkt, sec = "bj", f"0.{code}"
    else:
        mkt, sec = "sz", f"0.{code}"
    return {"code": code, "market": mkt, "symbol": mkt + code, "secid": sec}


def _get(url: str, params: dict | None = None, retry: int = 3, backoff: float = 1.5,
         encoding: str | None = None) -> requests.Response | None:
    """带重试的 GET；失败返回 None 而不是抛异常（数据层永不阻塞主流程）。"""
    for i in range(retry):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=TIMEOUT)
            if r.status_code == 200:
                if encoding:
                    r.encoding = encoding
                return r
        except requests.RequestException:
            pass
        if i < retry - 1:
            time.sleep(backoff * (i + 1))
    return None


def _f(parts: list, i: int) -> float | None:
    try:
        return float(parts[i])
    except (IndexError, ValueError):
        return None


# ---------------------------------------------------------------- 腾讯

def tencent_realtime(sym: str) -> dict | None:
    r = _get(f"https://qt.gtimg.cn/q={sym}", encoding="gbk")
    if not r or "=" not in r.text:
        return None
    parts = r.text.split("=", 1)[1].strip('";\n').split("~")
    if len(parts) < 46:
        return None
    return {
        "name": parts[1],
        "price": _f(parts, 3),
        "prev_close": _f(parts, 4),
        "open": _f(parts, 5),
        "time": parts[30] if len(parts) > 30 else "",
        "change": _f(parts, 31),
        "change_pct": _f(parts, 32),
        "high": _f(parts, 33),
        "low": _f(parts, 34),
        "volume_hand": _f(parts, 36),
        "amount_wan": _f(parts, 37),
        "turnover_pct": _f(parts, 38),
        "pe_ttm": _f(parts, 39),
        "amplitude_pct": _f(parts, 43),
        "float_mv_yi": _f(parts, 44),
        "total_mv_yi": _f(parts, 45),
        "pb": _f(parts, 46),
        "limit_up": _f(parts, 47),
        "limit_down": _f(parts, 48),
        "vol_ratio": _f(parts, 49),
    }


def tencent_futures(sym: str) -> dict | None:
    """hf_ 前缀的期货/贵金属行情：0 现价、1 涨跌%、4 高、5 低、7 昨结、末位名称。"""
    r = _get(f"https://qt.gtimg.cn/q={sym}", encoding="gbk")
    if not r or "=" not in r.text:
        return None
    parts = r.text.split("=", 1)[1].strip('";\n').split(",")
    if len(parts) < 14:
        return None
    price = _f(parts, 0)
    if price is None:
        return None
    return {
        "name": parts[-1],
        "price": price,
        "change_pct": _f(parts, 1),
        "high": _f(parts, 4),
        "low": _f(parts, 5),
        "prev_close": _f(parts, 7),
    }


def tencent_kline(sym: str, days: int = 140) -> pd.DataFrame | None:
    r = _get("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
             params={"param": f"{sym},day,,,{days},qfq"})
    if not r:
        return None
    try:
        node = r.json()["data"][sym]
        rows = node.get("qfqday") or node.get("day") or []
    except (KeyError, ValueError):
        return None
    if not rows:
        return None
    df = pd.DataFrame(
        [[r0[0], float(r0[1]), float(r0[2]), float(r0[3]), float(r0[4]), float(r0[5])]
         for r0 in rows if len(r0) >= 6],
        columns=["date", "open", "close", "high", "low", "volume_hand"],
    )
    return df.sort_values("date").reset_index(drop=True)


def tencent_profile(sym: str) -> dict:
    r = _get("https://proxy.finance.qq.com/ifzqgtimg/stock/corp/cwbb/search",
             params={"symbol": sym, "type": "sum", "jianjie": "1"})
    out: dict = {}
    if not r:
        return out
    try:
        d = r.json()["data"]
        gegu = d.get("gegu", {})
        out["full_name"] = gegu.get("gsmz", "")
        out["main_business"] = gegu.get("yw", "")
        out["listed_date"] = gegu.get("riqi", "")
    except (ValueError, KeyError):
        pass
    return out


# ---------------------------------------------------------------- 东财（可失败）

def eastmoney_valuation(secid: str) -> dict | None:
    r = _get("https://push2.eastmoney.com/api/qt/stock/get",
             params={"secid": secid,
                     "fields": "f50,f57,f58,f116,f117,f162,f163,f164,f167,f183,f184"})
    if not r:
        return None
    try:
        d = r.json()["data"]
    except ValueError:
        return None
    if not d:
        return None

    def _scaled(k: str, div: float = 100.0) -> float | None:
        v = d.get(k)
        return None if v in (None, "-") else round(v / div, 2)

    return {
        "vol_ratio": _scaled("f50"),
        "total_mv": d.get("f116"),
        "float_mv": d.get("f117"),
        "pe_ttm": _scaled("f162"),
        "pe_dynamic": _scaled("f163"),
        "pe_static": _scaled("f164"),
        "pb": _scaled("f167"),
    }


def eastmoney_fundflow(secid: str, days: int = 5) -> list[dict] | None:
    r = _get("https://push2.eastmoney.com/api/qt/stock/fflow/kline/get",
             params={"lmt": days, "klt": "101", "secid": secid,
                     "fields1": "f1,f2,f3,f7",
                     "fields2": "f51,f52,f53,f54,f55,f56"})
    if not r:
        return None
    try:
        klines = r.json()["data"]["klines"]
    except (ValueError, KeyError, TypeError):
        return None
    out = []
    for line in klines:
        p = line.split(",")
        if len(p) < 6:
            continue
        out.append({
            "date": p[0],
            "main_yi": round(float(p[1]) / 1e8, 2),
            "small_yi": round(float(p[2]) / 1e8, 2),
            "mid_yi": round(float(p[3]) / 1e8, 2),
            "large_yi": round(float(p[4]) / 1e8, 2),
            "super_yi": round(float(p[5]) / 1e8, 2),
        })
    return out


def eastmoney_announcements(code: str, size: int = 5) -> list[dict] | None:
    r = _get("https://np-anotice-stock.eastmoney.com/api/security/ann",
             params={"sr": "-1", "page_size": size, "page_index": "1",
                     "ann_type": "A", "client_source": "web", "stock_list": code})
    if not r:
        return None
    try:
        items = r.json()["data"]["list"]
    except (ValueError, KeyError, TypeError):
        return None
    return [{
        "date": a.get("notice_date", "")[:10],
        "title": a.get("title", ""),
        "url": f"https://data.eastmoney.com/notices/detail/{code}/{a.get('art_code', '')}.html",
    } for a in items]


# ---------------------------------------------------------------- 新闻

def cls_telegraph(stock_name: str, pool: int = 200) -> tuple[list[str], list[str]]:
    """财联社电报 → (个股相关, 市场要闻)。失败时两个空列表。"""
    try:
        import akshare as ak

        df = ak.stock_info_global_cls(symbol="全部")
    except Exception:
        return [], []
    if df is None or df.empty:
        return [], []
    df = df.tail(pool)
    text = (df["标题"].fillna("") + " " + df["内容"].fillna("")).tolist()
    dates = df["发布日期"].astype(str).tolist()
    times = df["发布时间"].astype(str).tolist()
    hits, macro = [], []
    for t, d, tm in zip(text, dates, times):
        line = f"[{d} {tm[:5]}] {t.strip()[:120]}"
        if stock_name and stock_name in t:
            hits.append(line)
        elif len(macro) < 8:
            macro.append(line)
    return hits[-10:], macro


# ---------------------------------------------------------------- 汇总

@dataclass
class StockBundle:
    code: str
    symbol: str
    name: str = ""
    realtime: dict = field(default_factory=dict)
    kline: pd.DataFrame | None = None
    profile: dict = field(default_factory=dict)
    valuation: dict | None = None
    fundflow: list | None = None
    announcements: list | None = None
    news_hits: list = field(default_factory=list)
    news_macro: list = field(default_factory=list)
    sector: dict = field(default_factory=dict)
    peers: dict | None = None
    fin: dict = field(default_factory=dict)

    @property
    def available(self) -> bool:
        return bool(self.realtime) and self.kline is not None and len(self.kline) > 0


def collect(code: str, kline_days: int = 140, news_pool: int = 200) -> StockBundle:
    meta = normalize_code(code)
    b = StockBundle(code=meta["code"], symbol=meta["symbol"])

    b.realtime = tencent_realtime(meta["symbol"]) or {}
    b.name = b.realtime.get("name", "")
    b.kline = tencent_kline(meta["symbol"], kline_days)
    if not b.available:
        return b                      # 行情/K线是硬依赖，拿不到后面没必要跑

    b.profile = tencent_profile(meta["symbol"])
    b.valuation = eastmoney_valuation(meta["secid"])
    b.fundflow = eastmoney_fundflow(meta["secid"])
    b.announcements = eastmoney_announcements(meta["code"])
    b.news_hits, b.news_macro = cls_telegraph(b.name, news_pool)

    # 工作台扩展数据（各自可失败）
    try:
        from .sector import fetch_peers, sector_info

        b.sector = sector_info(meta["symbol"])
        b.peers = fetch_peers(b.sector.get("industry"), meta["code"])
    except Exception as e:
        print(f"   ⚠️  板块/同业数据获取失败：{str(e)[:80]}")
    try:
        from .finance import build_financials

        b.fin = build_financials(meta["code"], meta["symbol"])
    except Exception as e:
        print(f"   ⚠️  财报数据获取失败：{str(e)[:80]}")
    return b
