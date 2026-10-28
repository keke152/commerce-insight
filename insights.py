"""Transparent customer segmentation and purchase-day-based replenishment ranking."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from statistics import median


def customer_profiles(orders: list[dict], today: date | None = None) -> list[dict]:
    today = today or date.today()
    groups = defaultdict(list)
    for order in orders:
        groups[order["customer_id"]].append(order)
    profiles = []
    for customer_id, items in groups.items():
        days = sorted({item["ordered_at"] for item in items})
        recency = (today - days[-1]).days
        frequency = len(days)
        monetary = round(sum(item["amount"] for item in items), 2)
        segment = ("高价值活跃" if recency <= 60 and frequency >= 3 and monetary >= 500
                   else "待唤回" if recency > 90 else "新客户" if frequency == 1 else "成长客户")
        profiles.append({"customer_id": customer_id, "recency_days": recency, "frequency": frequency,
                         "monetary": monetary, "order_count": len(items), "segment": segment,
                         "platforms": sorted({item["platform"] for item in items}),
                         "categories": sorted({item["category"] for item in items})})
    return sorted(profiles, key=lambda item: (-item["monetary"], item["customer_id"]))


def opportunities(orders: list[dict], today: date | None = None) -> list[dict]:
    today = today or date.today()
    groups = defaultdict(list)
    for order in orders:
        if order["category"] != "其他":
            groups[order["customer_id"], order["category"]].append(order)
    result = []
    for (customer_id, category), items in groups.items():
        days = sorted({item["ordered_at"] for item in items})
        if len(days) < 2:
            continue
        gaps = [(right - left).days for left, right in zip(days, days[1:])]
        cycle = max(7, round(median(gaps)))
        elapsed = (today - days[-1]).days
        ratio = elapsed / cycle
        if ratio < .65:
            continue
        # Extremely overdue customers are a win-back segment, not near-certain buyers.
        score = max(5, min(95, round(85 - abs(ratio - 1) * 25 + min(len(days) - 2, 4) * 2)))
        status = "需唤回评估" if ratio > 2 else "建议触达" if ratio >= 1 else "即将复购"
        last = max(items, key=lambda item: (item["ordered_at"], item["order_id"]))
        result.append({"customer_id": customer_id, "category": category, "last_product": last["product_name"],
                       "last_order_date": days[-1].isoformat(), "order_count": len(items), "purchase_days": len(days),
                       "avg_cycle_days": cycle, "days_since_last": elapsed,
                       "predicted_date": (days[-1] + timedelta(days=cycle)).isoformat(),
                       "priority_score": score, "likelihood": score, "status": status,
                       "reason": f"{len(days)}个购买日，间隔中位数{cycle}天，距上次{elapsed}天；分值仅用于排序",
                       "suggested_action": "先核对需求，再考虑补货提醒" if ratio <= 2 else "先了解流失原因，避免重复打扰"})
    return sorted(result, key=lambda item: (-item["priority_score"], item["customer_id"], item["category"]))
