"""多 Agent 股票研判流水线（与 TradingAgents-CN 同构）：

  prepare(数据+指标) → 分析师×3(并行) → 多头研究员 → 空头研究员
      → 交易员 → 风控(红线+评分) → [不合格回环重写] → 投委会结论

设计原则：永不中断。LLM 调用失败自动降级为规则引擎；东财数据失败降级为仅腾讯。
"""

import json
import operator
import re
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from . import llm, prompts, rules
from .data_feed import collect
from .indicators import brief as ind_brief, compute


# ---------------------------------------------------------------- 状态

class BenchState(TypedDict, total=False):
    code: str
    name: str
    bundle: object
    indicators: dict
    analyst_notes: Annotated[list[dict], operator.add]
    degraded: Annotated[bool, operator.or_]
    bull_case: str
    bear_case: str
    decision: dict
    decision_raw: str
    score: int
    feedback: str
    revisions: int
    committee_note: str
    ok: bool
    error: str
    position: dict


def _safe_chat(system: str, user: str, fallback: str) -> tuple[str, bool]:
    """调 LLM；任何失败都返回 (降级文本, True)，保证日任务不炸。"""
    try:
        out = llm.chat(system, user)
    except Exception as e:
        print(f"   ⚠️  LLM 调用失败，降级规则模式：{str(e)[:90]}")
        return fallback, True
    if out is None:
        return fallback, True
    return out, False


def _fmt_fundflow(bundle) -> str:
    if not bundle.fundflow:
        return "（资金流数据暂不可用）"
    lines = [f"{f['date']}：主力 {f['main_yi']:+.2f} 亿（超大单 {f['super_yi']:+.2f} / 大单 {f['large_yi']:+.2f}）"
             for f in bundle.fundflow]
    return "\n".join(lines)


# ---------------------------------------------------------------- 节点

def prepare(state: BenchState) -> dict:
    from .config import load_holdings, settings

    code = state["code"]
    print(f"\n📡 [prepare] 拉取 {code} 数据（腾讯行情+东财辅助+财联社新闻）...")
    bundle = collect(code, kline_days=settings.kline_days, news_pool=settings.news_pool_size)
    if not bundle.available:
        print(f"   ❌ 行情或K线获取失败，{code} 跳过")
        return {"ok": False, "error": "行情/K线获取失败", "name": bundle.name or code}

    ind = compute(bundle.kline)
    position = next((h for h in load_holdings() if str(h.get("code")) == code), None)
    tag = "｜持仓票" if position else ""
    print(f"   ✅ {bundle.name} 现价 {ind['close']}，{len(bundle.kline)} 根日K，"
          f"公告 {len(bundle.announcements or [])} 条，个股新闻 {len(bundle.news_hits)} 条{tag}")
    return {"ok": True, "name": bundle.name, "bundle": bundle,
            "indicators": ind, "position": position}


def route_prepare(state: BenchState):
    if not state.get("ok"):
        return END
    payload = {"bundle": state["bundle"], "indicators": state["indicators"]}
    return [Send("analyst", {**payload, "role": r})
            for r in ("technical", "fundamental", "financial", "news")]


def _sector_text(bundle) -> str:
    s = bundle.sector or {}
    lines = [f"行业：{s.get('industry') or '未知'}｜地域：{s.get('region') or '未知'}"]
    if s.get("concepts"):
        lines.append("概念标签：" + "、".join(s["concepts"][:10]))
    if bundle.peers and bundle.peers.get("stocks"):
        tag = "（缓存）" if bundle.peers.get("cached") else ""
        lines.append(f"同业对比{tag}（{bundle.peers['board']}，按市值）：")
        for p in bundle.peers["stocks"][:8]:
            mark = "★" if p.get("is_self") else " "
            lines.append(f"  {mark}{p['name']}({p['code']})：现价 {p['price']}，涨跌 {p['pct']}%，"
                         f"PE {p['pe']}，市值 {p['mv_yi']} 亿")
    return "\n".join(lines)


