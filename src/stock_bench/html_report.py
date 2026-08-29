"""HTML 工作台：自包含单文件报告（内联 ECharts），离线双击即开。

红涨绿跌（A股惯例）。页面结构：
决策摘要 → K线(MA+量+MACD) → 资金流 → 财报(单季/年度/质量/分红) → 行业板块与同业
→ 研判流水线(分析师/多空/风控/投委会) → 公告新闻 → 附录
"""

import json
from datetime import date
from pathlib import Path

import pandas as pd

from .config import ROOT

ECHARTS_JS = (ROOT / "assets" / "echarts.min.js").read_text(encoding="utf-8")


# ---------------------------------------------------------------- payload

def _ma_series(df: pd.DataFrame, n: int) -> list:
    s = df["close"].rolling(n).mean()
    return [None if pd.isna(v) else round(float(v), 2) for v in s]


def build_payload(state: dict, mode_desc: str) -> dict:
    b = state["bundle"]
    ind = state["indicators"]
    d = state["decision"]
    df = b.kline

    from .diagnosis import diagnose
    from .indicators import macd_series

    dif, dea, hist = macd_series(df["close"])

    fin = b.fin or {}
    sector = b.sector or {}

    return {
        "meta": {
            "name": b.name, "code": b.code, "date": date.today().isoformat(),
            "mode": mode_desc, "degraded": bool(state.get("degraded")),
            "industry": sector.get("industry"), "region": sector.get("region"),
        },
        "quote": {
            "price": b.realtime.get("price"), "pct": b.realtime.get("change_pct"),
            "turnover": b.realtime.get("turnover_pct"), "vol_ratio": b.realtime.get("vol_ratio"),
            "pe": b.realtime.get("pe_ttm"), "pb": b.realtime.get("pb"),
            "mv_yi": b.realtime.get("total_mv_yi"), "amplitude": b.realtime.get("amplitude_pct"),
        },
        "decision": d,
        "risk": {"score": state.get("score"), "feedback": state.get("feedback", ""),
                 "revisions": state.get("revisions", 0)},
        "committee": state.get("committee_note", ""),
        "kline": {
            "dates": df["date"].tolist(),
            "ohlc": [[round(float(r.open), 2), round(float(r.close), 2),
                      round(float(r.low), 2), round(float(r.high), 2)] for r in df.itertuples()],
            "volumes": [round(float(v), 0) for v in df["volume_hand"]],
            "ma": {"MA5": _ma_series(df, 5), "MA10": _ma_series(df, 10),
                   "MA20": _ma_series(df, 20), "MA60": _ma_series(df, 60)},
            "macd": {"dif": dif, "dea": dea, "hist": hist},
        },
        "fundflow": b.fundflow or [],
        "fin": {"quarters": fin.get("quarters", []), "annual": fin.get("annual", []),
                "available": bool(fin.get("available"))},
        "sector": sector,
        "peers": b.peers,
        "notes": {n["role"]: n["content"] for n in state["analyst_notes"]},
        "bull": state.get("bull_case", ""),
        "bear": state.get("bear_case", ""),
        "announcements": b.announcements or [],
        "news": {"hits": b.news_hits, "macro": b.news_macro[:6]},
        "appendix": ind,
        "diagnosis": diagnose(ind, b),
        "pipeline": pipeline_block(state),
    }


