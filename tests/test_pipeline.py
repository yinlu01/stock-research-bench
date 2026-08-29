"""端到端测试：全部用 mock/fixture，不联网不烧 token。

覆盖：
1. 编排全流程（含风控打回→重写→通过的质检回环）
2. 交易员仓位纪律（超限必被钳到 30% 以下）
3. 红线一票否决（重仓/不设止损必被打回）
4. 技术指标计算正确性
5. 股票代码归一化
"""

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ["MA_MOCK"] = "1"          # 必须在导入 stock_bench 前设置


@pytest.fixture(scope="module")
def fixture_bundle():
    """手工构造 90 根日K的 bundle，绕开网络。"""
    from stock_bench.data_feed import StockBundle

    rng = np.random.default_rng(42)
    n = 90
    close = 1200 + np.cumsum(rng.normal(1.2, 12, n))
    close = np.maximum(close, 900)
    df = pd.DataFrame({
        "date": pd.date_range("2026-04-01", periods=n).strftime("%Y-%m-%d"),
        "open": close * (1 + rng.normal(0, 0.004, n)),
        "close": close,
        "high": close * (1 + np.abs(rng.normal(0, 0.008, n))),
        "low": close * (1 - np.abs(rng.normal(0, 0.008, n))),
        "volume_hand": rng.uniform(12000, 26000, n),
    })
    b = StockBundle(code="600519", symbol="sh600519", name="贵州茅台",
                    realtime={"price": float(close[-1]), "change_pct": 0.39,
                              "turnover_pct": 0.13, "pe_ttm": 19.9, "pb": 6.8,
                              "total_mv_yi": 16218.0, "float_mv_yi": 16218.0,
                              "amplitude_pct": 0.77},
                    kline=df,
                    profile={"main_business": "贵州茅台系列产品的生产与销售",
                             "listed_date": "2001-08-27"},
                    fundflow=[{"date": f"2026-08-{24+i}", "main_yi": [1.2, -0.4, 2.1, -0.8, 1.5][i],
                               "small_yi": 0.01, "mid_yi": 0.3, "large_yi": 0.5, "super_yi": 0.7}
                              for i in range(5)],
                    announcements=[{"date": "2026-08-15", "title": "贵州茅台2026年半年度报告摘要",
                                    "url": "https://example.com"}],
                    news_hits=["[2026-08-28 10:02] 贵州茅台获北向资金增持"],
                    news_macro=["[2026-08-28 09:00] 市场要闻示例"])
    b.sector = {
        "industry": "酿酒", "region": "贵州", "plate": ["酿酒"],
        "concepts": ["上证50", "沪深300", "融资融券"],
        "revenue_mix": [{"segment": "酒类", "income_yi": 1687.8},
                        {"segment": "其他", "income_yi": 0.6}],
        "dividends": [{"year": "2025", "per_10_share": 280.24, "ex_date": "2026-06-26"},
                      {"year": "2025", "per_10_share": 239.57, "ex_date": "2025-12-19"}],
    }
    b.peers = {"board": "酿酒行业", "asof": "2026-08-28", "cached": False, "stocks": [
        {"code": "600519", "name": "贵州茅台", "price": 1297.4, "pct": 0.39,
         "pe": 19.9, "mv_yi": 16218.0, "is_self": True},
        {"code": "000858", "name": "五粮液", "price": 128.5, "pct": -0.62,
         "pe": 14.2, "mv_yi": 4988.0, "is_self": False},
    ]}
    b.fin = {
        "available": True,
        "quarters": [
            {"label": f"2025Q{i}", "period": f"2025{m}", "revenue_yi": 380 + i * 10,
             "profit_yi": 190 + i * 5, "revenue_yoy": 12.0 - i, "profit_yoy": 10.0 - i,
             "roe": 8.2, "gross_margin": 91.5, "net_margin": 50.1, "debt_ratio": 17.5}
            for i, m in ((1, "0331"), (2, "0630"), (3, "0930"), (4, "1231"))
        ],
        "annual": [
            {"label": str(y), "period": f"{y}1231", "revenue_yi": 1500 + (y - 2023) * 150,
             "profit_yi": 750 + (y - 2023) * 70, "revenue_yoy": 15.0, "profit_yoy": 13.0,
             "debt_ratio": 17.8}
            for y in (2023, 2024, 2025)
        ],
        "latest": None, "annual_summary": None,
    }
    b.fin["latest"] = b.fin["quarters"][-1]
    return b


