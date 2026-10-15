"""
麦麦夜宵官 · 命令行入口

    python -m src.cli --budget 30 --keyword 奉贤
    python -m src.cli --at 23:30          # 强制按 23:30 演示夜宵场景
    python -m src.cli --kcal 400          # 自定义热量上限
"""

from __future__ import annotations

import argparse
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from rich.console import Console

from . import nutrition as nut
from . import optimizer as opt
from . import store_filter as sf
from . import time_guard as tg
from .card import render
from .mcp_client import MCPClient, MCPError


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="麦麦夜宵官 · 深夜点餐决策助手")
    p.add_argument("--city", default="上海市")
    p.add_argument("--keyword", default="奉贤")
    p.add_argument("--budget", type=float, default=30.0, help="预算（元）")
    p.add_argument("--kcal", type=float, default=None, help="热量上限，默认按时段")
    p.add_argument("--weight", type=float, default=60.0, help="体重kg，用于运动折算")
    p.add_argument("--max-items", type=int, default=3, help="组合最多几件")
    p.add_argument("--at", default=None, help='强制时刻 "HH:MM"，用于白天演示夜宵场景')
    p.add_argument("--beam", type=int, default=8, help="束搜索宽度")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    console = Console()

    console.print("[dim]🌙 麦麦夜宵官 · 正在连接麦当劳 MCP …[/dim]")

    try:
        client = MCPClient()
        client.initialize()
    except MCPError as e:
        console.print(f"[bold red]✗ {e}[/bold red]")
        return 2

    # ① 时段判定
    if args.at:
        try:
            h, m = (int(x) for x in args.at.split(":")[:2])
        except ValueError:
            console.print("[red]--at 格式应为 HH:MM[/red]")
            return 2
        period, time_data = tg.resolve(h, m), {}
        now_text = f"{args.at}（手动指定）"
        now_min = tg.to_minutes(h, m)
    else:
        period, time_data = tg.from_mcp(client)
        now_text = str(time_data.get("formatted") or time_data.get("datetime") or "")
        now_min = tg.to_minutes(int(time_data.get("hour") or tg._hour_from(time_data)))

    kcal_limit = args.kcal if args.kcal else float(period.kcal_limit)
    console.print(f"[cyan]{period.emoji} 当前时段：{period.name}[/cyan] "
                  f"[dim]热量上限 {kcal_limit:.0f} kcal · {period.advice}[/dim]")

    # ② 营业门店过滤
    stores = sf.fetch_open_stores(client, args.city, args.keyword, now_min)
    if not stores:
        console.print("[bold yellow]这个点附近没有营业中的门店，换个关键词试试？[/bold yellow]")
        client.close()
        return 1
    store = stores[0]
    console.print(f"[green]✓[/green] 找到 {len(stores)} 家营业门店，"
                  f"最近：{store.name}（{store.distance_text}）")

    # ③ 菜单
    raw = client.call("query-meals", {
        "storeCode": store.code, "orderType": 1, "beType": 1})
    data = raw.get("data") if isinstance(raw, dict) else None
    meals = (data or {}).get("meals") if isinstance(data, dict) else None
    if not meals:
        console.print("[red]该门店暂无菜单数据[/red]")
        client.close()
        return 1
    console.print(f"[green]✓[/green] 菜单 {len(meals)} 个餐品")

    # ④ 营养表
    nraw = client.call("list-nutrition-foods", {})
    ntext = nraw.get("data") if isinstance(nraw, dict) else None
    table = nut.parse(ntext or "")
    console.print(f"[green]✓[/green] 营养表 {len(table)} 条")

    # ⑤ 组合寻优
    # 热量下限 = 时段上限的一半，保证推荐出来的是真能吃饱的夜宵，
    # 而不是一包 ¥3 的蘸酱（没有这个约束时最优解必然是蘸酱）。
    min_kcal = kcal_limit * 0.5
    pool = opt.load_pool(meals, table, max_price=args.budget)
    combos = opt.beam_search(pool, args.budget, kcal_limit,
                             max_items=args.max_items, beam_width=args.beam,
                             min_kcal=min_kcal)
    console.print(f"[dim]生成 {len(combos)} 个候选组合，正在用 calculate-price 校验…[/dim]")
    combos = opt.verify(client, combos, store.code)
    verified = sum(1 for c in combos if c.verified)
    console.print(f"[green]✓[/green] 服务端校验通过 {verified}/{len(combos)}")

    ranked = opt.rank(combos, min_kcal)
    if not ranked:
        console.print("[yellow]预算内没有可行组合，试试提高 --budget[/yellow]")
        client.close()
        return 1

    plan = ranked[0]
    front = [c for c in opt.pareto(combos) if c.codes != plan.codes]
    kcal_total = plan.kcal or sum(i.kcal for i in plan.items)
    if kcal_total <= 0:
        kcal_total = nut.total([(i.name, 1) for i in plan.items], table).energy_kcal

    console.print()
    render(console, store, period, now_text, plan, front,
           args.budget, args.weight, kcal_total)

    console.print(f"\n[dim]本次共调用 MCP {client.call_count} 次[/dim]")
    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
