"""
时段判定 —— 夜宵官的第一层决策

麦当劳官方在 reservationTimeOptions 里就有「早餐/午餐/下午茶/夜市/宵夜」的时段划分，
本模块把当前时间映射到时段，并给出该时段的默认热量预算。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Period:
    name: str
    start_min: int      # 自 00:00 起的分钟数
    end_min: int        # 自 00:00 起的分钟数（跨午夜时 end < start）
    kcal_limit: int     # 该时段默认热量上限
    emoji: str
    advice: str


# 时段表：顺序即优先级，命中即返回
PERIODS: tuple[Period, ...] = (
    Period("夜宵", 21 * 60, 5 * 60, 500, "🌙",
           "距睡觉时间近，建议控制在 500 kcal 内，少油炸多蛋白"),
    Period("早餐", 5 * 60, 10 * 60 + 30, 550, "🌅",
           "早餐要吃好，蛋白质优先，可适度放宽到 550 kcal"),
    Period("正餐", 10 * 60 + 30, 21 * 60, 900, "🍽️",
           "正餐时段，单餐建议不超过 900 kcal"),
)


def to_minutes(hour: int, minute: int = 0) -> int:
    return hour * 60 + minute


def resolve(hour: int, minute: int = 0) -> Period:
    """把时刻映射到时段。跨午夜的时段（end < start）单独判断。"""
    now = to_minutes(hour, minute)
    for p in PERIODS:
        if p.end_min > p.start_min:
            if p.start_min <= now < p.end_min:
                return p
        else:  # 跨午夜，如 21:00 → 次日 05:00
            if now >= p.start_min or now < p.end_min:
                return p
    return PERIODS[-1]


def from_mcp(client) -> tuple[Period, dict]:
    """调用 now-time-info 拿服务端时间，再判定时段。返回 (时段, 原始时间数据)。"""
    raw = client.call("now-time-info", {})
    data = raw.get("data", {}) if isinstance(raw, dict) else {}
    hour = int(data.get("hour") or _hour_from(data))
    minute = int(data.get("minute") or 0)
    return resolve(hour, minute), data


def _hour_from(data: dict) -> int:
    """now-time-info 返回里没有独立的 hour 字段，从 formatted/datetime 里取。"""
    for key in ("formatted", "datetime", "date"):
        v = str(data.get(key) or "")
        if " " in v and ":" in v:
            try:
                return int(v.split(" ")[1].split(":")[0])
            except Exception:
                continue
        if len(v) >= 13 and v[4] == "-":
            try:
                return int(v[11:13])
            except Exception:
                continue
    return 0


def minutes_until_close(now_min: int, end_min: int) -> int:
    """距打烊还有多少分钟（自动处理跨午夜）。"""
    if end_min > now_min:
        return end_min - now_min
    return (24 * 60 - now_min) + end_min