@pytest.fixture(scope="module")
def final_state(fixture_bundle, monkeypatch_module):
    from stock_bench import graph
    from stock_bench.graph import build_graph

    monkeypatch_module.setattr(graph, "collect", lambda *a, **k: fixture_bundle)
    app = build_graph()
    return app.invoke({"code": "600519", "analyst_notes": [], "degraded": False,
                       "revisions": 0, "score": 0, "feedback": "", "ok": True})


@pytest.fixture(scope="module")
def monkeypatch_module():
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()


def test_full_pipeline(final_state):
    s = final_state
    assert s["ok"] is True
    assert len(s["analyst_notes"]) == 4
    assert {n["role"] for n in s["analyst_notes"]} == {
        "技术分析师", "基本面分析师", "财报分析师", "新闻与公告分析师"}
    assert s["bull_case"] and s["bear_case"]
    assert s["committee_note"]


def test_review_loop_triggered(final_state):
    """mock 第一轮故意给 72 分+重仓表述 → 必须打回重写一次。"""
    assert final_state["revisions"] >= 1
    assert final_state["score"] >= 80


def test_position_discipline(final_state):
    assert 0 <= final_state["decision"]["position_pct"] <= 30


def test_no_red_line_in_final(final_state):
    from stock_bench.rules import red_line_check

    assert red_line_check(final_state["decision_raw"]) == []


def test_indicators_math(fixture_bundle):
    from stock_bench.indicators import compute

    ind = compute(fixture_bundle.kline)
    assert ind["ma"][5] > 0
    assert 0 <= ind["rsi14"] <= 100
    assert ind["pos60_pct"] >= 0
    assert ind["alignment"] in ("多头排列", "空头排列", "均线纠缠")


def test_code_normalize():
    from stock_bench.data_feed import normalize_code

    assert normalize_code("600519")["symbol"] == "sh600519"
    assert normalize_code("300750")["symbol"] == "sz300750"
    assert normalize_code("sh600519")["secid"] == "1.600519"
    assert normalize_code("830799")["symbol"] == "bj830799"


def test_red_lines():
    from stock_bench.rules import red_line_check

    assert len(red_line_check('{"action": "重仓买入"}')) == 1
    assert len(red_line_check("不设止损")) == 1
    assert red_line_check("建议仓位 20%，跌破止损离场") == []


def test_render_and_save(final_state, tmp_path):
    from stock_bench import report as rp

    text = rp.render(final_state, "MOCK 模式（不调用 API）")
    for keyword in ("投委会结论", "多空辩论", "财务分析", "行业板块与同业", "资金流", "公告与新闻", "不构成投资建议"):
        assert keyword in text


def test_quarter_math():
    """累计值 → 单季：2026Q2 单季 = 中报累计 - 一季报累计；同比对去年同期单季。"""
    from stock_bench.finance import build_quarters

    income = pd.DataFrame([
        {"period": "20250331", "revenue": 100e8, "net_profit": 40e8},
        {"period": "20250630", "revenue": 260e8, "net_profit": 100e8},   # Q2 累计
        {"period": "20260331", "revenue": 120e8, "net_profit": 44e8},
        {"period": "20260630", "revenue": 300e8, "net_profit": 112e8},
    ])
    qs = {q["label"]: q for q in build_quarters(income)}
    assert qs["2025Q2"]["revenue_yi"] == 160.0          # 260-100
    assert qs["2026Q2"]["revenue_yi"] == 180.0          # 300-120
    assert qs["2026Q2"]["revenue_yoy"] == 12.5          # 180/160-1
    assert qs["2026Q2"]["profit_yoy"] == round((68 / 60 - 1) * 100, 1)
    assert qs["2026Q1"]["revenue_yi"] == 120.0          # 一季度即累计


def test_render_html(final_state):
    from stock_bench import html_report as hr

    html = hr.render_html(final_state, "MOCK 模式（不调用 API）")
    assert "echarts" in html.lower()
    assert "__PAYLOAD__" not in html and "__ECHARTS_JS__" not in html and "__TITLE__" not in html
    assert "贵州茅台" in html
    assert "投委会决议" in html and "财务分析（单季）" in html
    assert "量化诊断" in html and "radar" in html
    payload_start = html.index("const P = ") + len("const P = ")
    payload_end = html.index(";\nconst UP")
    payload = json.loads(html[payload_start:payload_end])   # payload 必须是合法 JSON
    assert len(payload["diagnosis"]["values"]) == 5
    assert 0 <= payload["diagnosis"]["overall"] <= 100


def test_diagnosis(final_state):
    """五维评分必须在 0-100 之间，且每一维都有可读的评分依据。"""
    from stock_bench.diagnosis import diagnose

    d = diagnose(final_state["indicators"], final_state["bundle"])
    assert len(d["labels"]) == 5 and len(d["values"]) == 5
    assert all(0 <= v <= 100 for v in d["values"])
    assert all(d["reasons"][k] for k in d["labels"])
    assert d["grade"] in ("强", "较强", "中性", "较弱", "弱")


