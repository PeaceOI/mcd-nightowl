"""
营养核算 —— 夜宵官的第四层决策

list-nutrition-foods 返回的是纯文本（表头 + CSV 行，共 160 条），需要自己解析。
另一个真实难点：菜单里的商品名（如「麦辣鸡腿汉堡三件套」）和营养表里的名称
（「麦辣鸡腿汉堡」）对不上，必须做模糊匹配。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

FIELDS = ("name", "desc", "energyKj", "energyKcal",
          "protein", "fat", "carbohydrate", "sodium", "calcium")

# 菜单名里常见的组合后缀，匹配时先剥掉
SUFFIXES = ("三件套", "两件套", "四件套", "套餐", "组合", "单人餐", "双人餐",
            "多人餐", "随心配", "超值", "加", "（", "(")


@dataclass
class Nutrition:
    name: str
    energy_kcal: float = 0.0
    protein: float = 0.0
    fat: float = 0.0
    carbohydrate: float = 0.0
    sodium: float = 0.0
    calcium: float = 0.0

    def __add__(self, other: "Nutrition") -> "Nutrition":
        return Nutrition(
            name=f"{self.name}+{other.name}",
            energy_kcal=self.energy_kcal + other.energy_kcal,
            protein=self.protein + other.protein,
            fat=self.fat + other.fat,
            carbohydrate=self.carbohydrate + other.carbohydrate,
            sodium=self.sodium + other.sodium,
            calcium=self.calcium + other.calcium,
        )

    def scaled(self, qty: int) -> "Nutrition":
        return Nutrition(self.name, self.energy_kcal * qty, self.protein * qty,
                         self.fat * qty, self.carbohydrate * qty,
                         self.sodium * qty, self.calcium * qty)

    @classmethod
    def zero(cls, name: str = "未知") -> "Nutrition":
        return cls(name)


def _num(v: str) -> float:
    v = (v or "").strip()
    if v in ("", "null", "None", "-"):
        return 0.0
    try:
        return float(v)
    except ValueError:
        return 0.0


def parse(raw_text: str) -> dict[str, Nutrition]:
    """把营养文本解析成 {名称: Nutrition}。"""
    table: dict[str, Nutrition] = {}
    for line in (raw_text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("[") or line.startswith("#"):   # 表头
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < len(FIELDS):
            continue
        name = parts[0]
        if not name or name == "productName":
            continue
        try:
            table[name] = Nutrition(
                name=name,
                energy_kcal=_num(parts[3]),
                protein=_num(parts[4]),
                fat=_num(parts[5]),
                carbohydrate=_num(parts[6]),
                sodium=_num(parts[7]),
                calcium=_num(parts[8]),
            )
        except Exception:
            continue
    return table


def _norm(s: str) -> str:
    return re.sub(r"[\s（）()·・]+", "", s or "")


def match(menu_name: str, table: dict[str, Nutrition]) -> Nutrition | None:
    """菜单商品名 → 营养条目。依次尝试精确、剥后缀、双向包含。"""
    if not menu_name or not table:
        return None
    key = _norm(menu_name)
    if key in table:
        return table[key]

    # 剥掉组合后缀再试
    for suf in SUFFIXES:
        if suf and suf in key:
            base = _norm(key.split(suf)[0])
            if base and base in table:
                return table[base]

    # 双向包含（取最长匹配，避免"小薯条"命中"薯条"以外的短词）
    best: Nutrition | None = None
    for name, nut in table.items():
        n = _norm(name)
        if len(n) < 2:
            continue
        if n in key or key in n:
            if best is None or len(n) > len(_norm(best.name)):
                best = nut
    return best


@dataclass
class Exercise:
    km: float
    minutes: float


def to_exercise(kcal: float, weight_kg: float = 60.0, speed_kmh: float = 8.0) -> Exercise:
    """热量折算成慢跑距离。公式：kcal ≈ 体重(kg) × 距离(km) × 1.036"""
    if kcal <= 0:
        return Exercise(0.0, 0.0)
    km = kcal / (weight_kg * 1.036)
    return Exercise(round(km, 1), round(km / speed_kmh * 60, 0))


def total(items: list[tuple[str, int]], table: dict[str, Nutrition]) -> Nutrition:
    """汇总 [(商品名, 数量)] 的营养。未命中的项记 0 但不中断。"""
    acc = Nutrition("合计")
    for name, qty in items:
        nut = match(name, table)
        if nut:
            acc = acc + nut.scaled(qty)
    return acc
