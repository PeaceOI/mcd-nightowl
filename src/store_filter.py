"""
营业门店过滤 —— 夜宵官的第二层决策

深夜场景的真实痛点不是"吃什么"，而是"这个点还有哪家店开着"。
麦当劳门店返回里有 businessStatus 和 businessStartTime/EndTime，
本模块据此判断「此刻真的能点」，并按距离排序。
"""

from __future__ import annotations

from dataclasses import dataclass

from .time_guard import to_minutes, minutes_until_close


@dataclass
class Store:
    code: str
    name: str
    address: str
    distance: int
    open_now: bool
    start: str
    end: str
    minutes_left: int        # 距打烊分钟数，-1 表示 24 小时
    raw: dict

    @property
    def distance_text(self) -> str:
        if self.distance >= 1000:
            return f"{self.distance / 1000:.1f}km"
        return f"{self.distance}m"

    @property
    def close_text(self) -> str:
        if self.minutes_left < 0:
            return "24小时"
        h, m = divmod(self.minutes_left, 60)
        return f"{h}小时{m}分后打烊" if h else f"{m}分钟后打烊"


def _is_open(start: str, end: str, now_min: int) -> tuple[bool, int]:
    """判断此刻是否营业，返回 (是否营业, 距打烊分钟数)。

    营业时间可能跨午夜（如 22:00–06:00），也可能两端相同（视为 24 小时）。
    """
    try:
        s_h, s_m = (int(x) for x in start.split(":")[:2])
        e_h, e_m = (int(x) for x in end.split(":")[:2])
    except Exception:
        return False, 0

    s = to_minutes(s_h, s_m)
    e = to_minutes(e_h, e_m)

    if s == e:                       # 起止相同 → 24 小时营业
        return True, -1

    if e > s:                        # 不跨午夜
        opened = s <= now_min < e
    else:                            # 跨午夜
        opened = now_min >= s or now_min < e

    return opened, (minutes_until_close(now_min, e) if opened else 0)


def parse_stores(raw_stores: list[dict], now_min: int) -> list[Store]:
    stores: list[Store] = []
    for s in raw_stores or []:
        start = str(s.get("businessStartTime") or "00:00")
        end = str(s.get("businessEndTime") or "00:00")
        opened, left = _is_open(start, end, now_min)
        # businessStatus 是服务端给的实时状态，与本地计算互相校验
        if s.get("businessStatus") is False:
            opened, left = False, 0
        stores.append(Store(
            code=str(s.get("storeCode") or ""),
            name=str(s.get("storeName") or "未知门店"),
            address=str(s.get("address") or ""),
            distance=int(s.get("distance") or 0),
            open_now=opened,
            start=start,
            end=end,
            minutes_left=left,
            raw=s,
        ))
    return stores


def fetch_open_stores(client, city: str, keyword: str, now_min: int,
                      be_type: int = 1, limit: int = 5) -> list[Store]:
    """拉取门店并只保留此刻营业的，按距离升序返回。"""
    raw = client.call("query-nearby-stores", {
        "beType": be_type, "searchType": 2, "city": city, "keyword": keyword,
    })
    data = raw.get("data") if isinstance(raw, dict) else None
    if isinstance(data, dict):
        data = data.get("stores") or data.get("list") or []
    if not isinstance(data, list):
        return []

    stores = parse_stores(data, now_min)
    opened = [s for s in stores if s.open_now]
    opened.sort(key=lambda x: (x.distance, x.code))
    return opened[:limit]
