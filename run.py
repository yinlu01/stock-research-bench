#!/usr/bin/env python3
"""股票研判工作台命令行入口。

  python run.py                # 跑全部自选股
  python run.py 600519         # 只跑指定股票
  MA_MOCK=1 python run.py      # 不调 API，只验证编排
  python run.py --data-only    # 强制规则模式（不调 LLM）
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass


def main() -> None:
    if "--data-only" in sys.argv:
        import os

        os.environ["MA_PROTOCOL"] = "off"

    # .env 之后才允许导入包（config 在 import 时读环境变量）
    from stock_bench.config import load_watchlist, settings, Settings
    from stock_bench.graph import run_one
    from stock_bench.llm import describe
    from stock_bench import report as rp

    # ---------- 重建模式：只重渲染图表，不调 LLM/数据 ----------
    if "--rebuild-html" in sys.argv:
        from stock_bench import html_report as hr
        from stock_bench import persist

        sources = persist.find_latest_sources()
        if not sources:
            print("❌ 没有可重建的状态（先跑一次 python run.py 生成）")
            sys.exit(1)
        states = []
        for code, (kind, path) in sorted(sources.items()):
            state = (persist.load_state(path) if kind == "state"
                     else persist.harvest_from_html(path))
            if not state:
                print(f"   ❌ {code}：{path.name} 无法解析")
                continue
            out = hr.save_html(state, state.get("_mode") or describe(), state.get("_date"))
            rp.save(state, state.get("_mode") or describe())
            states.append(state)
            print(f"   🖥️  重建 {code}（来源：{kind}）→ {out}")
        if states:
            from stock_bench import market as mk
            from stock_bench import master_report as mr
            from stock_bench import portfolio as pf
            from stock_bench import sentiment as sent_mod
            from stock_bench.config import load_focus, load_holdings

            senti = sent_mod.run_sentiment([s["bundle"].name for s in states],
                                           load_focus(), allow_llm=False)
            port = pf.build_portfolio({s["bundle"].code: s for s in states},
                                      load_holdings())
            idx = mr.save_master(states, mk.fetch_market(), describe(),
                                 sentiment=senti, portfolio=port)
            print(f"🗂️  总工作台：{idx}")
        return

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    from stock_bench.config import load_focus, load_holdings

    holdings = load_holdings()
    focus = load_focus()
    hold_codes = [str(h["code"]) for h in holdings]
    if args:
        codes = args
    else:
        codes = hold_codes + [s["code"] for s in load_watchlist()
                              if s["code"] not in hold_codes]

    print(f"🧭 模式：{describe()}")
    print(f"📋 待研判：{', '.join(codes)}（持仓 {len(hold_codes)} 只优先）\n")

    import json
    import time as _time
    from datetime import date as _date

    from stock_bench import html_report as hr
    from stock_bench import llm as llm_mod

    BUDGET_SEC = 2400          # 40 分钟预算：持仓优先，超时自选降级规则模式
    t0 = _time.monotonic()
    budget_hit = False

    ok, fail = 0, 0
    states, states_by_code = [], {}
    for i, code in enumerate(codes):
        if i:
            _time.sleep(1.5)          # 票间喘息，降低被限流概率
        if not budget_hit and code not in hold_codes \
                and _time.monotonic() - t0 > BUDGET_SEC:
            budget_hit = True
            llm_mod.set_override("off")
            print("   ⏱️  超过 40 分钟预算：剩余自选切换规则模式（持仓不受影响）")
        try:
            state = run_one(code)
            if not state.get("ok"):   # 行情偶发拒绝 → 重试一次
                print(f"   ↻ {code} 首轮取数失败，3 秒后重试一次...")
                _time.sleep(3)
                state = run_one(code)
        except Exception as e:  # 单票失败不影响其他票
            print(f"   ❌ {code} 运行异常：{str(e)[:120]}")
            fail += 1
            continue
        if not state.get("ok"):
            print(f"   ❌ {code}：{state.get('error')}")
            fail += 1
            continue
        local, obs = rp.save(state, describe())
        html_path = hr.save_html(state, describe())
        from stock_bench import persist

        persist.save_state(state, describe())
        sidecar = Path(local).parent / f"summary_{_date.today().isoformat()}_{state['bundle'].code}.json"
        sidecar.write_text(json.dumps(hr.summary_json(state), ensure_ascii=False, indent=1),
                           encoding="utf-8")
        print(f"   💾 Markdown：{local}")
        print(f"   🖥️  工作台：{html_path}")
        if obs:
            print(f"   📚 Obsidian：{obs}")
        ok += 1
        states.append(state)
        states_by_code[code] = state
        print("-" * 64)

    if ok:
        from stock_bench import market as mk
        from stock_bench import master_report as mr
        from stock_bench import portfolio as pf
        from stock_bench import sentiment as sent_mod

        names = [s["bundle"].name for s in states]
        senti = sent_mod.run_sentiment(names, focus)
        print(f"   📰 舆情漏斗：池 {senti['pool_size']} 条 → {len(senti['items'])} 条（{senti['mode']}）")
        port = pf.build_portfolio(states_by_code, holdings)
        idx = mr.save_master(states, mk.fetch_market(), describe(),
                             sentiment=senti, portfolio=port)
        print(f"🗂️  总工作台：{idx}")

    print(f"\n✅ 完成 {ok} 只，失败 {fail} 只")
    if ok == 0 and codes:
        sys.exit(1)


if __name__ == "__main__":
    main()
