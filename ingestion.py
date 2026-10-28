"""Bounded CSV parsing, Chinese header mapping, row validation, and in-file deduplication."""
from __future__ import annotations

import csv
import io
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

MAX_BYTES = 8 * 1024 * 1024
MAX_ROWS = 10000
ALIASES = {
    "order_id": ("order_id", "订单号", "订单编号", "主订单编号"),
    "platform": ("platform", "平台", "订单来源"),
    "customer_id": ("customer_id", "客户编号", "买家编号", "用户ID"),
    "product_name": ("product_name", "商品名称", "商品标题", "商品"),
    "amount": ("amount", "实付金额", "订单金额", "金额"),
    "quantity": ("quantity", "购买数量", "数量"),
    "ordered_at": ("ordered_at", "下单时间", "下单日期", "订单日期"),
}
REQUIRED = {"order_id", "customer_id", "product_name", "amount", "ordered_at"}


def normalize(row: dict, today: date | None = None) -> dict:
    result = {}
    for name, maximum in (("order_id", 80), ("platform", 40), ("customer_id", 80), ("product_name", 240)):
        value = str(row.get(name) or ("授权CSV" if name == "platform" else "")).strip()
        if not value or len(value) > maximum:
            raise ValueError(f"{name} 不能为空，且最长 {maximum} 字符")
        result[name] = value
    try:
        amount = Decimal(str(row.get("amount", "")).strip().replace(",", "").removeprefix("¥").removeprefix("￥"))
        if not amount.is_finite() or not 0 < amount <= Decimal("10000000"):
            raise ValueError("amount 必须是大于 0 且不超过 1000 万的有限金额")
        amount = amount.quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
        if amount <= 0:
            raise ValueError("amount 四舍五入到分后必须大于 0")
        quantity = Decimal(str(row.get("quantity") or "1"))
        if not quantity.is_finite() or quantity != quantity.to_integral_value() or not 1 <= quantity <= 100000:
            raise ValueError("quantity 必须是 1 到 100000 的整数")
        text = str(row.get("ordered_at") or "").strip().replace("/", "-")
        ordered = datetime.fromisoformat(text).date() if "T" in text or " " in text else date.fromisoformat(text)
        if ordered > (today or date.today()):
            raise ValueError("下单日期不能晚于今天")
    except (InvalidOperation, OverflowError, ValueError) as exc:
        raise ValueError(f"金额、数量或日期无效：{exc}") from exc
    result.update(amount=float(amount), quantity=int(quantity), ordered_at=ordered)
    return result


def parse_csv(raw: bytes) -> dict:
    if len(raw) > MAX_BYTES:
        raise ValueError("文件最大 8 MB")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = raw.decode("gb18030")
        except UnicodeDecodeError as exc:
            raise ValueError("请使用 UTF-8 或 GB18030 编码的 CSV") from exc
    reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
    try:
        headers = reader.fieldnames
        if not headers:
            raise ValueError("CSV 没有表头")
        reverse = {alias: key for key, aliases in ALIASES.items() for alias in aliases}
        mapping = {header: reverse.get(header.strip(), header.strip()) for header in headers}
        if len(set(mapping.values())) != len(headers):
            raise ValueError("表头重复或多个表头映射到同一字段")
        if not REQUIRED.issubset(set(mapping.values())):
            raise ValueError("缺少字段：" + "、".join(sorted(REQUIRED - set(mapping.values()))))
        valid, errors, seen = [], [], set()
        total = duplicate = invalid = 0
        for row in reader:
            total += 1
            if total > MAX_ROWS:
                raise ValueError("单次最多 10000 条订单")
            try:
                if None in row:
                    raise ValueError("字段数量超过表头，请检查 CSV 引号")
                normalized = normalize({mapping[k]: v for k, v in row.items()})
                key = normalized["platform"], normalized["order_id"]
                if key in seen:
                    duplicate += 1
                else:
                    seen.add(key)
                    valid.append(normalized)
            except ValueError as exc:
                invalid += 1
                if len(errors) < 30:
                    errors.append({"line": reader.line_num, "message": str(exc)})
        if not total:
            raise ValueError("CSV 没有订单数据")
        return {"rows": valid, "total": total, "invalid": invalid, "duplicates_in_file": duplicate,
                "errors": errors, "mapping": mapping}
    except csv.Error as exc:
        raise ValueError(f"CSV 格式错误：{exc}") from exc
