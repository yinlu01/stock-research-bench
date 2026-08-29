"""总工作台：一页汇总大盘行情 + 自选股总览 + 每只票的图表与 Agent 流水线全记录。

替代旧版 index.html，成为 reports/index.html。
"""

import json
from datetime import date
from pathlib import Path

from .config import ROOT
from .html_report import ECHARTS_JS, build_payload

_MASTER = r"""<!DOCTYPE html>
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
  .wrap{max-width:1240px;margin:0 auto;padding:20px 16px 60px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px 20px;margin-bottom:16px}
  h2{font-size:17px;margin-bottom:12px;display:flex;align-items:center;gap:8px}
  h2::before{content:"";width:4px;height:16px;background:var(--accent);border-radius:2px}
  h3{font-size:14px;color:var(--sub);margin:10px 0 6px}
  .muted{color:var(--sub);font-size:12px}
  .mdh{display:block;margin:8px 0 4px;font-weight:700}
  .up{color:var(--up)} .down{color:var(--down)}
  .chip{display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;background:#eef1f7;
        color:#44506b;margin:2px 4px 2px 0;border:1px solid var(--line)}
  .badge{padding:4px 12px;border-radius:8px;font-weight:700;font-size:13px;color:#fff;white-space:nowrap}
  .b-bull{background:var(--up)} .b-bear{background:var(--down)} .b-flat{background:#8492ab}
  /* 大盘 */
  .mkt{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}
  .mkt .idx{border:1px solid var(--line);border-radius:10px;padding:12px 14px;background:#fbfcfe}
  .mkt .idx .n{font-weight:700}
  .mkt .idx .p{font-size:22px;font-weight:700;font-variant-numeric:tabular-nums}
  .spark{width:100%;height:64px}
  /* 自选总览 */
  .watch{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:12px}
  .wcard{border:1px solid var(--line);border-radius:10px;padding:14px 16px;background:#fbfcfe}
  .wcard .top{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
  .wcard .name{font-size:18px;font-weight:700}
  .wcard .price{font-size:20px;font-weight:700;margin-left:auto}
  .kvrow{display:flex;flex-wrap:wrap;gap:6px 18px;margin-top:8px;font-size:13px}
  .kvrow b{font-variant-numeric:tabular-nums}
  /* 个股区 */
  .stockhead{display:flex;align-items:center;gap:14px;flex-wrap:wrap;border-bottom:2px solid var(--accent);
             padding-bottom:10px;margin-bottom:14px}
  .stockhead .name{font-size:24px;font-weight:800}
  .row2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
  @media(max-width:900px){.row2{grid-template-columns:1fr}}
  .chart{width:100%;height:420px}
  .chart-sm{width:100%;height:280px}
  table{width:100%;border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums}
  th{background:#f2f5fa;color:var(--sub);font-weight:600;text-align:right;padding:6px 10px;white-space:nowrap}
  td{padding:6px 10px;border-top:1px solid var(--line);text-align:right;white-space:nowrap}
  th:first-child,td:first-child{text-align:left}
  tr.self td{background:#fff8e6;font-weight:600}
  /* 流水线 */
  .pnode{border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:8px;
         padding:12px 16px;background:#fbfcfe}
  .pnode + .pline{width:2px;height:16px;background:#c8cfdd;margin-left:26px}
  .phead{font-size:15px;margin-bottom:6px}
  .phead .st{font-size:11px;color:#fff;background:var(--accent);border-radius:4px;padding:1px 8px;margin-left:8px;vertical-align:2px}
  .core{display:flex;flex-wrap:wrap;gap:6px 20px;margin:8px 0;padding:8px 12px;background:#f2f5fa;border-radius:6px;font-size:13px}
  .core i{font-style:normal;color:var(--sub);margin-right:6px}
  .core b{font-variant-numeric:tabular-nums}
  .pout{white-space:pre-wrap;font-size:13px;margin-top:6px}
  .committee{background:linear-gradient(135deg,#fffdf4,#fbf6e3);border:1px solid #eadfa8;border-radius:10px;padding:14px 16px}
  footer{color:var(--sub);font-size:12px;text-align:center;margin-top:24px}
  a{color:var(--accent);text-decoration:none}
</style>
</head>
<body>
<div class="wrap">
  <div class="card">
    <div style="display:flex;align-items:baseline;gap:14px;flex-wrap:wrap">
      <h2 style="margin:0">📊 A股投研工作台</h2>
      <span class="muted" id="metaLine"></span>
      <span class="muted" style="margin-left:auto">多Agent流水线：分析师×4 → 多空辩论 → 交易员 → 风控 → 投委会</span>
    </div>
  </div>

  <div class="card">
    <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap">
      <h2 style="margin:0">大盘温度</h2>
      <div id="tempStrip" style="display:flex;align-items:center;gap:10px;flex-wrap:wrap"></div>
      <button id="toggleDetail" style="margin-left:auto;border:1px solid var(--line);background:#fff;
        border-radius:8px;padding:6px 14px;cursor:pointer;font-size:13px">展开详情 ▾</button>
    </div>
    <div id="sentStrip" style="margin-top:10px;line-height:2.0"></div>
    <div id="mktDetail" style="display:none;margin-top:16px">
      <div class="mkt" id="market"></div>
      <div class="row2" style="margin-top:14px">
        <div><h3>黄金与科技赛道</h3><div id="goldSectors"></div></div>
        <div><h3>热点舆情 · 为什么与我相关</h3><div id="sentiment"></div></div>
      </div>
    </div>
  </div>
  <div class="card"><h2>自选股监测总览</h2><div class="watch" id="watch"></div></div>
  <div class="card"><h2>持仓与组合风险</h2><div id="portfolio"></div></div>
  <div id="stocks"></div>

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
const badgeCls = s => (s||'').includes('多') ? 'b-bull' : ((s||'').includes('空') ? 'b-bear' : 'b-flat');
const CHARTS = [];
const reg = c => { CHARTS.push(c); return c; };
window.addEventListener('resize', () => CHARTS.forEach(c => c.resize()));

/* ---------- 头部 ---------- */
document.getElementById('metaLine').textContent = P.date + ' · ' + P.mode;
document.getElementById('modeLine').textContent = P.mode;

/* ---------- 大盘温度（打开页面时实时刷新报价与温度） ---------- */
(function(){
  const M = P.market||{};
  const senti = P.sentiment;
  const tempLabel = s => s<20?'冰':s<40?'冷':s<60?'温':s<80?'热':'过热';
  const devScore = d => Math.max(0, Math.min(100, (d+3)/6*100));

  function render(){
    const t = M.temperature;
    const strip = [];
    if(t) strip.push(`<span style="font-size:26px;font-weight:800">${t.score}</span>
      <span class="badge ${t.score>=60?'b-bull':t.score>=40?'b-flat':'b-bear'}">${tempLabel(t.score)}</span>
      <span class="muted">基线 ${t.baseline} / 量能 ${t.volume}${t.live?' · 实时 '+t.live:''}</span>`);
    if(M.gold) strip.push(`<span class="chip" style="font-weight:700">🥇 ${esc(M.gold.name)} ${fmt(M.gold.price)}
      <span class="${pctCls(M.gold.change_pct)}">${M.gold.change_pct>0?'+':''}${fmt(M.gold.change_pct)}%</span></span>`);
    (M.sectors||[]).forEach(s=>strip.push(`<span class="chip">${esc(s.name)}
      <b class="${pctCls(s.pct)}">${s.pct>0?'+':''}${fmt(s.pct)}%</b></span>`));
    document.getElementById('tempStrip').innerHTML = strip.join('') || '<span class="muted">大盘数据暂不可用</span>';

    document.getElementById('sentStrip').innerHTML =
      (senti && (senti.items||[]).length)
      ? `<div class="muted" style="margin-bottom:4px"><b>今日热点</b> · 与我的关注点相关 · ${senti.mode==='llm'?'LLM 精选':'规则兜底'}</div>` +
        senti.items.slice(0,5).map((x,i)=>`
        <div style="display:flex;gap:10px;align-items:baseline;margin:4px 0;font-size:13px">
          <span style="color:var(--accent);font-weight:800;flex-shrink:0">${i+1}</span>
          <span style="flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="${esc(x.text)}">${esc(x.title||x.text)}</span>
          <span class="muted" style="flex-shrink:0;max-width:360px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(x.why||'')}</span>
        </div>`).join('')
      : '';

    const el = document.getElementById('market');
    if(!(M.indices||[]).length){el.innerHTML='<div class="muted">大盘数据暂不可用</div>';}
    else{
      el.innerHTML = M.indices.map((x,i)=>`
        <div class="idx"><div class="n">${esc(x.name)}</div>
          <div class="p ${pctCls(x.pct)}">${fmt(x.price)} <span style="font-size:14px">${x.pct>0?'+':''}${fmt(x.pct)}%</span></div>
          <div class="muted">成交额 ${fmt(x.amount_yi,0)} 亿</div>
          <div class="spark" id="spark_${i}"></div></div>`).join('');
      M.indices.forEach((x,i)=>{
        if(!(x.spark||[]).length) return;
        const dom = document.getElementById('spark_'+i);
        echarts.dispose(dom);
        reg(echarts.init(dom)).setOption({
          grid:{left:0,right:0,top:4,bottom:0},
          xAxis:{type:'category',show:false,data:x.spark.map((_,j)=>j)},
          yAxis:{type:'value',show:false,scale:true},
          series:[{type:'line',data:x.spark,showSymbol:false,
            lineStyle:{width:1.6,color:x.spark[x.spark.length-1]>=x.spark[0]?UP:DOWN},
            areaStyle:{color:x.spark[x.spark.length-1]>=x.spark[0]?'rgba(230,69,69,.10)':'rgba(30,158,106,.10)'}}]
        });
      });
    }

    const gs = [];
    if(M.gold) gs.push(`<div style="margin:6px 0"><b>🥇 ${esc(M.gold.name)}</b>
      ${fmt(M.gold.price)}（<span class="${pctCls(M.gold.change_pct)}">${M.gold.change_pct>0?'+':''}${fmt(M.gold.change_pct)}%</span>）
      <span class="muted">高 ${fmt(M.gold.high)} / 低 ${fmt(M.gold.low)} / 昨结 ${fmt(M.gold.prev_close)}</span></div>`);
    (M.sectors||[]).forEach(s=>gs.push(`<div style="margin:6px 0"><b>${esc(s.name)}</b>
      <span class="muted">${esc(s.symbol)}</span> ${fmt(s.price)}
      <span class="${pctCls(s.pct)}">${s.pct>0?'+':''}${fmt(s.pct)}%</span></div>`));
    document.getElementById('goldSectors').innerHTML = gs.join('') || '<div class="muted">暂不可用</div>';

    const se = document.getElementById('sentiment');
    if(senti && (senti.items||[]).length){
      se.innerHTML = senti.items.map((x,i)=>`<div style="margin:8px 0">
        <div><b style="color:var(--accent)">${i+1}.</b> ${esc(x.title||x.text)}</div>
        ${x.title ? `<div class="muted" style="white-space:normal">${esc(x.text)}</div>` : ''}
        <div class="muted">${esc(x.why||'')}　${esc(x.when||'')}</div></div>`).join('');
    } else se.innerHTML = '<div class="muted">今日暂无命中关注点的舆情</div>';
  }
  render();

  document.getElementById('toggleDetail').onclick = () => {
    const d = document.getElementById('mktDetail');
    const open = d.style.display === 'none';
    d.style.display = open ? 'block' : 'none';
    document.getElementById('toggleDetail').textContent = open ? '收起详情 ▴' : '展开详情 ▾';
    if(open) setTimeout(()=>CHARTS.forEach(c=>c.resize()), 30);
  };

  /* 实时刷新：gtimg 支持 script 标签直拉（无 CORS 问题），打开页面即更新 */
  const syms = (M.indices||[]).map(x=>x.symbol).concat((M.sectors||[]).map(x=>x.symbol));
  if(M.gold) syms.push('hf_XAU');
  if(!syms.length) return;
  const s = document.createElement('script');
  s.src = 'https://qt.gtimg.cn/q=' + syms.join(',');
  s.onload = () => {
    let changed = false;
    (M.indices||[]).concat(M.sectors||[]).forEach(x=>{
      const raw = window['v_'+x.symbol];
      if(!raw) return;
      const p = raw.split('~');
      if(p.length > 33 && +p[3] > 0){ x.price = +p[3]; x.pct = +p[32]; changed = true; }
    });
    if(M.gold){
      const raw = window['v_hf_XAU'];
      if(raw){ const p = raw.split(',');
        if(p.length > 1 && +p[0] > 0){ M.gold.price = +p[0]; M.gold.change_pct = +p[1]; changed = true; } }
    }
    if(!changed) return;
    const devs = [];
    (M.indices||[]).forEach(x=>{
      const arr = x.spark||[];
      if(!arr.length || !x.price) return;
      const ma20 = arr.slice(-20).reduce((a,b)=>a+b,0) / Math.min(20, arr.length);
      devs.push(devScore((x.price/ma20 - 1) * 100));
    });
    if(devs.length){
      const base = devs.reduce((a,b)=>a+b,0) / devs.length;
      const vol = (M.temperature||{}).volume ?? 50;
      M.temperature = Object.assign({}, M.temperature, {
        score: Math.round((0.6*base + 0.4*vol) * 10) / 10,
        baseline: Math.round(base*10)/10,
        live: new Date().toTimeString().slice(0,5),
      });
    }
    render();
    setTimeout(()=>CHARTS.forEach(c=>c.resize()), 30);
  };
  document.head.appendChild(s);
})();

/* ---------- 自选总览 ---------- */
(function(){
  document.getElementById('watch').innerHTML = P.stocks.map(p=>{
    const q=p.quote, d=p.decision, dg=p.diagnosis;
    return `<div class="wcard">
      <div class="top"><span class="name">${esc(p.meta.name)}</span>
        <span class="muted">${esc(p.meta.code)} · ${esc(p.meta.industry||'')}</span>
        <span class="badge ${badgeCls(d.stance)}">${esc(d.stance)} · ${esc(d.action)}</span>
        <span class="price ${pctCls(q.pct)}">${fmt(q.price)} <span style="font-size:13px">${q.pct>0?'+':''}${fmt(q.pct)}%</span></span>
      </div>
      <div class="kvrow">
        <span>置信度 <b>${d.confidence}</b></span><span>综合分 <b>${dg.overall}（${dg.grade}）</b></span>
        <span>仓位上限 <b>${d.position_pct}%</b></span><span>PE <b>${fmt(q.pe)}</b></span>
        <span>市值 <b>${fmt(q.mv_yi,0)}亿</b></span><span>风控 <b>${p.risk.score}</b></span>
      </div>
      <div class="muted" style="margin-top:6px">止损：${esc(d.stop_loss||'—')}　|　<a href="#stock_${p.meta.code}">查看完整研判 ↓</a></div>
    </div>`;
  }).join('');
})();

/* ---------- 持仓与组合风险 ---------- */
(function(){
  const el = document.getElementById('portfolio');
  const pf = P.portfolio;
  if(!pf){el.innerHTML='<div class="muted">未配置持仓（编辑 holdings.toml 后重跑）</div>';return;}
  let html = '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px">' +
    (pf.alerts||[]).map(a=>`<span class="chip" style="border-color:#e64545;color:#e64545;font-weight:700">⚠ ${esc(a)}</span>`).join('') +
    (pf.industry_weights||[]).map(w=>`<span class="chip">行业 ${esc(w.name)} ${w.pct}%</span>`).join('') +
    `<span class="chip">组合市值 ${(pf.total_mv/1e4).toFixed(1)} 万</span>` +
    Object.entries(pf.stances||{}).map(([k,v])=>`<span class="chip">立场 ${esc(k)} ×${v}</span>`).join('') +
    '</div>';
  html += `<table><tr><th>名称</th><th>股数</th><th>成本</th><th>现价</th><th>市值(万)</th>
    <th>盈亏%</th><th>今日%</th><th>行业</th><th>仓位%</th><th>止损(距离)</th><th>持仓建议</th></tr>` +
    pf.rows.map(r=>`<tr><td><b>${esc(r.name)}</b></td><td>${r.shares}</td><td>${fmt(r.cost)}</td>
      <td>${fmt(r.price)}</td><td>${fmt(r.mv/1e4,1)}</td>
      <td class="${pctCls(r.pnl_pct)}">${r.pnl_pct>0?'+':''}${fmt(r.pnl_pct)}</td>
      <td class="${pctCls(r.day_pct)}">${r.day_pct>0?'+':''}${fmt(r.day_pct)}</td>
      <td>${esc(r.industry)}</td><td>${r.weight_pct}</td>
      <td>${r.stop!=null?fmt(r.stop)+'（'+r.stop_dist+'%）':'—'}</td>
      <td><b>${esc(r.action||'—')}</b></td></tr>`).join('') + '</table>';
  el.innerHTML = html;
})();

/* ---------- 每只票 ---------- */
P.stocks.forEach(p => {
  const sid = p.meta.code;
  const sec = document.createElement('div');
  sec.innerHTML = `
  <div class="card" id="stock_${sid}">
    <div class="stockhead">
      <span class="name">${esc(p.meta.name)}</span>
      <span class="muted">${esc(p.meta.code)} · ${esc(p.meta.industry||'')} · ${esc(p.meta.region||'')}</span>
      <span class="badge ${badgeCls(p.decision.stance)}">${esc(p.decision.stance)} · ${esc(p.decision.action)}</span>
      <span class="muted" style="margin-left:auto"><a href="${esc(p.deep_link)}" target="_blank">打开深度图表页 ↗</a></span>
    </div>
    <div id="levels_${sid}" style="margin:4px 0 10px"></div>

    <div class="row2">
      <div><h3>五维诊断</h3><div id="radar_${sid}" class="chart-sm"></div></div>
      <div><h3>综合分 / 置信度</h3><div id="gauge_${sid}" class="chart-sm"></div>
        <div class="muted" style="font-size:12px;line-height:1.8" id="reasons_${sid}"></div></div>
    </div>
    <h3>日K走势（前复权 · 红涨绿跌 · 滚轮缩放）</h3>
    <div id="kline_${sid}" class="chart"></div>
    <div class="row2">
      <div><h3>主力资金（近5日，亿元）</h3><div id="ff_${sid}" class="chart-sm"></div></div>
      <div><h3>营收构成</h3><div id="mix_${sid}" class="chart-sm"></div></div>
    </div>
    <div class="row2">
      <div><h3>单季营收/净利 + 同比</h3><div id="qfin_${sid}" class="chart-sm"></div></div>
      <div><h3>盈利质量（%）</h3><div id="qm_${sid}" class="chart-sm"></div></div>
    </div>
    <div class="row2">
      <div><h3>同业对比（市值+PE）</h3><div id="peer_${sid}" class="chart-sm"></div>
        <div id="peertbl_${sid}" style="margin-top:8px"></div></div>
      <div><h3>年度趋势 + 分红</h3><div id="afin_${sid}" class="chart-sm"></div>
        <div id="div_${sid}" class="chart-sm" style="height:180px"></div></div>
    </div>

    <h2 style="margin-top:18px">Agent 流水线全记录</h2>
    <div id="pipe_${sid}"></div>
    <div class="committee" style="margin-top:14px"><b>🏛️ 投委会结论</b>
      <p style="white-space:pre-wrap;margin-top:6px">${md(p.committee)}</p></div>
  </div>`;
  document.getElementById('stocks').appendChild(sec);
  renderCharts(p, sid);
  renderPipeline(p, sid);
});

/* ---------- 图表 ---------- */
function renderCharts(p, sid){
  const dg = p.diagnosis, k = p.kline;
  reg(echarts.init(document.getElementById('radar_'+sid))).setOption({
    radar:{indicator:dg.labels.map(l=>({name:l,max:100})),radius:'66%',
      axisName:{color:'#44506b',fontSize:12}},
    series:[{type:'radar',symbolSize:4,data:[{value:dg.values,
      areaStyle:{color:'rgba(43,78,255,.16)'},lineStyle:{color:'#2b4eff',width:2},itemStyle:{color:'#2b4eff'}}]}]});
  const gOpt=(v,t)=>({type:'gauge',startAngle:210,endAngle:-30,min:0,max:100,radius:'72%',
    axisLine:{lineStyle:{width:14,color:[[0.3,'#1e9e6a'],[0.6,'#8492ab'],[1,'#e64545']]}},
    pointer:{show:false},axisTick:{show:false},splitLine:{show:false},axisLabel:{show:false},
    detail:{formatter:'{value}',offsetCenter:[0,'-8%'],fontSize:28,fontWeight:700},
    title:{show:true,offsetCenter:[0,'34%'],fontSize:12,color:'#68738a'},data:[{value:v,name:t}]});
  reg(echarts.init(document.getElementById('gauge_'+sid))).setOption({series:[
    Object.assign({center:['27%','55%']},gOpt(dg.overall,'综合分（'+dg.grade+'）')),
    Object.assign({center:['73%','55%']},gOpt(p.decision.confidence||0,'置信度'))]});
  document.getElementById('reasons_'+sid).innerHTML =
    dg.labels.map((l,i)=>`<div><b>${l} ${dg.values[i]}</b>｜${dg.reasons[l].join('；')}</div>`).join('');
  document.getElementById('levels_'+sid).innerHTML = levelsHTML(p);

  reg(echarts.init(document.getElementById('kline_'+sid))).setOption({
    animation:false,axisPointer:{link:[{xAxisIndex:'all'}]},
    tooltip:{trigger:'axis',axisPointer:{type:'cross'}},
    legend:{data:['K线','MA5','MA10','MA20','MA60'],top:0},
    grid:[{left:56,right:20,top:30,height:'46%'},{left:56,right:20,top:'58%',height:'14%'},
          {left:56,right:20,top:'76%',height:'14%'}],
    xAxis:[{type:'category',data:k.dates,boundaryGap:true},
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
         data:extractLevels(p).map(x=>({yAxis:x.v,
           label:{formatter:`${x.tag} ${x.v}`,position:'insideEndTop',fontSize:10,color:x.c},
           lineStyle:{color:x.c,type:'dashed',width:1.4}}))}},
      ...['MA5','MA10','MA20','MA60'].map((n,i)=>({name:n,type:'line',data:k.ma[n],smooth:true,
        showSymbol:false,lineStyle:{width:1.2,color:['#f5a623','#8e6cef','#2b4eff','#0aa2c0'][i]}})),
      {name:'成交量',type:'bar',xAxisIndex:1,yAxisIndex:1,data:k.volumes.map((v,i)=>({value:v,
        itemStyle:{color:k.ohlc[i][1]>=k.ohlc[i][0]?UP:DOWN}}))},
      {name:'MACD',type:'bar',xAxisIndex:2,yAxisIndex:2,data:k.macd.hist.map(v=>({value:v,
        itemStyle:{color:v>=0?UP:DOWN}}))},
      {name:'DIF',type:'line',xAxisIndex:2,yAxisIndex:2,data:k.macd.dif,showSymbol:false,lineStyle:{width:1,color:'#f5a623'}},
      {name:'DEA',type:'line',xAxisIndex:2,yAxisIndex:2,data:k.macd.dea,showSymbol:false,lineStyle:{width:1,color:'#2b4eff'}},
    ]});

  const ffEl = document.getElementById('ff_'+sid);
  if((p.fundflow||[]).length){
    reg(echarts.init(ffEl)).setOption({tooltip:{trigger:'axis'},
      legend:{data:['主力','超大单','大单'],top:0},
      grid:{left:50,right:16,top:34,bottom:24},
      xAxis:{type:'category',data:p.fundflow.map(f=>f.date.slice(5))},
      yAxis:{type:'value',name:'亿',splitLine:{lineStyle:{color:'#eef1f6'}}},
      series:[
        {name:'主力',type:'bar',data:p.fundflow.map(f=>({value:f.main_yi,itemStyle:{color:f.main_yi>=0?UP:DOWN}}))},
        {name:'超大单',type:'line',data:p.fundflow.map(f=>f.super_yi),lineStyle:{color:'#8e6cef'}},
        {name:'大单',type:'line',data:p.fundflow.map(f=>f.large_yi),lineStyle:{color:'#f5a623'}}]});
  } else ffEl.innerHTML = '<div class="muted">东财资金流本次不可用</div>';

  const mixEl = document.getElementById('mix_'+sid);
  const mix = (p.sector.revenue_mix||[]);
  if(mix.length){
    reg(echarts.init(mixEl)).setOption({tooltip:{trigger:'item',formatter:'{b}：{c} 亿（{d}%）'},
      series:[{type:'pie',radius:['38%','68%'],center:['50%','52%'],label:{formatter:'{b}\n{d}%'},
        data:mix.map(m=>({name:m.segment,value:m.income_yi}))}]});
  } else mixEl.innerHTML = '<div class="muted">暂无营收构成</div>';

  const q = (p.fin.quarters||[]).slice(-8);
  const qEl = document.getElementById('qfin_'+sid);
  if(q.length){
    reg(echarts.init(qEl)).setOption({tooltip:{trigger:'axis'},
      legend:{data:['营收','归母净利','营收同比','净利同比'],top:0},
      grid:{left:50,right:52,top:34,bottom:24},
      xAxis:{type:'category',data:q.map(x=>x.label)},
      yAxis:[{type:'value',name:'亿',splitLine:{lineStyle:{color:'#eef1f6'}}},{type:'value',name:'%',splitLine:{show:false}}],
      series:[
        {name:'营收',type:'bar',data:q.map(x=>x.revenue_yi),itemStyle:{color:'#2b4eff'},barMaxWidth:24},
        {name:'归母净利',type:'bar',data:q.map(x=>x.profit_yi),itemStyle:{color:'#f5a623'},barMaxWidth:24},
        {name:'营收同比',type:'line',yAxisIndex:1,data:q.map(x=>x.revenue_yoy),lineStyle:{color:'#0aa2c0'}},
        {name:'净利同比',type:'line',yAxisIndex:1,data:q.map(x=>x.profit_yoy),lineStyle:{color:'#e64545'}}]});
    reg(echarts.init(document.getElementById('qm_'+sid))).setOption({tooltip:{trigger:'axis'},
      legend:{data:['ROE','毛利率','净利率','负债率'],top:0},
      grid:{left:46,right:16,top:34,bottom:24},
      xAxis:{type:'category',data:q.map(x=>x.label)},
      yAxis:{type:'value',name:'%',splitLine:{lineStyle:{color:'#eef1f6'}}},
      series:[
        {name:'ROE',type:'line',data:q.map(x=>x.roe),lineStyle:{color:'#e64545'}},
        {name:'毛利率',type:'line',data:q.map(x=>x.gross_margin),lineStyle:{color:'#2b4eff'}},
        {name:'净利率',type:'line',data:q.map(x=>x.net_margin),lineStyle:{color:'#f5a623'}},
        {name:'负债率',type:'line',data:q.map(x=>x.debt_ratio),lineStyle:{color:'#8e6cef',type:'dashed'}}]});
  } else { qEl.innerHTML='<div class="muted">财报数据本次不可用</div>';
    document.getElementById('qm_'+sid).innerHTML='<div class="muted">同上</div>'; }

  const a = p.fin.annual||[];
  const aEl = document.getElementById('afin_'+sid);
  if(a.length){
    reg(echarts.init(aEl)).setOption({tooltip:{trigger:'axis'},
      legend:{data:['营收','净利','净利同比'],top:0},
      grid:{left:56,right:52,top:34,bottom:24},
      xAxis:{type:'category',data:a.map(x=>x.period.slice(0,4))},
      yAxis:[{type:'value',name:'亿',splitLine:{lineStyle:{color:'#eef1f6'}}},{type:'value',name:'%',splitLine:{show:false}}],
      series:[
        {name:'营收',type:'bar',data:a.map(x=>x.revenue_yi),itemStyle:{color:'#2b4eff'},barMaxWidth:36},
        {name:'净利',type:'bar',data:a.map(x=>x.profit_yi),itemStyle:{color:'#f5a623'},barMaxWidth:36},
        {name:'净利同比',type:'line',yAxisIndex:1,data:a.map(x=>x.profit_yoy),lineStyle:{color:'#e64545'}}]});
  } else aEl.innerHTML='<div class="muted">暂无年度数据</div>';

  const divs = p.sector.dividends||[];
  const dEl = document.getElementById('div_'+sid);
  if(divs.length){
    const by={}; divs.forEach(x=>{by[x.year]=(by[x.year]||0)+(x.per_10_share||0);});
    const ys=Object.keys(by).sort().slice(-6);
    reg(echarts.init(dEl)).setOption({grid:{left:56,right:16,top:26,bottom:22},
      tooltip:{trigger:'axis',formatter:ps=>ps[0].name+' 合计：'+ps[0].value+' 元/10股'},
      xAxis:{type:'category',data:ys},yAxis:{type:'value',name:'元/10股'},
      series:[{type:'bar',barMaxWidth:40,itemStyle:{color:'#b8860b'},
        data:ys.map(y=>+by[y].toFixed(2)),label:{show:true,position:'top',formatter:'{c}'}}]});
  } else dEl.style.display='none';

  const pr = p.peers;
  const pEl = document.getElementById('peer_'+sid);
  if(pr && (pr.stocks||[]).length){
    const st = pr.stocks.slice(0,8);
    reg(echarts.init(pEl)).setOption({tooltip:{trigger:'axis'},
      legend:{data:['总市值(亿)','PE(TTM)'],top:0},
      grid:{left:60,right:52,top:34,bottom:48},
      xAxis:{type:'category',data:st.map(s=>s.name),axisLabel:{rotate:22,fontSize:11}},
      yAxis:[{type:'value',name:'亿',splitLine:{lineStyle:{color:'#eef1f6'}}},{type:'value',name:'PE',splitLine:{show:false}}],
      series:[
        {name:'总市值(亿)',type:'bar',barMaxWidth:28,data:st.map(s=>({value:s.mv_yi,
          itemStyle:{color:s.is_self?'#e64545':'#2b4eff'}}))},
        {name:'PE(TTM)',type:'line',yAxisIndex:1,data:st.map(s=>s.pe),
          lineStyle:{color:'#f5a623'},itemStyle:{color:'#f5a623'}}]});
    document.getElementById('peertbl_'+sid).innerHTML =
      `<table><tr><th>公司</th><th>现价</th><th>涨跌%</th><th>PE</th><th>市值(亿)</th></tr>`+
      st.map(x=>`<tr class="${x.is_self?'self':''}"><td>${x.is_self?'★ ':''}${esc(x.name)}</td>
        <td>${fmt(x.price)}</td><td class="${pctCls(x.pct)}">${x.pct>0?'+':''}${fmt(x.pct)}</td>
        <td>${fmt(x.pe)}</td><td>${fmt(x.mv_yi,0)}</td></tr>`).join('')+`</table>`;
  } else { pEl.innerHTML='<div class="muted">同业数据暂不可用（东财限流）</div>'; }
}

/* ---------- 流水线全记录 ---------- */
function renderPipeline(p, sid){
  document.getElementById('pipe_'+sid).innerHTML = p.pipeline.map((n,i)=>`
    ${i?'<div class="pline"></div>':''}
    <div class="pnode">
      <div class="phead">${n.icon} <b>${esc(n.role)}</b><span class="st">节点 ${i+1}</span></div>
      <div>${(n.inputs||[]).map(x=>`<span class="chip">${esc(x)}</span>`).join('')}</div>
      ${(n.core && Object.keys(n.core).length) ? `<div class="core">`+
        Object.entries(n.core).map(([kk,vv])=>`<span><i>${esc(kk)}</i><b>${esc(vv)}</b></span>`).join('')+
        `</div>` : ''}
      <p class="pout">${md(n.output)}</p>
    </div>`).join('');
}
</script>
</body>
</html>
"""


