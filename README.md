# stock-research-bench —— 多 Agent 股票研判工作台

与 [TradingAgents-CN](https://github.com/hsliuping/TradingAgents-CN) 同构的轻量实现：
**分析师团队 ×4（并行）→ 多空研究员辩论 → 交易员决策 → 风控质检回环 → 投委会结论**。
每个交易日对自选股跑一遍，产出三样东西：

1. **HTML 工作台**（核心交付）：自包含单文件，双击即开，离线可用，红涨绿跌（A股惯例）。图表包括：
   - **量化诊断**：五维雷达图（趋势/动量/资金/财务质量/估值，规则引擎评分、依据逐条展示）+ 综合分与置信度双仪表盘
   - **日K蜡烛图**：前复权 140 日 + MA5/10/20/60 + 成交量副图 + MACD 副图，滚轮缩放
   - **财报图表**：单季营收/净利柱图 + 同比折线、ROE/毛利率/净利率/负债率质量图、年度趋势、分红柱图
   - **资金与同业**：主力资金 5 日柱图、营收构成饼图、同业市值+PE 对比图（本股红色高亮）+ 对比表
   - 分析正文：多空辩论、交易员决策卡片（触发条件/止损）、投委会结论
2. **Markdown 研判报告**：同步存入 `~/Obsidian/AI技术/股票每日研究/`。
3. **总工作台** `reports/index.html`（一页汇总）：
   - 大盘行情：上证/深成/创业板/沪深300 实时 + 30 日迷你走势
   - 自选股监测总览：每只票的决策徽章、置信度、综合分、仓位、止损一屏看完
   - 每只票完整区块：五维诊断、日K、资金、财报、同业图表
   - **Agent 流水线全记录**：10 个节点（数据准备→4 分析师→多空→交易员→风控→投委会），
     每个节点透出关键输入数据、核心结论数据（立场/仓位/触发/止损/评分）与完整文字输出
   - 每只票另有"深度图表页"链接（分红/年度/营收构成等更全）

## 架构

```
prepare  拉数据：腾讯行情/日K/行业板块/概念/分红 + 新浪财报(单季推导+同比)
         + 新浪财务指标(ROE/利润率/负债率) + 东财估值/资金流/公告/同业 + 财联社新闻
   │ Send ×4（并行）
   ├── 技术分析师（价量：均线/RSI/MACD/量价/60日分位）
   ├── 基本面分析师（估值 + 行业位置 + 同业相对估值）
   ├── 财报分析师（单季与年度趋势/盈利质量/负债/分红）
   └── 新闻与公告分析师（公告优先，没有就明说没有）
   │ fan-in
debate_bull → debate_bear   多头陈述 → 空头逐条反驳
trader      综合辩论出决策（JSON：立场/操作/置信度/仓位/触发条件/止损）
risk        风控评分 + 红线一票否决
   ├─ ≥80 分 ────────────────→ committee 投委会结论 → MD + HTML + 首页
   └─ <80 分且重写<2 次 → rework → trader（带整改意见重写）
```

三个**确定性纪律**，不管模型说什么都强制执行（`rules.py`）：

1. 单票仓位上限 30%，超限自动钳位
2. 红线词（满仓/重仓买入/必涨/不设止损）一票否决，打回重写
3. 重写最多 2 次，超限带当前版本交付（防止死循环）

## 数据源（2026-08-29 本机实测）

| 数据 | 来源 | 可靠性 |
| --- | --- | --- |
| 实时行情（价/量/换手/PE/PB/市值/量比） | 腾讯 qt.gtimg.cn（GBK） | 稳定，主用（偶发拒绝 → 自动重试一轮） |
| 日K（前复权 140 天，蜡烛图源） | 腾讯 ifzq.gtimg.cn | 稳定，主用 |
| 行业/地域/概念板块/营收构成/分红历史 | 腾讯 F10（cwbb/search） | 稳定 |
| 财报（营收/净利累计值，100+ 期） | 新浪利润表（akshare） | 稳定，推导单季+同比 |
| 财务指标（ROE/净利率/负债率/每股现金流） | 新浪财务指标（akshare） | 稳定（个别字段源头缺失显示 —） |
| 同业对比（板块→成分股→批量行情） | 东财 clist + 腾讯行情 | **间歇限流**：重试 5 次 + 7 天本地缓存兜底 |
| 估值补充/资金流/公告 | 东财 push2 / np-anotice | **间歇性拒绝**：重试 3 次，失败降级跳过 |
| 新闻（个股提及+市场要闻） | 财联社电报（akshare） | 按股票名过滤 |

东财对 Python 客户端的 TLS 指纹敏感（curl 能过、requests 时好时坏），所以一律
"重试 + 缓存 + 可失败"设计：东财全挂也不影响报告主体，最多同业表显示缓存。

## 快速开始

```bash
cd stock-research-bench
uv venv --python 3.12 && source .venv/bin/activate
uv pip install -e .                 # langgraph akshare pandas pytest python-dotenv
cp .env.example .env                # 填 MA_API_KEY
cp holdings.example.toml holdings.toml   # 填你的真实持仓（个人数据，不进 git）

pytest tests/ -q                    # 14 个测试，全 mock，不联网
MA_MOCK=1 python run.py 600519      # 编排冒烟（不调 API）
python run.py                       # 真模型 + 全自选股
python run.py --data-only           # 无 LLM：规则引擎照出报告
python run.py --rebuild-html        # 只重渲染图表（从 data/state_*.json 或已有 HTML 反解，不烧 token）
open reports/index.html             # 打开工作台首页
```

状态会持久化到 `data/state_{日期}_{代码}.json`：调整页面样式后跑一次
`--rebuild-html` 即可全量重出图表，无需重跑流水线。

## 模型协议

`llm.py` 支持两种协议，`.env` 切换：

- `anthropic`：直连 `{base_url}/v1/messages`（MiniMax 的 Claude 兼容端点默认用这个；
  45 秒超时 + 重试 1 次，模型名不确定时按 `config.model_fallbacks` 自动探测）
- `openai`：走 langchain-openai（通义/DeepSeek/月之暗面/智谱等兼容端点）

没有 Key 时自动进入**数据模式**：数据照拉、指标照算、决策由规则引擎生成
（`rules.py` 评分卡：趋势/动量/量能/资金流/位置/舆情关键词），报告头部会标注。
任何单点失败（数据源、LLM）都只降级对应环节，**定时任务永远不会空手而归**。

## 目录

| 文件 | 职责 |
| --- | --- |
| `src/stock_bench/graph.py` | LangGraph 编排（核心） |
| `src/stock_bench/data_feed.py` | 行情数据层（腾讯/东财/财联社，全部可降级） |
| `src/stock_bench/finance.py` | 财报数据层（新浪报表→单季推导→指标合并） |
| `src/stock_bench/sector.py` | 行业板块与同业（腾讯 F10 + 东财板块 + 缓存） |
| `src/stock_bench/diagnosis.py` | 五维量化诊断（纯规则，评分依据全记录） |
| `src/stock_bench/persist.py` | 状态持久化 / HTML 反解 / 免 LLM 重建 |
| `src/stock_bench/indicators.py` | 技术指标（纯 pandas，含 MACD 序列供绘图） |
| `src/stock_bench/rules.py` | 规则引擎 + 红线 + 评分卡 |
| `src/stock_bench/prompts.py` | 8 个角色的提示词（角色边界钉死） |
| `src/stock_bench/llm.py` | anthropic/openai 双协议 + 超时重试 + 模型探测 |
| `src/stock_bench/mock.py` | 固定话术（第一轮故意被打回，验证回环） |
| `src/stock_bench/report.py` | Markdown 渲染 + Obsidian 落盘 |
| `src/stock_bench/html_report.py` | 个股深度图表页（内联 ECharts）+ payload 构建 |
| `src/stock_bench/master_report.py` | 总工作台（大盘+自选总览+流水线全记录） |
| `src/stock_bench/market.py` | 四大指数实时+迷你走势（缓存兜底） |
| `assets/echarts.min.js` | ECharts 5.5.1（离线） |
| `watchlist.toml` | 自选股 |
| `tests/test_pipeline.py` | 14 个端到端测试（全离线） |

## 升级路线

1. 接 Checkpointer（`MemorySaver` + `thread_id=日期`）→ 支持"对比昨日结论"
2. 加情绪/热度源（雪球热度、涨停家数、北向资金总量）
3. 评测集：20 只股 × 30 天回看，统计决策与后续 5 日涨跌的一致性
4. 接 Langfuse 看每个角色的 token 与耗时归因

---
免责声明：本项目输出仅为多 Agent 编排的学习与研究记录，不构成任何投资建议。
