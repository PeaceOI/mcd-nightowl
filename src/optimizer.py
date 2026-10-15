"""
券组合寻优 —— 夜宵官的技术核心

设计要点（也是本项目区别于其他参赛作品的地方）：

  绝大多数参赛项目把菜单拉下来「自己算钱」。这是错的 —— 优惠券的互斥规则、
  门店差异、时段限制只有服务端知道，本地算出来的价格不可信。

  本模块的做法：本地只负责「生成候选组合」（束搜索 + 预算/热量剪枝），
  然后逐个调用 calculate-price 拿服务端真实价格作为 ground truth，
  最后在「价格 × 热量」两个目标上求帕累托前沿，输出多档方案。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import nutrition as nut


@dataclass(frozen=True)
class Item:
    code: str
    name: str
    price: float        # 元（菜单 currentPrice）
    kcal: float = 0.0

    @property
    def label(self) -> str:
        return f"{self.name} ¥{self.price:.1f}"


@dataclass
class Combo:
    items: list[Item] = field(default_factory=list)
    est_price: float = 0.0      # 本地估算（元）
    est_kcal: float = 0.0
    real_price: float | None = None   # MCP 校验后的真实到手价（元）
    discount: float = 0.0             # 优惠金额（元）
    verified: bool = False
    raw: dict | None = None

    @property
    def price(self) -> float:
        """优先用校验过的真实价。"""
        return self.real_price if self.real_price is not None else self.est_price

    @property
    def kcal(self) -> float:
        return self.est_kcal

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(i.code for i in self.items)

    def clone(self) -> "Combo":
        return Combo(list(self.items), self.est_price, self.est_kcal,
                     self.real_price, self.discount, self.verified, self.raw)


def is_condiment(name: str) -> bool:
    """判断是否为蘸酱/小料。

    实测发现：按价格升序取候选，最便宜的永远是「韩式烟熏芝士风味酱」这类蘸酱，
    直接拿来当夜宵推荐就是个笑话 —— 必须先把它们排除掉。
    """
    n = (name or "").strip()
    return (n.endswith("酱") or "风味酱" in n or "蘸酱" in n
            or "糖浆" in n or "沙拉汁" in n or "奶油球" in n)


def load_pool(meals: dict, table: dict[str, nut.Nutrition],
              max_price: float | None = None,
              exclude: tuple[str, ...] = ()) -> list[Item]:
    """把 query-meals 的 meals dict 转成候选池（自动剔除蘸酱小料）。"""
    pool: list[Item] = []
    for code, m in (meals or {}).items():
        if not isinstance(m, dict):
            continue
        try:
            price = float(m.get("currentPrice") or m.get("originalPrice") or 0)
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        if max_price and price > max_price:
            continue
        name = str(m.get("name") or code)
        if is_condiment(name):
            continue
        if any(x in name for x in exclude):
            continue
        n = nut.match(name, table)
        pool.append(Item(str(code), name, price, n.energy_kcal if n else 0.0))
    pool.sort(key=lambda x: x.price)
    return pool


def beam_search(pool: list[Item], budget: float, kcal_limit: float | None = None,
                max_items: int = 3, beam_width: int = 8,
                pool_size: int = 40, min_kcal: float = 0.0) -> list[Combo]:
    """束搜索生成候选组合。

    剪枝条件：总价不超过预算、总热量不超过上限、不重复选同一商品。
    每层只保留最便宜的 beam_width 个部分解，把搜索规模压到可控范围。
    """
    candidates = pool[:pool_size]
    beam: list[Combo] = [Combo()]

    for _ in range(max_items):
        expanded: list[Combo] = []
        for combo in beam:
            for item in candidates:
                if item.code in combo.codes:
                    continue
                new_price = combo.est_price + item.price
                if new_price > budget:
                    continue
                new_kcal = combo.est_kcal + item.kcal
                if kcal_limit and new_kcal > kcal_limit:
                    continue
                c = combo.clone()
                c.items.append(item)
                c.est_price = new_price
                c.est_kcal = new_kcal
                expanded.append(c)
        if not expanded:
            break
        # 关键：先按「能不能吃饱」分层，再按价格排。
        # 若单纯按价格取前 N，便宜的甜品/饮料会占满束，正经餐品永远进不来。
        expanded.sort(key=lambda c: (0 if c.est_kcal >= min_kcal else 1, c.est_price))
        # 去重：同样的商品集合只保留一次
        seen: set[tuple[str, ...]] = set()
        beam = []
        for c in expanded:
            key = tuple(sorted(c.codes))
            if key in seen:
                continue
            seen.add(key)
            beam.append(c)
            if len(beam) >= beam_width:
                break

    # 单品也算候选，同样优先能吃饱的
    singles = [Combo([it], it.price, it.kcal) for it in candidates
               if it.price <= budget and (not kcal_limit or it.kcal <= kcal_limit)]
    singles.sort(key=lambda c: (0 if c.est_kcal >= min_kcal else 1, c.est_price))
    return (singles + beam)[:beam_width + 8]


def verify(client, combos: list[Combo], store_code: str,
           order_type: int = 1, be_type: int = 1) -> list[Combo]:
    """逐个候选组合调用 calculate-price，拿服务端真实价格。

    注意：单次决策调用数 = len(combos)，远低于 600 次/分钟限流。
    """
    for c in combos:
        if not c.items:
            continue
        try:
            res = client.call("calculate-price", {
                "storeCode": store_code,
                "orderType": order_type,
                "beType": be_type,
                "items": [{"productCode": i.code, "quantity": 1} for i in c.items],
            })
        except Exception:
            c.verified = False
            continue

        data = res.get("data") if isinstance(res, dict) else None
        if not isinstance(data, dict):
            continue
        # 服务端价格单位是「分」
        price = _to_yuan(data.get("price"))
        origin = _to_yuan(data.get("originalPrice") or data.get("productOriginalPrice"))
        if price is None:
            continue
        c.real_price = price
        c.discount = round((origin - price), 2) if origin else 0.0
        c.verified = True
        c.raw = data
    return combos


def _to_yuan(v) -> float | None:
    try:
        return round(float(v) / 100.0, 2)
    except (TypeError, ValueError):
        return None


def pareto(combos: list[Combo]) -> list[Combo]:
    """在 (价格, 热量) 上求帕累托前沿：不被任何其他方案在两个维度同时击败。

    热量为 0 表示该商品在官方营养表里查不到（新品居多），无法参与双目标比较，
    优先剔除；若全部查不到则退回全集，保证仍有输出。
    """
    valid = [c for c in combos if c.items and c.kcal > 0]
    if not valid:
        valid = [c for c in combos if c.items]
    front: list[Combo] = []
    for c in valid:
        dominated = any(
            (o.price <= c.price and o.kcal <= c.kcal)
            and (o.price < c.price or o.kcal < c.kcal)
            for o in valid if o is not c
        )
        if not dominated:
            front.append(c)
    front.sort(key=lambda c: c.price)
    return front


def rank(combos: list[Combo], min_kcal: float = 0.0) -> list[Combo]:
    """排序规则：先要「吃得饱」（热量达下限），再要比「花得少」。

    min_kcal 是防呆设计 —— 没有热量下限时，最优解永远是一包 ¥3 的蘸酱。
    若所有组合都达不到下限（例如预算太小），则退化为只看价格，保证仍有输出。
    """
    valid = [c for c in combos if c.items]
    filling = [c for c in valid if c.kcal >= min_kcal]
    target = filling if filling else valid
    return sorted(target, key=lambda c: (c.price, -c.kcal))[:5]