def _fin_text(bundle) -> str:
    fin = bundle.fin or {}
    if not fin.get("available"):
        return "（财报数据暂不可用）"
    lines = ["单季表现（近4季）："]
    for q in fin["quarters"][-4:]:
        lines.append(f"  {q['label']}：营收 {q['revenue_yi']} 亿（同比 {q['revenue_yoy']}%），"
                     f"归母净利 {q['profit_yi']} 亿（同比 {q['profit_yoy']}%），"
                     f"ROE {q.get('roe')}%，毛利率 {q.get('gross_margin')}%，净利率 {q.get('net_margin')}%")
    if fin.get("annual"):
        lines.append("年度（近3年）：")
        for q in fin["annual"][-3:]:
            lines.append(f"  {q['period'][:4]}：营收 {q['revenue_yi']} 亿（同比 {q['revenue_yoy']}%），"
                         f"净利 {q['profit_yi']} 亿（同比 {q['profit_yoy']}%），负债率 {q.get('debt_ratio')}%")
    s = bundle.sector or {}
    if s.get("dividends"):
        div = "；".join(f"{d['year']} 年度每10股派 {d['per_10_share']} 元" for d in s["dividends"][:3])
        lines.append("分红记录：" + div)
        from .sector import dividend_yield

        dy = dividend_yield(s["dividends"], bundle.realtime.get("price"))
        if dy:
            lines.append(f"按现价估算最近年度股息率约 {dy}%")
    if s.get("revenue_mix"):
        lines.append("营收构成：" + "、".join(f"{m['segment']} {m['income_yi']}亿" for m in s["revenue_mix"][:4]))
    return "\n".join(lines)


def analyst(state: dict) -> dict:
    role, bundle, ind = state["role"], state["bundle"], state["indicators"]
    titles = {"technical": "技术分析师", "fundamental": "基本面分析师",
              "financial": "财报分析师", "news": "新闻与公告分析师"}

    if role == "technical":
        user = (f"股票：{bundle.name}({bundle.code})\n\n技术面数据：\n{ind_brief(ind)}\n"
                f"当日：现价 {ind['close']}，5日涨跌 {ind['ret_5d']}%")
        system, fallback = prompts.TECH_ANALYST, (
            f"规则摘要：{ind['alignment']}；收盘 {ind['close']} 对 MA20 "
            f"{'上穿' if ind['ma'][20] and ind['close'] > ind['ma'][20] else '下破'}；"
            f"RSI {ind['rsi14']}，MACD 柱 {ind['macd']['hist']}；"
            f"60日区间分位 {ind['pos60_pct']}%，距高点 {ind['drawdown_from_60d_high_pct']}%。")
    elif role == "fundamental":
        v = bundle.valuation or {}
        rt = bundle.realtime
        user = (f"股票：{bundle.name}({bundle.code})\n"
                f"估值：PE(TTM) {rt.get('pe_ttm') or v.get('pe_ttm')}，PB {rt.get('pb') or v.get('pb')}，"
                f"总市值 {rt.get('total_mv_yi')} 亿，流通市值 {rt.get('float_mv_yi')} 亿\n"
                f"主营：{bundle.profile.get('main_business', '（未获取）')[:200]}\n"
                f"上市时间：{bundle.profile.get('listed_date', '')}\n\n"
                f"行业与同业：\n{_sector_text(bundle)}")
        system, fallback = prompts.FUND_ANALYST, (
            f"规则摘要：PE {rt.get('pe_ttm')} / PB {rt.get('pb')}，市值 {rt.get('total_mv_yi')} 亿；"
            f"行业：{(bundle.sector or {}).get('industry', '未知')}")
    elif role == "financial":
        user = (f"股票：{bundle.name}({bundle.code})\n\n财务数据：\n{_fin_text(bundle)}")
        fin = bundle.fin or {}
        latest = fin.get("latest") or {}
        system, fallback = prompts.FIN_ANALYST, (
            f"规则摘要：最新季度 {latest.get('label', '未知')} 营收 {latest.get('revenue_yi')} 亿"
            f"（同比 {latest.get('revenue_yoy')}%），净利 {latest.get('profit_yi')} 亿"
            f"（同比 {latest.get('profit_yoy')}%），ROE {latest.get('roe')}%")
    else:
        ann = bundle.announcements or []
        user = (f"股票：{bundle.name}({bundle.code})\n\n近期公告：\n"
                + ("\n".join(f"[{a['date']}] {a['title']}" for a in ann) or "（无）")
                + "\n\n相关新闻：\n"
                + ("\n".join(bundle.news_hits) or "（无）")
                + "\n\n市场要闻（参考）：\n" + "\n".join(bundle.news_macro))
        system, fallback = prompts.NEWS_ANALYST, (
            "规则摘要：" + ("、".join(a["title"] for a in ann[:3]) or "近期无重大公告")
            + "；个股相关新闻 " + (f"{len(bundle.news_hits)} 条" if bundle.news_hits else "无"))

    content, degraded = _safe_chat(system, user, fallback)
    print(f"   📊 [{titles[role]}] {len(content)} 字{'（规则降级）' if degraded else ''}")
    return {"analyst_notes": [{"role": titles[role], "content": content}], "degraded": degraded}


