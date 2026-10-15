"""
核心逻辑单元测试（无需 MCP Token，离线可跑）

    python tests/test_core.py          # 直接运行
    pytest tests/                      # 或交给 pytest
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src import nutrition as nut
from src import optimizer as opt
from src import time_guard as tg
from src.store_filter import _is_open, parse_stores

PASS, FAIL = 0, 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name}  {extra}")


# ---------------- 时段判定 ----------------

def test_periods():
    print("\n[时段判定]")
    check("23:30 → 夜宵", tg.resolve(23, 30).name == "夜宵")
    check("02:00 → 夜宵（跨午夜延续）", tg.resolve(2, 0).name == "夜宵")
    check("04:59 → 夜宵", tg.resolve(4, 59).name == "夜宵")
    check("05:00 → 早餐", tg.resolve(5, 0).name == "早餐")
    check("08:00 → 早餐", tg.resolve(8, 0).name == "早餐")
    check("12:00 → 正餐", tg.resolve(12, 0).name == "正餐")
    check("20:59 → 正餐", tg.resolve(20, 59).name == "正餐")
    check("21:00 → 夜宵", tg.resolve(21, 0).name == "夜宵")
    check("夜宵热量上限 500", tg.resolve(23, 0).kcal_limit == 500)


# ---------------- 营业判断 ----------------

def test_is_open():
    print("\n[营业判断（含跨午夜）]")
    noon = tg.to_minutes(12, 0)
    check("10:00-22:00 在 12:00 营业", _is_open("10:00", "22:00", noon)[0])

    night = tg.to_minutes(23, 30)
    check("10:00-22:00 在 23:30 已打烊", not _is_open("10:00", "22:00", night)[0])
    check("00:00-23:59 在 23:30 营业", _is_open("00:00", "23:59", night)[0])
    check("05:00-00:00 在 23:30 营业（跨午夜）", _is_open("05:00", "00:00", night)[0])

    early = tg.to_minutes(1, 0)
    check("05:00-00:00 在 01:00 已过打烊", not _is_open("05:00", "00:00", early)[0])
    check("22:00-06:00 在 01:00 营业（跨午夜）", _is_open("22:00", "06:00", early)[0])

    opened, left = _is_open("00:00", "23:59", night)
    check("24 小时门店距打烊 29 分钟", left == 29, f"实际 {left}")


def test_parse_stores():
    print("\n[门店解析]")
    raw = [{"storeCode": "1", "storeName": "A", "distance": 100,
            "businessStartTime": "10:00", "businessEndTime": "22:00",
            "businessStatus": True},
           {"storeCode": "2", "storeName": "B", "distance": 50,
            "businessStartTime": "00:00", "businessEndTime": "23:59",
            "businessStatus": True}]
    night = tg.to_minutes(23, 30)
    stores = parse_stores(raw, night)
    check("已打烊门店被标记", stores[0].open_now is False)
    check("营业门店被标记", stores[1].open_now is True)
    check("服务端 businessStatus=False 优先",
          parse_stores([{"storeCode": "3", "businessStartTime": "00:00",
                         "businessEndTime": "23:59", "businessStatus": False}],
                       night)[0].open_now is False)


# ---------------- 营养解析 ----------------

SAMPLE = """[3]{productName,nutritionDescription,energyKj,energyKcal,protein,fat,carbohydrate,sodium,calcium}:
  猪柳麦满分,null,1288,308,16,16,24,781,213
  巨无霸,null,2146,513,27,26,42,961,171
  中薯条,null,1210,289,4,12,38,165,18
"""


def test_nutrition():
    print("\n[营养解析]")
    table = nut.parse(SAMPLE)
    check("解析出 3 条", len(table) == 3, f"实际 {len(table)}")
    check("巨无霸 513 kcal", table["巨无霸"].energy_kcal == 513)
    check("巨无霸 蛋白 27g", table["巨无霸"].protein == 27)
    check("中薯条 钠 165mg", table["中薯条"].sodium == 165)

    print("\n[名称模糊匹配]")
    check("精确命中", nut.match("巨无霸", table) is not None)
    check("剥后缀：麦辣鸡腿汉堡三件套 → 麦辣鸡腿汉堡",
          nut.match("巨无霸三件套", table) is not None)
    check("未命中返回 None", nut.match("不存在的商品", table) is None)

    print("\n[运动折算]")
    ex = nut.to_exercise(385, 60)
    check("385 kcal ≈ 6.2 km", 6.0 <= ex.km <= 6.4, f"实际 {ex.km}")
    check("0 kcal → 0 km", nut.to_exercise(0).km == 0)


# ---------------- 组合寻优 ----------------

def _pool() -> list[opt.Item]:
    return [
        opt.Item("a", "巨无霸", 25.0, 513),
        opt.Item("b", "中薯条", 12.0, 289),
        opt.Item("c", "圆筒冰淇淋", 5.0, 93),
        opt.Item("d", "苹果片", 7.0, 32),
        opt.Item("e", "麦香鱼", 15.0, 325),
    ]


def test_optimizer():
    print("\n[蘸酱剔除]")
    check("韩式烟熏芝士风味酱 被判定为蘸酱", opt.is_condiment("韩式烟熏芝士风味酱"))
    check("日式鲜磨山葵酱 被判定为蘸酱", opt.is_condiment("日式鲜磨山葵酱"))
    check("巨无霸 不是蘸酱", not opt.is_condiment("巨无霸"))
    check("板烧鸡腿堡 不是蘸酱", not opt.is_condiment("板烧鸡腿堡"))

    print("\n[束搜索]")
    combos = opt.beam_search(_pool(), 40.0, kcal_limit=600,
                             max_items=2, beam_width=8, min_kcal=250)
    check("产生候选组合", len(combos) > 0, f"实际 {len(combos)}")
    check("组合不超预算", all(c.est_price <= 40.0 for c in combos))
    check("组合不超热量上限", all(c.est_kcal <= 600 for c in combos))
    check("优先产出能吃饱的（≥250kcal）",
          any(c.est_kcal >= 250 for c in combos),
          f"实际最大 {max((c.est_kcal for c in combos), default=0)}")

    print("\n[排序防呆]")
    ranked = opt.rank(combos, min_kcal=250)
    check("排首位的是能吃饱的", ranked[0].est_kcal >= 250,
          f"实际 {ranked[0].est_kcal} kcal")

    print("\n[帕累托前沿]")
    cs = [opt.Combo([opt.Item("x", "X", 10, 300)], 10, 300),
          opt.Combo([opt.Item("y", "Y", 20, 200)], 20, 200),
          opt.Combo([opt.Item("z", "Z", 15, 400)], 15, 400)]
    cs[0].real_price, cs[1].real_price, cs[2].real_price = 10, 20, 15
    front = opt.pareto(cs)
    check("X(10,300) 不被支配 → 在前沿", any(c.kcal == 300 for c in front))
    check("Y(20,200) 与 X 互不支配 → 保留", any(c.kcal == 200 for c in front))
    check("Z(15,400) 被 X 支配 → 剔除", not any(c.kcal == 400 for c in front))

    print("\n[分转元]")
    check("3400 分 → 34.0 元", opt._to_yuan(3400) == 34.0)
    check("None → None", opt._to_yuan(None) is None)


def main() -> int:
    for fn in (test_periods, test_is_open, test_parse_stores,
               test_nutrition, test_optimizer):
        fn()
    print(f"\n{'=' * 46}\n通过 {PASS} ｜ 失败 {FAIL}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
