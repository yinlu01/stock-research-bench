"""状态持久化：跑一次流水线，反复改图表。

- save_state：运行结束后把最终状态（含 K线/财报/板块/各角色产出）存成 JSON
- load_state：从 JSON 重建可直接喂给 render_html 的状态
- harvest_from_html：从已生成的 HTML 里反解 payload（没有 state 文件时的回填通道）
- rebuild：只重渲染 HTML + 首页，不调任何 LLM 与数据接口
"""

import json
from pathlib import Path

import pandas as pd

from .config import ROOT
from .data_feed import StockBundle

STATE_DIR = ROOT / "data"


def _bundle_from_payload(p: dict) -> StockBundle:
    k = p["kline"]
    df = pd.DataFrame({
        "date": k["dates"],
        "open": [x[0] for x in k["ohlc"]],
        "close": [x[1] for x in k["ohlc"]],
        "low": [x[2] for x in k["ohlc"]],
        "high": [x[3] for x in k["ohlc"]],
        "volume_hand": k["volumes"],
    })
    q = p["quote"]
    b = StockBundle(code=p["meta"]["code"], symbol="", name=p["meta"]["name"])
    b.kline = df
    b.realtime = {
        "name": p["meta"]["name"], "price": q.get("price"), "change_pct": q.get("pct"),
        "turnover_pct": q.get("turnover"), "vol_ratio": q.get("vol_ratio"),
        "pe_ttm": q.get("pe"), "pb": q.get("pb"), "total_mv_yi": q.get("mv_yi"),
        "amplitude_pct": q.get("amplitude"),
    }
    b.fundflow = p.get("fundflow") or None
    b.announcements = p.get("announcements") or None
    b.news_hits = (p.get("news") or {}).get("hits") or []
    b.news_macro = (p.get("news") or {}).get("macro") or []
    b.sector = p.get("sector") or {}
    b.peers = p.get("peers")
    b.fin = p.get("fin") or {}
    return b


def payload_to_state(p: dict) -> dict:
    ind = p["appendix"]
    if isinstance(ind.get("ma"), dict):
        ind["ma"] = {int(k): v for k, v in ind["ma"].items()}
    return {
        "code": p["meta"]["code"], "name": p["meta"]["name"], "ok": True,
        "_date": p["meta"].get("date"),
        "_mode": p["meta"].get("mode", ""),
        "bundle": _bundle_from_payload(p),
        "indicators": ind,
        "analyst_notes": [{"role": r, "content": c} for r, c in p.get("notes", {}).items()],
        "bull_case": p.get("bull", ""), "bear_case": p.get("bear", ""),
        "decision": p["decision"],
        "score": (p.get("risk") or {}).get("score", 0),
        "feedback": (p.get("risk") or {}).get("feedback", ""),
        "revisions": (p.get("risk") or {}).get("revisions", 0),
        "committee_note": p.get("committee", ""),
        "degraded": bool(p["meta"].get("degraded")),
    }


def state_to_payload_compat(state: dict) -> dict:
    """与 html_report.build_payload 对齐的可序列化结构（用于 state 落盘）。"""
    from .html_report import build_payload

    return build_payload(state, state.get("_mode", "（重建）"))


def save_state(state: dict, mode_desc: str) -> Path:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = state_to_payload_compat(state)
    payload["meta"]["mode"] = mode_desc
    path = STATE_DIR / f"state_{payload['meta']['date']}_{state['bundle'].code}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")
    return path


def load_state(path: Path) -> dict:
    p = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload_to_state(p)


def harvest_from_html(html_path: Path) -> dict | None:
    text = Path(html_path).read_text(encoding="utf-8")
    start = text.find("const P = ")
    if start < 0:
        return None
    start += len("const P = ")
    end = text.find(";\nconst UP", start)
    if end < 0:
        return None
    try:
        return payload_to_state(json.loads(text[start:end]))
    except (ValueError, KeyError):
        return None


def find_latest_sources(codes: list[str] | None = None) -> dict:
    """每只票找最新的可重建来源：优先 data/state_*.json，其次 reports/*.html。"""
    out = {}
    for f in sorted(STATE_DIR.glob("state_*.json"), reverse=True):
        code = f.stem.rsplit("_", 1)[-1]
        if code not in out and (codes is None or code in codes):
            out[code] = ("state", f)
    rep = ROOT / "reports"
    for f in sorted(rep.glob("*.html"), reverse=True):
        if f.name == "index.html":
            continue
        parts = f.stem.split("_", 2)
        if len(parts) < 3:
            continue
        code = parts[1]
        if code not in out and (codes is None or code in codes):
            out[code] = ("html", f)
    return out