def test_persist_roundtrip(final_state):
    """状态落盘 → 读回 → 能重新渲染出同样的工作台（不碰网络）。"""
    from stock_bench import html_report as hr
    from stock_bench import persist

    path = persist.save_state(final_state, "MOCK 模式（不调用 API）")
    assert path.exists()
    state2 = persist.load_state(path)
    assert state2["bundle"].code == "600519"
    assert len(state2["analyst_notes"]) == 4
    html = hr.render_html(state2, "（重建）", state2.get("_date"))
    assert "贵州茅台" in html and "量化诊断" in html
    path.unlink()


def test_summary_json(final_state):
    from stock_bench import html_report as hr

    s = hr.summary_json(final_state)
    assert s["code"] == "600519" and s["name"] == "贵州茅台"
    assert s["stance"] and s["action"] and 0 <= s["position_pct"] <= 30


def test_master_workbench(final_state):
    """总工作台：大盘 + 自选总览 + 每只票的流水线全记录都要在页面里。"""
    from stock_bench import master_report as mr

    html = mr.build_master([final_state], {"asof": "t", "indices": []}, "MOCK")
    assert "大盘温度" in html and "自选股监测总览" in html and "持仓与组合风险" in html
    assert "Agent 流水线全记录" in html
    payload_start = html.index("const P = ") + len("const P = ")
    payload_end = html.index(";\nconst UP")
    p = json.loads(html[payload_start:payload_end])
    assert len(p["stocks"]) == 1
    roles = [n["role"] for n in p["stocks"][0]["pipeline"]]
    assert roles == ["数据准备", "技术分析师", "基本面分析师", "财报分析师",
                     "新闻与公告分析师", "多头研究员", "空头研究员",
                     "交易员", "风控管理员", "投委会"]
    trader = p["stocks"][0]["pipeline"][7]
    assert trader["core"]["操作"] and trader["core"]["止损"]

def test_temperature_mapping():
    from stock_bench import market as mk

    assert mk._dev_score(0) == 50
    assert mk._dev_score(3) == 100 and mk._dev_score(-3) == 0
    assert mk._vol_score(1.5) == 100 and mk._vol_score(0.5) == 0
    assert mk.temperature_label(10) == "冰" and mk.temperature_label(50) == "温"
    assert mk.temperature_label(85) == "过热"


def test_sentiment_rule_scoring():
    from stock_bench.sentiment import rule_score

    focus = [{"name": "半导体", "weight": 2, "keywords": ["光刻", "芯片"]}]
    pool = [
        {"text": "美国拟扩大光刻设备出口管制", "when": "t1"},
        {"text": "某公司签约新芯片产线", "when": "t2"},
        {"text": "与关注点无关的农业新闻", "when": "t3"},
    ]
    scored = rule_score(pool, focus, ["宁德时代"])
    assert scored[0]["text"].startswith("美国")          # 光刻 weight2 且先命中
    assert all(s["text"] != "与关注点无关的农业新闻" for s in scored)


def test_portfolio_risk_alerts():
    from types import SimpleNamespace

    from stock_bench.portfolio import build_portfolio, parse_price

    assert parse_price("跌破344.75元止损", 368.5) == 344.75
    assert parse_price("幅度约-8%", 368.5) is None

    def _st(code, name, price, industry, action="持有"):
        return {"bundle": SimpleNamespace(
                    name=name, realtime={"price": price, "change_pct": 0.5},
                    sector={"industry": industry}),
                "decision": {"stance": "中性", "action": action,
                             "levels": {"stop": price * 0.92},
                             "stop_loss": f"跌破{price * 0.92:.2f}止损"}}

    states = {"300750": _st("300750", "宁德时代", 400, "电池"),
              "002594": _st("002594", "比亚迪", 100, "电池")}
    holdings = [{"code": "300750", "shares": 400, "cost_price": 344.75},
                {"code": "002594", "shares": 800, "cost_price": 110}]
    pf = build_portfolio(states, holdings)
    assert pf is not None and len(pf["rows"]) == 2
    assert any("同赛道重叠" in a for a in pf["alerts"])      # 两只同属电池
    assert pf["rows"][0]["pnl_pct"] == round((400 / 344.75 - 1) * 100, 1)


def test_position_trader_prompt():
    from stock_bench import prompts

    assert "加仓|持有|减仓|清仓" in prompts.POSITION_TRADER
    assert "已持有" in prompts.POSITION_TRADER