def _all_notes(state: BenchState) -> str:
    return "\n\n".join(f"【{n['role']}】\n{n['content']}" for n in state["analyst_notes"])


def debate_bull(state: BenchState) -> dict:
    user = (f"股票：{state['name']}({state['code']})\n\n分析师笔记：\n{_all_notes(state)}\n"
            f"\n资金流（近5日）：\n{_fmt_fundflow(state['bundle'])}")
    content, degraded = _safe_chat(prompts.BULL, user,
        "（多头研究员降级）看多依据：" + "；".join(rules.scorecard(state["bundle"], state["indicators"])["drivers"][:3]))
    print(f"   🐂 [多头研究员] {len(content)} 字")
    return {"bull_case": content, "degraded": degraded}


def debate_bear(state: BenchState) -> dict:
    user = (f"股票：{state['name']}({state['code']})\n\n多头论点：\n{state['bull_case']}\n\n"
            f"分析师笔记：\n{_all_notes(state)}\n资金流（近5日）：\n{_fmt_fundflow(state['bundle'])}")
    content, degraded = _safe_chat(prompts.BEAR, user,
        "（空头研究员降级）风险提示：" + "；".join(rules.scorecard(state["bundle"], state["indicators"])["risks"][:3]))
    print(f"   🐻 [空头研究员] {len(content)} 字")
    return {"bear_case": content, "degraded": degraded}


def _parse_decision(raw: str) -> dict | None:
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return d if isinstance(d.get("action"), str) else None


