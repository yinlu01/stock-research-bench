"""行业板块与同业对比。

- 行业/地域/概念/营收构成/分红：腾讯 F10（稳定）
- 同业对比：东财板块→成分股→腾讯批量行情（东财间歇限流，重试 5 次 + 7 天本地缓存兜底）
"""

import json
import time
from pathlib import Path

from .config import ROOT
from .data_feed import UA, _get

CACHE_DIR = ROOT / "data"
CACHE_TTL_DAYS = 7


# ---------------------------------------------------------------- 腾讯 F10

def sector_info(sym: str) -> dict:
    out: dict = {"industry": None, "region": None, "plate": [], "concepts": [],
                 "revenue_mix": [], "dividends": []}
    r = _get("https://proxy.finance.qq.com/ifzqgtimg/stock/corp/cwbb/search",
             params={"symbol": sym, "type": "sum", "jianjie": "1"})
    if not r:
        return out
    try:
        d = r.json()["data"]
    except ValueError:
        return out

    gegu = d.get("gegu", {}) or {}
    out["industry"] = gegu.get("hy") or None
    out["region"] = gegu.get("dy") or None
    out["plate"] = [p.get("name") for p in gegu.get("plate", []) if isinstance(p, dict)]
    out["concepts"] = [c.get("name") for c in gegu.get("concept", []) if isinstance(c, dict)]

    for y in gegu.get("yysr", []) or []:
        try:
            out["revenue_mix"].append({
                "segment": y.get("sector", ""),
                "income_yi": round(float(y.get("income", 0)) / 1e8, 1),
            })
        except (TypeError, ValueError):
            continue

    for f in gegu.get("fenhong", []) or []:
        try:
            out["dividends"].append({
                "year": str(f.get("nd", "")),
                "per_10_share": round(float(f.get("fh", 0)), 2),
                "ex_date": str(f.get("cqr", "")),
            })
        except (TypeError, ValueError):
            continue
    return out


def dividend_yield(dividends: list, price: float | None, year: str | None = None) -> float | None:
    """按年度合计每股分红 / 现价。year 缺省取最近年度。"""
    if not dividends or not price:
        return None
    years = sorted({d["year"] for d in dividends}, reverse=True)
    target = year or years[0]
    total = sum(d["per_10_share"] for d in dividends if d["year"] == target) / 10.0
    return round(total / price * 100, 2) if total else None


# ---------------------------------------------------------------- 同业（东财，可失败）

def _em_boards() -> list[dict] | None:
    for _ in range(3):
        r = _get("https://push2.eastmoney.com/api/qt/clist/get",
                 params={"pn": "1", "pz": "400", "po": "1", "np": "1", "fltt": "2",
                         "invt": "2", "fid": "f12", "fs": "m:90+t:2+f:!50",
                         "fields": "f12,f14"}, retry=1)
        if r:
            try:
                return r.json()["data"]["diff"]
            except (ValueError, KeyError, TypeError):
                return None
        time.sleep(1.5)
    return None


def _em_constituents(board_code: str) -> list[dict] | None:
    for _ in range(3):
        r = _get("https://push2.eastmoney.com/api/qt/clist/get",
                 params={"pn": "1", "pz": "14", "po": "1", "np": "1", "fltt": "2",
                         "invt": "2", "fid": "f20", "fs": f"b:{board_code}",
                         "fields": "f12,f14"}, retry=1)
        if r:
            try:
                diff = r.json()["data"]["diff"]
                return [{"code": it["f12"], "name": it["f14"]} for it in diff]
            except (ValueError, KeyError, TypeError):
                return None
        time.sleep(1.5)
    return None


def _tencent_batch(codes: list[str]) -> dict:
    """批量实时行情（腾讯，稳定）。返回 {code: {...}}"""
    from .data_feed import normalize_code, tencent_realtime

    out = {}
    for c in codes:
        sym = normalize_code(c)["symbol"]
        q = tencent_realtime(sym)
        if q:
            out[c] = q
        time.sleep(0.2)
    return out


def _cache_path(board_code: str) -> Path:
    return CACHE_DIR / f"peers_{board_code}.json"


def fetch_peers(industry: str | None, self_code: str) -> dict | None:
    """返回 {board, asof, cached, stocks:[{code,name,price,pct,pe,mv_yi}]}；失败返回 None。"""
    if not industry:
        return None

    boards = _em_boards()
    if boards:
        board = next((b for b in boards if industry in b["f14"] or b["f14"] in industry), None)
        if board is None:
            board = next((b for b in boards if industry[:2] in b["f14"]), None)
        if board:
            cons = _em_constituents(board["f12"])
            if cons:
                quotes = _tencent_batch([c["code"] for c in cons[:12]])
                stocks = []
                for c in cons[:12]:
                    q = quotes.get(c["code"])
                    if not q:
                        continue
                    stocks.append({
                        "code": c["code"], "name": q.get("name", c["name"]),
                        "price": q.get("price"), "pct": q.get("change_pct"),
                        "pe": q.get("pe_ttm"), "mv_yi": q.get("total_mv_yi"),
                        "is_self": c["code"] == self_code,
                    })
                stocks.sort(key=lambda s: (s["mv_yi"] or 0), reverse=True)
                result = {"board": board["f14"], "asof": time.strftime("%Y-%m-%d"),
                          "cached": False, "stocks": stocks}
                try:
                    CACHE_DIR.mkdir(parents=True, exist_ok=True)
                    _cache_path(board["f12"]).write_text(
                        json.dumps(result, ensure_ascii=False), encoding="utf-8")
                except OSError:
                    pass
                return result

    # 东财全挂 → 尝试读 7 天内缓存（缓存按行业名匹配不了，遍历缓存目录）
    try:
        for f in sorted(CACHE_DIR.glob("peers_*.json"), key=lambda p: p.stat().st_mtime,
                        reverse=True):
            data = json.loads(f.read_text(encoding="utf-8"))
            age_days = (time.time() - f.stat().st_mtime) / 86400
            if age_days <= CACHE_TTL_DAYS and industry in data.get("board", ""):
                data["cached"] = True
                return data
    except (OSError, ValueError):
        pass
    return None
