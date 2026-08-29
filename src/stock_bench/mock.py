"""Mock LLM：按角色返回固定话术，用于不烧 token 验证编排。

第一次风控故意打回（评分 72），重写后通过（评分 88），用来验证回环与终止条件。
"""

import json

from . import prompts

_STATE = {"trader_calls": 0}


def mock_chat(system: str, user: str) -> str:
    if system.startswith(prompts.TECH_ANALYST[:20]):
        return ("收盘高于20日线，均线呈多头排列，趋势健康。MACD 红柱放大、RSI 58 属强势区。"
                "支撑看20日线，压力在60日高点。量价配合良好，但高位波动会放大。")
    if system.startswith(prompts.FUND_ANALYST[:20]):
        return ("当前 PE 处于该股历史中低区间，估值与盈利匹配度尚可。主营在行业内具定价权。"
                "缺口：材料未提供最新季度营收与现金流，无法确认边际变化。")
    if system.startswith(prompts.FIN_ANALYST[:20]):
        return ("财报摘要（mock）：近四季营收与净利同比小幅波动，净利率维持高位，盈利质量稳定；"
                "资产负债率低，财务安全边际充足；年度分红力度大，股息率具吸引力。"
                "缺口：未见经营现金流明细与分季度毛利率拆分。")
    if system.startswith(prompts.NEWS_ANALYST[:20]):
        return ("近期公告以业绩说明会与定期报告摘要为主，性质中性。无重大利好或利空事件。"
                "市场要闻层面未见直接冲击该行业的政策信号。")
    if system.startswith(prompts.BULL[:20]):
        return ("多头逻辑：1) 趋势与资金共振——站上20日线且主力资金连续净流入；"
                "2) 估值未透支——PE 处于历史中低位；3) 消息面无利空压制，风险偏好可修复。")
    if system.startswith(prompts.BEAR[:20]):
        return ("空头反驳：1) 资金流入的持续性未验证，单日流出即证伪；"
                "2) 缺乏最新业绩数据，估值锚不可靠；3) 位置偏高，回撤空间大于上行空间，赔率不佳。")
    if system.startswith(prompts.POSITION_TRADER[:20]):
        _STATE["trader_calls"] += 1
        aggressive = _STATE["trader_calls"] == 1
        return json.dumps({
            "stance": "偏多",
            "action": "加仓" if aggressive else "持有",
            "confidence": 62,
            "position_pct": 40 if aggressive else 20,
            "reasoning": "趋势修复且成本安全垫足够，维持持仓纪律"
                         if not aggressive else "趋势强劲直接加满",
            "trigger_buy": "放量突破60日均线且主力净流入",
            "trigger_exit": "跌破成本价且MACD死叉",
            "stop_loss": "收盘跌破成本价-8%（约1122元）"
                         if not aggressive else "不设止损",
            "levels": {"stop": None if aggressive else 1122.0,
                       "pressure": 1320.0, "support": 1265.0},
        }, ensure_ascii=False)
    if system.startswith(prompts.TRADER[:20]):
        _STATE["trader_calls"] += 1
        aggressive = _STATE["trader_calls"] == 1
        return json.dumps({
            "stance": "偏多",
            "action": "逢低布局" if not aggressive else "重仓买入",
            "confidence": 62,
            "position_pct": 20 if not aggressive else 40,
            "reasoning": "趋势与资金共振且估值可控，但数据缺口限制置信度"
                         if not aggressive else "趋势强劲应该满仓干",
            "trigger_buy": "缩量回踩20日线不破",
            "trigger_exit": "放量跌破20日线且主力资金转为净流出",
            "stop_loss": "收盘跌破20日线，或较买入价回撤8%"
                         if not aggressive else "不设止损",
            "levels": {"stop": None if aggressive else 1220.0,
                       "pressure": None if aggressive else 1265.0,
                       "support": None if aggressive else 1288.0},
        }, ensure_ascii=False)
    if system.startswith(prompts.RISK[:20]):
        first = _STATE["trader_calls"] == 1
        return (f"评分：{72 if first else 88}\n"
                f"意见：{'仓位超过单票上限且缺少止损条件，请降到30%以下并补充明确止损' if first else '通过'}")
    if system.startswith(prompts.COMMITTEE[:20]):
        return ("投委会结论：立场偏多，建议以不超过 20% 仓位逢低布局；"
                "风控强调放量跌破20日线即离场，禁止追高。提醒：本结论基于公开数据的规则与模型分析，不构成投资建议。")
    return "（mock：未识别的角色）"