def _rule_decision(bundle, ind) -> dict:
    sc = rules.scorecard(bundle, ind)
    return {
        "stance": sc["stance"], "action": sc["action"], "confidence": sc["confidence"],
        "position_pct": min(20, sc["confidence"] // 3),
        "reasoning": "、".join(sc["drivers"][:2]) or "无显著正向驱动",
        "trigger_buy": "缩量回踩20日线不破",
        "trigger_exit": "放量跌破20日线且主力资金转为净流出",
        "stop_loss": "收盘跌破20日线，或较买入价回撤8%",
    }


def trader(state: BenchState) -> dict:
    bundle, ind = state["bundle"], state["indicators"]
    user = (f"股票：{state['name']}({state['code']})\n\n多头：\n{state['bull_case']}\n\n"
            f"空头：\n{state['bear_case']}\n\n分析师笔记：\n{_all_notes(state)}")
    if state.get("feedback"):
        user += f"\n\n⚠️ 风控整改意见（必须执行）：{state['feedback']}"

    pos = state.get("position")
    if pos:
        price = bundle.realtime.get("price")
        pnl = round((price / pos["cost_price"] - 1) * 100, 1) \
            if price and pos.get("cost_price") else None
        user += (f"\n\n【持仓上下文】已持有 {pos.get('shares')} 股，成本 {pos.get('cost_price')}，"
                 f"现价 {price}，浮动盈亏 {pnl}%。action 词汇限定：加仓/持有/减仓/清仓。")
        system = prompts.POSITION_TRADER
    else:
        system = prompts.TRADER

    fallback = json.dumps(_rule_decision(bundle, ind), ensure_ascii=False)
    raw, degraded = _safe_chat(system, user, fallback)

    decision = _parse_decision(raw)
    if decision is None:
        print("   ⚠️  交易员输出无法解析，降级规则决策")
        decision, degraded = _rule_decision(bundle, ind), True
        raw = fallback

    # 确定性纪律：仓位上限 30%，无论模型说什么
    try:
        pos = int(decision.get("position_pct", 0))
    except (TypeError, ValueError):
        pos = 0
    decision["position_pct"] = max(0, min(30, pos))

    label = "重写" if state.get("feedback") else "决策"
    print(f"   🎯 [交易员·{label}] {decision['stance']} / {decision['action']} / "
          f"置信 {decision.get('confidence')} / 仓位上限 {decision['position_pct']}%{'（规则降级）' if degraded else ''}")
    return {"decision": decision, "decision_raw": raw, "degraded": degraded}


def risk(state: BenchState) -> dict:
    decision = state["decision"]
    red = rules.red_line_check(state["decision_raw"])

    user = (f"交易员决策（JSON）：\n{json.dumps(decision, ensure_ascii=False, indent=2)}\n\n"
            f"多空辩论摘要：\n多头：{state['bull_case'][:150]}\n空头：{state['bear_case'][:150]}")

    def _rule_risk() -> tuple[int, str]:
        if decision["position_pct"] > 30:
            return 68, "仓位超过单票30%上限"
        if not decision.get("stop_loss"):
            return 68, "缺少止损条件"
        if not decision.get("trigger_exit"):
            return 72, "缺少离场触发条件"
        return 86, "通过"

    out, degraded = _safe_chat(prompts.RISK, user, "")
    if degraded or not out:
        score, feedback = _rule_risk()
    else:
        m = re.search(r"(?:评分|得分)[^\d]{0,4}(\d{1,3})", out)
        score = min(int(m.group(1)), 100) if m else 60
        fb = re.search(r"意见[：:]\s*(.+)", out)
        feedback = fb.group(1).strip() if fb else out.strip().splitlines()[-1]

    if red:   # 红线一票否决，不受模型评分影响
        score = min(score, 70)
        feedback = "；".join(red[:2])
        print(f"   🚨 [风控] 触发红线：{red[0]}")

    print(f"   🛡️  [风控] 评分 {score}/100{'（规则）' if degraded else ''}")
    return {"score": score, "feedback": feedback, "degraded": degraded}


def quality_gate(state: BenchState):
    if state["score"] >= 80:
        return "pass"
    if state.get("revisions", 0) >= 2:
        print("   ⚠️  返工次数已达上限，带当前版本提交投委会")
        return "pass"
    return "rework"


def rework(state: BenchState) -> dict:
    return {"revisions": state.get("revisions", 0) + 1}


def committee(state: BenchState) -> dict:
    d = state["decision"]
    user = (f"股票：{state['name']}({state['code']})\n最终决策：{json.dumps(d, ensure_ascii=False)}\n"
            f"风控评分：{state['score']}，意见：{state['feedback']}")
    fallback = (f"投委会结论：立场{d['stance']}，建议「{d['action']}」，仓位不超过 {d['position_pct']}%；"
                f"加仓触发：{d.get('trigger_buy', '未设')}；离场触发：{d.get('trigger_exit', '未设')}；"
                f"止损：{d.get('stop_loss', '未设')}。本结论由规则/模型生成，不构成投资建议。")
    content, degraded = _safe_chat(prompts.COMMITTEE, user, fallback)
    print(f"   🏛️  [投委会] 结论成文{'（规则降级）' if degraded else ''}")
    return {"committee_note": content, "degraded": degraded}


# ---------------------------------------------------------------- 组装

def build_graph():
    from .config import settings

    g = StateGraph(BenchState)
    g.add_node("prepare", prepare)
    g.add_node("analyst", analyst)
    g.add_node("debate_bull", debate_bull)
    g.add_node("debate_bear", debate_bear)
    g.add_node("trader", trader)
    g.add_node("risk", risk)
    g.add_node("rework", rework)
    g.add_node("committee", committee)

    g.add_edge(START, "prepare")
    g.add_conditional_edges("prepare", route_prepare, ["analyst", "__end__"])
    g.add_edge("analyst", "debate_bull")
    g.add_edge("debate_bull", "debate_bear")
    g.add_edge("debate_bear", "trader")
    g.add_edge("trader", "risk")
    g.add_conditional_edges("risk", quality_gate, {"pass": "committee", "rework": "rework"})
    g.add_edge("rework", "trader")
    g.add_edge("committee", END)
    return g.compile()


def run_one(code: str) -> dict:
    app = build_graph()
    return app.invoke({
        "code": code.strip(), "analyst_notes": [], "degraded": False,
        "revisions": 0, "score": 0, "feedback": "", "ok": True,
    })
