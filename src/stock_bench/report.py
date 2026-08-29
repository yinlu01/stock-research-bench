"""研报渲染与落盘：workspace/reports + Obsidian/AI技术/股票每日研究/"""

from datetime import date
from pathlib import Path

from .config import ROOT
from .data_feed import StockBundle

OBSIDIAN_DIR = Path.home() / "Obsidian" / "AI技术" / "股票每日研究"


def _snapshot_table(b: StockBundle) -> str:
    rt = b.realtime
    v = b.valuation or {}
    rows = [
        ("现价", rt.get("price")), ("涨跌幅%", rt.get("change_pct")),
        ("换手率%", rt.get("turnover_pct")), ("量比", rt.get("vol_ratio") or v.get("vol_ratio")),
        ("PE(TTM)", rt.get("pe_ttm") or v.get("pe_ttm")), ("PB", rt.get("pb") or v.get("pb")),
        ("总市值(亿)", rt.get("total_mv_yi")), ("振幅%", rt.get("amplitude_pct")),
    ]
    head = "| " + " | ".join(k for k, _ in rows) + " |"
    sep = "|---" * len(rows) + "|"
    vals = "| " + " | ".join(str(vv) if vv is not None else "—" for _, vv in rows) + " |"
    return f"{head}\n{sep}\n{vals}"


def render(state: dict, mode_desc: str) -> str:
    b: StockBundle = state["bundle"]
    ind = state["indicators"]
    d = state["decision"]
    notes = {n["role"]: n["content"] for n in state["analyst_notes"]}
    today = date.today().isoformat()

    parts = [
        f"# {b.name}（{b.code}）每日研判 · {today}",
        "",
        f"> 模式：{mode_desc}{'｜部分环节规则降级' if state.get('degraded') else ''}｜"
        f"决策：{d['stance']} · {d['action']} · 置信度 {d.get('confidence')}｜重写 {state.get('revisions', 0)} 次",
        f"> 📊 图表版工作台：`reports/{today}_{b.code}_{b.name}.html`（浏览器打开：K线蜡烛图/财报图表/量化诊断/同业对比）",
        "",
        "## 快照",
        _snapshot_table(b),
        "",
        "## 投委会结论",
        state["committee_note"],
        "",
        f"**操作要点**：仓位上限 {d['position_pct']}%｜加仓触发：{d.get('trigger_buy', '—')}｜"
        f"离场触发：{d.get('trigger_exit', '—')}｜止损：{d.get('stop_loss', '—')}",
        "",
        "## 分析师笔记",
    ]
    for role in ("技术分析师", "基本面分析师", "财报分析师", "新闻与公告分析师"):
        if role in notes:
            parts += [f"### {role}", notes[role], ""]

    parts += [
        "## 多空辩论",
        "### 多头研究员", state["bull_case"], "",
        "### 空头研究员", state["bear_case"], "",
    ]

    parts += ["", "## 财务分析"]
    fin = b.fin or {}
    if fin.get("quarters"):
        parts += ["### 单季（近4季）",
                  "| 季度 | 营收(亿) | 营收同比 | 归母净利(亿) | 净利同比 | ROE% | 毛利率% | 净利率% |",
                  "|---|---|---|---|---|---|---|---|"]
        for q in fin["quarters"][-4:]:
            g = lambda k: q.get(k) if q.get(k) is not None else "—"
            parts.append(f"| {q['label']} | {q['revenue_yi']} | {q['revenue_yoy']}% | {q['profit_yi']} "
                         f"| {q['profit_yoy']}% | {g('roe')} | {g('gross_margin')} | {g('net_margin')} |")
        if fin.get("annual"):
            parts += ["", "### 年度（近3年）",
                      "| 年度 | 营收(亿) | 营收同比 | 净利(亿) | 净利同比 | 负债率% |",
                      "|---|---|---|---|---|---|"]
            for q in fin["annual"][-3:]:
                dr = q.get("debt_ratio") if q.get("debt_ratio") is not None else "—"
                parts.append(f"| {q['period'][:4]} | {q['revenue_yi']} | {q['revenue_yoy']}% "
                             f"| {q['profit_yi']} | {q['profit_yoy']}% | {dr} |")
    else:
        parts.append("（新浪财报接口本次不可用，财务图表见 HTML 工作台在数据恢复后自动生成）")

    parts += ["", "## 行业板块与同业"]
    s = b.sector or {}
    if s.get("industry"):
        parts.append(f"行业：**{s['industry']}**｜地域：{s.get('region', '—')}")
        if s.get("concepts"):
            parts.append("概念：" + "、".join(s["concepts"][:12]))
    if b.peers and b.peers.get("stocks"):
        tag = "（缓存）" if b.peers.get("cached") else ""
        parts += [f"\n同业对比{tag} · {b.peers['board']}（按市值）：",
                  "| 公司 | 现价 | 涨跌% | PE | 市值(亿) |", "|---|---|---|---|---|"]
        for p in b.peers["stocks"][:8]:
            mark = "★ " if p.get("is_self") else ""
            parts.append(f"| {mark}{p['name']} | {p['price']} | {p['pct']} | {p['pe']} | {p['mv_yi']} |")
    else:
        parts.append("\n（同业数据暂不可用：东财板块接口限流，不影响其他环节）")

    parts += [
        "",
        "## 资金流（近5日，亿元）",
    ]
    if b.fundflow:
        parts += ["| 日期 | 主力 | 超大单 | 大单 | 中单 |", "|---|---|---|---|---|"]
        for f in b.fundflow:
            parts.append(f"| {f['date']} | {f['main_yi']:+.2f} | {f['super_yi']:+.2f} "
                         f"| {f['large_yi']:+.2f} | {f['mid_yi']:+.2f} |")
    else:
        parts.append("（东财资金流接口本次不可用，不影响其他环节）")

    parts += ["", "## 公告与新闻"]
    if b.announcements:
        for a in b.announcements[:5]:
            parts.append(f"- [{a['date']}] [{a['title']}]({a['url']})")
    else:
        parts.append("- 近期无公告（或东财公告接口暂不可用）")
    if b.news_hits:
        parts += ["", "近期提及："] + [f"- {t}" for t in b.news_hits[:6]]

    parts += [
        "",
        "## 技术面附录",
        f"MA5/10/20/60：{ind['ma'][5]} / {ind['ma'][10]} / {ind['ma'][20]} / {ind['ma'][60]}（{ind['alignment']}）",
        f"RSI14 {ind['rsi14']}｜MACD 柱 {ind['macd']['hist']}｜20日年化波动 {ind['vol20_annualized_pct']}%",
        f"60日区间分位 {ind['pos60_pct']}%（{ind['low60']} ~ {ind['high60']}）",
        "",
        "---",
        "*由 stock-research-bench 自动生成。所有输出仅为研究记录，不构成投资建议。*",
    ]
    return "\n".join(parts)


def save(state: dict, mode_desc: str, obsidian: bool = True) -> tuple[Path, Path | None]:
    b: StockBundle = state["bundle"]
    today = date.today().isoformat()
    text = render(state, mode_desc)

    local = ROOT / "reports" / f"{today}_{b.code}_{b.name}.md"
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(text, encoding="utf-8")

    obs = None
    if obsidian:
        try:
            OBSIDIAN_DIR.mkdir(parents=True, exist_ok=True)
            obs = OBSIDIAN_DIR / f"{today}_{b.code}_{b.name}.md"
            obs.write_text(text, encoding="utf-8")
        except OSError as e:
            print(f"   ⚠️  写入 Obsidian 失败：{e}")
    return local, obs