def build_master(states: list, market: dict, mode_desc: str,
                 deep_links: dict | None = None,
                 sentiment: dict | None = None,
                 portfolio: dict | None = None) -> str:
    stocks = []
    for st in states:
        p = build_payload(st, mode_desc)
        code = st["bundle"].code
        p["deep_link"] = (deep_links or {}).get(
            code, f"{p['meta']['date']}_{code}_{st['bundle'].name}.html")
        stocks.append(p)
    payload = {"date": date.today().isoformat(), "mode": mode_desc,
               "market": market, "stocks": stocks,
               "sentiment": sentiment, "portfolio": portfolio}
    payload_json = json.dumps(payload, ensure_ascii=False, default=str).replace("</", "<\\/")
    return (_MASTER
            .replace("__TITLE__", f"A股投研工作台 · {payload['date']}")
            .replace("__ECHARTS_JS__", ECHARTS_JS)
            .replace("__PAYLOAD__", payload_json))


def save_master(states: list, market: dict, mode_desc: str,
                deep_links: dict | None = None,
                sentiment: dict | None = None,
                portfolio: dict | None = None) -> Path:
    out = ROOT / "reports" / "index.html"
    out.write_text(build_master(states, market, mode_desc, deep_links,
                                sentiment, portfolio), encoding="utf-8")
    return out
