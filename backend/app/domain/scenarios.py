"""随机演训场景生成（FE-18 下沉后端）：紫金山范围内随机火情，基地恒为紫霞湖。"""
import math
import random
from typing import Any, Dict, Optional

ZIXIAHU_BASE_GPS = {"latitude": 32.062229, "longitude": 118.839016}
METERS_PER_LAT = 111320.0

# 面积分层（BE-15，与前端演示生成器同口径）：40% 小 / 45% 中 / 15% 大。
# 小火保证"扑灭成功"主路径常见，中火让多机协同成为常态，大火保留"请求增援"演示；
# 此前 API 路径是 300–6000 均匀分布（audit 记录：分层只在前端，口径不一）。
AREA_LAYERS = ((0.40, 300, 600), (0.85, 900, 1600), (1.00, 2500, 3500))


def layered_area_m2(rng: Optional[random.Random] = None) -> int:
    """按 40/45/15 分层抽火情面积：小 300–900 / 中 900–2500 / 大 2500–6000 m²。"""
    rng = rng or random
    roll = rng.random()
    for bound, base, span in AREA_LAYERS:
        if roll < bound:
            return round(base + rng.random() * span)
    return round(2500 + rng.random() * 3500)


def random_scenario() -> Dict[str, Any]:
    """生成紫金山范围内的随机火情场景。

    火点位于紫霞湖东北向 0.8~2.5km 的山体范围内；机群框架原点（fire_origin）
    由火点 GPS 反推，保证无人机停靠位（fleet position 框架坐标）恒为紫霞湖基地。
    """
    base = fleet_average_position()
    distance = 800 + random.random() * 1700
    angle = (-25 + random.random() * 100) * math.pi / 180
    fire_origin = {
        "x": min(700.0, max(-500.0, round(base["x"] + math.cos(angle) * distance))),
        "y": min(800.0, max(-1000.0, round(base["y"] + math.sin(angle) * distance))),
    }
    area_m2 = layered_area_m2()
    growth_rate = round((0.2 + random.random() * 0.4), 2)
    people = random.choice(["confirmed", "absent", "unknown"])
    meters_per_lng = METERS_PER_LAT * math.cos(ZIXIAHU_BASE_GPS["latitude"] * math.pi / 180)
    fire_gps = {
        "latitude": round(ZIXIAHU_BASE_GPS["latitude"] + (fire_origin["y"] - base["y"]) / METERS_PER_LAT, 6),
        "longitude": round(ZIXIAHU_BASE_GPS["longitude"] + (fire_origin["x"] - base["x"]) / meters_per_lng, 6),
    }
    return {
        "scenario": {
            "fire_origin": fire_origin,
            "fire_area_m2": area_m2,
            "growth_rate": growth_rate,
            "people_status": people,
            "fire_origin_gps": fire_gps,
        },
        "summary": {
            "fire_gps": fire_gps,
            "area_m2": area_m2,
            "growth_rate": growth_rate,
            "people": people,
        },
    }


def fleet_average_position() -> Dict[str, float]:
    """机群平均停靠位（相对框架，米）。基地=紫霞湖：全部机位在基地停机坪小幅散布。"""
    positions = BASE_SCATTER.values()
    return {
        "x": sum(p["x"] for p in positions) / len(list(BASE_SCATTER.values())),
        "y": sum(p["y"] for p in positions) / len(list(BASE_SCATTER.values())),
    }


import math  # noqa: E402

BASE_SCATTER = {
    "R1": {"x": -254, "y": -671}, "R2": {"x": -228, "y": -663},
    "E1": {"x": -242, "y": -689}, "E2": {"x": -268, "y": -693},
    "E3": {"x": -224, "y": -701}, "E4": {"x": -282, "y": -705},
    "E5": {"x": -232, "y": -712}, "E6": {"x": -276, "y": -716},
    "S1": {"x": -214, "y": -657}, "S2": {"x": -262, "y": -645},
    "S3": {"x": -200, "y": -668}, "S4": {"x": -286, "y": -638},
}