def pipeline_block(state: dict) -> list:
    """每个 Agent 节点的关键输入 + 输出 + 核心结论数据，供总工作台全量透出。"""
    b = state["bundle"]
    ind = state["indicators"]
    fin = b.fin or {}
    s = b.sector or {}
    d = state["decision"]
    notes = {n["role"]: n["content"] for n in state["analyst_notes"]}
    latest = fin.get("latest") or {}
    peers = (b.peers or {}).get("stocks") or []

    from .sector import dividend_yield

    dy = dividend_yield(s.get("dividends", []), b.realtime.get("price"))

    return [{
        "role": "数据准备", "icon": "📡",
        "inputs": [f"{len(b.kline)} 根日K", f"公告 {len(b.announcements or [])} 条",
                   f"财报 {len(fin.get('quarters') or [])} 个单季",
                   f"行业：{s.get('industry') or '未知'}", f"概念 {len(s.get('concepts') or [])} 个",
                   f"同业 {len(peers)} 家", f"个股新闻 {len(b.news_hits)} 条"],
        "output": "行情 / 财报 / 板块 / 新闻数据包就绪，进入四分析师并行研判。",
        "core": {"现价": b.realtime.get("price"), "涨跌%": b.realtime.get("change_pct"),
                 "PE(TTM)": b.realtime.get("pe_ttm"), "PB": b.realtime.get("pb"),
                 "总市值(亿)": b.realtime.get("total_mv_yi")},
    }, {
        "role": "技术分析师", "icon": "📈",
        "inputs": [f"收盘 {ind['close']}", f"MA20 {ind['ma'][20]}", f"MA60 {ind['ma'][60]}",
                   f"RSI14 {ind['rsi14']}", f"MACD柱 {ind['macd']['hist']}",
                   f"60日分位 {ind['pos60_pct']}%", f"量比 {ind['vol_vs_ma5']}"],
        "output": notes.get("技术分析师", ""),
        "core": {"均线形态": ind["alignment"], "距60日高点%": ind["drawdown_from_60d_high_pct"],
                 "5日涨幅%": ind["ret_5d"], "20日年化波动%": ind["vol20_annualized_pct"]},
    }, {
        "role": "基本面分析师", "icon": "🏢",
        "inputs": [f"PE {b.realtime.get('pe_ttm')}", f"PB {b.realtime.get('pb')}",
                   f"市值 {b.realtime.get('total_mv_yi')} 亿", f"行业：{s.get('industry') or '未知'}",
                   f"股息率 {dy}%" if dy else "股息率 未计",
                   "同业：" + "、".join(p["name"] for p in peers[:4]) if peers else "同业：本次不可用"],
        "output": notes.get("基本面分析师", ""),
        "core": {},
    }, {
        "role": "财报分析师", "icon": "🧾",
        "inputs": ([f"{latest.get('label')} 营收 {latest.get('revenue_yi')} 亿（{latest.get('revenue_yoy')}%）",
                    f"净利 {latest.get('profit_yi')} 亿（{latest.get('profit_yoy')}%）",
                    f"ROE {latest.get('roe')}%", f"净利率 {latest.get('net_margin')}%"]
                   if latest else ["财报数据本次不可用"]),
        "output": notes.get("财报分析师", ""),
        "core": {"最新单季营收(亿)": latest.get("revenue_yi"), "最新单季净利(亿)": latest.get("profit_yi"),
                 "ROE%": latest.get("roe"), "负债率%": latest.get("debt_ratio")},
    }, {
        "role": "新闻与公告分析师", "icon": "📰",
        "inputs": ([f"[{a['date']}] {a['title']}" for a in (b.announcements or [])[:3]]
                   or ["近期无公告"]) + [f"个股新闻 {len(b.news_hits)} 条"],
        "output": notes.get("新闻与公告分析师", ""),
        "core": {},
    }, {
        "role": "多头研究员", "icon": "🐂",
        "inputs": ["四位分析师笔记 + 资金流"],
        "output": state.get("bull_case", ""), "core": {},
    }, {
        "role": "空头研究员", "icon": "🐻",
        "inputs": ["多头论点 + 全部材料（逐条反驳）"],
        "output": state.get("bear_case", ""), "core": {},
    }, {
        "role": "交易员", "icon": "🎯",
        "inputs": ["多空辩论 + 分析师笔记"],
        "output": d.get("reasoning", ""),
        "core": {"立场": d.get("stance"), "操作": d.get("action"), "置信度": d.get("confidence"),
                 "仓位上限%": d.get("position_pct"), "加仓触发": d.get("trigger_buy"),
                 "离场触发": d.get("trigger_exit"), "止损": d.get("stop_loss")},
    }, {
        "role": "风控管理员", "icon": "🛡️",
        "inputs": ["交易员决策 + 红线检查（仓位≤30% / 禁收益承诺 / 必须止损）"],
        "output": state.get("feedback", "") or "通过",
        "core": {"评分": state.get("score"), "重写次数": state.get("revisions", 0)},
    }, {
        "role": "投委会", "icon": "🏛️",
        "inputs": ["交易员最终决策 + 风控意见"],
        "output": state.get("committee_note", ""), "core": {},
    }]


# ---------------------------------------------------------------- 模板

_PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<script>__ECHARTS_JS__</script>
<style>
  :root{--up:#e64545;--down:#1e9e6a;--ink:#1c2333;--sub:#68738a;--line:#e4e8f0;
        --bg:#f4f6fa;--card:#fff;--accent:#2b4eff;--gold:#b8860b}
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:"PingFang SC","Microsoft YaHei",-apple-system,sans-serif;background:var(--bg);
       color:var(--ink);line-height:1.65;font-size:14px}
  .wrap{max-width:1180px;margin:0 auto;padding:20px 16px 60px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px 20px;margin-bottom:16px}
  h2{font-size:17px;margin-bottom:12px;display:flex;align-items:center;gap:8px}
  h2::before{content:"";width:4px;height:16px;background:var(--accent);border-radius:2px}
  h3{font-size:14px;color:var(--sub);margin:10px 0 6px}
  .muted{color:var(--sub);font-size:12px}
  .mdh{display:block;margin:8px 0 4px;font-weight:700}
  /* 头部 */
  .head{display:flex;flex-wrap:wrap;align-items:center;gap:18px}
  .head .name{font-size:26px;font-weight:700}
  .head .code{color:var(--sub);font-size:14px;margin-left:6px}
  .price{font-size:30px;font-weight:700;font-variant-numeric:tabular-nums}
  .up{color:var(--up)} .down{color:var(--down)}
  .chip{display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;background:#eef1f7;
        color:#44506b;margin:2px 4px 2px 0;border:1px solid var(--line)}
  .badge{padding:5px 14px;border-radius:8px;font-weight:700;font-size:15px;color:#fff}
  .b-bull{background:var(--up)} .b-bear{background:var(--down)} .b-flat{background:#8492ab}
  /* 决策卡片 */
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
  .kv{background:#f8fafd;border:1px solid var(--line);border-radius:8px;padding:10px 12px}
  .kv .k{font-size:12px;color:var(--sub)}
  .kv .v{font-size:16px;font-weight:700;margin-top:2px}
  /* 图表 */
  .chart{width:100%;height:420px}
  .chart-sm{width:100%;height:300px}
  .row2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
  @media(max-width:900px){.row2{grid-template-columns:1fr}}
  /* 表格 */
  table{width:100%;border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums}
  th{background:#f2f5fa;color:var(--sub);font-weight:600;text-align:right;padding:7px 10px;white-space:nowrap}
  td{padding:7px 10px;border-top:1px solid var(--line);text-align:right;white-space:nowrap}
  th:first-child,td:first-child{text-align:left}
  tr.self td{background:#fff8e6;font-weight:600}
  /* 流水线 */
  .notes{display:grid;grid-template-columns:1fr 1fr;gap:12px}
  @media(max-width:900px){.notes{grid-template-columns:1fr}}
  .note{border:1px solid var(--line);border-radius:8px;padding:12px 14px;background:#fbfcfe}
  .note .role{font-weight:700;margin-bottom:6px;color:var(--accent)}
  .note p{white-space:pre-wrap;font-size:13px}
  .debate{display:grid;grid-template-columns:1fr 1fr;gap:12px}
  @media(max-width:900px){.debate{grid-template-columns:1fr}}
  .bullbox{border-left:4px solid var(--up)} .bearbox{border-left:4px solid var(--down)}
  .committee{background:linear-gradient(135deg,#fffdf4,#fbf6e3);border:1px solid #eadfa8;
             border-radius:10px;padding:16px 18px}
  .committee p{white-space:pre-wrap}
  .riskline{margin-top:8px;font-size:13px;color:var(--sub)}
  .ann a{color:var(--accent);text-decoration:none}
  footer{color:var(--sub);font-size:12px;text-align:center;margin-top:24px}
</style>
</head>
<body>
<div class="wrap">

  <div class="card head" id="head"></div>

  <div class="card">
    <h2>投委会决议</h2>
    <div class="grid" id="decisionGrid"></div>
    <div id="levels" style="margin:12px 0 2px"></div>
    <div class="committee" style="margin-top:14px"><p id="committee"></p>
      <div class="riskline" id="riskline"></div></div>
  </div>

  <div class="card">
    <h2>量化诊断（规则引擎 · 评分依据全透明）</h2>
    <div class="row2">
      <div><h3>五维评分：趋势 / 动量 / 资金 / 财务质量 / 估值</h3><div id="radar" class="chart-sm"></div></div>
      <div><h3>综合分与置信度</h3><div id="gauge" class="chart-sm"></div>
        <div id="diagReasons" class="muted" style="font-size:12px;line-height:1.8"></div></div>
    </div>
  </div>

  <div class="card">
    <h2>日K走势（前复权 · 红涨绿跌）</h2>
    <div id="kline" class="chart" style="height:560px"></div>
  </div>

  <div class="row2">
    <div class="card"><h2>主力资金（近5日，亿元）</h2><div id="fundflow" class="chart-sm"></div></div>
    <div class="card"><h2>营收构成</h2><div id="revmix" class="chart-sm"></div></div>
  </div>

  <div class="card">
    <h2>财务分析（单季）</h2>
    <div class="row2">
      <div><h3>营收与归母净利（亿元）+ 同比</h3><div id="qfin" class="chart-sm"></div></div>
      <div><h3>盈利质量：ROE / 毛利率 / 净利率（%）</h3><div id="qmargin" class="chart-sm"></div></div>
    </div>
    <h3 style="margin-top:14px">年度趋势</h3>
    <div id="afin" class="chart-sm"></div>
    <h3 style="margin-top:14px">分红（按年度合计）</h3>
    <div id="divChart" class="chart-sm" style="height:210px"></div>
    <div id="divTable" style="margin-top:10px"></div>
  </div>

  <div class="card">
    <h2>行业板块与同业对比</h2>
    <div id="sectorChips"></div>
    <div id="peerChart" class="chart-sm" style="height:260px;margin-top:12px"></div>
    <div id="peers" style="margin-top:12px"></div>
  </div>

  <div class="card">
    <h2>分析师笔记</h2>
    <div class="notes" id="notes"></div>
  </div>

  <div class="card">
    <h2>多空辩论</h2>
    <div class="debate">
      <div class="note bullbox"><div class="role">🐂 多头研究员</div><p id="bull"></p></div>
      <div class="note bearbox"><div class="role">🐻 空头研究员</div><p id="bear"></p></div>
    </div>
  </div>

  <div class="card">
    <h2>公告与新闻</h2>
    <div class="ann" id="ann"></div>
  </div>

  <div class="card">
    <h2>技术面附录</h2>
    <div id="appendix"></div>
  </div>

  <footer>由 stock-research-bench 多Agent流水线自动生成 · 仅供研究参考，不构成投资建议<br>
  数据源：腾讯行情/新浪财报/东财（辅助）/财联社 · <span id="modeLine"></span></footer>
</div>

<script>
const P = __PAYLOAD__;
const UP = '#e64545', DOWN = '#1e9e6a';
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fmt = (v, n=2) => (v === null || v === undefined || isNaN(v)) ? '—' : Number(v).toFixed(n);
const pctCls = v => v > 0 ? 'up' : (v < 0 ? 'down' : '');
const md = s => esc(s||'')
  .replace(/^#{1,3}\s*(.+)$/gm,'<span class="mdh">$1</span>')
  .replace(/\*\*([^*]+)\*\*/g,'<b>$1</b>')
  .replace(/^\s*[-•]\s+/gm,'· ');
function extractLevels(p){
  const d = p.decision||{}, cur = (p.quote||{}).price||0, L = [];
  if(!cur) return L;
  const ok = v => v > cur*0.2 && v < cur*5;
  const nums = t => ((t||'').match(/\d+(?:\.\d+)?/g)||[]).map(Number).filter(ok);
  const lv = d.levels||{};
  if(lv.stop != null) L.push({v:lv.stop, tag:'止损', c:'#e64545'});
  else nums(d.stop_loss).slice(0,1).forEach(v=>L.push({v, tag:'止损', c:'#e64545'}));
  if(lv.pressure != null) L.push({v:lv.pressure, tag:'压力', c:'#f5a623'});
  else nums(d.trigger_exit).slice(0,2).forEach(v=>L.push({v, tag:'压力', c:'#f5a623'}));
  if(lv.support != null) L.push({v:lv.support, tag:'支撑', c:'#1e9e6a'});
  else nums(d.trigger_buy).slice(0,1).forEach(v=>L.push({v, tag:'支撑', c:'#1e9e6a'}));
  const seen = new Set();
  return L.filter(x=>!seen.has(x.v)&&seen.add(x.v));
}
function levelsHTML(p){
  const cur = (p.quote||{}).price||0, L = extractLevels(p);
  const chip = x => { const dd = (x.v/cur-1)*100;
    return `<span class="chip" style="border-color:${x.c};color:${x.c};font-weight:700">${x.tag} ${fmt(x.v)}（${dd>=0?'+':''}${dd.toFixed(1)}%）</span>`; };
  return `<span class="chip" style="font-weight:700">现价 ${fmt(cur)}</span>` + L.map(chip).join('');
}

/* ---------- 头部 ---------- */
(function(){
  const m = P.meta, q = P.quote, d = P.decision;
  const badge = d.stance.includes('多') ? 'b-bull' : (d.stance.includes('空') ? 'b-bear' : 'b-flat');
  document.getElementById('head').innerHTML =
    `<div><span class="name">${esc(m.name)}</span><span class="code">${esc(m.code)} · ${esc(m.date)}</span>
     <div style="margin-top:6px">${m.industry ? `<span class="chip">行业：${esc(m.industry)}</span>` : ''}
     ${m.region ? `<span class="chip">${esc(m.region)}</span>` : ''}${m.degraded ? '<span class="chip">⚠ 部分环节规则降级</span>' : ''}</div></div>
     <div style="margin-left:auto;text-align:right">
       <span class="price ${pctCls(q.pct)}">${fmt(q.price)}</span>
       <span class="${pctCls(q.pct)}" style="font-size:16px;font-weight:700">&nbsp;${q.pct > 0 ? '+' : ''}${fmt(q.pct)}%</span>
       <div class="muted">换手 ${fmt(q.turnover)}% ｜ 量比 ${fmt(q.vol_ratio)} ｜ PE ${fmt(q.pe)} ｜ PB ${fmt(q.pb)} ｜ 市值 ${fmt(q.mv_yi,0)} 亿</div>
     </div>
     <span class="badge ${badge}">${esc(d.stance)} · ${esc(d.action)}</span>`;
})();

/* ---------- 决策卡 ---------- */
(function(){
  const d = P.decision, r = P.risk;
  const items = [
    ['立场', d.stance], ['操作建议', d.action], ['置信度', d.confidence + ' / 100'],
    ['建议仓位上限', d.position_pct + '%'], ['风控评分', r.score + ' / 100'], ['重写次数', r.revisions],
    ['加仓触发', d.trigger_buy], ['离场触发', d.trigger_exit], ['止损参考', d.stop_loss],
  ];
  document.getElementById('decisionGrid').innerHTML = items.map(([k,v]) =>
    `<div class="kv"><div class="k">${esc(k)}</div><div class="v">${esc(v ?? '—')}</div></div>`).join('');
  document.getElementById('levels').innerHTML = levelsHTML(P);
  document.getElementById('committee').innerHTML = md(P.committee || '（无）');
  document.getElementById('riskline').textContent =
    `核心逻辑：${d.reasoning || '—'}　|　风控意见：${r.feedback || '通过'}`;
})();

/* ---------- K线 ---------- */
(function(){
  const k = P.kline;
  const chart = echarts.init(document.getElementById('kline'));
  chart.setOption({
    animation:false,
    axisPointer:{link:[{xAxisIndex:'all'}]},
    tooltip:{trigger:'axis', axisPointer:{type:'cross'}},
    legend:{data:['K线','MA5','MA10','MA20','MA60'], top:0},
    grid:[{left:56,right:20,top:30,height:'46%'},
          {left:56,right:20,top:'58%',height:'14%'},
          {left:56,right:20,top:'76%',height:'14%'}],
    xAxis:[{type:'category',data:k.dates,boundaryGap:true,axisLine:{lineStyle:{color:'#c8cfdd'}}},
           {type:'category',gridIndex:1,data:k.dates,axisLabel:{show:false}},
           {type:'category',gridIndex:2,data:k.dates,axisLabel:{show:false}}],
    yAxis:[{scale:true,splitLine:{lineStyle:{color:'#eef1f6'}}},
           {gridIndex:1,scale:true,splitLine:{show:false},axisLabel:{show:false}},
           {gridIndex:2,scale:true,splitLine:{show:false},axisLabel:{show:false}}],
    dataZoom:[{type:'inside',xAxisIndex:[0,1,2],start:30,end:100},
              {type:'slider',xAxisIndex:[0,1,2],bottom:0,height:18,start:30,end:100}],
    series:[
      {name:'K线',type:'candlestick',data:k.ohlc,
       itemStyle:{color:UP,color0:DOWN,borderColor:UP,borderColor0:DOWN},
       markLine:{symbol:'none',silent:true,animation:false,
         data:extractLevels(P).map(x=>({yAxis:x.v,
           label:{formatter:`${x.tag} ${x.v}`,position:'insideEndTop',fontSize:10,color:x.c},
           lineStyle:{color:x.c,type:'dashed',width:1.4}}))}},
      ...['MA5','MA10','MA20','MA60'].map((n,i)=>({
        name:n,type:'line',data:k.ma[n],smooth:true,showSymbol:false,
        lineStyle:{width:1.2,color:['#f5a623','#8e6cef','#2b4eff','#0aa2c0'][i]}})),
      {name:'成交量',type:'bar',xAxisIndex:1,yAxisIndex:1,data:k.volumes.map((v,i)=>({
        value:v,itemStyle:{color:k.ohlc[i][1]>=k.ohlc[i][0]?UP:DOWN}}))},
      {name:'MACD',type:'bar',xAxisIndex:2,yAxisIndex:2,data:k.macd.hist.map(v=>({
        value:v,itemStyle:{color:v>=0?UP:DOWN}}))},
      {name:'DIF',type:'line',xAxisIndex:2,yAxisIndex:2,data:k.macd.dif,showSymbol:false,lineStyle:{width:1,color:'#f5a623'}},
      {name:'DEA',type:'line',xAxisIndex:2,yAxisIndex:2,data:k.macd.dea,showSymbol:false,lineStyle:{width:1,color:'#2b4eff'}},
    ]
  });
  window.addEventListener('resize',()=>chart.resize());
})();

/* ---------- 资金流 ---------- */
(function(){
  const el = document.getElementById('fundflow');
  if(!P.fundflow.length){el.innerHTML='<div class="muted">东财资金流接口本次不可用</div>';return;}
  const chart = echarts.init(el);
  chart.setOption({
    tooltip:{trigger:'axis'},
    legend:{data:['主力','超大单','大单'],top:0},
    grid:{left:50,right:16,top:34,bottom:24},
    xAxis:{type:'category',data:P.fundflow.map(f=>f.date.slice(5))},
    yAxis:{type:'value',name:'亿元',splitLine:{lineStyle:{color:'#eef1f6'}}},
    series:[
      {name:'主力',type:'bar',data:P.fundflow.map(f=>({value:f.main_yi,itemStyle:{color:f.main_yi>=0?UP:DOWN}}))},
      {name:'超大单',type:'line',data:P.fundflow.map(f=>f.super_yi),lineStyle:{color:'#8e6cef'}},
      {name:'大单',type:'line',data:P.fundflow.map(f=>f.large_yi),lineStyle:{color:'#f5a623'}},
    ]
  });
  window.addEventListener('resize',()=>chart.resize());
})();

/* ---------- 营收构成 ---------- */
(function(){
  const el = document.getElementById('revmix');
  const mix = (P.sector.revenue_mix||[]);
  if(!mix.length){el.innerHTML='<div class="muted">暂无营收构成数据</div>';return;}
  const chart = echarts.init(el);
  chart.setOption({
    tooltip:{trigger:'item',formatter:'{b}：{c} 亿（{d}%）'},
    series:[{type:'pie',radius:['38%','68%'],center:['50%','54%'],
      label:{formatter:'{b}\n{d}%'},
      data:mix.map(m=>({name:m.segment,value:m.income_yi}))}]
  });
  window.addEventListener('resize',()=>chart.resize());
})();

/* ---------- 财报 ---------- */
(function(){
  const q = P.fin.quarters.slice(-8);
  const el = document.getElementById('qfin');
  if(!q.length){el.innerHTML='<div class="muted">财报数据暂不可用（新浪接口本次未返回）</div>';}
  else{
    const chart = echarts.init(el);
    chart.setOption({
      tooltip:{trigger:'axis'},
      legend:{data:['营收','归母净利','营收同比','净利同比'],top:0},
      grid:{left:50,right:52,top:34,bottom:24},
      xAxis:{type:'category',data:q.map(x=>x.label)},
      yAxis:[{type:'value',name:'亿元',splitLine:{lineStyle:{color:'#eef1f6'}}},
             {type:'value',name:'%',splitLine:{show:false}}],
      series:[
        {name:'营收',type:'bar',data:q.map(x=>x.revenue_yi),itemStyle:{color:'#2b4eff'},barMaxWidth:26},
        {name:'归母净利',type:'bar',data:q.map(x=>x.profit_yi),itemStyle:{color:'#f5a623'},barMaxWidth:26},
        {name:'营收同比',type:'line',yAxisIndex:1,data:q.map(x=>x.revenue_yoy),lineStyle:{color:'#0aa2c0'}},
        {name:'净利同比',type:'line',yAxisIndex:1,data:q.map(x=>x.profit_yoy),lineStyle:{color:'#e64545'}},
      ]
    });
    window.addEventListener('resize',()=>chart.resize());
  }

  const el2 = document.getElementById('qmargin');
  if(!q.length){el2.innerHTML='<div class="muted">同上</div>';}
  else{
    const chart = echarts.init(el2);
    chart.setOption({
      tooltip:{trigger:'axis'},
      legend:{data:['ROE','毛利率','净利率','负债率'],top:0},
      grid:{left:46,right:16,top:34,bottom:24},
      xAxis:{type:'category',data:q.map(x=>x.label)},
      yAxis:{type:'value',name:'%',splitLine:{lineStyle:{color:'#eef1f6'}}},
      series:[
        {name:'ROE',type:'line',data:q.map(x=>x.roe),lineStyle:{color:'#e64545'}},
        {name:'毛利率',type:'line',data:q.map(x=>x.gross_margin),lineStyle:{color:'#2b4eff'}},
        {name:'净利率',type:'line',data:q.map(x=>x.net_margin),lineStyle:{color:'#f5a623'}},
        {name:'负债率',type:'line',data:q.map(x=>x.debt_ratio),lineStyle:{color:'#8e6cef',type:'dashed'}},
      ]
    });
    window.addEventListener('resize',()=>chart.resize());
  }

  const a = P.fin.annual;
  const el3 = document.getElementById('afin');
  if(!a.length){el3.innerHTML='<div class="muted">暂无年度数据</div>';}
  else{
    const chart = echarts.init(el3);
    chart.setOption({
      tooltip:{trigger:'axis'},
      legend:{data:['营收','净利','净利同比'],top:0},
      grid:{left:56,right:52,top:34,bottom:24},
      xAxis:{type:'category',data:a.map(x=>x.period.slice(0,4))},
      yAxis:[{type:'value',name:'亿元',splitLine:{lineStyle:{color:'#eef1f6'}}},
             {type:'value',name:'%',splitLine:{show:false}}],
      series:[
        {name:'营收',type:'bar',data:a.map(x=>x.revenue_yi),itemStyle:{color:'#2b4eff'},barMaxWidth:40},
        {name:'净利',type:'bar',data:a.map(x=>x.profit_yi),itemStyle:{color:'#f5a623'},barMaxWidth:40},
        {name:'净利同比',type:'line',yAxisIndex:1,data:a.map(x=>x.profit_yoy),lineStyle:{color:'#e64545'}},
      ]
    });
    window.addEventListener('resize',()=>chart.resize());
  }

  const div = P.sector.dividends || [];
  document.getElementById('divTable').innerHTML = div.length ?
    `<h3>分红记录（每10股）</h3><table><tr><th>年度</th><th>派息(元/10股)</th><th>除权日</th></tr>` +
    div.slice(0,5).map(d=>`<tr><td>${esc(d.year)}</td><td>${fmt(d.per_10_share)}</td><td>${esc(d.ex_date)}</td></tr>`).join('') +
    `</table>` : '';
})();

/* ---------- 板块与同业 ---------- */
(function(){
  const s = P.sector;
  let html = `<span class="chip">行业：${esc(s.industry||'未知')}</span><span class="chip">地域：${esc(s.region||'未知')}</span>` +
    (s.concepts||[]).slice(0,14).map(c=>`<span class="chip">${esc(c)}</span>`).join('');
  document.getElementById('sectorChips').innerHTML = html;

  const p = P.peers;
  const el = document.getElementById('peers');
  if(!p || !(p.stocks||[]).length){
    el.innerHTML = '<div class="muted">同业数据暂不可用（东财板块接口限流），不影响其他分析</div>'; return;
  }
  el.innerHTML = `<h3>${esc(p.board)} · 按市值排序 ${p.cached ? '<span class="chip">缓存 '+esc(p.asof)+'</span>' : ''}</h3>
    <table><tr><th>公司</th><th>代码</th><th>现价</th><th>涨跌%</th><th>PE(TTM)</th><th>总市值(亿)</th></tr>` +
    p.stocks.map(x=>`<tr class="${x.is_self?'self':''}"><td>${esc(x.name)}${x.is_self?' ★':''}</td><td>${esc(x.code)}</td>
      <td>${fmt(x.price)}</td><td class="${pctCls(x.pct)}">${x.pct>0?'+':''}${fmt(x.pct)}</td>
      <td>${fmt(x.pe)}</td><td>${fmt(x.mv_yi,0)}</td></tr>`).join('') + `</table>`;
})();

/* ---------- 分析师与辩论 ---------- */
(function(){
  const order = ['技术分析师','基本面分析师','财报分析师','新闻与公告分析师'];
  document.getElementById('notes').innerHTML = order.filter(r=>P.notes[r]).map(r=>
    `<div class="note"><div class="role">${esc(r)}</div><p>${md(P.notes[r])}</p></div>`).join('');
  document.getElementById('bull').innerHTML = md(P.bull || '（无）');
  document.getElementById('bear').innerHTML = md(P.bear || '（无）');
})();

/* ---------- 公告新闻 ---------- */
(function(){
  let html = '<h3>近期公告</h3>';
  html += P.announcements.length ?
    P.announcements.slice(0,6).map(a=>`<div>· [${esc(a.date)}] <a href="${esc(a.url)}" target="_blank">${esc(a.title)}</a></div>`).join('')
    : '<div class="muted">近期无公告（或东财公告接口暂不可用）</div>';
  if((P.news.hits||[]).length){
    html += '<h3>近期提及</h3>' + P.news.hits.slice(0,6).map(t=>`<div>· ${esc(t)}</div>`).join('');
  }
  if((P.news.macro||[]).length){
    html += '<h3>市场要闻</h3>' + P.news.macro.map(t=>`<div class="muted">· ${esc(t)}</div>`).join('');
  }
  document.getElementById('ann').innerHTML = html;
})();

/* ---------- 量化诊断 ---------- */
(function(){
  const dg = P.diagnosis;
  if(!dg){document.getElementById('radar').innerHTML='<div class="muted">诊断不可用</div>';return;}
  const radar = echarts.init(document.getElementById('radar'));
  radar.setOption({
    tooltip:{},
    radar:{indicator:dg.labels.map(l=>({name:l,max:100})),radius:'66%',
      splitArea:{areaStyle:{color:['#f8fafd','#ffffff']}},
      axisName:{color:'#44506b',fontSize:12}},
    series:[{type:'radar',symbolSize:4,data:[{value:dg.values,name:'当前评分',
      areaStyle:{color:'rgba(43,78,255,.16)'},
      lineStyle:{color:'#2b4eff',width:2},itemStyle:{color:'#2b4eff'}}]}]
  });
  const gaugeOpt = (val,title) => ({
    type:'gauge',startAngle:210,endAngle:-30,min:0,max:100,radius:'72%',
    axisLine:{lineStyle:{width:14,color:[[0.3,'#1e9e6a'],[0.6,'#8492ab'],[1,'#e64545']]}},
    pointer:{show:false},axisTick:{show:false},splitLine:{show:false},axisLabel:{show:false},
    detail:{formatter:'{value}',offsetCenter:[0,'-8%'],fontSize:30,fontWeight:700,color:'#1c2333'},
    title:{show:true,offsetCenter:[0,'34%'],fontSize:12,color:'#68738a'},
    data:[{value:val,name:title}]});
  const gauge = echarts.init(document.getElementById('gauge'));
  gauge.setOption({series:[
    Object.assign({center:['27%','55%']},gaugeOpt(dg.overall,'综合分（'+dg.grade+'）')),
    Object.assign({center:['73%','55%']},gaugeOpt(P.decision.confidence||0,'投委会置信度')),
  ]});
  document.getElementById('diagReasons').innerHTML =
    dg.labels.map((l,i)=>`<div><b>${l} ${dg.values[i]}</b>｜${dg.reasons[l].join('；')}</div>`).join('');
  window.addEventListener('resize',()=>{radar.resize();gauge.resize();});
})();

/* ---------- 同业对比图 ---------- */
(function(){
  const el = document.getElementById('peerChart');
  const p = P.peers;
  if(!p || !(p.stocks||[]).length){el.style.display='none';return;}
  const stocks = p.stocks.slice(0,8);
  const chart = echarts.init(el);
  chart.setOption({
    tooltip:{trigger:'axis'},
    legend:{data:['总市值(亿)','PE(TTM)'],top:0},
    grid:{left:60,right:52,top:34,bottom:48},
    xAxis:{type:'category',data:stocks.map(s=>s.name),axisLabel:{rotate:22,fontSize:11}},
    yAxis:[{type:'value',name:'亿',splitLine:{lineStyle:{color:'#eef1f6'}}},
           {type:'value',name:'PE',splitLine:{show:false}}],
    series:[
      {name:'总市值(亿)',type:'bar',barMaxWidth:30,data:stocks.map(s=>({value:s.mv_yi,
        itemStyle:{color:s.is_self?'#e64545':'#2b4eff'}}))},
      {name:'PE(TTM)',type:'line',yAxisIndex:1,data:stocks.map(s=>s.pe),
        lineStyle:{color:'#f5a623'},itemStyle:{color:'#f5a623'}},
    ]
  });
  window.addEventListener('resize',()=>chart.resize());
})();

/* ---------- 分红图 ---------- */
(function(){
  const el = document.getElementById('divChart');
  const divs = P.sector.dividends || [];
  if(!divs.length){el.style.display='none';return;}
  const byYear = {};
  divs.forEach(d=>{byYear[d.year]=(byYear[d.year]||0)+(d.per_10_share||0);});
  const years = Object.keys(byYear).sort().slice(-6);
  const chart = echarts.init(el);
  chart.setOption({
    tooltip:{trigger:'axis',formatter:ps=>ps[0].name+' 年度合计派息：'+ps[0].value+' 元/10股'},
    grid:{left:56,right:20,top:30,bottom:24},
    xAxis:{type:'category',data:years},
    yAxis:{type:'value',name:'元/10股',splitLine:{lineStyle:{color:'#eef1f6'}}},
    series:[{type:'bar',barMaxWidth:42,itemStyle:{color:'#b8860b'},
      data:years.map(y=>+byYear[y].toFixed(2)),
      label:{show:true,position:'top',formatter:'{c}'}}]
  });
  window.addEventListener('resize',()=>chart.resize());
})();

/* ---------- 附录 ---------- */
(function(){
  const a = P.appendix;
  const rows = [
    ['MA5/10/20/60', `${fmt(a.ma[5])} / ${fmt(a.ma[10])} / ${fmt(a.ma[20])} / ${fmt(a.ma[60])}（${esc(a.alignment)}）`],
    ['RSI14', fmt(a.rsi14,1)], ['MACD 柱', fmt(a.macd.hist,3)],
    ['20日年化波动率', fmt(a.vol20_annualized_pct,1)+'%'],
    ['60日区间分位', fmt(a.pos60_pct,1)+'%（'+fmt(a.low60)+' ~ '+fmt(a.high60)+'）'],
    ['距60日高点回撤', fmt(a.drawdown_from_60d_high_pct)+'%'],
    ['5日/20日/60日涨幅', `${fmt(a.ret_5d)}% / ${fmt(a.ret_20d)}% / ${fmt(a.ret_60d)}%`],
    ['量比（当日/5日均量）', fmt(a.vol_vs_ma5)],
  ];
  document.getElementById('appendix').innerHTML =
    `<table>${rows.map(([k,v])=>`<tr><td style="width:200px;color:#68738a">${esc(k)}</td><td>${v}</td></tr>`).join('')}</table>`;
  document.getElementById('modeLine').textContent = P.meta.mode;
})();
</script>
</body>
</html>
"""


def render_html(state: dict, mode_desc: str, as_date: str | None = None) -> str:
    payload = build_payload(state, mode_desc)
    if as_date:
        payload["meta"]["date"] = as_date
    payload_json = json.dumps(payload, ensure_ascii=False, default=str).replace("</", "<\\/")
    title = f"{payload['meta']['name']}（{payload['meta']['code']}）研判工作台 · {payload['meta']['date']}"
    return (_PAGE
            .replace("__TITLE__", title)
            .replace("__ECHARTS_JS__", ECHARTS_JS)
            .replace("__PAYLOAD__", payload_json))


def save_html(state: dict, mode_desc: str, as_date: str | None = None) -> Path:
    b = state["bundle"]
    d = as_date or date.today().isoformat()
    path = ROOT / "reports" / f"{d}_{b.code}_{b.name}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_html(state, mode_desc, as_date), encoding="utf-8")
    return path


def summary_json(state: dict) -> dict:
    b = state["bundle"]
    d = state["decision"]
    return {
        "date": date.today().isoformat(), "code": b.code, "name": b.name,
        "price": b.realtime.get("price"), "pct": b.realtime.get("change_pct"),
        "industry": (b.sector or {}).get("industry"),
        "stance": d["stance"], "action": d["action"],
        "confidence": d.get("confidence"), "position_pct": d.get("position_pct"),
        "risk_score": state.get("score"), "revisions": state.get("revisions", 0),
    }


def build_index() -> Path:
    """扫描 reports/ 生成 index.html：每票最新研判 + 历史链接。"""
    rep = ROOT / "reports"
    latest: dict = {}
    history: dict = {}
    for f in sorted(rep.glob("*.html")):
        if f.name == "index.html":
            continue
        parts = f.stem.split("_", 2)
        if len(parts) < 3:
            continue
        d, code = parts[0], parts[1]
        history.setdefault(code, []).append((d, f.name))
        if code not in latest or d > latest[code][0]:
            latest[code] = (d, f.name)

    rows = []
    for code, (d, fname) in sorted(latest.items()):
        sidecar = rep / f"summary_{d}_{code}.json"
        s = {}
        if sidecar.exists():
            try:
                s = json.loads(sidecar.read_text(encoding="utf-8"))
            except ValueError:
                pass
        cls = "up" if (s.get("pct") or 0) > 0 else ("down" if (s.get("pct") or 0) < 0 else "")
        badge = {"偏多": "b-bull", "偏空": "b-bear"}.get(s.get("stance"), "b-flat")
        hist_links = " · ".join(
            f'<a href="{fn}">{dd[5:]}</a>' for dd, fn in sorted(history[code], reverse=True)[:7])
        rows.append(f"""<tr>
          <td><a class="main" href="{fname}"><b>{s.get('name', code)}</b>（{code}）</a></td>
          <td>{s.get('industry') or '—'}</td>
          <td class="{cls}">{s.get('price') or '—'}</td>
          <td class="{cls}">{('+' if (s.get('pct') or 0) > 0 else '')}{s.get('pct') if s.get('pct') is not None else '—'}%</td>
          <td><span class="badge {badge}">{s.get('stance', '?')} · {s.get('action', '?')}</span></td>
          <td>{s.get('confidence') if s.get('confidence') is not None else '—'}</td>
          <td class="muted">{hist_links}</td></tr>""")

    html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>股票研判工作台</title><style>
body{{font-family:"PingFang SC","Microsoft YaHei",sans-serif;background:#f4f6fa;color:#1c2333;margin:0}}
.wrap{{max-width:1180px;margin:0 auto;padding:28px 16px}}
h1{{font-size:22px}} .muted{{color:#68738a;font-size:12px}}
table{{width:100%;border-collapse:collapse;background:#fff;border:1px solid #e4e8f0;border-radius:10px;overflow:hidden}}
th{{background:#f2f5fa;color:#68738a;padding:10px 12px;text-align:left;font-size:13px}}
td{{padding:12px;border-top:1px solid #eef1f6;font-size:14px}}
a{{color:#2b4eff;text-decoration:none}} a.main{{font-size:15px}}
.badge{{padding:4px 10px;border-radius:6px;color:#fff;font-size:12px;font-weight:700}}
.b-bull{{background:#e64545}} .b-bear{{background:#1e9e6a}} .b-flat{{background:#8492ab}}
.up{{color:#e64545;font-weight:600}} .down{{color:#1e9e6a;font-weight:600}}
</style></head><body><div class="wrap">
<h1>📊 股票研判工作台</h1>
<div class="muted">每个交易日 17:30 自动更新 · 多Agent流水线：分析师×4 → 多空辩论 → 交易员 → 风控 → 投委会 · 仅供研究参考</div>
<table style="margin-top:16px"><tr><th>标的</th><th>行业</th><th>现价</th><th>涨跌</th>
<th>投委会决策</th><th>置信度</th><th>历史</th></tr>{''.join(rows)}</table>
<div class="muted" style="margin-top:14px">更新于 {date.today().isoformat()} · stock-research-bench</div>
</div></body></html>"""
    out = rep / "index.html"
    out.write_text(html, encoding="utf-8")
    return out
