"""
夜宵决策卡 —— 项目的门面

一张卡说清四件事：此刻去哪家店、点什么、花多少、吃完要跑几公里。
视觉呈现是本项目传播力的核心，也是 README 首屏的主图来源。
"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .optimizer import Combo
from .store_filter import Store
from .time_guard import Period
from . import nutrition as nut

TAGS = ["🥇 最省", "🥈 最均衡", "🥉 最轻量", "备选", "备选"]


def _money(v: float) -> str:
    return f"¥{v:.1f}"


def render(console: Console, store: Store, period: Period, now_text: str,
           plan: Combo, alternatives: list[Combo], budget: float,
           weight: float, kcal_total: float) -> None:
    ex = nut.to_exercise(kcal_total, weight)

    # 头部
    head = Text()
    head.append(f"{period.emoji} 麦麦夜宵官", style="bold")
    head.append(f"  ·  {now_text}  ·  {period.name}时段\n", style="dim")
    head.append(f"📍 {store.name}\n", style="bold cyan")
    head.append(f"   {store.address}  ·  距你 {store.distance_text}  ·  营业 {store.start}-{store.end}  ·  {store.close_text}\n",
                style="dim")
    head.append(f"   {period.advice}", style="dim italic")
    console.print(Panel(head, border_style="cyan"))

    # 推荐组合
    t = Table(show_header=False, box=None, padding=(0, 1))
    t.add_column(style="cyan")
    t.add_column(justify="right")
    for it in plan.items:
        t.add_row(f"· {it.name}", _money(it.price))
    console.print(Panel(t, title="🍔 推荐组合", border_style="green"))

    # 价格
    saved = plan.discount
    saved_pct = (saved / plan.price * 100) if plan.price and saved else 0
    price_line = Text()
    price_line.append("券后到手 ", style="dim")
    price_line.append(_money(plan.price), style="bold green")
    if saved > 0:
        price_line.append(f"   原价 {_money(plan.price + saved)}   立省 ", style="dim")
        price_line.append(f"{_money(saved)} ({saved_pct:.0f}%)", style="bold red")
    if plan.verified:
        price_line.append("   ✓ 服务端校验", style="dim green")
    else:
        price_line.append("   ⚠ 未校验", style="dim yellow")
    console.print(Panel(price_line, title="💰 价格", border_style="green"))

    # 营养
    n_line = Text()
    over = kcal_total > period.kcal_limit
    style = "bold red" if over else "bold green"
    n_line.append(f"{kcal_total:.0f} kcal", style=style)
    n_line.append(f"  /  本时段上限 {period.kcal_limit} kcal  ", style="dim")
    n_line.append("超标" if over else "达标 ✓", style=style)
    n_line.append(f"\n🏃 ≈ 慢跑 {ex.km} km（{weight:.0f}kg，约 {ex.minutes:.0f} 分钟）",
                  style="yellow")
    console.print(Panel(n_line, title="🔥 热量", border_style="yellow"))

    # 备选方案（帕累托前沿）
    if alternatives:
        at = Table(box=None, padding=(0, 1))
        at.add_column("方案", style="cyan")
        at.add_column("到手价", justify="right")
        at.add_column("热量", justify="right")
        at.add_column("内容", overflow="fold")
        for i, c in enumerate(alternatives[:4]):
            tag = TAGS[i] if i < len(TAGS) else "备选"
            content = " + ".join(x.name[:12] for x in c.items)
            at.add_row(tag, _money(c.price), f"{c.kcal:.0f}kcal", content)
        console.print(Panel(at, title="⚖️ 其他选择（价格 × 热量 帕累托前沿）",
                            border_style="magenta"))

    console.print(f"[dim]预算 {_money(budget)}  ·  门店 {store.code}  ·  "
                  f"数据来自麦当劳 MCP，仅供参考[/dim]")
