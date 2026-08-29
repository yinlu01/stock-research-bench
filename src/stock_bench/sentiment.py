"""热点舆情两级漏斗（PRD §3.1 S1）：

1. 规则粗筛：关注图谱 + 自选/持仓名 对财联社电报打分 → Top 30
2. LLM 精选：Top 30 → Top 5，每条一句"为什么与你相关"
降级：LLM 失败/离线 → 规则 Top 5（带命中关注标签），永不空窗。
结果按日缓存 data/sentiment_{date}.json。
"""

import json
import re
import time
from pathlib import Path

from .config import ROOT
from .llm import chat

SENT_SYSTEM = ("你是投研信息助理。从候选新闻中选出对关注领域最重要的 5 条。"
               "输出严格 JSON 数组，元素为 {\"i\": 候选序号, \"why\": 一句中文说明为什么与该关注点相关}，"
               "不要任何其他文字。")


def fetch_pool(size: int = 200) -> list[dict]:
    try:
        import akshare as ak

        df = ak.stock_info_global_cls(symbol="全部")
    except Exception:
        return []
    if df is None or df.empty:
        return []
    df = df.tail(size)
    out = []
    for _, r in df.iterrows():
        text = f"{r.get('标题', '')} {r.get('内容', '')}".strip()
        if text:
            out.append({"text": text, "title": str(r.get("标题", "") or "")[:60],
                        "when": f"{r.get('发布日期', '')} {str(r.get('发布时间', ''))[:5]}"})
    return out


def rule_score(pool: list[dict], focus: list[dict], names: list[str]) -> list[dict]:
    scored = []
    for item in pool:
        t = item["text"]
        score, hits = 0, []
        for g in focus:
            for kw in g["keywords"]:
                if kw in t:
                    score += g["weight"]
                    hits.append(f"{g['name']}·{kw}")
                    break          # 同组只计一次
        for n in names:
            if n and n in t:
                score += 3
                hits.append(f"个股·{n}")
        if score > 0:
            scored.append({**item, "score": score, "hits": hits})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


def llm_pick(candidates: list[dict]) -> list[dict] | None:
    if not candidates:
        return None
    listing = "\n".join(f"{i}. {c['text'][:80]}" for i, c in enumerate(candidates))
    try:
        raw = chat(SENT_SYSTEM, f"候选新闻：\n{listing}")
    except Exception:
        return None
    if not raw:
        return None
    m = re.search(r"\[.*\]", raw, re.S)
    if not m:
        return None
    try:
        arr = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    picked = []
    for el in arr[:5]:
        i = el.get("i")
        if isinstance(i, int) and 0 <= i < len(candidates):
            picked.append({
                "text": candidates[i]["text"][:120],
                "title": candidates[i].get("title", ""),
                "when": candidates[i].get("when", ""),
                "why": str(el.get("why", ""))[:60],
                "hits": candidates[i].get("hits", []),
                "mode": "llm",
            })
    return picked or None


def run_sentiment(names: list[str], focus: list[dict], allow_llm: bool = True) -> dict:
    cache = ROOT / "data" / f"sentiment_{time.strftime('%Y-%m-%d')}.json"
    if cache.exists():
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except ValueError:
            pass

    pool = fetch_pool()
    scored = rule_score(pool, focus, names)
    top30 = scored[:30]
    picked = llm_pick(top30) if allow_llm else None
    if picked:
        items = picked
    else:
        items = [{
            "text": c["text"][:120], "title": c.get("title", ""), "when": c.get("when", ""),
            "why": "命中：" + "、".join(c["hits"][:3]),
            "hits": c["hits"], "mode": "rule",
        } for c in scored[:5]]

    out = {"asof": time.strftime("%Y-%m-%d %H:%M"), "items": items,
           "pool_size": len(pool), "mode": "llm" if picked else "rule"}
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return out
